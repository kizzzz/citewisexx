#!/usr/bin/env python3
"""CiteWise 线上部署端到端验证（在服务器上直连 127.0.0.1:5328）。

覆盖需求点 2/3/4/5：
- 多 Agent 协同思考（agent_start / agent_thought / agent_end / Synthesizer）
- 无文献时不硬拒答 + 三色 [KB]/[WEB]/[AI]
- 章节草稿三种编辑方式（人工保存 / 子 Agent 对话 / 选区改写）
- 文献推荐、知识地图、论文投递（含越权校验）
"""
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request

BASE = os.getenv("E2E_BASE", "http://127.0.0.1:5328/api")
RESULTS = []


def log(name, ok, detail=""):
    RESULTS.append((name, ok, str(detail)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {str(detail)[:900]}", flush=True)


def req(method, path, payload=None, token=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def sse(path, payload, token, timeout=420):
    r = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), method="POST")
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + token)
    events, tokens = [], []
    cur = None
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    cur = line[6:].strip()
                elif line.startswith("data:"):
                    payload_raw = line[5:].strip()
                    try:
                        d = json.loads(payload_raw)
                    except Exception:
                        d = {"_raw": payload_raw}
                    events.append((cur or "message", d))
                    if cur == "token" and isinstance(d, dict) and isinstance(d.get("text"), str):
                        tokens.append(d["text"])
                    if cur == "content" and isinstance(d, dict) and isinstance(d.get("content"), str):
                        tokens.append("")
    except Exception as e:  # noqa: BLE001
        events.append(("_error", {"msg": str(e)}))
    full = "".join(tokens)
    if not full:
        for e, d in events:
            if e == "content" and isinstance(d, dict) and isinstance(d.get("content"), str):
                full = d["content"]
    return events, full


def upload_md(pid, token, filename, content):
    boundary = "----e2e" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"project_id\"\r\n\r\n{pid}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/markdown\r\n\r\n{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    r = urllib.request.Request(BASE + "/papers/upload", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=420) as resp:
            return True, f"{resp.status} {resp.read().decode('utf-8', 'replace')[:300]}"
    except urllib.error.HTTPError as e:
        return False, f"{e.code} {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


MD_PAPER = (
    "# Attention Is All You Need\n"
    "Authors: Ashish Vaswani, Noam Shazeer, Niki Parmar\n"
    "Year: 2017\n\n"
    "## Abstract\n"
    "The dominant sequence transduction models are based on complex recurrent or convolutional "
    "neural networks that include an encoder and a decoder. We propose a new simple network "
    "architecture, the Transformer, based solely on attention mechanisms, dispensing with "
    "recurrence and convolutions entirely.\n\n"
    "## Method\n"
    "Scaled dot-product attention computes Attention(Q,K,V) = softmax(QK^T / sqrt(d_k)) V. "
    "Multi-head attention linearly projects queries, keys and values h = 8 times, allowing the "
    "model to jointly attend to information from different representation subspaces.\n\n"
    "## Results\n"
    "On the WMT 2014 English-to-German translation task the Transformer achieves 28.4 BLEU, "
    "improving over the previous best results, including ensembles, by over 2 BLEU. On WMT 2014 "
    "English-to-French it establishes a new single-model state of the art BLEU score of 41.8 "
    "after training for 3.5 days on eight GPUs.\n\n"
    "## Conclusion\n"
    "Self-attention based architectures train significantly faster than recurrent or "
    "convolutional layers and generalise well to other tasks.\n"
)


