"""CiteWise 配置文件"""
import os
from dotenv import load_dotenv

# 加载 .env 文件（静默忽略缺失）
load_dotenv(override=False)

# === 项目根目录（自动检测）===
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# === LLM 配置（智谱 GLM）===
# 优先级: 环境变量 > .env 文件
def _get_config(key: str, default: str = "") -> str:
    """从环境变量获取配置（.env 已由 load_dotenv 加载）"""
    return os.getenv(key, default)

OPENAI_API_KEY = _get_config("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    import warnings
    warnings.warn("OPENAI_API_KEY not set — set it via .env or environment variable")
OPENAI_BASE_URL = _get_config("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
LLM_MODEL = _get_config("LLM_MODEL", "glm-4.7")

# === Embedding 配置（智谱）===
EMBEDDING_MODEL = _get_config("EMBEDDING_MODEL", "embedding-3")
EMBEDDING_DIMENSION = int(_get_config("EMBEDDING_DIMENSION", "2048"))

# === 向量库配置 ===
CHROMA_PATH = os.path.join(_PROJECT_ROOT, "data", "db", "chroma")

# === 项目数据路径 ===
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
PAPERS_DIR = os.path.join(DATA_DIR, "papers")
FIGURES_DIR = os.path.join(DATA_DIR, "figures")
DB_PATH = os.path.join(DATA_DIR, "db", "citewise.db")
PROFILE_PATH = os.path.join(DATA_DIR, "user_profile.json")

# === 切片配置 ===
CHUNK_MIN_SIZE = 200           # 最小 chunk 字符数
CHUNK_MAX_SIZE = 1500          # 最大 chunk 字符数
CHUNK_TARGET_SIZE = 800        # 目标 chunk 大小（努力趋近）
SENTENCE_OVERLAP_COUNT = 2     # 相邻 chunk 重叠的句子数

# === 检索配置 ===
VECTOR_TOP_K = 20
BM25_TOP_K = 20
RERANK_TOP_K = 5
RRF_K = 60

# === Phase 1: 查询改写 + BM25 持久化 + Embedding 缓存 ===
ENABLE_QUERY_REWRITE = _get_config("ENABLE_QUERY_REWRITE", "true").lower() == "true"
ENABLE_HYDE = _get_config("ENABLE_HYDE", "false").lower() == "true"
BM25_INDEX_PATH = os.path.join(DATA_DIR, "db", "bm25_index.pkl")
EMBEDDING_CACHE_SIZE = int(_get_config("EMBEDDING_CACHE_SIZE", "10000"))

# === Phase 2: 专用 Reranker + 父子 Chunk ===
RERANKER_TYPE = _get_config("RERANKER_TYPE", "mmr")  # mmr | cross_encoder | llm
RERANKER_MODEL = _get_config("RERANKER_MODEL", "")
ENABLE_PARENT_CHUNK_EXPANSION = _get_config("ENABLE_PARENT_CHUNK_EXPANSION", "true").lower() == "true"

# === Phase 3: 意图感知 + 查询缓存 ===
ENABLE_INTENT_RETRIEVAL = _get_config("ENABLE_INTENT_RETRIEVAL", "true").lower() == "true"
ENABLE_QUERY_CACHE = _get_config("ENABLE_QUERY_CACHE", "true").lower() == "true"
QUERY_CACHE_TTL = int(_get_config("QUERY_CACHE_TTL", "300"))
QUERY_CACHE_MAX_SIZE = int(_get_config("QUERY_CACHE_MAX_SIZE", "500"))

# === Phase 4: 多查询 + 分数归一化 ===
ENABLE_MULTI_QUERY = _get_config("ENABLE_MULTI_QUERY", "true").lower() == "true"
MULTI_QUERY_MAX_SUBQUERIES = int(_get_config("MULTI_QUERY_MAX_SUBQUERIES", "3"))
ENABLE_SCORE_NORMALIZATION = _get_config("ENABLE_SCORE_NORMALIZATION", "true").lower() == "true"

# === 确保目录存在 ===
for d in [DATA_DIR, PAPERS_DIR, FIGURES_DIR, os.path.dirname(DB_PATH), CHROMA_PATH]:
    os.makedirs(d, exist_ok=True)
