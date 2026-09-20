"""来源标注与摘要 — 独立的纯函数模块"""
import re
import logging

logger = logging.getLogger(__name__)


def _normalize_author(author: str) -> str:
    """标准化作者名：去'等'/'et al.'，取姓氏部分"""
    author = author.strip()
    author = re.sub(r'\s*等\.?\s*$', '', author)
    author = re.sub(r'\s*et al\.?\s*$', '', author, flags=re.IGNORECASE)
    parts = author.split()
    return parts[0].lower() if parts else author.lower()


def _cite_matches_rag(cite: str, year_author_pairs: list, rag_citations: set) -> bool:
    """检查引用是否匹配 RAG 来源（精确 + 模糊）"""
    if cite in rag_citations:
        return True
    cite_year_match = re.search(r'(\d{4})', cite)
    cite_year = cite_year_match.group(1) if cite_year_match else ""
    cite_author = _normalize_author(re.sub(r',?\s*\d{4}$', '', cite))
    for ref_year, ref_author in year_author_pairs:
        if not ref_author:
            # year-only match (from chunk text extraction)
            if cite_year == ref_year:
                return True
            continue
        if cite_year == ref_year and cite_author == ref_author:
            return True
    return False


def _extract_paper_citations(text: str) -> list[str]:
    """从 chunk 文本中提取常见引用格式，返回标准化的 '作者, 年份' 列表"""
    refs = []
    # (Author, 2023) / (Author et al., 2023) / (Author & B, 2023)
    for m in re.finditer(r'\(([A-Z][a-z]+(?:\s+(?:et\s+al\.?|&|[A-Z][a-z]+))?),\s*(\d{4})\)', text):
        refs.append(f"{m.group(1)}, {m.group(2)}")
    # [Author, 2023] / [Author et al., 2023]
    for m in re.finditer(r'\[([A-Z][\w\s]+?(?:et\s+al\.?)?),\s*(\d{4})\]', text):
        refs.append(f"{m.group(1)}, {m.group(2)}")
    return refs


def _extract_years_from_text(text: str) -> list[str]:
    """从文本中提取年份（1900-2099）"""
    return re.findall(r'\b((?:19|20)\d{2})\b', text)


_TAG_RE = re.compile(r'^(\s*)\[(KB|WEB|AI)\]\s*')

# 允许标记出现在列表符号 / 加粗包裹之后，例如 "- **[WEB] 文献来源**：..."
_TAG_LEAD_RE = re.compile(
    r'^(\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*|__|\*|_)?\s*)\[(KB|WEB|AI)\]\s*[:：]?\s*'
)
_TAG_INLINE_RE = re.compile(r'\s*\[(KB|WEB|AI)\]\s*')

# 占位式假参考文献，例如 "- [1] 作者. 标题. 期刊, 年份." / "[2] XXX等. XXX. XXX, XXXX."
_PLACEHOLDER_REF_RE = re.compile(
    r'^\s*(?:[-*+]\s*)?(?:\[\d+\]|\(\d+\)|\d+[.)])?\s*'
    r'(?:作者|某作者|佚名|XXX|xxx|Author|作者姓名)\s*(?:等|et\s*al\.?)?\s*[.、,，]'
)
_PLACEHOLDER_TOKEN_RE = re.compile(r'(（?年份）?|（?标题）?|（?期刊）?|XXXX|xxxx)')


def _strip_existing_tag(para: str) -> tuple[str, str]:
    """剥离 LLM 自行输出的 [KB]/[WEB]/[AI] 标记

    LLM 会把标记写在行首，也会写成 "- **[WEB] 文献来源**：..." 这类内嵌形式。
    若不统一剥离，程序化标注会再补一个前缀，导致同一段落出现两个互相矛盾的来源标记。

    Returns:
        (declared_tag, para_without_tag)，无标记时 declared_tag 为 ""
    """
    m = _TAG_RE.match(para)
    if m:
        cleaned = m.group(1) + para[m.end():]
        return m.group(2), _TAG_INLINE_RE.sub(' ', cleaned).rstrip()

    m = _TAG_LEAD_RE.match(para)
    if m:
        cleaned = m.group(1) + para[m.end():]
        return m.group(2), _TAG_INLINE_RE.sub(' ', cleaned).rstrip()

    inline = _TAG_INLINE_RE.search(para)
    if inline:
        return inline.group(1), _TAG_INLINE_RE.sub(' ', para).rstrip()

    return "", para


