"""论文管理路由"""
import os
import re
import uuid
import json
import asyncio
import logging

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from api.deps import require_auth, verify_project_owner
from config.settings import PAPERS_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

from src.core.file_parser import is_supported, get_file_extension, parse_file


@router.get("/papers")
async def list_papers(project_id: str, user: dict = Depends(require_auth)):
    verify_project_owner(project_id, user["user_id"])
    from src.core.memory import project_memory
    return project_memory.get_papers(project_id)


@router.post("/papers/upload")
async def upload_papers(files: list[UploadFile] = File(...), project_id: str = Form(...), user: dict = Depends(require_auth)):
    """上传论文 — JSON 响应（适合简单前端）"""
    verify_project_owner(project_id, user["user_id"])
    result = await _process_uploads(files, project_id)
    return result


@router.post("/papers/upload/stream")
async def upload_papers_stream(files: list[UploadFile] = File(...), project_id: str = Form(...), user: dict = Depends(require_auth)):
    """上传论文 — SSE 流式返回进度（适合需要实时进度的前端）"""
    verify_project_owner(project_id, user["user_id"])
    async def progress_generator():
        from src.core.rag import chunk_paper
        from src.core.memory import project_memory

        total = len(files)
        all_chunks = []
        fig_count = 0
        processed = 0

        yield {"event": "progress", "data": json.dumps({
            "phase": "uploading", "total": total, "current": 0
        }, ensure_ascii=False)}

        for idx, f in enumerate(files):
            original_name = os.path.basename(f.filename or "unknown")
            ext = get_file_extension(original_name)
            safe_name = f"{uuid.uuid4().hex}{ext}"

            # Validate file extension
            if not is_supported(original_name):
                yield {"event": "warning", "data": json.dumps({
                    "file": original_name, "error": "不支持的文件格式",
                }, ensure_ascii=False)}
                continue

            # Read content for validation
            content = await f.read()
            if len(content) > MAX_FILE_SIZE:
                yield {"event": "warning", "data": json.dumps({
                    "file": original_name, "error": "File exceeds 50MB size limit",
                }, ensure_ascii=False)}
                continue

            path = os.path.join(PAPERS_DIR, safe_name)
            with open(path, "wb") as fp:
                fp.write(content)

            yield {"event": "progress", "data": json.dumps({
                "phase": "parsing", "file": original_name,
                "current": idx + 1, "total": total,
            }, ensure_ascii=False)}

            try:
                data = await asyncio.to_thread(parse_file, path, safe_name)
                chunks = await asyncio.to_thread(chunk_paper, data)

                sections_json = json.dumps(
                    data.get("sections", []),
                    ensure_ascii=False
                )
                raw_text = data.get("raw_text", "")

                project_memory.add_paper(
                    data["paper_id"], project_id,
                    data.get("title", original_name), data.get("authors", ""),
                    data.get("year", 0), safe_name, len(chunks),
                    raw_text=raw_text, sections_json=sections_json
                )
                all_chunks.extend(chunks)

                for fig in data.get("figures", []):
                    project_memory.add_figure(
                        fig["figure_id"], data["paper_id"], project_id,
                        fig["page"], fig["caption"],
                        fig.get("context_before", ""), fig.get("context_after", ""),
                        fig.get("section_title", ""),
                        fig.get("width", 0), fig.get("height", 0)
                    )
                    fig_count += 1
                processed += 1

                yield {"event": "progress", "data": json.dumps({
                    "phase": "parsed", "file": original_name,
                    "chunks": len(chunks),
                    "current": idx + 1, "total": total,
                }, ensure_ascii=False)}

            except Exception as e:
                logger.error(f"解析 {original_name} 失败: {e}", exc_info=True)
                yield {"event": "warning", "data": json.dumps({
                    "file": original_name, "error": "文件解析失败，请稍后重试",
                }, ensure_ascii=False)}

        # 索引阶段
        if all_chunks:
            yield {"event": "progress", "data": json.dumps({
                "phase": "indexing", "chunks": len(all_chunks),
            }, ensure_ascii=False)}

            from src.core.embedding import vector_store
            from src.core.retriever import bm25_index

            await asyncio.to_thread(vector_store.index_chunks, all_chunks)
            await asyncio.to_thread(bm25_index.add_chunks, all_chunks)
            await asyncio.to_thread(bm25_index.save)

        # Invalidate recommender / knowledge-map caches for this project so
        # newly indexed papers show up immediately, then pre-warm paper-level
        # embeddings in the background so the first knowledge-map / recommend
        # request isn't slow.
        try:
            from src.core.recommender import invalidate_project_cache
            invalidate_project_cache(project_id)
        except Exception:
            pass
        try:
            asyncio.create_task(_precompute_paper_embeddings(project_id))
        except Exception:
            pass

        yield {"event": "done", "data": json.dumps({
            "message": f"已入库 {processed} 篇论文，{len(all_chunks)} 个片段" +
                       (f"，{fig_count} 张图表" if fig_count else ""),
            "chunks_count": len(all_chunks),
            "papers_count": processed,
        }, ensure_ascii=False)}

    return EventSourceResponse(progress_generator())


