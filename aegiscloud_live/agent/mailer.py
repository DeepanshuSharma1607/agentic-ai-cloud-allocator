"""
mailer.py - sends one email by SMTP (default: Gmail). Nothing else.

    send_email(subject, body, attachments) -> (ok, message)

  attachments : list of (file_name, csv_text) pairs
It never raises: on any problem it returns (False, "reason"), so a mail problem can never crash the agent.
Gmail needs 2-step verification ON and an "app password" (Google Account -> Security -> App passwords).

TEST YOUR MAIL SETUP WITHOUT WAITING FOR AN ALERT:
    python -m agent.mailer --check     # shows which .env values are set (password hidden), sends nothing
    python -m agent.mailer --test      # sends one test email and prints the exact result / reason

WHAT IS HARDENED (compared with the first version)
    - the subject is forced onto ONE line (an LLM subject with a line break made Python refuse to build the email)
    - spaces inside the app password are removed (Google shows it as "abcd efgh ijkl mnop")
    - several recipients may be separated by comma or semicolon
    - every success / failure is also written to the agent log, with a plain-English reason (wrong password, blocked port ...)
    - a wrong password is still reported at once and NOT retried on another port; a blocked port 465 still falls back to 587
"""
import logging
import re
import smtplib
import sys
from email.message import EmailMessage

from agent import config as cfg

mlog = logging.getLogger("agent")


def _one_line(text, limit=200):
    """A header must be a single line."""
    return " ".join(str(text).split())[:limit]


def _recipients(raw):
    return [r.strip() for r in re.split(r"[,;]", raw or "") if r.strip()]


def _password():
    return "".join((cfg.EMAIL_PASSWORD or "").split())            # also removes the non-breaking spaces of a copied app password


def _explain(error):
    text = str(error)
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (f"the mail server rejected the login ({text}). Gmail needs a 16-letter APP PASSWORD "
                "(Google Account -> Security -> 2-step verification -> App passwords), not your normal password")
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return f"the recipient address was refused: {text}"
    if isinstance(error, smtplib.SMTPSenderRefused):
        return f"the sender address was refused: {text}"
    if isinstance(error, OSError):
        return f"could not reach {cfg.SMTP_HOST} (network, firewall or VPN is blocking it): {text}"
    return text


def send_email(subject, body, attachments=()):
    recipients = _recipients(cfg.EMAIL_TO)
    password = _password()
    if not (cfg.EMAIL_SENDER and password and recipients):
        missing = [n for n, v in (("EMAIL_SENDER", cfg.EMAIL_SENDER), ("EMAIL_PASSWORD", password), ("EMAIL_TO", recipients)) if not v]
        mlog.warning("email not sent: %s missing in .env", ", ".join(missing))
        return False, "EMAIL_SENDER, EMAIL_PASSWORD or EMAIL_TO is missing in .env"
    try:
        msg = EmailMessage()
        msg["Subject"] = _one_line(subject, 150)
        msg["From"] = cfg.EMAIL_SENDER
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)
        for name, text in attachments:
            msg.add_attachment(text.encode("utf-8"), maintype="text", subtype="csv", filename=name)
        try:
            with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.login(cfg.EMAIL_SENDER, password)
                server.send_message(msg, to_addrs=recipients)
        except smtplib.SMTPAuthenticationError:
            raise                                                 # wrong password: report it, do not retry on another port
        except (OSError, smtplib.SMTPConnectError) as first:     # port 465 blocked: try STARTTLS on 587
            mlog.warning("email: SSL on port %s failed (%s), trying STARTTLS on port %s", cfg.SMTP_PORT, first, cfg.SMTP_PORT_STARTTLS)
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT_STARTTLS, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.starttls()
                server.login(cfg.EMAIL_SENDER, password)
                server.send_message(msg, to_addrs=recipients)
        mlog.info("email sent to %s: %s", ", ".join(recipients), msg["Subject"])
        return True, f"sent to {', '.join(recipients)}"
    except Exception as e:
        reason = _explain(e)
        mlog.warning("email FAILED: %s", reason)
        return False, f"email failed: {reason}"


def _mask(value):
    return "(not set)" if not value else value[:2] + "*" * max(len(value) - 2, 0)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    print(f"EMAIL_SENDER   : {cfg.EMAIL_SENDER or '(not set)'}")
    print(f"EMAIL_PASSWORD : {_mask(_password())}  ({len(_password())} characters; a Gmail app password has 16)")
    print(f"EMAIL_TO       : {', '.join(_recipients(cfg.EMAIL_TO)) or '(not set)'}")
    print(f"server         : {cfg.SMTP_HOST} port {cfg.SMTP_PORT} (SSL), then {cfg.SMTP_PORT_STARTTLS} (STARTTLS)")
    print(f"ALERT_SEND_EMAIL in agent/config.py: {cfg.ALERT_SEND_EMAIL}")
    if "--test" not in argv:
        print("\nRun  python -m agent.mailer --test  to send one test email.")
        return 0
    ok, message = send_email("[TEST] AegisCloud alert email works",
                             "This is a test email from AegisCloud.\nIf you can read it, real alerts will reach this address too.\n")
    print(("OK: " if ok else "FAILED: ") + message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