def _is_placeholder_reference(line: str) -> bool:
    """判断是否是占位式假参考文献行（模型照抄输出格式模板导致）"""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if not _PLACEHOLDER_REF_RE.match(stripped):
        return False
    # "作者. 标题. 期刊, 年份." 这类占位行通常同时含多个占位词
    return len(_PLACEHOLDER_TOKEN_RE.findall(stripped)) >= 1


def _drop_placeholder_references(content: str) -> str:
    """删除模型照抄模板生成的占位参考文献行"""
    lines = content.split("\n")
    kept = [ln for ln in lines if not _is_placeholder_reference(ln)]
    dropped = len(lines) - len(kept)
    if dropped:
        logger.info(f"[Annotate] Dropped {dropped} placeholder reference line(s)")
    return "\n".join(kept)


_REF_HEADING_RE = re.compile(
    r'^\s*(?:#{1,6}\s*)?(?:\*\*|__)?\s*'
    r'(?:本节)?(?:参考文献|引用文献|References?|Reference\s+List|Bibliography)'
    r'\s*(?:\*\*|__)?\s*[:：]?\s*$',
    re.IGNORECASE,
)
_REF_ENTRY_RE = re.compile(r'^\s*(?:[-*+•]\s*|\[\d+\]\s*|\(\d+\)\s*|\d+[.)]\s+)')
_NO_REF_HINT = "本节暂无可核验的文献引用（参考材料中未包含对应文献）"
_NO_REF_HINT_RE = re.compile(r'暂无.{0,8}(文献引用|可核验)')


def _kb_reference_keys(rag_chunks: list[dict]) -> list[dict]:
    """从知识库片段提取可核验的文献标识：标题词、作者姓氏、年份"""
    papers = {}
    for c in rag_chunks:
        meta = c.get("metadata", {}) or {}
        title = (meta.get("title") or c.get("paper_title") or c.get("title") or "").strip()
        authors = (meta.get("authors") or c.get("authors") or "").strip()
        year = str(meta.get("year") or c.get("year") or "").strip()
        key = (title.lower(), authors.lower(), year)
        if key in papers:
            continue
        tokens = {w.lower() for w in re.findall(r'[a-zA-Z]{4,}', title)}
        tokens |= {w for w in re.findall(r'[一-鿿]{2,}', title)}
        surnames = set()
        for a in re.split(r'[,;、&和]| and ', authors):
            a = a.strip()
            if not a:
                continue
            surnames.add(_normalize_author(a))
            # 作者字段可能是「名 姓」也可能是「姓 名」，两种顺序都收进来，避免真引用被误判
            surnames.update(w.lower() for w in re.findall(r'[A-Za-z][A-Za-z\-]{1,}', a))
            cjk = re.findall(r'[一-鿿]{2,4}', a)
            surnames.update(x.lower() for x in cjk)
        papers[key] = {
            "title": title,
            "tokens": {t for t in tokens if t not in ("that", "with", "from", "this", "using")},
            "surnames": {s for s in surnames if s},
            "year": year if year and year != "0" else "",
        }
    return list(papers.values())


def _reference_is_verifiable(line: str, kb_papers: list[dict]) -> bool:
    """参考文献条目能否在知识库文献中找到对应"""
    _, clean = _strip_existing_tag(line)
    text = clean.lower()
    cjk = set(re.findall(r'[一-鿿]{2,}', clean))
    words = set(re.findall(r'[a-z]{4,}', text))
    years = set(re.findall(r'\b((?:19|20)\d{2})\b', clean))

    for p in kb_papers:
        if p["title"] and p["title"].lower() in text:
            return True
        overlap = (p["tokens"] & words) | (p["tokens"] & cjk)
        if len(overlap) >= 2:
            return True
        if p["surnames"] and any(s in text or s in cjk for s in p["surnames"]):
            if not p["year"] or p["year"] in years:
                return True
    return False