async def _precompute_paper_embeddings(project_id: str) -> None:
    """Background task: warm paper-level embedding cache after upload.

    Runs after upload completes so the user doesn't pay the ChromaDB round-trip
    on the first knowledge-map / recommendations call. Failures are swallowed
    because this is strictly an optimization — cached entries are recomputed
    lazily on demand.
    """
    try:
        from src.core.recommender import get_paper_embeddings, invalidate_project_cache
        # Force refresh here so we recompute for the newly-added papers.
        get_paper_embeddings(project_id, force_refresh=True)
        invalidate_project_cache(project_id)
    except Exception as e:
        logger.warning(f"Pre-compute paper embeddings failed: {e}")


async def _process_uploads(files: list[UploadFile], project_id: str) -> dict:
    """处理上传文件的共享逻辑"""
    from src.core.rag import chunk_paper
    from src.core.embedding import vector_store
    from src.core.retriever import bm25_index
    from src.core.memory import project_memory

    all_chunks = []
    fig_count = 0
    processed = 0

    for f in files:
        original_name = os.path.basename(f.filename or "unknown")
        ext = get_file_extension(original_name)
        safe_name = f"{uuid.uuid4().hex}{ext}"

        # Validate file extension
        if not is_supported(original_name):
            logger.warning(f"跳过不支持的文件格式: {original_name}")
            continue

        # Read content for validation
        file_content = await f.read()
        if len(file_content) > MAX_FILE_SIZE:
            logger.warning(f"跳过超大文件: {original_name}")
            continue

        path = os.path.join(PAPERS_DIR, safe_name)
        with open(path, "wb") as fp:
            fp.write(file_content)

        try:
            data = await asyncio.to_thread(parse_file, path, safe_name)
            chunks = await asyncio.to_thread(chunk_paper, data)
            sections_json = json.dumps(
                data.get("sections", []),
                ensure_ascii=False
            )
            raw_text = data.get("raw_text", "")
            project_memory.add_paper(
                data["paper_id"], project_id,
                data.get("title", original_name), data.get("authors", ""),
                data.get("year", 0), safe_name, len(chunks),
                raw_text=raw_text, sections_json=sections_json
            )
            all_chunks.extend(chunks)

            for fig in data.get("figures", []):
                project_memory.add_figure(
                    fig["figure_id"], data["paper_id"], project_id,
                    fig["page"], fig["caption"],
                    fig.get("context_before", ""), fig.get("context_after", ""),
                    fig.get("section_title", ""),
                    fig.get("width", 0), fig.get("height", 0)
                )
                fig_count += 1
            processed += 1
        except Exception as e:
            logger.error(f"解析 {safe_name} 失败: {e}")

    if all_chunks:
        await asyncio.to_thread(vector_store.index_chunks, all_chunks)
        await asyncio.to_thread(bm25_index.add_chunks, all_chunks)
        await asyncio.to_thread(bm25_index.save)

    try:
        from src.core.recommender import invalidate_project_cache
        invalidate_project_cache(project_id)
    except Exception:
        pass
    try:
        asyncio.create_task(_precompute_paper_embeddings(project_id))
    except Exception:
        pass

    return {
        "message": f"已入库 {processed} 篇论文，{len(all_chunks)} 个片段" +
                   (f"，{fig_count} 张图表" if fig_count else ""),
        "chunks_count": len(all_chunks),
        "papers_count": processed,
    }


@router.delete("/papers/{paper_id}")
async def delete_paper(paper_id: str, project_id: str = "", user: dict = Depends(require_auth)):
    """删除论文及其向量索引"""
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    verify_project_owner(project_id, user["user_id"])

    from src.core.memory import project_memory
    from src.core.embedding import vector_store
    from src.core.retriever import bm25_index

    # Verify paper belongs to project
    papers = project_memory.get_papers(project_id)
    if not any(p["id"] == paper_id for p in papers):
        raise HTTPException(status_code=404, detail="Paper not found in project")

    vector_store.delete_paper(paper_id)
    project_memory.delete_paper_cascade(paper_id)

    # 重建 BM25 索引（删除后全量重建）
    all_chunks = await asyncio.to_thread(vector_store.get_all_chunks)
    if all_chunks:
        await asyncio.to_thread(bm25_index.build_index, all_chunks)
    else:
        bm25_index.bm25 = None
    await asyncio.to_thread(bm25_index.save)

    try:
        from src.core.recommender import invalidate_project_cache
        invalidate_project_cache(project_id)
    except Exception:
        pass

    return {"status": "ok", "paper_id": paper_id}


