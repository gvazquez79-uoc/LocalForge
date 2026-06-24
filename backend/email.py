from __future__ import annotations

import smtplib
from email.message import EmailMessage

from backend.config import SmtpConfig


def send_password_reset_email(smtp: SmtpConfig, to_email: str, reset_url: str) -> None:
    if not smtp.enabled:
        raise RuntimeError("El envío de correo está desactivado")
    if not smtp.host or not smtp.port:
        raise RuntimeError("SMTP no configurado")

    from_email = smtp.from_email or smtp.username
    if not from_email:
        raise RuntimeError("Falta la dirección remitente")

    msg = EmailMessage()
    msg["Subject"] = "Restablecer contraseña de LocalForge"
    msg["From"] = f"{smtp.from_name} <{from_email}>" if smtp.from_name else from_email
    msg["To"] = to_email
    msg.set_content(
        "Has solicitado restablecer tu contraseña de LocalForge.\n\n"
        f"Abre este enlace para elegir una nueva contraseña:\n{reset_url}\n\n"
        "Si no has sido tú, puedes ignorar este correo."
    )

    if smtp.use_ssl:
        server = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=15)
    else:
        server = smtplib.SMTP(smtp.host, smtp.port, timeout=15)

    with server:
        if not smtp.use_ssl and smtp.use_tls:
            server.starttls()
        if smtp.username:
            server.login(smtp.username, smtp.password)
        server.send_message(msg)