def sanitize_reference_block(content: str, rag_chunks: list[dict]) -> str:
    """核验章节末尾「参考文献」条目，删掉无法在知识库中核验的虚构条目

    模型即使被明确禁止，仍可能在参考文献区编造条目（甚至被误标 [KB]）。
    这里以知识库文献元数据为唯一事实来源做程序化核验：
      * 能匹配到真实文献（标题词重合 / 作者+年份）→ 保留
      * 匹配不上 → 删除，并在全部删除时给出明确提示
    """
    if not content:
        return content

    lines = content.split("\n")
    heading_idx = -1
    for i, ln in enumerate(lines):
        _, clean = _strip_existing_tag(ln)
        if _REF_HEADING_RE.match(clean):
            heading_idx = i
    if heading_idx < 0:
        return content

    kb_papers = _kb_reference_keys(rag_chunks or [])
    head, tail = lines[: heading_idx + 1], lines[heading_idx + 1:]

    kept, dropped, seen = [], 0, set()
    for ln in tail:
        _, clean = _strip_existing_tag(ln)
        stripped = clean.strip()
        if not stripped:
            kept.append(ln)
            continue
        if _NO_REF_HINT_RE.search(stripped):
            # 「暂无文献引用」提示行统一由本函数按核验结果重建，先剔除
            continue
        is_entry = bool(_REF_ENTRY_RE.match(stripped)) or bool(
            re.search(r'\b(?:19|20)\d{2}\b', stripped)
        )
        if not is_entry:
            kept.append(ln)
            continue

        sig = re.sub(r'[^0-9a-z一-鿿]', '', stripped.lower())
        if sig and sig in seen:
            dropped += 1
            continue

        if kb_papers and _reference_is_verifiable(ln, kb_papers):
            seen.add(sig)
            kept.append(ln)
        else:
            dropped += 1

    has_entry = bool(seen)
    if not has_entry:
        kept = [ln for ln in kept if ln.strip()] + [_NO_REF_HINT]
    if dropped:
        logger.warning(
            f"[Annotate] Dropped {dropped} unverifiable reference entry(ies); "
            f"kb_papers={len(kb_papers)}"
        )
    return "\n".join(head + kept)



UNVERIFIED_MARK = "⚠"
_UNVERIFIED_STRIP_RE = re.compile(r'([\]\)）]|\d{4}[a-z]?)\s*⚠+')

# 正文内联引用的四类常见写法
_CITE_BRACKET_RE = re.compile(r'\[([^\[\]\n]{2,60}?[,，]\s*(?:19|20)\d{2}[a-z]?)\]')
_CITE_PAREN_RE = re.compile(r'[（(]([^（()）\n]{2,60}?[,，]\s*(?:19|20)\d{2}[a-z]?)[)）]')
_CITE_NARRATIVE_RE = re.compile(
    r'([A-Z][A-Za-z\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z\-]+|&\s*[A-Z][A-Za-z\-]+))?)'
    r'\s*[（(]\s*((?:19|20)\d{2}[a-z]?)\s*[)）]'
)
_CITE_ZH_NARRATIVE_RE = re.compile(r'([一-鿿]{2,4}(?:等|和[一-鿿]{2,4})?)\s*[（(]\s*((?:19|20)\d{2})\s*[)）]')
_CITE_NUM_RE = re.compile(r'\[(\d{1,3}(?:\s*[-–,，]\s*\d{1,3})*)\]')
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')


def strip_unverified_marks(content: str) -> str:
    """移除内联引用的未核验标记，便于重新核验（幂等）"""
    if not content or UNVERIFIED_MARK not in content:
        return content
    return _UNVERIFIED_STRIP_RE.sub(lambda m: m.group(1), content)


def kb_papers_from_meta(items: list[dict]) -> list[dict]:
    """把 papers 表行 / 任意含 title-authors-year 的字典，转成核验用的文献标识"""
    normalized = []
    for it in items or []:
        year = it.get("year")
        normalized.append({
            "metadata": {
                "title": it.get("title") or "",
                "authors": it.get("authors") or "",
                "year": "" if year in (None, 0, "0") else str(year),
            }
        })
    return _kb_reference_keys(normalized)


def _load_project_kb_papers(project_id: str) -> list[dict]:
    """读取项目内全部知识库文献作为核验事实源

    只用检索命中的 chunk 做核验会误伤：引用的文献可能确实在项目库里，
    只是本次检索没命中。核验必须以项目全量文献为准。
    """
    if not project_id:
        return []
    try:
        from src.core.memory import project_memory
        return kb_papers_from_meta(project_memory.get_papers(project_id))
    except Exception as e:  # 库不可用时退化为仅用 chunk 核验，不阻断主流程
        logger.warning(f"[Cite] Load project papers failed: {e}")
        return []