@router.get("/papers/{paper_id}")
async def get_paper_detail(paper_id: str, user: dict = Depends(require_auth)):
    from src.core.memory import project_memory
    from src.core.embedding import vector_store

    row = project_memory.get_paper_row(paper_id)
    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper = dict(row)

    # Strategy 1: Read from SQLite raw_text / sections_json (persisted at upload time)
    raw_text = paper.get("raw_text", "") or ""
    sections_json_str = paper.get("sections_json", "[]") or ""
    sections = []
    try:
        sections = json.loads(sections_json_str) if sections_json_str else []
    except (json.JSONDecodeError, TypeError):
        sections = []

    # Fast path: anything usable in SQLite is returned immediately (ms-level latency).
    if sections and any(s.get("text", "").strip() for s in sections):
        paper["abstract"] = ""
        paper["sections"] = [
            {
                "title": s.get("title", "全文"),
                "level": "L1",
                "text": s.get("text", ""),
            }
            for s in sections
        ]
        paper["full_text"] = raw_text or "\n\n".join(
            s.get("text", "") for s in sections
        )
        # Strip heavy fields the front-end doesn't need in the detail view.
        paper.pop("raw_text", None)
        paper.pop("sections_json", None)
        paper.pop("avg_embedding", None)
        return paper

    # If raw_text is rich enough, segment it cheaply in-memory and return fast —
    # avoids the expensive ChromaDB round-trip that was causing "加载中" to hang.
    if len(raw_text) > 200:
        paper["sections"] = _segment_raw_text(raw_text)
        paper["abstract"] = paper["sections"][0]["text"][:500] if paper["sections"] else ""
        paper["full_text"] = raw_text
        paper.pop("raw_text", None)
        paper.pop("sections_json", None)
        paper.pop("avg_embedding", None)
        return paper

    # Strategy 2: Fallback to ChromaDB chunks (no embeddings — text only).
    try:
        chunks = await asyncio.to_thread(
            lambda: vector_store.get_chunks_by_paper(paper_id, include_embedding=False)
        )
        if chunks:
            grouped = []
            current_section = None
            for c in chunks:
                title = c.get("section_title", "全文")
                if not current_section or current_section["title"] != title:
                    current_section = {"title": title, "level": c.get("section_level", "L2"), "text": c["text"]}
                    grouped.append(current_section)
                else:
                    current_section["text"] += "\n\n" + c["text"]

            abstract = ""
            for s in grouped:
                if s["level"] == "L0":
                    abstract = s["text"]
                    break

            paper["abstract"] = abstract
            paper["sections"] = grouped
            paper["full_text"] = "\n\n".join(s["text"] for s in grouped)
        else:
            paper["abstract"] = raw_text[:500] if raw_text else "暂无内容"
            paper["sections"] = []
            paper["full_text"] = raw_text or ""
    except Exception as e:
        logger.error(f"获取论文 chunks 失败: {e}")
        paper["abstract"] = raw_text[:500] if raw_text else "加载失败"
        paper["sections"] = []
        paper["full_text"] = raw_text or ""

    paper.pop("raw_text", None)
    paper.pop("sections_json", None)
    paper.pop("avg_embedding", None)
    return paper


def _segment_raw_text(raw_text: str) -> list[dict]:
    """Cheap in-memory segmentation of raw paper text.

    Avoids the ChromaDB round-trip when SQLite already has a usable raw_text
    but no structured sections_json. Splits on common section headings + double
    newlines. Returns ``[{title, level, text}, ...]``.
    """
    if not raw_text:
        return []
    heading_re = re.compile(
        r"(?m)^\s*(?:"
        r"(?:Abstract|Introduction|Background|Related\s+Work|Methods?|Materials?[^.\n]*|"
        r"Results?|Discussion|Conclusions?|References?|Acknowledg(?:e)?ments?|附录|摘要|"
        r"引言|前言|背景|相关工作|方法|实验|结果|讨论|结论|参考文献|致谢)"
        r"[^\n]{0,80})"
        r"\s*$"
    )
    sections: list[dict] = []
    current_title = "全文"
    current_level = "L1"
    buf: list[str] = []

    def flush():
        nonlocal buf
        if buf:
            text = "\n".join(buf).strip()
            if text:
                sections.append({
                    "title": current_title,
                    "level": current_level,
                    "text": text,
                })
            buf = []

    for line in raw_text.splitlines():
        if heading_re.match(line):
            flush()
            current_title = line.strip()[:120] or "章节"
            current_level = "L1"
        else:
            buf.append(line)
    flush()

    if not sections:
        # Fallback: split by blank lines into ~3000-char chunks so the UI has
        # multiple cards instead of one giant wall of text.
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw_text) if p.strip()]
        chunk_size = 3000
        text_acc = ""
        for p in paragraphs:
            if len(text_acc) + len(p) > chunk_size and text_acc:
                sections.append({"title": "全文", "level": "L2", "text": text_acc})
                text_acc = ""
            text_acc = (text_acc + "\n\n" + p).strip() if text_acc else p
        if text_acc:
            sections.append({"title": "全文", "level": "L2", "text": text_acc})
    return sections


class PaperTitleUpdate(BaseModel):
    title: str


@router.patch("/papers/{paper_id}/title")
async def update_paper_title(paper_id: str, body: PaperTitleUpdate, user: dict = Depends(require_auth)):
    """Update a paper's title"""
    from src.core.memory import project_memory

    paper = project_memory.get_paper_row(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    project_memory.update_paper_title(paper_id, body.title.strip())
    return {"status": "ok", "paper_id": paper_id, "title": body.title.strip()}
