"""Settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # --- WhatsApp Cloud API (Meta) ---
    access_token: str = ""
    phone_number_id: str = ""
    verify_token: str = ""
    app_secret: str = ""
    graph_version: str = "v23.0"
    graph_base: str = "https://graph.facebook.com"
    # When true, nothing is sent to Meta: outgoing payloads are stored in the
    # local outbox and shown in the dashboard. Defaults to true when no token.
    dry_run: bool = True
    # --- Agent ---
    business_file: str = ""
    db_path: str = "whatsapp_agent.db"
    provider: str = "mock"
    model: str = ""
    # Reminder template (must be approved in WhatsApp Manager before use)
    reminder_template: str = "appointment_reminder"
    reminder_template_lang: str = "ar"
    # --- Dashboard ---
    dashboard_user: str = "admin"
    dashboard_password: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        return cls(
            access_token=token,
            phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
            graph_version=os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0"),
            graph_base=os.getenv("WHATSAPP_GRAPH_BASE", "https://graph.facebook.com"),
            dry_run=_bool("WA_DRY_RUN", default=not token),
            business_file=os.getenv("WA_BUSINESS_FILE", ""),
            db_path=os.getenv("WA_DB_PATH", "whatsapp_agent.db"),
            provider=os.getenv("WA_LLM_PROVIDER", "mock"),
            model=os.getenv("WA_LLM_MODEL", ""),
            reminder_template=os.getenv("WA_REMINDER_TEMPLATE", "appointment_reminder"),
            reminder_template_lang=os.getenv("WA_REMINDER_TEMPLATE_LANG", "ar"),
            dashboard_user=os.getenv("DASHBOARD_USER", "admin"),
            dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
        )

    def problems(self) -> list[str]:
        """Human-readable configuration problems (empty list = ready for production)."""
        out = []
        if not self.verify_token:
            out.append("WHATSAPP_VERIFY_TOKEN is empty: Meta cannot verify the webhook.")
        if not self.app_secret:
            out.append("WHATSAPP_APP_SECRET is empty: webhook signatures cannot be checked (requests will be rejected).")
        if not self.dry_run:
            if not self.access_token:
                out.append("WHATSAPP_ACCESS_TOKEN is empty but WA_DRY_RUN is off.")
            if not self.phone_number_id:
                out.append("WHATSAPP_PHONE_NUMBER_ID is empty but WA_DRY_RUN is off.")
        if not self.dashboard_password:
            out.append("DASHBOARD_PASSWORD is empty: the dashboard is open to anyone who can reach it.")
        return out
