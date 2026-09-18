"""随手记路由 — CRUD + AI 文献关联 + 类型管理 + 排序置顶 + AI 分类 + 合并"""
import asyncio
import json
import logging
import math

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from api.deps import require_auth, verify_project_owner

logger = logging.getLogger(__name__)
router = APIRouter()


class NoteCreate(BaseModel):
    project_id: str
    content: str
    source_url: str = ""
    note_type: str = "general"


class NoteUpdate(BaseModel):
    content: str | None = None
    source_url: str | None = None
    note_type: str | None = None


class NoteTypeCreate(BaseModel):
    project_id: str
    name: str
    color: str = "slate"


class NoteTypeUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class ReorderBody(BaseModel):
    ordered_ids: list[str]


class MergeBody(BaseModel):
    keep_id: str
    absorb_ids: list[str]


class BatchClassifyBody(BaseModel):
    project_id: str


async def _link_papers_for_note(note_content: str, project_id: str) -> list[dict]:
    """对笔记内容做 embedding → 向量检索 top_k=3 → 去重得 paper_id 列表"""
    try:
        from src.core.embedding import vector_store
        from src.core.memory import project_memory

        results = await asyncio.to_thread(
            vector_store.vector_search, note_content, 6
        )
        if not results:
            return []

        seen_papers = set()
        linked = []
        for r in results:
            meta = r.get("metadata", {})
            pid = meta.get("paper_id", "")
            if not pid or pid in seen_papers:
                continue
            seen_papers.add(pid)
            paper_row = project_memory.get_paper_row(pid)
            linked.append({
                "paper_id": pid,
                "title": paper_row.get("title", meta.get("paper_title", "")) if paper_row else meta.get("paper_title", ""),
                "authors": paper_row.get("authors", "") if paper_row else meta.get("authors", ""),
                "distance": r.get("distance", 0),
            })
            if len(linked) >= 3:
                break
        return linked
    except Exception as e:
        logger.warning(f"AI 关联文献失败: {e}")
        return []


# ===== 笔记 CRUD =====

@router.post("/notes")
async def create_note(body: NoteCreate, user: dict = Depends(require_auth)):
    verify_project_owner(body.project_id, user["user_id"])
    from src.core.memory import project_memory

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="笔记内容不能为空")

    # Ensure default types exist
    project_memory.seed_default_types(body.project_id)

    note_id = project_memory.add_note(
        body.project_id, body.content.strip(),
        body.source_url, body.note_type
    )

    linked_papers = await _link_papers_for_note(body.content, body.project_id)
    if linked_papers:
        paper_ids = [p["paper_id"] for p in linked_papers]
        project_memory.update_note_linked_papers(note_id, paper_ids)

    note = project_memory.get_note(note_id)
    note["linked_papers"] = linked_papers
    return note


@router.get("/notes")
async def list_notes(
    project_id: str = Query(...),
    limit: int = Query(20),
    offset: int = Query(0),
    note_type: str = Query(None),
    user: dict = Depends(require_auth),
):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    project_memory.seed_default_types(project_id)
    return project_memory.get_notes(project_id, limit, offset, note_type=note_type)


# ===== 笔记类型 CRUD（固定路径，必须在 /notes/{note_id} 之前注册）=====

@router.get("/notes/types")
async def get_note_types(
    project_id: str = Query(...),
    user: dict = Depends(require_auth),
):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    project_memory.seed_default_types(project_id)
    return project_memory.get_note_types(project_id)


@router.post("/notes/types")
async def create_note_type(body: NoteTypeCreate, user: dict = Depends(require_auth)):
    verify_project_owner(body.project_id, user["user_id"])
    from src.core.memory import project_memory
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="类型名称不能为空")
    tid = project_memory.add_note_type(body.project_id, body.name.strip(), body.color)
    return {"id": tid, "name": body.name, "color": body.color}


