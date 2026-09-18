"""PDF 解析与层级切片模块 — 语义切块（embedding-based）+ 图表提取"""
import re
import os
import uuid
import logging
import numpy as np
import pdfplumber
from PyPDF2 import PdfReader

from config.settings import (
    PAPERS_DIR, CHUNK_MIN_SIZE, CHUNK_MAX_SIZE,
    CHUNK_TARGET_SIZE, SENTENCE_OVERLAP_COUNT,
)

logger = logging.getLogger(__name__)


# ================================================================
#  PDF 解析（保持原逻辑，仅微调）
# ================================================================

def parse_pdf(pdf_path: str) -> dict:
    """解析 PDF，提取元数据、文本、表格信息"""
    filename = os.path.basename(pdf_path)
    paper_id = f"paper_{uuid.uuid4().hex[:8]}"

    # 提取元数据
    metadata = {"paper_id": paper_id, "filename": filename}
    try:
        reader = PdfReader(pdf_path)
        info = reader.metadata
        if info:
            metadata["title"] = info.title or ""
            metadata["authors"] = info.author or ""
        metadata["page_count"] = len(reader.pages)
    except Exception as e:
        logger.warning(f"元数据提取失败: {e}")
        metadata["page_count"] = 0

    # 用文件名解析标题、作者和年份
    if not metadata.get("title") or not metadata.get("authors") or not metadata.get("year"):
        _parse_from_filename(filename, metadata)

    # 提取文本和表格
    sections = []
    all_figures = []  # 新增：收集图表元数据
    try:
        with pdfplumber.open(pdf_path) as pdf:
            current_section = {"title": "全文", "text": "", "tables": []}
            # 支持英文数字编号 (1.2.3 Title) 和中文编号 (一、引言 / 第一章 引言)
            section_pattern = re.compile(
                r'^(\d+(?:\.\d+)*)\s+([A-Z\u4e00-\u9fff][^\n]{2,80})'
                r'|^[一二三四五六七八九十百]+[、．.]\s*([^\n]{2,80})'
                r'|^第[一二三四五六七八九十百]+[章节]\s*([^\n]{2,80})'
            )

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if not text.strip():
                    continue

                # 提取表格
                tables = page.extract_tables()
                for table in tables:
                    if table and len(table) > 1:
                        table_md = _table_to_markdown(table)
                        current_section["tables"].append({
                            "page": i + 1,
                            "content": table_md,
                            "section_title": current_section["title"],
                        })

                # 提取图表元数据（图片位置 + caption）
                figures_on_page = _extract_figures_from_page(page, i + 1, text)
                all_figures.extend(figures_on_page)

                # 逐行检测章节标题
                lines = text.split('\n')
                buffer_lines = []
                for line in lines:
                    stripped = line.strip()
                    match = section_pattern.match(stripped)
                    if match and len(stripped) < 80:
                        if buffer_lines:
                            current_section["text"] += "\n" + "\n".join(buffer_lines)
                            buffer_lines = []
                        if current_section["text"].strip():
                            sections.append(current_section.copy())
                        # Extract section title from whichever group matched
                        if match.group(1) and match.group(2):
                            # English: "1.2.3 Title"
                            section_title = f"{match.group(1)} {match.group(2).strip()}"
                        elif match.group(3):
                            # Chinese: "一、引言"
                            section_title = match.group(3).strip()
                        elif match.group(4):
                            # Chinese: "第一章 引言"
                            section_title = match.group(4).strip()
                        else:
                            section_title = stripped
                        current_section = {
                            "title": section_title,
                            "text": "",
                            "tables": []
                        }
                    else:
                        buffer_lines.append(line)

                if buffer_lines:
                    current_section["text"] += "\n" + "\n".join(buffer_lines)

            if current_section["text"].strip():
                sections.append(current_section)

    except Exception as e:
        logger.error(f"PDF 文本提取失败: {e}")
        return {**metadata, "sections": [], "raw_text": "", "error": str(e)}

    # 如果没有检测到章节，整篇作为一节
    if not sections:
        all_text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    all_text += (page.extract_text() or "") + "\n"
        except Exception as e:
            logger.warning(f"全文本提取失败: {e}")
        sections = [{"title": "全文", "text": all_text, "tables": []}]

    return {
        **metadata,
        "sections": sections,
        "figures": all_figures,
        "raw_text": "\n".join(s["text"] for s in sections),
    }


