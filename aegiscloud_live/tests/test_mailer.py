"""mailer.py: a wrong password must be reported at once, not retried on another port."""
import smtplib
from unittest import mock

from agent import config as cfg
from agent import mailer


def _creds(monkeypatch):
    monkeypatch.setattr(cfg, "EMAIL_SENDER", "a@example.com")
    monkeypatch.setattr(cfg, "EMAIL_PASSWORD", "pw")
    monkeypatch.setattr(cfg, "EMAIL_TO", "b@example.com")


def test_missing_credentials_never_raises(monkeypatch):
    monkeypatch.setattr(cfg, "EMAIL_SENDER", "")
    ok, msg = mailer.send_email("s", "b")
    assert not ok and "missing" in msg


def test_wrong_password_does_not_fall_back_to_starttls(monkeypatch):
    _creds(monkeypatch)
    with mock.patch("smtplib.SMTP_SSL") as ssl, mock.patch("smtplib.SMTP") as plain:
        ssl.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad credentials")
        ok, msg = mailer.send_email("s", "b")
    assert not ok and "failed" in msg
    plain.assert_not_called()


def test_blocked_port_465_falls_back_to_587(monkeypatch):
    _creds(monkeypatch)
    with mock.patch("smtplib.SMTP_SSL", side_effect=OSError("blocked")), mock.patch("smtplib.SMTP") as plain:
        ok, msg = mailer.send_email("s", "b", [("x.csv", "a,b\n1,2\n")])
    assert ok and "sent" in msg
    plain.assert_called_once()
