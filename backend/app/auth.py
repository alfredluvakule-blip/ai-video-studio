"""Authentication.

Built-in: email + password (PBKDF2-SHA256, 310k iterations) with opaque bearer
tokens stored hashed in the database.

Optional: if SUPABASE_JWT_SECRET is set, Supabase access tokens are accepted
too, and a local user row is created for the Supabase user on first use.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuthToken, User, now

_ITER = 310_000
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
    return f"pbkdf2${_ITER}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, digest = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it))
    return hmac.compare_digest(dk.hex(), digest)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user: User, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token_hash=_sha(token), user_id=user.id, expires_at=now() + timedelta(days=days)))
    db.commit()
    return token


def revoke_token(db: Session, token: str) -> None:
    db.query(AuthToken).filter(AuthToken.token_hash == _sha(token)).delete()
    db.commit()


def _supabase_user(db: Session, token: str) -> User | None:
    if not settings.supabase_jwt_secret or token.count(".") != 2:
        return None
    try:
        import jwt

        claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    except Exception:
        return None
    sub, email = claims.get("sub"), claims.get("email") or f"{claims.get('sub')}@supabase"
    uid = hashlib.sha256(f"supabase:{sub}".encode()).hexdigest()[:32]
    user = db.get(User, uid)
    if not user:
        user = User(id=uid, email=email, password_hash="")
        db.add(user)
        db.commit()
    return user


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user_from_token(db, creds.credentials)


def user_from_token(db: Session, token: str) -> User:
    row = db.get(AuthToken, _sha(token))
    if row:
        exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=now().tzinfo)
        if exp > now():
            user = db.get(User, row.user_id)
            if user:
                return user
    user = _supabase_user(db, token)
    if user:
        return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
