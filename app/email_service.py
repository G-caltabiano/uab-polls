from __future__ import annotations

import smtplib
import subprocess
from email.message import EmailMessage

from .config import settings


def send_response_notification(
    *,
    recipient: str,
    poll_title: str,
    participant_name: str,
    admin_url: str,
    response_details: str = "",
) -> tuple[str, str]:
    body = (
        f"{participant_name} ha respost l'enquesta «{poll_title}».\n\n"
        + (f"Disponibilitat:\n{response_details}\n\n" if response_details else "")
        + f"Consulta tots els resultats: {admin_url}\n"
    )

    if settings.email_provider == "gog":
        try:
            completed = subprocess.run(
                [
                    settings.gog_path,
                    "gmail",
                    "send",
                    "--account",
                    settings.gog_account,
                    "--to",
                    recipient,
                    "--subject",
                    f"Nova resposta: {poll_title}",
                    "--body-file",
                    "-",
                    "--json",
                    "--no-input",
                ],
                input=body,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if completed.returncode == 0:
                return "sent", f"Gmail: {settings.gog_account}"
            detail = (completed.stderr or completed.stdout or "error gog").strip()
            return "failed", f"gog: {detail[:240]}"
        except Exception as exc:
            return "failed", f"gog {type(exc).__name__}: {str(exc)[:220]}"

    if not settings.smtp_host:
        return "skipped", "SMTP no configurat"

    message = EmailMessage()
    message["Subject"] = f"Nova resposta: {poll_title}"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return "sent", ""
    except Exception as exc:  # logged for the admin; public request still succeeds
        return "failed", f"{type(exc).__name__}: {str(exc)[:240]}"