# ================================================================
#  层级切片（重构核心）
# ================================================================

def chunk_paper(paper_data: dict) -> list[dict]:
    """将论文按层级切片 — 语义边界感知 + 句子级 overlap

    管道: L0(论文级) → L1(章节级) / L2(段落级) → 表格(带上下文)
    """
    paper_id = paper_data["paper_id"]
    chunks = []

    # Stage 1: L0 论文级（改进的摘要提取）
    abstract = _extract_abstract(paper_data["raw_text"])
    if abstract:
        chunks.append(_build_chunk(
            paper_data, "摘要", "L0", abstract
        ))

    # Stage 2: L1/L2 章节级 + 段落级（语义切片 + overlap）
    for section in paper_data.get("sections", []):
        text = section["text"].strip()
        if not text:
            continue

        section_title = section["title"]
        has_table = len(section.get("tables", [])) > 0

        if len(text) <= CHUNK_TARGET_SIZE:
            # 短章节：整体作为一个 L1 chunk
            chunks.append(_build_chunk(
                paper_data, section_title, "L1", text, has_table=has_table
            ))
        else:
            # 长章节：L1 作为父 chunk，L2 子 chunk 记录 parent_chunk_id
            l1_chunk = _build_chunk(
                paper_data, section_title, "L1", text[:CHUNK_TARGET_SIZE], has_table=has_table
            )
            chunks.append(l1_chunk)

            # 语义切块（embedding-based，自动降级到规则切分）
            sub_texts = _semantic_chunk(text)
            for sub in sub_texts:
                chunks.append(_build_chunk(
                    paper_data, section_title, "L2", sub, has_table=has_table,
                    parent_chunk_id=l1_chunk["chunk_id"]
                ))

    # Stage 3: 表格（带上下文）
    for section in paper_data.get("sections", []):
        section_text = section["text"].strip()
        for table in section.get("tables", []):
            context = _build_table_context(table, section_text)
            chunks.append(_build_chunk(
                paper_data,
                f"{table.get('section_title', section['title'])} - 表格",
                "L2",
                context,
                has_table=True,
            ))

    logger.info(f"论文 {paper_id} 切片完成: {len(chunks)} 个 chunks")
    return chunks


# ================================================================
#  语义切片核心
# ================================================================

def _semantic_chunk(text: str) -> list[str]:
    """Embedding-based 语义切块

    原理: 对每个句子生成 embedding，计算相邻句余弦相似度，
    在相似度骤降处（低于均值-1σ）切分，实现真正的语义边界检测。

    回退: embedding 调用失败时自动降级到规则切分。
    """
    sentences = _split_sentences(text)
    if len(sentences) <= 2:
        return [text] if text.strip() else []

    try:
        from src.core.embedding import embedding_manager
        # 批量 embed 所有句子
        embeddings = embedding_manager.embed(sentences)
        if not embeddings or len(embeddings) != len(sentences):
            logger.warning("Embedding 数量不匹配，降级到规则切分")
            return _split_by_semantic_boundaries(text)

        # 计算相邻句余弦相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            a = np.array(embeddings[i])
            b = np.array(embeddings[i + 1])
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a > 0 and norm_b > 0:
                sim = float(np.dot(a, b) / (norm_a * norm_b))
            else:
                sim = 0.0
            similarities.append(sim)

        if not similarities:
            return _split_by_semantic_boundaries(text)

        # 检测谷值: 低于 mean - 1*std 的位置
        mean_sim = np.mean(similarities)
        std_sim = np.std(similarities)
        threshold = mean_sim - std_sim

        # 在谷值处切分
        split_points = [0]
        for i, sim in enumerate(similarities):
            if sim < threshold and i > 0:
                split_points.append(i + 1)
        split_points.append(len(sentences))

        # 组装 chunks
        chunks = []
        for j in range(len(split_points) - 1):
            start = split_points[j]
            end = split_points[j + 1]
            chunk_text = " ".join(sentences[start:end]).strip()
            if chunk_text:
                chunks.append(chunk_text)

        # 合并过短 chunks
        chunks = _merge_short_chunks(chunks)

        # 添加 overlap
        chunks = _add_sentence_overlap(chunks, sentences)

        logger.info(f"语义切块: {len(sentences)} 句 → {len(chunks)} chunks (threshold={threshold:.3f})")
        return chunks if chunks else _split_by_semantic_boundaries(text)

    except Exception as e:
        logger.warning(f"语义切块失败，降级到规则切分: {e}")
        return _split_by_semantic_boundaries(text)


