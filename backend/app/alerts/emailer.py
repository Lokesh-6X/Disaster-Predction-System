"""Alert email: content (Jinja2 templates) and sending over SMTP (FR-ALT-02, FR-ALT-04).

Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_STARTTLS=true and an app password.
Mailpit (local test inbox): SMTP_HOST=localhost, SMTP_PORT=1025, SMTP_STARTTLS=false.
"""

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from backend.app.settings import EnvSettings

TEMPLATES = Path(__file__).resolve().parent / "templates"
SEND_TIMEOUT_S = 20

LEVEL_NAMES = {
    "wind": {
        "yellow": "Gusty wind",
        "orange": "Strong gusty wind",
        "red": "Severe / damaging wind",
    },
    "heat": {"yellow": "Heat wave", "orange": "Severe heat wave", "red": "Extreme heat"},
}

_templates = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class AlertEmail:
    subject: str
    text: str
    html: str


def render_alert_email(
    *,
    site_name: str,
    timezone: str,
    kit_id: str,
    kit_description: str,
    hazard: str,
    level: str,
    probabilities: dict[str, float],
    thresholds: dict[str, str],
    run_at: datetime,
    valid_until: datetime,
    reading: dict | None,
    model_version: str | None,
    synthetic_model: bool,
    fallback_used: bool,
    dashboard_url: str,
    horizon_hours: int,
    cooldown_hours: float,
) -> AlertEmail:
    tz = ZoneInfo(timezone)

    def local(ts: datetime) -> str:
        return ts.astimezone(tz).strftime("%d %b %Y, %H:%M IST")

    context = {
        "site_name": site_name,
        "kit_id": kit_id,
        "kit_description": kit_description,
        "hazard": hazard.capitalize(),
        "level": level.upper(),
        "level_name": LEVEL_NAMES[hazard][level],
        "levels": [
            {
                "name": name.capitalize(),
                "threshold": thresholds[name],
                "percent": round(probabilities[name] * 100),
            }
            for name in ("yellow", "orange", "red")
        ],
        "run_at": local(run_at),
        "valid_until": local(valid_until),
        "reading": None if reading is None else {**reading, "time": local(reading["ts"])},
        "model_version": model_version or "unknown",
        "synthetic_model": synthetic_model,
        "fallback_used": fallback_used,
        "dashboard_url": dashboard_url,
        "horizon_hours": horizon_hours,
        "cooldown_hours": f"{cooldown_hours:g}",
    }
    subject = (
        f"[{level.upper()}] {hazard.capitalize()} risk at {site_name} — next {horizon_hours} h"
    )
    return AlertEmail(
        subject=subject,
        text=_templates.get_template("alert_email.txt").render(context),
        html=_templates.get_template("alert_email.html").render(context),
    )


class Emailer:
    def __init__(self, env: EnvSettings) -> None:
        self._env = env

    @property
    def recipient(self) -> str:
        return self._env.admin_email

    async def send(self, email: AlertEmail) -> None:
        env = self._env
        message = EmailMessage()
        message["From"] = env.smtp_from
        message["To"] = env.admin_email
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        await aiosmtplib.send(
            message,
            hostname=env.smtp_host,
            port=env.smtp_port,
            username=env.smtp_user or None,
            password=env.smtp_password.get_secret_value() or None,
            start_tls=env.smtp_starttls,
            timeout=SEND_TIMEOUT_S,
        )
