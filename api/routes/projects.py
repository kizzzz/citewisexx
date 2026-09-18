"""项目管理路由"""
import logging

from fastapi import APIRouter, Depends

from api.deps import require_auth, verify_project_owner
from api.schemas import ProjectCreate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/projects")
async def list_projects(user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    projects = project_memory.list_projects(user_id=user["user_id"])
    return projects


@router.post("/projects")
async def create_project(req: ProjectCreate, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory, global_profile
    pid = project_memory.create_project(req.name, req.topic, user_id=user["user_id"])
    # global_profile.update is non-critical — don't fail project creation if it errors
    try:
        global_profile.update("research_field", req.topic)
    except Exception as e:
        logger.warning(f"Failed to update global profile: {e}")
    project = project_memory.get_project(pid)
    return project


@router.get("/projects/{project_id}/state")
async def get_project_state(project_id: str, user: dict = Depends(require_auth)):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    state = project_memory.get_project_state(project_id)
    return state


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: dict = Depends(require_auth)):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    ok = project_memory.delete_project(project_id, user_id=user["user_id"])
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"detail": "删除成功"}