def _valid_reference_numbers(ref_lines: list[str]) -> set[str]:
    """参考文献区存活条目对应的合法编号（显式编号 + 顺序编号）"""
    explicit, count = set(), 0
    for ln in ref_lines:
        _, clean = _strip_existing_tag(ln)
        stripped = clean.strip()
        if not stripped or _NO_REF_HINT_RE.search(stripped):
            continue
        m = re.match(r'^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})[.)])\s+', stripped)
        if m:
            explicit.add(next(g for g in m.groups() if g))
            count += 1
        elif _REF_ENTRY_RE.match(stripped):
            count += 1
    return explicit | {str(i) for i in range(1, count + 1)}


def _author_year_verifiable(author: str, year: str, kb_papers: list[dict],
                            author_year_pairs: list[tuple], web_blobs: list[str]) -> bool:
    """作者+年份式引用能否核验"""
    key = _normalize_author(author)
    if not key:
        return False
    # 中文作者可能被正则多带了前缀字（"如张伟等"），用 2-4 字滑窗覆盖真实姓名
    cjk_chars = re.sub(r'[^一-鿿]', '', re.sub(r'等|和', '', author))
    cjk = {cjk_chars[i:i + n] for n in (2, 3, 4) for i in range(max(0, len(cjk_chars) - n + 1))
           if len(cjk_chars[i:i + n]) == n}
    for p in kb_papers:
        hit_author = key in p["surnames"] or bool(cjk & p["surnames"])
        hit_title = key in p["tokens"] or bool(cjk & p["tokens"])
        if hit_author or hit_title:
            if not year or not p["year"] or p["year"] == year:
                return True
    for ref_year, ref_author in author_year_pairs:
        # 只接受带作者的配对，年份单独命中不足以证明引用真实存在
        if ref_author and ref_author == key and (not year or ref_year == year):
            return True
    for blob in web_blobs:
        if key in blob and (not year or year in blob):
            return True
    return False


def _cite_candidates(line: str) -> list[tuple]:
    """抽取一行正文中的内联引用候选，返回 [(start, end, raw, author, year, numbers)]"""
    spans = []
    for m in _CITE_NARRATIVE_RE.finditer(line):
        spans.append((m.start(), m.end(), m.group(0), m.group(1), m.group(2), None))
    for m in _CITE_ZH_NARRATIVE_RE.finditer(line):
        spans.append((m.start(), m.end(), m.group(0), m.group(1), m.group(2), None))
    for regex in (_CITE_BRACKET_RE, _CITE_PAREN_RE):
        for m in regex.finditer(line):
            inner = m.group(1)
            ym = re.search(r'((?:19|20)\d{2})', inner)
            author = re.sub(r'[,，]\s*(?:19|20)\d{2}[a-z]?\s*$', '', inner).strip()
            spans.append((m.start(), m.end(), m.group(0), author, ym.group(1) if ym else "", None))
    for m in _CITE_NUM_RE.finditer(line):
        nums = re.findall(r'\d{1,3}', m.group(1))
        spans.append((m.start(), m.end(), m.group(0), "", "", nums))

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    picked, last_end = [], -1
    for s in spans:
        if s[0] < last_end:  # 重叠时保留更长的那个匹配
            continue
        picked.append(s)
        last_end = s[1]
    return picked


