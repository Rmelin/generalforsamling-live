"""Enkel rollebaseret adgangskontrol med hashede adgangskoder."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select

from .config import Settings
from .db import Database
from .models import User
from .services import Actor
from .state import ROLE_FOH, ROLE_STAGE

PBKDF2_ITERATIONS = 240_000
STAGE_USERNAME = "scene"


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def ensure_users(db: Database, settings: Settings) -> None:
    """Opret/opdatér FOH- og scenebrugeren ud fra miljøvariablerne.

    Miljøvariablerne er autoritative: ændres en adgangskode i .env, opdateres
    hashen ved næste opstart.
    """
    wanted = [
        (settings.foh_username, ROLE_FOH, settings.foh_password),
        (STAGE_USERNAME, ROLE_STAGE, settings.stage_password),
    ]
    with db.write() as s:
        for username, role, password in wanted:
            user = s.scalar(select(User).where(User.username == username))
            if user is None:
                s.add(User(username=username, role=role, password_hash=hash_password(password)))
            else:
                user.role = role
                if not verify_password(password, user.password_hash):
                    user.password_hash = hash_password(password)


def authenticate(db: Database, username: str, password: str) -> Optional[User]:
    with db.read() as s:
        user = s.scalar(select(User).where(User.username == username))
    if user and verify_password(password, user.password_hash):
        return user
    # Brug tid på en hash alligevel, så svartiden ikke afslører brugernavne.
    if user is None:
        verify_password(password, hash_password("x", iterations=1000))
    return None


def session_actor(request: Request) -> Optional[Actor]:
    role = request.session.get("role")
    username = request.session.get("user")
    if role in (ROLE_FOH, ROLE_STAGE) and username:
        return Actor(role=role, username=username)
    return None


def can_view(actor: Optional[Actor], page: str) -> bool:
    if page == "foh":
        return actor is not None and actor.role == ROLE_FOH
    if page == "stage":
        return actor is not None and actor.role in (ROLE_FOH, ROLE_STAGE)
    return True


def require_actor(*roles: str):
    """FastAPI-dependency: kræver login med en af de angivne roller."""

    def dependency(request: Request) -> Actor:
        actor = session_actor(request)
        if actor is None:
            raise HTTPException(status_code=401, detail="Du er ikke logget ind.")
        if actor.role not in roles:
            raise HTTPException(status_code=403, detail="Din rolle må ikke udføre denne handling.")
        return actor

    return dependency


def require_client_header(request: Request) -> None:
    """Simpel CSRF-beskyttelse: skrivekald skal sende en brugerdefineret header,
    som en fremmed hjemmeside ikke kan sætte uden CORS-tilladelse."""
    if request.headers.get("x-live-client") != "1":
        raise HTTPException(status_code=400, detail="Manglende klient-header.")
