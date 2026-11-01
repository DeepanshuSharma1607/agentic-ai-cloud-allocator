"""
mailer.py - sends one email by SMTP (default: Gmail). Nothing else.

    send_email(subject, body, attachments) -> (ok, message)

  attachments : list of (file_name, csv_text) pairs
It never raises: on any problem it returns (False, "reason"), so a mail problem can never crash the agent.
Gmail needs 2-step verification ON and an "app password" (Google Account -> Security -> App passwords).
"""
import smtplib
from email.message import EmailMessage

import config as cfg


def send_email(subject, body, attachments=()):
    if not (cfg.EMAIL_SENDER and cfg.EMAIL_PASSWORD and cfg.EMAIL_TO):
        return False, "EMAIL_SENDER, EMAIL_PASSWORD or EMAIL_TO is missing in .env"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg.EMAIL_SENDER
        msg["To"] = cfg.EMAIL_TO
        msg.set_content(body)
        for name, text in attachments:
            msg.add_attachment(text.encode("utf-8"), maintype="text", subtype="csv", filename=name)
        try:
            with smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
                server.send_message(msg)
        except (OSError, smtplib.SMTPConnectError):          # port 465 blocked: try STARTTLS on 587
            # (a wrong password raises SMTPAuthenticationError, which is not caught here, so it is still reported clearly)
            with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT_STARTTLS, timeout=cfg.EMAIL_TIMEOUT) as server:
                server.starttls()
                server.login(cfg.EMAIL_SENDER, cfg.EMAIL_PASSWORD)
                server.send_message(msg)
        return True, f"sent to {cfg.EMAIL_TO}"
    except Exception as e:
        return False, f"email failed: {e}"