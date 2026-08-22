"""Tests for PDF generation and optional email delivery."""

from pathlib import Path

import scanner


def test_pdf_can_be_disabled(tmp_path, scored_article):
    config = {"reports": {"pdf": {"enabled": False, "local_path": str(tmp_path)}}}

    assert scanner.generate_pdf([scored_article], "2026-08-22", config) is None


def test_pdf_handles_unicode_without_system_fonts(tmp_path, scored_article):
    article = dict(scored_article)
    article.update(
        {
            "title": "L’agente — prova 🧪",
            "summary": "Testo con emoji 🤖 e caratteri non latini: 日本語",
            "relevance_reason": "È utile perché evita un crash.",
        }
    )
    config = {
        "reports": {
            "pdf": {
                "enabled": True,
                "local_path": str(tmp_path),
                "filename_template": "report-{date}.pdf",
            }
        }
    }

    result = scanner.generate_pdf([article], "2026-08-22", config)

    assert result == str(tmp_path / "report-2026-08-22.pdf")
    assert Path(result).is_file()
    assert Path(result).stat().st_size > 0


def test_email_uses_environment_for_credentials_and_recipient(monkeypatch, scored_article):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example.test", 587, 20)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            return None

        def login(self, username, password):
            assert username == "sender@example.test"
            assert password == "test-password"

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setenv("EMAIL_USER", "sender@example.test")
    monkeypatch.setenv("EMAIL_PASSWORD", "test-password")
    monkeypatch.setenv("EMAIL_TO", "recipient@example.test")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    config = {
        "notifications": {
            "email": {
                "enabled": True,
                "smtp_server": "smtp.example.test",
                "smtp_port": 587,
            }
        }
    }

    scanner._send_email([scored_article], config)

    assert len(sent) == 1
    assert sent[0]["To"] == "recipient@example.test"