def _merge_short_chunks(chunks: list[str]) -> list[str]:
    """合并过短的 chunks"""
    merged = []
    buffer = ""
    for chunk in chunks:
        if len(buffer) + len(chunk) < CHUNK_MIN_SIZE:
            buffer += " " + chunk
        else:
            if buffer.strip():
                merged.append(buffer.strip())
            buffer = chunk
    if buffer.strip():
        if merged and len(buffer.strip()) < CHUNK_MIN_SIZE:
            merged[-1] += " " + buffer.strip()
        else:
            merged.append(buffer.strip())
    return merged


def _split_by_semantic_boundaries(text: str) -> list[str]:
    """按语义边界切片，带句子级 overlap

    流程: 句子分割 → 滑动窗口合并 → 句子级 overlap
    """
    if not text or not text.strip():
        return []

    # 1. 句子分割（中英文混合）
    sentences = _split_sentences(text)
    if not sentences:
        return [text[:CHUNK_MAX_SIZE]]

    # 2. 滑动窗口合并到目标大小
    chunks = _merge_sentences_to_chunks(sentences)

    # 3. 句子级 overlap
    chunks = _add_sentence_overlap(chunks, sentences)

    return chunks


def _split_sentences(text: str) -> list[str]:
    """中英文混合句子分割

    规则:
    - 英文: . ! ? 后跟空格或行尾
    - 中文: 。！？ 后直接分割
    - 保护编号行（如 "1.2.3 xxx"、"Fig. 1"）不被误切
    """
    # 保护性替换：编号模式中的点
    protected = text
    # 保护 "1.2.3"、"Fig."、"Eq."、"et al."、"e.g."、"i.e." 中的点
    protected = re.sub(r'(\d+\.(?:\d+\.)*)(?=\s)', r'__NUMDOT__\1', protected)
    protected = re.sub(r'\b(Fig|Eq|et al|e\.g|i\.e|vs|cf|ref|al)\.', r'\1__DOT__', protected)

    # 按中英文句号分割
    # 英文: 句号+空格 或 句号+行尾
    # 中文: 。！？ 直接分割
    parts = re.split(r'(?<=[。！？])|(?<=[.!?])(?=\s|$)', protected)

    # 还原保护标记，过滤空串
    sentences = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        s = s.replace('__NUMDOT__', '').replace('__DOT__', '.')
        sentences.append(s)

    return sentences


def _merge_sentences_to_chunks(sentences: list[str]) -> list[str]:
    """滑动窗口合并句子到目标大小

    策略:
    - 累积句子直到接近 CHUNK_TARGET_SIZE
    - 如果单句超过 CHUNK_MAX_SIZE，强制截断（保留完整句子优先）
    - 不足 CHUNK_MIN_SIZE 的尾部合并到上一个 chunk
    """
    chunks = []
    current_sentences = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)

        # 单句超长：截断为独立 chunk
        if sent_len > CHUNK_MAX_SIZE:
            # 先保存当前累积
            if current_sentences:
                chunks.append(" ".join(current_sentences))
                current_sentences = []
                current_len = 0
            # 截断长句（在允许的最大字符数处找最近的句内逗号/分号）
            chunks.append(_truncate_at_boundary(sent, CHUNK_MAX_SIZE))
            continue

        # 累积到目标大小
        if current_len + sent_len > CHUNK_TARGET_SIZE and current_sentences:
            chunks.append(" ".join(current_sentences))
            current_sentences = [sent]
            current_len = sent_len
        else:
            current_sentences.append(sent)
            current_len += sent_len

    # 处理尾部
    if current_sentences:
        text = " ".join(current_sentences)
        if len(text) < CHUNK_MIN_SIZE and chunks:
            # 太短，合并到上一个 chunk
            chunks[-1] = chunks[-1] + " " + text
        else:
            chunks.append(text)

    return chunks