def verify_inline_citations(content: str, kb_papers: list[dict],
                            author_year_pairs: list[tuple] = None,
                            web_results: list[dict] = None) -> tuple[str, dict]:
    """核验正文内联引用，给无法核验的引用加 ⚠ 标记

    参考文献区已由 sanitize_reference_block 核验，但正文里的 "(Smith, 2023)"、
    "[3]" 这类内联引用仍可能是模型编造的。这里以项目知识库文献为事实源逐条核验：
      * 能匹配到真实文献（作者/标题词 + 年份）→ 原样保留
      * 编号式引用能对应到存活的参考文献条目 → 原样保留
      * 匹配不上 → 在引用后追加 ⚠（纯追加，不改写原文字）

    Returns:
        (marked_content, report)；report 含 total / verified / unverified / items
    """
    report = {"total": 0, "verified": 0, "unverified": 0, "items": []}
    if not content or not content.strip():
        return content, report

    content = strip_unverified_marks(content)
    kb_papers = kb_papers or []
    author_year_pairs = author_year_pairs or []
    web_blobs = [
        f"{r.get('title', '')} {r.get('snippet', '') or r.get('content', '')}".lower()
        for r in (web_results or [])
    ]

    lines = content.split("\n")
    ref_start = len(lines)
    for i, ln in enumerate(lines):
        _, clean = _strip_existing_tag(ln)
        if _REF_HEADING_RE.match(clean):
            ref_start = i
    valid_numbers = _valid_reference_numbers(lines[ref_start + 1:]) if ref_start < len(lines) else set()

    out, in_fence = [], False
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or idx >= ref_start or not line.strip():
            out.append(line)
            continue

        spans = _cite_candidates(line)
        if not spans:
            out.append(line)
            continue

        pieces, cursor = [], 0
        for start, end, raw, author, year, nums in spans:
            report["total"] += 1
            if nums is not None:
                ok = bool(valid_numbers) and all(n in valid_numbers for n in nums)
            else:
                ok = _author_year_verifiable(author, year, kb_papers, author_year_pairs, web_blobs)
            pieces.append(line[cursor:start])
            pieces.append(raw if ok else raw + UNVERIFIED_MARK)
            cursor = end
            if ok:
                report["verified"] += 1
            else:
                report["unverified"] += 1
                if raw not in report["items"]:
                    report["items"].append(raw)
        pieces.append(line[cursor:])
        out.append("".join(pieces))

    if report["unverified"]:
        logger.warning(
            f"[Cite] {report['unverified']}/{report['total']} inline citation(s) unverifiable: "
            f"{report['items'][:5]}"
        )
    return "\n".join(out), report


def check_inline_citations(content: str, project_id: str = "",
                           rag_chunks: list[dict] = None) -> tuple[str, dict]:
    """对外入口：按项目知识库核验正文内联引用（用于保存 / 导出等非生成路径）"""
    kb_papers = _load_project_kb_papers(project_id)
    if not kb_papers and rag_chunks:
        kb_papers = _kb_reference_keys(rag_chunks)
    return verify_inline_citations(content, kb_papers)


