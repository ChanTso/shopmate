"""Explicit local runtime configuration, separate from model credentials."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    citybuddy_dir: Path = ROOT.parent / "citybuddy"
    auth_url: str = "http://127.0.0.1:9081"
    commerce_url: str = "http://127.0.0.1:9082"
    jwks_url: str = "http://127.0.0.1:9081/auth/jwks"
    issuer: str = "https://identity.citybuddy.test"
    user_audience: str = "citybuddy-web"
    merchant_service_secret: str = field(default="", repr=False)
    shopping_service_secret: str = field(default="", repr=False)
    payment_callback_secret: str = field(default="", repr=False)
    sql_host: str = "127.0.0.1"
    sql_port: int = 3306
    sql_user: str = "shopmate_analysis"
    sql_password: str = field(default="", repr=False)
    sql_database: str = "commerce_db"
    state_path: Path = ROOT / ".run/sessions.sqlite3"
    model: str = "gpt-5.6-terra"
    analysis_model: str = "gpt-5.6-terra"
    task_timeout_s: float = 300.0
    max_model_calls: int = 16
    sql_timeout_ms: int = 2000
    sql_max_rows: int = 200
    sql_max_bytes: int = 16000
    analysis_sandbox_image: str = "shopmate-analysis:1"
    as_of: str | None = None

    def __post_init__(self) -> None:
        for name in ("auth_url", "commerce_url", "jwks_url"):
            parsed = urlsplit(getattr(self, name))
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Invalid {name}")
        if (
            not 1 <= self.sql_port <= 65535
            or self.task_timeout_s <= 0
            or self.max_model_calls < 1
            or self.sql_timeout_ms < 1
            or self.sql_max_rows < 1
            or self.sql_max_bytes < 1
        ):
            raise ValueError("Runtime limits must be positive")

    @classmethod
    def load(cls) -> Settings:
        return load_settings()


def load_settings() -> Settings:
    path = Path(os.environ.get("SHOPMATE_CONFIG", ROOT / ".run/settings.json"))
    values = json.loads(path.read_text()) if path.exists() else {}
    for name in ("citybuddy_dir", "state_path"):
        if name in values:
            values[name] = Path(values[name]).expanduser().resolve()
    return Settings(**values)


def provider_credentials(citybuddy_dir: Path) -> tuple[str, str]:
    wanted = {"CLIPROXY_BASE_URL", "CLIPROXY_API_KEY"}
    values: dict[str, str] = {}
    for line in (citybuddy_dir / ".env").read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() in wanted:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name.strip()] = value
    if any(not values.get(name) for name in wanted):
        raise ValueError("CityBuddy .env must provide the configured model proxy credentials")
    return values["CLIPROXY_BASE_URL"], values["CLIPROXY_API_KEY"]
