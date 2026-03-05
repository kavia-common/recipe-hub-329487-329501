from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import UserPublic
from src.db.models import User
from src.db.session import get_db


_SECURITY = HTTPBearer(auto_error=False)


def _secret() -> bytes:
    # NOTE: In production, orchestrator should set AUTH_SECRET in .env
    secret = os.getenv("AUTH_SECRET", "").strip()
    if not secret:
        # Fall back for local/dev; still deterministic. Do not rely on this in prod.
        secret = "dev-secret-change-me"
    return secret.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


# PUBLIC_INTERFACE
def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256.

    Contract:
      - input: raw password (string)
      - output: 'pbkdf2$<iterations>$<salt_b64>$<hash_b64>'
    """
    salt = os.urandom(16)
    iterations = 120_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${_b64(salt)}${_b64(dk)}"


# PUBLIC_INTERFACE
def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    try:
        algo, iters_s, salt_b64, hash_b64 = password_hash.split("$", 3)
        if algo != "pbkdf2":
            return False
        iterations = int(iters_s)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# PUBLIC_INTERFACE
def create_access_token(user_id: uuid.UUID, expires_seconds: int = 60 * 60 * 24) -> str:
    """Create signed bearer token (minimal, stateless).

    Format: v1.<payload_b64>.<sig_b64>
    payload JSON bytes: "<user_id>|<exp_epoch>"
    """
    exp = int(time.time()) + int(expires_seconds)
    payload = f"{user_id}|{exp}".encode("utf-8")
    payload_b64 = _b64(payload)
    sig = hmac.new(_secret(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return f"v1.{payload_b64}.{_b64(sig)}"


@dataclass(frozen=True)
class AuthenticatedUser:
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool

    def to_public(self) -> UserPublic:
        return UserPublic(
            id=self.id, email=self.email, display_name=self.display_name, is_admin=self.is_admin
        )


def _parse_and_verify_token(token: str) -> Optional[tuple[uuid.UUID, int]]:
    try:
        prefix, payload_b64, sig_b64 = token.split(".", 2)
        if prefix != "v1":
            return None
        sig = _b64d(sig_b64)
        expected = hmac.new(_secret(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = _b64d(payload_b64).decode("utf-8")
        user_id_s, exp_s = payload.split("|", 1)
        return uuid.UUID(user_id_s), int(exp_s)
    except Exception:
        return None


# PUBLIC_INTERFACE
def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_SECURITY),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """FastAPI dependency to authenticate user by bearer token.

    Raises:
        HTTPException(401): if missing/invalid/expired token or user not found.
    """
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    parsed = _parse_and_verify_token(creds.credentials)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id, exp = parsed
    if int(time.time()) > exp:
        raise HTTPException(status_code=401, detail="Token expired")

    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


# PUBLIC_INTERFACE
def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """FastAPI dependency requiring admin privileges."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