def annotate_sources(content: str, rag_chunks: list[dict], web_results: list[dict],
                     project_id: str = "") -> str:
    """程序化标注内容来源：RAG文献 / 网络搜索 / LLM推理

    遍历每一段落，根据引用和关键词匹配判断来源类型，在段首添加标记。
    当 metadata 中 authors/year 缺失时，从 chunk 文本中自动提取引用信息作为补充。
    """
    if not content or not content.strip():
        return content

    rag_chunks = rag_chunks or []
    web_results = web_results or []

    # 0. 清掉模型照抄模板产生的占位参考文献行（"作者. 标题. 期刊, 年份."）
    content = _drop_placeholder_references(content)
    # 0b. 核验参考文献区条目，删除知识库中不存在的虚构文献
    content = sanitize_reference_block(content, rag_chunks)

    # 1. 构建 RAG 引用匹配集合
    rag_citations = set()
    year_author_pairs = []

    for c in rag_chunks:
        meta = c.get("metadata", {})
        authors = meta.get("authors", "") or c.get("authors", "")
        year = meta.get("year", "") or c.get("year", "")
        text = c.get("text", "")

        # 优先用 metadata
        if authors and year:
            try:
                y = str(int(year))
                rag_citations.add(f"{authors}, {y}")
                year_author_pairs.append((y, _normalize_author(authors)))
                continue
            except (ValueError, TypeError):
                pass

        # 回退：从 chunk 文本中提取引用
        chunk_cites = _extract_paper_citations(text)
        chunk_years = _extract_years_from_text(text)
        for cite in chunk_cites:
            rag_citations.add(cite)
            cite_year_match = re.search(r'(\d{4})', cite)
            if cite_year_match:
                cite_author = _normalize_author(re.sub(r',?\s*\d{4}$', '', cite))
                year_author_pairs.append((cite_year_match.group(1), cite_author))
        if chunk_years:
            for y in chunk_years:
                year_author_pairs.append((y, ""))

    logger.info(f"[Annotate] RAG citation refs: {rag_citations}")
    logger.info(f"[Annotate] RAG year_author_pairs: {year_author_pairs[:5]}")

    # 2. 构建 RAG 文本关键词集合（用于无引用段落的模糊匹配）
    rag_text_keywords = set()
    for c in rag_chunks:
        text = c.get("text", "")
        if text:
            for word in re.findall(r'[一-鿿]{2,}|[a-zA-Z]{4,}', text.lower()):
                rag_text_keywords.add(word)

    # 3. 构建网络来源关键词集合
    web_keywords = set()
    web_urls = []
    for r in web_results:
        title = r.get("title", "")
        if title:
            for word in re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', title):
                web_keywords.add(word.lower())
        url = r.get("url", "")
        if url:
            web_urls.append(url)
            domain_match = re.search(r'://([^/]+)', url)
            if domain_match:
                web_keywords.add(domain_match.group(1).lower())

    # 3b. 核验正文内联引用：无法在项目知识库中核验的引用追加 ⚠
    kb_papers = _load_project_kb_papers(project_id) or _kb_reference_keys(rag_chunks)
    content, _cite_report = verify_inline_citations(
        content, kb_papers, year_author_pairs, web_results
    )

    # 4. 按段落处理
    paragraphs = content.split("\n")
    annotated = []
    source_stats = {"rag": 0, "web": 0, "llm": 0}

    for raw_para in paragraphs:
        # LLM 现在会自行标注 [KB]/[WEB]/[AI]，先剥离已有标记避免重复前缀
        declared, para = _strip_existing_tag(raw_para)

        stripped = para.strip()
        if not stripped or stripped.startswith("#"):
            annotated.append(para)
            continue

        is_rag = False
        is_web = False

        # 已标 ⚠ 的引用无法核验，不能作为 [KB] 的依据
        en_cites = re.findall(r'\[([A-Z][\w\s]+(?:et al\.)?,\s*\d{4})\](?!⚠)', stripped)
        zh_cites = re.findall(r'\[[一-鿿]+等?,\s*\d{4}\](?!⚠)', stripped)
        all_cites = en_cites + zh_cites

        # 匹配策略 1：引用标记精确/模糊匹配
        for cite in all_cites:
            if _cite_matches_rag(cite, year_author_pairs, rag_citations):
                is_rag = True
                break

        # 匹配策略 2：无引用时，用关键词重叠判断是否来自 RAG
        if not is_rag and not all_cites and rag_text_keywords:
            para_words = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{4,}', stripped.lower()))
            overlap = para_words & rag_text_keywords
            zh_words = [w for w in para_words if re.match(r'[一-鿿]', w)]
            threshold = 3 if len(zh_words) > len(para_words) // 2 else 2
            if len(overlap) >= threshold:
                is_rag = True

        # 匹配策略 3：段落与 chunk 文本做短语重叠检测（需要多个独立短语命中）
        if not is_rag and rag_chunks:
            match_count = 0
            matched_phrases = set()
            for c in rag_chunks:
                chunk_text = c.get("text", "")
                if chunk_text and len(chunk_text) > 30:
                    for phrase in re.findall(r'[一-鿿]{4,}|[a-zA-Z]{5,}', chunk_text):
                        if len(phrase) >= 5 and phrase in stripped and phrase not in matched_phrases:
                            matched_phrases.add(phrase)
                            match_count += 1
            if match_count >= 3:
                is_rag = True

        if all_cites and not is_rag:
            logger.debug(f"[Annotate] Unmatched cites: {all_cites}")

        if not is_rag and web_keywords:
            for url in web_urls:
                if url and url in stripped:
                    is_web = True
                    break
            if not is_web:
                para_words = set(re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', stripped.lower()))
                overlap = para_words & web_keywords
                if len(overlap) >= 2:
                    is_web = True

        # 硬约束：没有对应证据时，绝不允许打出该来源标记
        if not rag_chunks:
            is_rag = False
        if not web_results:
            is_web = False

        if is_rag:
            annotated.append(f"[KB] {para}")
            source_stats["rag"] += 1
        elif is_web or (declared == "WEB" and web_results):
            annotated.append(f"[WEB] {para}")
            source_stats["web"] += 1
        else:
            annotated.append(f"[AI] {para}")
            source_stats["llm"] += 1

    logger.info(f"[Annotate] RAG={source_stats['rag']}, Web={source_stats['web']}, LLM={source_stats['llm']}")
    return "\n".join(annotated)


def summarize_section(llm_client, content: str) -> str:
    """用 LLM 压缩章节为100字摘要"""
    if len(content) < 200:
        return content
    messages = [
        {"role": "system", "content": "将以下论文章节压缩为100字以内的简洁摘要，保留核心观点和关键引用。"},
        {"role": "user", "content": content[:3000]},
    ]
    return llm_client.chat(messages, temperature=0.3, max_tokens=200)
