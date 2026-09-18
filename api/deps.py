"""FastAPI 依赖注入 — 认证守卫"""
from fastapi import Depends, HTTPException, Request

from api.routes.auth import get_current_user


async def require_auth(request: Request) -> dict:
    """依赖注入：要求有效的 JWT token，否则返回 401"""
    user = get_current_user(request)
    if not user or not user.get("user_id"):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


def verify_project_owner(project_id: str, user_id: str) -> None:
    """Verify the authenticated user owns the project. Raises 403 if not.

    Security (P0.7): Earlier versions treated ``owner == ""`` as a legacy
    project and allowed ANY authenticated user to access it — including
    modify/export/delete cascades. Legacy projects now require explicit
    ownership; if the owner field is missing the request is rejected with
    403 and the user is told to re-create the project (data migration is
    deliberate, not automatic, to avoid silently handing data to the
    wrong account).
    """
    from src.core.memory import project_memory
    project = project_memory.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    owner = project.get("user_id", "")
    # Reject legacy projects without explicit owner — no silent takeover.
    if not owner:
        raise HTTPException(
            status_code=403,
            detail="该项目缺少所有者信息，无法验证归属；请重新创建项目后再使用。",
        )
    if owner != user_id:
        raise HTTPException(status_code=403, detail="无权访问该项目")
