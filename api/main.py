"""CiteWise V3 — FastAPI 主入口"""
import sys
import os
import time
import logging
from collections import defaultdict

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from api.routes import chat, projects, papers, sections, extraction, search, auth, apikeys, recommendations, knowledge_map, submit, notes
from src.eval.dashboard import router as eval_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === In-memory rate limiter ===
import threading

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
RATE_LIMIT_MAX_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_IPS = 10000
_last_cleanup = time.time()
CLEANUP_INTERVAL = 60  # seconds


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For header."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(client_ip: str) -> bool:
    """Check whether a client IP has exceeded the rate limit. Thread-safe."""
    global _last_cleanup
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    with _rate_limit_lock:
        # Periodic cleanup of stale entries
        if now - _last_cleanup > CLEANUP_INTERVAL:
            stale = [ip for ip, times in _rate_limit_store.items()
                     if not times or times[-1] < window_start]
            for ip in stale:
                del _rate_limit_store[ip]
            _last_cleanup = now

        request_times = _rate_limit_store[client_ip]
        request_times[:] = [t for t in request_times if t > window_start]
        if len(request_times) >= RATE_LIMIT_MAX_REQUESTS:
            return True
        request_times.append(now)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化 BM25 索引（优先加载持久化索引）"""
    try:
        from src.core.retriever import bm25_index
        # 先尝试加载序列化索引
        if bm25_index.load():
            logger.info(f"BM25 索引从缓存加载成功")
        else:
            # 缓存不存在，从 ChromaDB 全量重建
            from src.core.embedding import vector_store
            all_chunks = vector_store.get_all_chunks()
            if all_chunks:
                bm25_index.build_index(all_chunks)
                bm25_index.save()
                logger.info(f"BM25 索引已构建并保存，共 {len(all_chunks)} 个片段")
    except Exception as e:
        logger.warning(f"BM25 初始化失败: {e}")

    # Initialize eval database
    try:
        from src.eval.metrics import init_eval_db
        from config.settings import DB_PATH
        eval_db_path = os.path.join(os.path.dirname(DB_PATH), "eval.db")
        init_eval_db(eval_db_path)
        logger.info(f"Eval DB 已初始化: {eval_db_path}")
    except Exception as e:
        logger.warning(f"Eval DB 初始化失败: {e}")

    yield


app = FastAPI(title="CiteWise V3", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# === Rate limiting middleware ===
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = _get_client_ip(request)
    if _is_rate_limited(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."}
        )
    return await call_next(request)


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5328",
        "http://127.0.0.1:5328",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:10000",
        "http://127.0.0.1:10000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "https://cite-wise-mu.vercel.app",
        "https://citewise-w9op.onrender.com",
        "https://citewise-msshk9qg.edgeone.cool",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(chat.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(papers.router, prefix="/api")
app.include_router(sections.router, prefix="/api")
app.include_router(extraction.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(apikeys.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(knowledge_map.router, prefix="/api")
app.include_router(submit.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(eval_router, prefix="/api")


# 静态文件
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    # 额外挂载子目录，使相对路径在前后端分离部署时也能工作
    for _sub in ("vendor", "js", "css", "html"):
        _sub_dir = os.path.join(static_dir, _sub)
        if os.path.isdir(_sub_dir):
            app.mount(f"/{_sub}", StaticFiles(directory=_sub_dir), name=f"static-{_sub}")


@app.get("/")
async def root():
    """提供 SPA 入口"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "CiteWise V3 API is running", "docs": "/docs"}
