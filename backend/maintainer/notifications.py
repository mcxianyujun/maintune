import asyncio
import smtplib
import ssl
from email.message import EmailMessage


class EmailNotifier:
    def __init__(self, settings: dict, password: str):
        self.settings, self.password = settings, password

    async def send(self, subject: str, body: str, idempotency_key: str) -> None:
        await asyncio.to_thread(self._send, subject, body, idempotency_key)

    def _send(self, subject: str, body: str, idempotency_key: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings["from_address"]
        message["To"] = self.settings["owner_email"]
        message["X-AI-Maintainer-Idempotency-Key"] = idempotency_key
        message.set_content(body)
        mode = self.settings.get("mode", "starttls")
        cls = smtplib.SMTP_SSL if mode == "ssl" else smtplib.SMTP
        with cls(self.settings["host"], self.settings["port"], timeout=20) as smtp:
            if mode == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if self.settings.get("username"):
                smtp.login(self.settings["username"], self.password)
            smtp.send_message(message)
