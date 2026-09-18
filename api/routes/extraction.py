"""结构化提取路由"""
import asyncio
import io
import json
import logging

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from api.deps import require_auth, verify_project_owner
from api.schemas import ExtractionRequest, FieldsRequest

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_FIELDS = ["研究方法", "核心算法", "数据集", "主要结论"]
MAX_FIELDS_COUNT = 10


@router.get("/fields")
async def get_fields():
    return {"fields": DEFAULT_FIELDS}


@router.post("/fields")
async def save_fields(req: FieldsRequest, user: dict = Depends(require_auth)):
    if not req.fields:
        raise HTTPException(status_code=422, detail="Fields list must not be empty")
    if len(req.fields) > MAX_FIELDS_COUNT:
        raise HTTPException(status_code=422, detail=f"Fields list must not exceed {MAX_FIELDS_COUNT} items")
    return {"fields": req.fields}


@router.post("/extraction")
async def run_extraction(req: ExtractionRequest, user: dict = Depends(require_auth)):
    verify_project_owner(req.project_id, user["user_id"])
    if not req.fields:
        raise HTTPException(status_code=422, detail="Fields list must not be empty")
    if len(req.fields) > MAX_FIELDS_COUNT:
        raise HTTPException(status_code=422, detail=f"Fields list must not exceed {MAX_FIELDS_COUNT} items")
    from src.core.memory import project_memory
    from src.core.retriever import hybrid_search, format_chunks_with_citations
    from src.core.prompt import prompt_engine, SYSTEM_PROMPT_BASE
    from src.core.llm import llm_client

    papers = project_memory.get_papers(req.project_id)
    if not papers:
        return []

    results = []
    for p in papers[:10]:
        try:
            chunks = await asyncio.to_thread(
                hybrid_search, ", ".join(req.fields), top_k=5,
                where={"paper_id": p["id"]}
            )
            if not chunks:
                continue

            txt = format_chunks_with_citations(chunks)
            ext = await asyncio.to_thread(
                llm_client.chat_json,
                [
                    {"role": "system", "content": SYSTEM_PROMPT_BASE},
                    {"role": "user", "content": prompt_engine.build_extract_prompt(req.fields, txt)},
                ],
                temperature=0.3,
            )

            if "fields" in ext:
                project_memory.save_extraction(
                    req.project_id, p["id"], "自定义",
                    ext.get("fields", {}), ext.get("confidence", {})
                )
                results.append({
                    "paper_title": p["title"],
                    "authors": p["authors"],
                    "year": p.get("year", ""),
                    **ext.get("fields", {}),
                })
        except Exception as e:
            logger.error(f"提取 {p.get('title', '')} 失败: {e}")

    return results


@router.get("/extraction/export")
async def export_extraction(project_id: str, user: dict = Depends(require_auth)):
    """导出结构化提取结果为 Excel 文件"""
    verify_project_owner(project_id, user["user_id"])
    import pandas as pd
    from src.core.memory import project_memory

    extractions = project_memory.get_extractions(project_id)
    if not extractions:
        raise HTTPException(status_code=404, detail="No extraction data found for this project")

    rows = []
    for ext in extractions:
        row = {
            "paper_id": ext.get("paper_id"),
            "template": ext.get("template_name"),
        }
        fields = ext.get("fields", {})
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except json.JSONDecodeError:
                fields = {}
        row.update(fields)
        rows.append(row)

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="结构化总结")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=extraction_results.xlsx"},
    )
