"""用户认证路由 — 注册/登录/获取当前用户

密码：PBKDF2-HMAC-SHA256（纯 Python，无 C 扩展依赖）。
Token：PyJWT HS256（P0.3 替换了早期的手搓 base64+HMAC 实现，避免 alg/aud/iss 缺失与签名格式不规范带来的伪造风险）。
"""
import hashlib
import hmac
import logging
import os
import datetime

import jwt as pyjwt
from jwt import PyJWTError

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import APIRouter, HTTPException, Request

from api.schemas import RegisterRequest, LoginRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# JWT config — MUST be set via environment variable
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET environment variable is required. "
        "Set it in .env or as an environment variable before starting the server."
    )
# Reject known insecure default secrets
_INSECURE_DEFAULTS = {"change-me-to-a-random-secret-in-production", "secret", "changeme", "jwt-secret"}
if JWT_SECRET in _INSECURE_DEFAULTS:
    raise RuntimeError(
        f"JWT_SECRET is set to an insecure default value. "
        f"Generate a secure random secret and set it in .env. "
        f"Example: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
# Minimum key length sanity check (HMAC-SHA256 should use ≥32 bytes)
if len(JWT_SECRET.encode()) < 16:
    raise RuntimeError(
        "JWT_SECRET is too short. Use at least 32 bytes of high-entropy random data."
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# Password hashing — PBKDF2 with per-user salt, pure Python
_ITERATIONS = 200_000


def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """PBKDF2-HMAC-SHA256 with per-user random salt — pure Python"""
    if salt is None:
        salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return h, salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored hash and salt"""
    h, _ = _hash_password(password, salt)
    return hmac.compare_digest(h, stored_hash)


def _create_jwt_token(user_id: str, username: str) -> str:
    """Create JWT token using PyJWT (HS256, standard header with alg/typ)."""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
        "iat": int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt_token(token: str) -> dict:
    """Decode and verify JWT token using PyJWT.

    Strict verification: HS256 algorithm pinned, ``exp`` and ``user_id`` required.
    Any signature/format/expiry failure returns ``{}`` so the auth dependency
    can raise a uniform 401.
    """
    try:
        payload = pyjwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "user_id"]},
        )
        return payload
    except PyJWTError:
        return {}
    except Exception:
        return {}


def get_current_user(request: Request) -> dict:
    """Extract current user from Authorization header"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {}
    token = auth_header[7:]
    payload = _decode_jwt_token(token)
    if not payload or not payload.get("user_id"):
        return {}
    return payload


@router.post("/auth/register")
async def register(req: RegisterRequest):
    """用户注册"""
    try:
        from src.core.memory import project_memory

        existing = project_memory.get_user_by_username(req.username)
        if existing:
            raise HTTPException(status_code=409, detail="用户名已存在")

        password_hash, password_salt = _hash_password(req.password)
        user_id = project_memory.create_user(req.username, password_hash, password_salt)

        if not user_id:
            raise HTTPException(status_code=500, detail="注册失败")

        token = _create_jwt_token(user_id, req.username)
        return {
            "token": token,
            "user": {"id": user_id, "username": req.username},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")


@router.post("/auth/login")
async def login(req: LoginRequest):
    """用户登录"""
    try:
        from src.core.memory import project_memory

        user = project_memory.get_user_by_username(req.username)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not _verify_password(req.password, user["password_hash"], user.get("password_salt", "")):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        token = _create_jwt_token(user["id"], user["username"])
        return {
            "token": token,
            "user": {"id": user["id"], "username": user["username"]},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="登录失败，请稍后重试")


@router.get("/auth/me")
async def get_me(request: Request):
    """获取当前用户信息"""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user