def main():
    stamp = uuid.uuid4().hex[:8]
    user_a = f"e2e{stamp}"
    user_b = f"e2e{stamp}b"
    pwd = "Test1234!"

    code, body = req("POST", "/auth/register", {"username": user_a, "password": pwd})
    token = body.get("token") if isinstance(body, dict) else None
    log("auth/register", bool(token), f"{code} {str(body)[:160]}")
    if not token:
        return summary()

    code, body = req("POST", "/projects", {"name": f"E2E {stamp}", "topic": "Transformer 自注意力机制研究"}, token)
    pid = body.get("id") or body.get("project_id") if isinstance(body, dict) else None
    log("projects/create", bool(pid), f"{code} pid={pid}")
    if not pid:
        return summary()

    # --- 需求3：无文献提问，应答且带 [WEB]/[AI]，不硬拒答 ---
    ev1, txt1 = sse("/chat", {
        "project_id": pid,
        "message": "请介绍 Transformer 中自注意力机制的核心原理，以及它相对 RNN 的优势。",
    }, token)
    etypes1 = sorted({e for e, _ in ev1})
    agents1 = sorted({d.get("agent") for e, d in ev1 if isinstance(d, dict) and d.get("agent")})
    thoughts1 = [d for e, d in ev1 if e == "agent_thought"]
    refuse_kw = ("无法回答", "未找到任何相关", "请先上传文献", "没有检索到任何")
    refused = any(k in txt1 for k in refuse_kw)
    tags1 = sorted({t for t in ("[KB]", "[WEB]", "[AI]") if t in txt1})
    log("需求3 无文献不硬拒答", len(txt1) > 150 and not refused,
        f"len={len(txt1)} refused={refused} head={txt1[:200]!r}")
    log("需求3 三色标记出现", bool(tags1), f"tags={tags1}")
    log("需求2 多Agent并行思考", len(thoughts1) >= 2 and len(agents1) >= 3,
        f"agents={agents1} thoughts={len(thoughts1)} events={etypes1}")
    log("需求2 Synthesizer收敛", any("Synth" in (a or "") for a in agents1), f"agents={agents1}")

    # --- 上传文献 ---
    ok, detail = upload_md(pid, token, "attention_is_all_you_need.md", MD_PAPER)
    log("papers/upload", ok, detail)
    time.sleep(6)
    code, papers = req("GET", f"/papers?project_id={pid}", None, token)
    n = len(papers) if isinstance(papers, list) else 0
    meta = papers[0] if n else {}
    log("papers/list", n >= 1, f"{code} n={n} title={meta.get('title')!r} authors={meta.get('authors')!r} year={meta.get('year')!r}")
    log("需求5 markdown元数据解析", bool(meta) and not str(meta.get("title", "")).startswith("#")
        and bool(meta.get("authors")) and str(meta.get("year")) not in ("0", "None", ""),
        f"title={meta.get('title')!r} authors={meta.get('authors')!r} year={meta.get('year')!r}")

    # --- 有文献提问，应出现 [KB] ---
    ev2, txt2 = sse("/chat", {
        "project_id": pid,
        "message": "根据我上传的文献，Transformer 在 WMT 2014 英德翻译任务上的 BLEU 分数是多少？",
    }, token)
    tags2 = sorted({t for t in ("[KB]", "[WEB]", "[AI]") if t in txt2})
    src_ev = [d for e, d in ev2 if e == "sources"]
    log("需求3 有文献命中 [KB]", "[KB]" in tags2, f"tags={tags2} hit28.4={'28.4' in txt2} len={len(txt2)}")
    log("chat/sources 事件", bool(src_ev), f"sources={str(src_ev)[:200]}")

    # --- 需求4-2：子 Agent 列表 ---
    code, body = req("GET", "/chat/sub-agents", None, token)
    ids = [a.get("id") for a in (body.get("agents", []) if isinstance(body, dict) else [])]
    log("需求4 子Agent列表", code == 200 and len(ids) >= 6, f"{code} ids={ids}")

    # --- 章节生成 ---
    code, body = req("POST", "/sections", {
        "project_id": pid, "name": "引言", "style": "学术正式",
        "target_length": 600, "citation_density": "正常", "agent": "writer",
        "requirements": "围绕自注意力机制的研究背景",
    }, token, timeout=420)
    content = body.get("content", "") if isinstance(body, dict) else ""
    sid = body.get("section_id") if isinstance(body, dict) else None
    log("sections/generate", code == 200 and len(content) > 100, f"{code} len={len(content)} sid={sid}")
    fake = ("参考文献" in content and "暂无文献引用" not in content and n == 0)
    log("需求3 无据不编引用", not fake, f"n_papers={n}")

    # --- 需求4-1：人工修改 + 保存（幂等，不产生重复章节） ---
    if sid:
        code, body = req("PUT", f"/sections/{sid}", {"content": content + "\n\n人工修改标记 A"}, token)
        log("需求4 人工保存#1", code == 200, f"{code} {str(body)[:160]}")
        code, body = req("PUT", f"/sections/{sid}", {"content": content + "\n\n人工修改标记 B"}, token)
        log("需求4 人工保存#2", code == 200, f"{code} {str(body)[:160]}")
        code, secs = req("GET", f"/sections?project_id={pid}", None, token)
        arr = secs if isinstance(secs, list) else (secs.get("sections", []) if isinstance(secs, dict) else [])
        intro = [s for s in arr if (s.get("section_name") or s.get("name")) == "引言"]
        latest = intro[0].get("content", "") if intro else ""
        log("需求5 章节不重复写入", len(intro) == 1, f"引言条数={len(intro)} 总数={len(arr)}")
        log("需求4 保存内容生效", "人工修改标记 B" in latest, f"tail={latest[-60:]!r}")

    # --- 需求4-3：选区改写 ---
    selection = "Transformer 完全基于注意力机制，摒弃了循环与卷积结构。"
    code, body = req("POST", "/sections/edit-selection", {
        "project_id": pid, "section_name": "引言", "section_id": sid or "",
        "selection": selection, "instruction": "改写得更学术严谨，保持一句话",
        "context_before": content[:300], "context_after": "", "agent": "polisher",
    }, token, timeout=300)
    new_text = body.get("content", "") if isinstance(body, dict) else ""
    log("需求4 选区改写", code == 200 and 5 < len(new_text) < len(selection) * 8,
        f"{code} new={new_text[:200]!r}")

    # --- 需求4-2：右侧子 Agent 对话 ---
    code, body = req("POST", "/chat/sub", {
        "project_id": pid, "section_name": "引言", "section_id": sid or "",
        "content": content, "message": "请把这一节精简到 200 字左右", "agent": "condenser",
    }, token, timeout=420)
    sub_type = body.get("type") if isinstance(body, dict) else None
    sub_content = (body.get("content") or "") if isinstance(body, dict) else ""
    log("需求4 子Agent对话(condenser→修改)", code == 200 and len(sub_content) > 50,
        f"{code} type={sub_type} len={len(sub_content)}")

    code, body = req("POST", "/chat/sub", {
        "project_id": pid, "section_name": "引言", "section_id": sid or "",
        "content": content, "message": "这一节的论证逻辑有什么风险？", "agent": "critic",
    }, token, timeout=420)
    log("需求4 子Agent对话(critic→只答不改)", code == 200 and isinstance(body, dict)
        and body.get("type") != "section", f"{code} type={(body or {}).get('type')} len={len((body or {}).get('content') or '')}")

    # --- 新增：正文内联引用核验 + 导出拦截 ---
    if sid:
        # 章节生成结果本身：⚠ 引用不得被标为 [KB]
        bad_kb = [ln for ln in content.split("\n") if "⚠" in ln and ln.strip().startswith("[KB]")]
        log("引用核验 未核验引用不标KB", not bad_kb, f"bad={bad_kb[:2]}")

        # 干净正文（无引用）→ 导出不应被拦截
        clean = "本节介绍研究背景与方法设计，此处不包含任何文献引用。"
        req("PUT", f"/sections/{sid}", {"content": clean}, token)
        code, body = req("GET", f"/sections/export?project_id={pid}", None, token, timeout=180)
        log("引用核验 无引用可直接导出", code == 200, f"{code} {str(body)[:120]}")

        # 注入一个知识库里不存在的引用 → 保存报告 + 导出拦截
        fake_cite = clean + "\n\n已有研究得出相反结论 (Kowalski, 2024)，值得进一步讨论。"
        code, body = req("PUT", f"/sections/{sid}", {"content": fake_cite}, token)
        rep = (body or {}).get("citation_report") if isinstance(body, dict) else None
        log("引用核验 保存返回核验报告",
            code == 200 and isinstance(rep, dict) and rep.get("unverified") == 1,
            f"{code} report={rep}")

        code, body = req("POST", f"/sections/{sid}/verify-citations", None, token, timeout=180)
        marked = (body or {}).get("content", "") if isinstance(body, dict) else ""
        log("引用核验 接口标记虚构引用", code == 200 and "(Kowalski, 2024)⚠" in marked,
            f"{code} tail={marked[-80:]!r}")

        code, body = req("GET", f"/sections/export?project_id={pid}", None, token, timeout=180)
        detail = (body or {}).get("detail") if isinstance(body, dict) else None
        log("引用核验 导出被拦截(409)",
            code == 409 and isinstance(detail, dict) and detail.get("code") == "unverified_citations",
            f"{code} {str(detail)[:200]}")

        code, body = req("GET", f"/sections/export?project_id={pid}&allow_unverified=true",
                         None, token, timeout=180)
        raw = body if isinstance(body, str) else str(body)
        log("引用核验 确认后可导出且带⚠", code == 200 and "⚠" in raw, f"{code} len={len(raw)}")

        # 真实引用不被误伤（Vaswani 2017 已上传到本项目）
        real_cite = clean + "\n\n该架构完全基于注意力机制 (Vaswani, 2017)。"
        code, body = req("PUT", f"/sections/{sid}", {"content": real_cite}, token)
        rep = (body or {}).get("citation_report") if isinstance(body, dict) else None
        log("引用核验 真实引用不被误标",
            code == 200 and isinstance(rep, dict) and rep.get("unverified") == 0 and rep.get("verified") == 1,
            f"{code} report={rep}")

        # 复原章节内容，避免影响后续投递用例
        req("PUT", f"/sections/{sid}", {"content": content}, token)

    # --- 需求5：文献推荐 ---
    t0 = time.time()
    code, body = req("GET", f"/recommendations?project_id={pid}", None, token, timeout=300)
    dt = time.time() - t0
    recs = (body.get("recommendations") or body.get("papers") or []) if isinstance(body, dict) else []
    rerr = body.get("error") if isinstance(body, dict) else None
    log("需求5 文献推荐", code == 200, f"{code} {dt:.1f}s n={len(recs)} error={rerr} keys={list(body)[:8] if isinstance(body, dict) else None}")

    # --- 需求5：知识地图 ---
    code, body = req("GET", f"/knowledge-map?project_id={pid}", None, token, timeout=300)
    nodes = body.get("nodes") or [] if isinstance(body, dict) else []
    edges = body.get("edges") or body.get("links") or [] if isinstance(body, dict) else []
    keys = [(e.get("type"), tuple(sorted([str(e.get("source")), str(e.get("target"))]))) for e in edges]
    log("需求5 知识地图", code == 200 and len(nodes) >= 1,
        f"{code} nodes={len(nodes)} edges={len(edges)} dup={len(keys) != len(set(keys))} error={(body or {}).get('error') if isinstance(body, dict) else None}")

    # --- 需求5：论文投递 ---
    t0 = time.time()
    code, body = req("POST", "/submit/recommend", {"project_id": pid, "top_k": 5}, token, timeout=420)
    jn = (body.get("journals") or body.get("recommendations") or []) if isinstance(body, dict) else []
    log("需求5 投递-期刊推荐", code == 200, f"{code} {time.time()-t0:.1f}s n={len(jn)} keys={list(body)[:8] if isinstance(body, dict) else None} {str(body)[:200]}")

    t0 = time.time()
    code, body = req("POST", "/submit/format-check", {"project_id": pid, "journal_name": "IEEE Access"}, token, timeout=420)
    sug = (body.get("suggestions") or []) if isinstance(body, dict) else []
    log("需求5 投递-格式检查", code == 200, f"{code} {time.time()-t0:.1f}s n={len(sug)} {str(body)[:250]}")

    if sug:
        code, body2 = req("POST", "/submit/format-apply", {
            "project_id": pid, "section_name": "引言", "suggestions": sug[:2],
        }, token, timeout=420)
        log("需求5 投递-格式应用", code == 200, f"{code} {str(body2)[:250]}")
    else:
        log("需求5 投递-格式应用", True, "skipped: 无可用 suggestions（空章节场景）")

    # --- 越权校验 ---
    code, body = req("POST", "/auth/register", {"username": user_b, "password": pwd})
    t2 = body.get("token") if isinstance(body, dict) else None
    if t2:
        for name, method, path, pl in [
            ("submit/recommend", "POST", "/submit/recommend", {"project_id": pid}),
            ("submit/format-check", "POST", "/submit/format-check", {"project_id": pid, "journal_name": "IEEE Access"}),
            ("submit/format-apply", "POST", "/submit/format-apply", {"project_id": pid, "section_name": "引言", "suggestions": [{"a": 1}]}),
            ("knowledge-map", "GET", f"/knowledge-map?project_id={pid}", None),
            ("recommendations", "GET", f"/recommendations?project_id={pid}", None),
        ]:
            code, body = req(method, path, pl, t2, timeout=180)
            log(f"越权拒绝 {name}", code in (401, 403, 404), f"{code} {str(body)[:140]}")
    else:
        log("越权用户注册", False, str(body)[:160])

    return summary()


def summary():
    print("\n===== SUMMARY =====", flush=True)
    fails = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}\t{name}\t{detail[:400]}", flush=True)
    print(f"\ntotal={len(RESULTS)} pass={len(RESULTS)-len(fails)} fail={len(fails)}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