@router.put("/notes/types/{type_id}")
async def update_note_type(type_id: str, body: NoteTypeUpdate, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    existing = project_memory.get_note_type(type_id)
    if not existing:
        raise HTTPException(status_code=404, detail="类型不存在")
    verify_project_owner(existing["project_id"], user["user_id"])
    ok = project_memory.rename_note_type(type_id, body.name, body.color)
    return {"status": "ok"}


@router.delete("/notes/types/{type_id}")
async def delete_note_type(type_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    existing = project_memory.get_note_type(type_id)
    if not existing:
        raise HTTPException(status_code=404, detail="类型不存在")
    verify_project_owner(existing["project_id"], user["user_id"])
    ok = project_memory.delete_note_type(type_id)
    return {"status": "ok"}


# ===== 排序与置顶（固定路径，必须在 /notes/{note_id} 之前注册）=====

@router.post("/notes/reorder")
async def reorder_notes(body: ReorderBody, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    # Verify ownership: check first note belongs to user's project
    if body.ordered_ids:
        note = project_memory.get_note(body.ordered_ids[0])
        if note:
            verify_project_owner(note["project_id"], user["user_id"])
    project_memory.reorder_notes(body.ordered_ids)
    return {"status": "ok"}


# ===== AI 自动归类（固定路径，必须在 /notes/{note_id} 之前注册）=====

@router.post("/notes/batch-classify")
async def batch_classify(body: BatchClassifyBody, user: dict = Depends(require_auth)):
    verify_project_owner(body.project_id, user["user_id"])
    from src.core.memory import project_memory
    from src.core.llm import llm_client

    project_memory.seed_default_types(body.project_id)
    types = project_memory.get_note_types(body.project_id)
    type_names = [t["name"] for t in types]

    # Get notes with default 'general' type, limit 20
    all_notes = project_memory.get_notes(body.project_id, limit=50)
    general_notes = [n for n in all_notes if n.get("note_type") == "general"][:20]

    if not general_notes:
        return {"classified": 0}

    # Build a set of valid note IDs for this batch
    valid_ids = {n["id"] for n in general_notes}

    notes_summary = [
        {"id": n["id"], "content": n["content"][:200]}
        for n in general_notes
    ]
    prompt = (
        f"将以下笔记分配到最合适的分类中。\n"
        f"可用分类: {json.dumps(type_names, ensure_ascii=False)}\n"
        f"笔记列表:\n{json.dumps(notes_summary, ensure_ascii=False)}\n\n"
        f"返回 JSON 数组: [{{\"id\": \"笔记id\", \"type\": \"分类名\"}}, ...]\n"
        f"只返回 JSON，不要其他内容。"
    )
    try:
        result = await llm_client.achat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=2000
        )
        if isinstance(result, list):
            classified = 0
            for item in result:
                nid = item.get("id", "")
                ntype = item.get("type", "")
                # Validate ID belongs to this batch
                if nid not in valid_ids:
                    continue
                # Strict match: exact or contains with min length
                matched = None
                for tn in type_names:
                    if ntype == tn or (len(ntype) >= 2 and tn in ntype):
                        matched = tn
                        break
                if not matched and type_names:
                    matched = type_names[0]
                if matched:
                    project_memory.update_note(nid, note_type=matched)
                    classified += 1
            return {"classified": classified}
    except Exception as e:
        logger.warning(f"批量分类失败: {e}")
    return {"classified": 0}


# ===== 笔记合并（固定路径，必须在 /notes/{note_id} 之前注册）=====

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@router.post("/notes/merge-suggestions")
async def merge_suggestions(body: BatchClassifyBody, user: dict = Depends(require_auth)):
    verify_project_owner(body.project_id, user["user_id"])
    from src.core.memory import project_memory
    from src.core.embedding import embedding_manager

    notes = project_memory.get_notes(body.project_id, limit=50)
    if len(notes) < 2:
        return {"pairs": []}

    contents = [n["content"] for n in notes]
    embeddings = await asyncio.to_thread(embedding_manager.embed, contents)

    pairs = []
    for i in range(len(notes)):
        for j in range(i + 1, len(notes)):
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim > 0.80:
                pairs.append({
                    "note_a": {"id": notes[i]["id"], "content": notes[i]["content"][:150], "type": notes[i].get("note_type", "general")},
                    "note_b": {"id": notes[j]["id"], "content": notes[j]["content"][:150], "type": notes[j].get("note_type", "general")},
                    "similarity": round(sim, 3),
                })
    pairs.sort(key=lambda x: x["similarity"], reverse=True)
    return {"pairs": pairs[:10]}


@router.post("/notes/merge")
async def merge_notes(body: MergeBody, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    # Verify ownership of keep note
    keep = project_memory.get_note(body.keep_id)
    if not keep:
        raise HTTPException(status_code=404, detail="目标笔记不存在")
    verify_project_owner(keep["project_id"], user["user_id"])
    result = project_memory.merge_notes(body.keep_id, body.absorb_ids)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ===== 参数化路由（必须在所有固定路径之后注册）=====

@router.get("/notes/{note_id}")
async def get_note(note_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    note = project_memory.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(note["project_id"], user["user_id"])
    return note


@router.put("/notes/{note_id}")
async def update_note(note_id: str, body: NoteUpdate, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    existing = project_memory.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(existing["project_id"], user["user_id"])
    project_memory.update_note(
        note_id, body.content, body.source_url, body.note_type
    )
    return project_memory.get_note(note_id)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    note = project_memory.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(note["project_id"], user["user_id"])
    ok = project_memory.delete_note(note_id)
    return {"status": "ok", "note_id": note_id}


@router.post("/notes/{note_id}/link-papers")
async def relink_papers(note_id: str, user: dict = Depends(require_auth)):
    """手动触发 AI 关联（重跑推荐）"""
    from src.core.memory import project_memory
    note = project_memory.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(note["project_id"], user["user_id"])

    linked_papers = await _link_papers_for_note(note["content"], note["project_id"])
    paper_ids = [p["paper_id"] for p in linked_papers]
    project_memory.update_note_linked_papers(note_id, paper_ids)

    updated = project_memory.get_note(note_id)
    updated["linked_papers"] = linked_papers
    return updated


@router.post("/notes/{note_id}/pin")
async def toggle_pin(note_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    note = project_memory.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(note["project_id"], user["user_id"])
    result = project_memory.toggle_pin(note_id)
    return result


@router.post("/notes/{note_id}/suggest-type")
async def suggest_type(note_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    from src.core.llm import llm_client

    note = project_memory.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    verify_project_owner(note["project_id"], user["user_id"])

    types = project_memory.get_note_types(note["project_id"])
    type_names = [t["name"] for t in types]
    if not type_names:
        return {"suggested_type": "通用笔记", "confidence": 0.5}

    prompt = (
        f"根据以下笔记内容，从给定的分类中选择最匹配的一个。\n"
        f"可用分类: {json.dumps(type_names, ensure_ascii=False)}\n"
        f"笔记内容: {note['content'][:500]}\n\n"
        f"返回 JSON: {{\"type\": \"最匹配的分类名\", \"confidence\": 0.0-1.0}}\n"
        f"只返回 JSON，不要其他内容。"
    )
    try:
        result = await llm_client.achat_json(
            [{"role": "user", "content": prompt}],
            temperature=0.1, max_tokens=200
        )
        suggested = result.get("type", "通用笔记")
        confidence = result.get("confidence", 0.5)
        return {"suggested_type": suggested, "confidence": round(confidence, 2)}
    except Exception as e:
        logger.warning(f"AI 分类失败: {e}")
        return {"suggested_type": "通用笔记", "confidence": 0.0}
