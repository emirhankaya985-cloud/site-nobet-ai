from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from argon2 import PasswordHasher, exceptions as argon_errors
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import get_settings
from .database import db_session
from .models import User, Membership

_password = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=2)
_bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str):
    return _password.hash(raw)


def verify_password(raw: str, encoded: str) -> bool:
    try:
        return _password.verify(encoded, raw)
    except (argon_errors.VerifyMismatchError, argon_errors.VerificationError, argon_errors.InvalidHashError):
        return False


def make_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(hours=8)}, get_settings().session_secret, algorithm="HS256")


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(db_session)) -> User:
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, get_settings().session_secret, algorithms=["HS256"], options={"require": ["sub", "iat", "exp"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(401, "Invalid or expired session")
    return user


def org_membership(user: User, organization_id: str, db: Session, write: bool = False) -> Membership:
    item = db.scalar(select(Membership).where(Membership.organization_id == organization_id, Membership.user_id == user.id))
    if not item or (write and item.role not in ("owner", "admin")):
        raise HTTPException(404, "Resource not found")
    return item
