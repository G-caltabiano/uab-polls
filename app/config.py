from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _session_secret() -> str:
    configured = os.getenv("UAB_POLLS_SESSION_SECRET", "").strip()
    if configured:
        return configured
    data_dir = Path(os.getenv("UAB_POLLS_DATA_DIR", BASE_DIR / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / ".session_secret"
    try:
        return secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(48)
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
        return value


@dataclass(frozen=True)
class Settings:
    app_name: str = "Disponibilitat Medicina UAB"
    data_dir: Path = Path(os.getenv("UAB_POLLS_DATA_DIR", BASE_DIR / "data"))
    session_secret: str = _session_secret()
    root_path: str = os.getenv("UAB_POLLS_ROOT_PATH", "").rstrip("/")
    secure_cookies: bool = _bool("UAB_POLLS_SECURE_COOKIES")
    initial_admin_email: str = os.getenv(
        "UAB_POLLS_INITIAL_ADMIN_EMAIL", "gianluigi.caltabiano@uab.cat"
    ).strip().lower()
    email_provider: str = os.getenv("UAB_POLLS_EMAIL_PROVIDER", "gog").strip().lower()
    gog_path: str = os.getenv("UAB_POLLS_GOG_PATH", "/home/gian/.local/bin/gog").strip()
    gog_account: str = os.getenv("UAB_POLLS_GOG_ACCOUNT", "fridaygc.bot@gmail.com").strip().lower()
    smtp_host: str = os.getenv("UAB_POLLS_SMTP_HOST", "").strip()
    smtp_port: int = int(os.getenv("UAB_POLLS_SMTP_PORT", "587"))
    smtp_username: str = os.getenv("UAB_POLLS_SMTP_USERNAME", "").strip()
    smtp_password: str = os.getenv("UAB_POLLS_SMTP_PASSWORD", "")
    smtp_from: str = os.getenv(
        "UAB_POLLS_SMTP_FROM", "Disponibilitat Medicina UAB <gianluigi.caltabiano@uab.cat>"
    )
    smtp_starttls: bool = _bool("UAB_POLLS_SMTP_STARTTLS", True)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "uab_polls.sqlite3"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
