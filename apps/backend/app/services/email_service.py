import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings


logger = logging.getLogger("mwobareullae.email")


def send_password_reset_code(email: str, code: str) -> None:
    subject = "뭐바를래 비밀번호 재설정 인증 코드"
    body = (
        "비밀번호 재설정을 위한 인증 코드입니다.\n\n"
        f"인증 코드: {code}\n\n"
        "이 코드는 10분 동안만 사용할 수 있습니다. "
        "본인이 요청하지 않았다면 이 메일을 무시해 주세요."
    )
    send_email(email, subject, body)


def send_email(to_email: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        logger.info("email_skipped smtp_not_configured to=%s subject=%s", to_email, subject)
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
