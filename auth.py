from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
import config

# New hashes use PBKDF2; existing bcrypt hashes remain verifiable.
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto",
                           pbkdf2_sha256__default_rounds=600000)
bearer = HTTPBearer(auto_error=False)

def validate_config():
    if len(config.JWT_SECRET_KEY) < 32 or config.JWT_ALGORITHM != "HS256":
        raise RuntimeError("Configure a JWT_SECRET_KEY of at least 32 characters and HS256.")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False

def create_access_token(user_id: int, expires_minutes: int | None = None) -> str:
    validate_config()
    expires = config.JWT_EXPIRE_MINUTES if expires_minutes is None else expires_minutes
    return jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=expires),
                       "type": "user"}, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)

def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=["HS256"],
                             options={"require_exp": True, "require_sub": True})
        if payload.get("type") != "user":
            raise ValueError()
        return int(payload["sub"])
    except (JWTError, ValueError, TypeError):
        raise ValueError("Invalid or expired token") from None

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)):
    try:
        if not credentials:
            raise ValueError()
        user = db.get(User, decode_access_token(credentials.credentials))
        if not user:
            raise ValueError()
        return user
    except ValueError:
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from None

def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user