def _add_sentence_overlap(chunks: list[str], original_sentences: list[str]) -> list[str]:
    """为相邻 chunk 添加句子级 overlap

    每个 chunk 末尾的 SENTENCE_OVERLAP_COUNT 个句子
    会作为下一个 chunk 的开头重复出现
    """
    if len(chunks) <= 1 or SENTENCE_OVERLAP_COUNT <= 0:
        return chunks

    overlapped = [chunks[0]]

    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        # 从前一个 chunk 末尾提取 overlap 句子
        prev_sentences = _split_sentences(prev)
        overlap_sents = prev_sentences[-SENTENCE_OVERLAP_COUNT:] if len(prev_sentences) > SENTENCE_OVERLAP_COUNT else prev_sentences

        if overlap_sents:
            overlap_text = " ".join(overlap_sents)
            overlapped.append(overlap_text + " " + chunks[i])
        else:
            overlapped.append(chunks[i])

    return overlapped


def _truncate_at_boundary(text: str, max_len: int) -> str:
    """在最近的语义边界截断超长文本"""
    if len(text) <= max_len:
        return text

    # 在 max_len 附近找最近的分隔符
    search_range = text[max_len - 100:max_len + 50]
    # 优先级：逗号 > 分号 > 空格
    for sep in [';', '，', ',', '；', ' ', '\n']:
        idx = search_range.rfind(sep)
        if idx > 0:
            cut = max_len - 100 + idx + 1
            return text[:cut].strip()

    # 兜底：直接截断
    return text[:max_len].strip()


# ================================================================
#  摘要提取（多策略回退）
# ================================================================

