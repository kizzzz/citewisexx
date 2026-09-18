"""高级 PDF 解析器 — 基于 Docling (IBM 开源)

提供比 pdfplumber 更强大的 PDF 解析能力：
- 版面分析与阅读顺序重排（处理多栏论文）
- 表格结构化提取
- 图片 caption 提取
- OCR 支持（扫描 PDF）

自动 fallback 到 rag.py 的 pdfplumber 方案。
"""
import os
import re
import logging
import uuid

logger = logging.getLogger(__name__)

# 延迟检测 Docling 是否可用
_docling_available = None


def is_docling_available() -> bool:
    """检测 Docling 是否已安装"""
    global _docling_available
    if _docling_available is None:
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401
            _docling_available = True
            logger.info("Docling 可用，将使用高级 PDF 解析")
        except ImportError:
            _docling_available = False
            logger.info("Docling 不可用，将使用 pdfplumber fallback")
    return _docling_available


def parse_pdf_advanced(filepath: str) -> dict:
    """使用 Docling 解析 PDF，返回与 rag.parse_pdf 兼容的格式

    Returns:
        {
            "paper_id": str,
            "filename": str,
            "title": str,
            "authors": str,
            "year": int/str,
            "sections": [{"title": str, "text": str, "tables": []}],
            "raw_text": str,
            "figures": [],
            "page_count": int,
        }
    """
    from docling.document_converter import DocumentConverter

    filename = os.path.basename(filepath)
    paper_id = f"paper_{uuid.uuid4().hex[:8]}"

    converter = DocumentConverter()
    result = converter.convert(filepath)
    doc = result.document

    # 提取元数据
    metadata = {
        "paper_id": paper_id,
        "filename": filename,
        "title": "",
        "authors": "",
        "year": "",
        "page_count": 0,
    }

    # 尝试从 Docling 输出获取标题
    try:
        # Docling 的 name 属性可能包含文档标题
        if hasattr(doc, 'name') and doc.name:
            metadata["title"] = str(doc.name)
    except Exception:
        pass

    # 从文件名解析元数据作为补充
    _parse_from_filename(filename, metadata)

    # 导出为 Markdown 并按标题分段
    try:
        markdown_text = doc.export_to_markdown()
    except Exception as e:
        logger.warning(f"Docling Markdown 导出失败: {e}")
        markdown_text = ""

    if not markdown_text.strip():
        raise ValueError("Docling 输出为空")

    # 按 Markdown 标题分段
    sections = _split_markdown_to_sections(markdown_text)

    # 提取表格（Docling 的结构化输出）
    tables = []
    try:
        # 遍历文档的 body 获取表格
        if hasattr(doc, 'body') and hasattr(doc.body, 'iterate_items'):
            for item, _level in doc.body.iterate_items():
                if hasattr(item, 'label') and item.label and 'table' in str(item.label).lower():
                    table_text = ""
                    if hasattr(item, 'text'):
                        table_text = item.text or ""
                    if table_text:
                        tables.append({"content": table_text, "section_title": ""})
    except Exception as e:
        logger.warning(f"Docling 表格提取失败（非致命）: {e}")

    # 将表格合并到对应 section
    for table in tables:
        merged = False
        for sec in sections:
            if not table["section_title"] and len(sections) > 0:
                sec["tables"].append(table)
                merged = True
                break
        if not merged and sections:
            sections[0]["tables"].append(table)

    # 提取图片信息
    figures = []
    try:
        if hasattr(doc, 'body') and hasattr(doc.body, 'iterate_items'):
            for item, _level in doc.body.iterate_items():
                if hasattr(item, 'label') and item.label and 'picture' in str(item.label).lower():
                    caption = ""
                    if hasattr(item, 'text'):
                        caption = item.text or ""
                    figures.append({"caption": caption, "type": "picture"})
    except Exception as e:
        logger.warning(f"Docling 图片提取失败（非致命）: {e}")

    raw_text = "\n".join(s["text"] for s in sections)

    return {
        **metadata,
        "sections": sections,
        "figures": figures,
        "raw_text": raw_text,
    }


def parse_pdf_with_fallback(filepath: str) -> dict:
    """智能 PDF 解析：优先 Docling，失败则 fallback 到 pdfplumber

    Returns:
        同 parse_pdf_advanced / rag.parse_pdf 的格式
    """
    if is_docling_available():
        try:
            result = parse_pdf_advanced(filepath)
            if result.get("raw_text", "").strip():
                logger.info(f"Docling 解析成功: {len(result['raw_text'])} 字符, {len(result.get('sections', []))} 个 section")
                return result
            else:
                logger.warning("Docling 输出为空，fallback 到 pdfplumber")
        except Exception as e:
            logger.warning(f"Docling 解析失败，fallback 到 pdfplumber: {e}")

    # Fallback: 使用 rag.py 的 pdfplumber 方案
    from src.core.rag import parse_pdf
    return parse_pdf(filepath)


def _split_markdown_to_sections(markdown_text: str) -> list[dict]:
    """将 Docling 导出的 Markdown 按标题分段

    支持 # ~ ###### 标题级别
    """
    lines = markdown_text.split('\n')
    sections = []
    current_section = {"title": "全文", "text": "", "tables": []}
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')

    buffer = []
    for line in lines:
        match = heading_pattern.match(line)
        if match:
            # 保存当前 section
            if buffer:
                current_section["text"] += "\n".join(buffer) + "\n"
                buffer = []
            if current_section["text"].strip():
                sections.append(current_section.copy())
            title = match.group(2).strip()
            current_section = {"title": title, "text": "", "tables": []}
        else:
            buffer.append(line)

    if buffer:
        current_section["text"] += "\n".join(buffer) + "\n"
    if current_section["text"].strip():
        sections.append(current_section)

    if not sections:
        sections = [{"title": "全文", "text": markdown_text, "tables": []}]

    return sections


def _parse_from_filename(filename: str, metadata: dict) -> None:
    """从文件名解析标题、作者和年份"""
    name = os.path.splitext(filename)[0]
    # 去掉常见的 paper_ 前缀
    name = re.sub(r'^paper_[a-f0-9]+_', '', name)

    # 尝试匹配: "Author1_Year_Title" 或 "Author1 Author2 - Title (Year)"
    year_match = re.search(r'[\(\[]?(\d{4})[\)\]]?', name)
    if year_match and not metadata.get("year"):
        metadata["year"] = year_match.group(1)

    if not metadata.get("title"):
        # 去掉年份部分，剩余作为标题
        title = re.sub(r'[\(\[]?\d{4}[\)\]]?', '', name).strip(' _-')
        metadata["title"] = title if title else name
