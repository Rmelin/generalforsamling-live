"""Konfiguration via miljøvariabler."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


@dataclass
class Settings:
    database_path: Path = Path("data/live.db")
    secret_key: str = ""
    foh_username: str = "admin"
    foh_password: str = "admin"
    stage_password: str = "scene"
    seed_demo_data: bool = False
    session_max_age: int = 60 * 60 * 24 * 7
    event_name: str = "Generalforsamling Live"
    device_token: str = ""  # tom = ingen enheder (Presto) har adgang
    ping_interval: float = 10.0
    warnings: list[str] = field(default_factory=list)

    def resolve_secret_key(self) -> str:
        """Brug SECRET_KEY, ellers en nøgle gemt ved siden af databasen.

        Nøglen gemmes, så login-sessioner overlever en genstart af serveren.
        """
        if self.secret_key:
            return self.secret_key
        key_file = self.database_path.parent / "secret_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            key = key_file.read_text().strip()
            if key:
                self.secret_key = key
                return key
        key = secrets.token_urlsafe(48)
        key_file.write_text(key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        self.secret_key = key
        return key


def load_settings() -> Settings:
    env = os.environ
    s = Settings(
        database_path=Path(env.get("DATABASE_PATH", "data/live.db")),
        secret_key=env.get("SECRET_KEY", ""),
        foh_username=env.get("FOH_USERNAME", "admin") or "admin",
        foh_password=env.get("FOH_PASSWORD", ""),
        stage_password=env.get("STAGE_PASSWORD", ""),
        seed_demo_data=_bool(env.get("SEED_DEMO_DATA"), False),
        session_max_age=int(env.get("SESSION_MAX_AGE", str(60 * 60 * 24 * 7))),
        event_name=env.get("EVENT_NAME", "Generalforsamling Live") or "Generalforsamling Live",
        device_token=env.get("DEVICE_TOKEN", "").strip(),
    )
    if s.device_token and len(s.device_token) < 16:
        s.warnings.append("DEVICE_TOKEN er kortere end 16 tegn – brug en længere, tilfældig værdi.")
    if not s.foh_password:
        s.foh_password = "admin"
        s.warnings.append("FOH_PASSWORD er ikke sat – bruger standardadgangskoden 'admin'.")
    if not s.stage_password:
        s.stage_password = "scene"
        s.warnings.append("STAGE_PASSWORD er ikke sat – bruger standardadgangskoden 'scene'.")
    return s
