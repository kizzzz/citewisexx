"""API Key 管理路由 — 多供应商 API Key 验证与配置记录"""
import logging

from fastapi import APIRouter, HTTPException, Request, Depends

from api.deps import require_auth
from api.schemas import ApiKeyVerifyRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# 预置供应商配置
PROVIDERS = {
    "zhipu": {
        "name": "智谱 (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "verify_url": "https://open.bigmodel.cn/api/paas/v4/models",
        "auth_header": "Bearer",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1/",
        "verify_url": "https://api.deepseek.com/v1/models",
        "auth_header": "Bearer",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1/",
        "verify_url": "https://api.openai.com/v1/models",
        "auth_header": "Bearer",
    },
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1/",
        "verify_url": "https://api.moonshot.cn/v1/models",
        "auth_header": "Bearer",
    },
    "qwen": {
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/",
        "verify_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "auth_header": "Bearer",
    },
    "custom": {
        "name": "自定义 (OpenAI 兼容)",
        "base_url": "",
        "verify_url": "",
        "auth_header": "Bearer",
    },
}


@router.get("/apikeys/providers")
async def list_providers():
    """获取支持的供应商列表"""
    return {
        "providers": {
            key: {"name": v["name"], "base_url": v["base_url"]}
            for key, v in PROVIDERS.items()
        }
    }


@router.post("/apikeys/verify")
async def verify_api_key(req: ApiKeyVerifyRequest):
    """验证 API Key 有效性 — 根据 provider 调用对应 models 接口"""
    import httpx

    api_key = req.api_key.strip()
    provider = req.provider or "zhipu"
    base_url = req.base_url.strip() if req.base_url else ""

    if not api_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空")

    # Get provider config
    prov = PROVIDERS.get(provider, PROVIDERS["custom"])

    # Determine verify URL
    if provider == "custom" and base_url:
        verify_url = base_url.rstrip("/") + "/models"
    else:
        verify_url = prov["verify_url"]

    if not verify_url:
        return {"valid": False, "message": "无法确定验证地址，请填写 Base URL"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                verify_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                return {
                    "valid": True,
                    "models": models,
                    "models_count": len(models),
                    "provider": prov["name"],
                    "base_url": base_url or prov["base_url"],
                    "message": f"验证成功，{prov['name']} 可用模型 {len(models)} 个",
                }
            else:
                return {
                    "valid": False,
                    "message": f"验证失败 (HTTP {resp.status_code})，请检查 Key 和供应商是否匹配",
                }
    except httpx.ConnectError:
        return {"valid": False, "message": "无法连接服务器，请检查 Base URL 是否正确"}
    except Exception as e:
        logger.error(f"API Key 验证请求失败: {e}")
        return {"valid": False, "message": "验证请求失败，请检查网络或代理设置"}


@router.post("/apikeys/save")
async def save_user_api_key_config(req: Request, user: dict = Depends(require_auth)):
    """记录用户已配置 API Key（仅保存布尔标记，密钥本身由前端 localStorage 管理）。

    Security (P0.5): Always use the authenticated user_id from the JWT token.
    Earlier versions read ``user_id`` from the request body, which allowed a
    logged-in user to write the ``api_key configured`` flag against another
    user's account (IDOR). The body field is now ignored.
    """
    body = await req.json()
    # 强制使用 JWT 鉴权身份，忽略 body 中的 user_id（防止越权写入他人配置）
    user_id = user["user_id"]
    has_key = bool(body.get("api_key", "").strip())

    from src.core.memory import project_memory

    target_user = project_memory.get_user_by_id(user_id)
    if target_user:
        project_memory.update_user_api_key(user_id, "configured" if has_key else "")
        return {"status": "ok", "message": "API Key 配置已记录"}

    return {"status": "ok", "message": "API Key 仅存储在本地"}