def _extract_abstract(text: str) -> str:
    """多策略摘要提取

    策略1: 正则匹配 Abstract → Introduction
    策略2: 搜索首个长段落（> 100 字）
    策略3: 兜底前 800 字符
    """
    if not text:
        return ""

    # 策略1: 正则匹配
    patterns = [
        r'(?:Abstract|ABSTRACT|摘要|内容摘要)[\s\n：:]*((?:.|\n){100,}?)(?=\n\s*\n|\n(?:Introduction|INTRODUCTION|1[\s.]\s|Keywords|关键词|1\s))',
        r'(?:Abstract|ABSTRACT)[\s\n：:]*(.*?)(?:\n\n|\x0c)',
        r'(?:摘要)[\s\n：:]*(.*?)(?:\n\n|关键词|Abstract)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            abstract = match.group(1).strip()
            if len(abstract) > 100:
                return abstract[:2000]

    # 策略2: 搜索首页中首个长段落
    first_page = text[:3000]
    paragraphs = re.split(r'\n\s*\n', first_page)
    for para in paragraphs:
        clean = para.strip()
        # 跳过标题、作者行、短文本
        if len(clean) > 150 and not re.match(r'^\d+\.', clean):
            return clean[:1500]

    # 策略3: 兜底
    return text[:800].strip()


# ================================================================
#  表格上下文
# ================================================================

def _build_table_context(table: dict, section_text: str) -> str:
    """为表格 chunk 添加上下文

    表格前后的段落文本作为上下文，帮助检索时理解表格含义
    """
    table_content = table.get("content", "")
    if not table_content:
        return ""

    # 从章节文本中提取表格前后各 1 段作为上下文
    paragraphs = re.split(r'\n\s*\n', section_text) if section_text else []
    context_before = paragraphs[0][:200] if paragraphs else ""
    context_after = paragraphs[-1][:200] if len(paragraphs) > 1 else ""

    parts = []
    if context_before:
        parts.append(f"[上下文] {context_before}")
    parts.append(f"[表格内容]\n{table_content}")
    if context_after:
        parts.append(f"[后续内容] {context_after}")

    return "\n\n".join(parts)


# ================================================================
#  Chunk 构建（统一入口）
# ================================================================

def _build_chunk(paper_data: dict, section_title: str,
                 level: str, text: str, has_table: bool = False,
                 parent_chunk_id: str = "") -> dict:
    """统一构建 chunk dict，保证数据结构兼容"""
    return {
        "chunk_id": f"{paper_data['paper_id']}_{level}_{uuid.uuid4().hex[:8]}",
        "paper_id": paper_data["paper_id"],
        "paper_title": paper_data.get("title", ""),
        "authors": paper_data.get("authors", ""),
        "year": paper_data.get("year", 0),
        "section_title": section_title,
        "section_level": level,
        "text": text,
        "has_figure": False,
        "has_table": has_table,
        "parent_chunk_id": parent_chunk_id,
    }


# ================================================================
#  辅助函数
# ================================================================

def _parse_from_filename(filename: str, metadata: dict):
    """从文件名解析作者和标题"""
    name = filename.replace(".pdf", "")
    parts = name.split(" - ")
    if len(parts) >= 3:
        metadata["authors"] = parts[0].strip()
        try:
            metadata["year"] = int(parts[1].strip())
        except ValueError:
            metadata["year"] = 0
        metadata["title"] = parts[2].strip()
    elif len(parts) == 2:
        metadata["authors"] = parts[0].strip()
        metadata["title"] = parts[1].strip()
    else:
        metadata["title"] = name


def _table_to_markdown(table: list) -> str:
    """将表格转为 Markdown 文本"""
    if not table or len(table) < 2:
        return ""
    header = "| " + " | ".join(str(c or "") for c in table[0]) + " |"
    separator = "| " + " | ".join("---" for _ in table[0]) + " |"
    rows = []
    for row in table[1:]:
        rows.append("| " + " | ".join(str(c or "") for c in row) + " |")
    return header + "\n" + separator + "\n" + "\n".join(rows)


# ================================================================
#  图表提取（元数据）
# ================================================================

def _extract_figures_from_page(page, page_num: int, page_text: str) -> list[dict]:
    """从 PDF 页面提取图表元数据

    提取: 图片位置 + caption（Fig./Figure/图 开头的行）+ 前后段落上下文
    不调用多模态模型，仅提取元数据。
    """
    figures = []

    # 提取图片信息（位置和尺寸）
    try:
        images = page.images
    except Exception:
        images = []

    if not images:
        return []

    # 搜索 caption: Figure/Fig./图 开头的行
    caption_pattern = re.compile(
        r'^(?:Fig\.?|Figure|图)\s*\d*[\.\:：]?\s*(.{5,})',
        re.IGNORECASE
    )
    captions = {}
    lines = page_text.split('\n')
    for j, line in enumerate(lines):
        match = caption_pattern.match(line.strip())
        if match:
            captions[j] = line.strip()

    # 为每张图片构建元数据
    for img_idx, img in enumerate(images):
        width = img.get("x1", 0) - img.get("x0", 0)
        height = img.get("bottom", 0) - img.get("top", 0)

        # 过滤过小的图片（装饰性元素、图标等）
        if width < 50 or height < 50:
            continue

        # 寻找最近的 caption
        caption = ""
        img_y = img.get("top", 0)
        for line_idx, cap_text in captions.items():
            # caption 通常在图片下方
            caption_y = line_idx * 12  # 粗略估算行高
            if abs(caption_y - img_y - height) < 100 or abs(caption_y - img_y) < 50:
                caption = cap_text
                break

        # 提取上下文：图片前后的文字段落
        context_before = ""
        context_after = ""
        if page_text:
            paragraphs = [p.strip() for p in page_text.split('\n\n') if p.strip()]
            for pi, para in enumerate(paragraphs):
                # 找到包含 caption 的段落
                if caption and caption[:20] in para:
                    context_before = paragraphs[pi - 1][:200] if pi > 0 else ""
                    context_after = paragraphs[pi + 1][:200] if pi < len(paragraphs) - 1 else ""
                    break

        figures.append({
            "figure_id": f"fig_{uuid.uuid4().hex[:8]}",
            "page": page_num,
            "caption": caption or f"Figure on page {page_num}",
            "width": round(width, 1),
            "height": round(height, 1),
            "context_before": context_before,
            "context_after": context_after,
        })

    return figures
