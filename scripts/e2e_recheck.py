#!/usr/bin/env python3
"""聚焦复核：最终 content 事件中的三色标记是否合法 + 章节是否残留占位参考文献。

关键点：SSE 的 token 事件是模型原始输出（可能自带 [KB] 字样），
真正渲染给用户的是 content 事件（经过 annotate_sources 程序化标注）。
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:5328/api"
R = []


def log(name, ok, detail=""):
    R.append((name, ok, str(detail)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {str(detail)[:700]}", flush=True)


def req(method, path, payload=None, token=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(b)
            except Exception:
                return resp.status, b
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(b)
        except Exception:
            return e.code, b
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def sse(path, payload, token, timeout=420):
    r = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), method="POST")
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + token)
    tokens, final, sources = [], "", []
    cur = None
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    cur = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if cur == "token" and isinstance(d, dict):
                        tokens.append(d.get("text", ""))
                    elif cur == "content" and isinstance(d, dict):
                        final = d.get("content", "") or final
                    elif cur == "sources":
                        sources = d
    except Exception as e:  # noqa: BLE001
        print("sse error:", e, flush=True)
    return "".join(tokens), final, sources


MD = (
    "# Attention Is All You Need\nAuthors: Ashish Vaswani, Noam Shazeer\nYear: 2017\n\n"
    "## Abstract\nWe propose the Transformer, based solely on attention mechanisms, dispensing "
    "with recurrence and convolutions entirely.\n\n"
    "## Results\nOn the WMT 2014 English-to-German translation task the Transformer achieves "
    "28.4 BLEU, improving over the previous best results by over 2 BLEU.\n"
)


def upload(pid, token):
    b = "----x" + uuid.uuid4().hex
    body = (
        f"--{b}\r\nContent-Disposition: form-data; name=\"project_id\"\r\n\r\n{pid}\r\n"
        f"--{b}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"p.md\"\r\n"
        f"Content-Type: text/markdown\r\n\r\n{MD}\r\n--{b}--\r\n"
    ).encode()
    r = urllib.request.Request(BASE + "/papers/upload", data=body, method="POST")
    r.add_header("Content-Type", f"multipart/form-data; boundary={b}")
    r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=420) as resp:
        return resp.read().decode("utf-8", "replace")[:120]


PLACEHOLDER = re.compile(r'作者\s*\.\s*(（?标题）?|标题)|标题\.\s*期刊|XXXX|（年份）|\[\d+\]\s*作者')


def bad_tag_lines(text, allowed):
    """返回含非法来源标记的行"""
    bad = []
    for ln in text.split("\n"):
        for tag in ("KB", "WEB", "AI"):
            if f"[{tag}]" in ln and tag not in allowed:
                bad.append(ln.strip()[:120])
                break
    return bad


def dup_tag_lines(text):
    return [ln.strip()[:120] for ln in text.split("\n")
            if len(re.findall(r'\[(?:KB|WEB|AI)\]', ln)) > 1]


def main():
    s = uuid.uuid4().hex[:8]
    code, body = req("POST", "/auth/register", {"username": f"v{s}", "password": "Test1234!"})
    token = body.get("token") if isinstance(body, dict) else None
    if not token:
        log("register", False, f"{code} {body}")
        return done()

    code, body = req("POST", "/projects", {"name": f"V {s}", "topic": "自注意力机制"}, token)
    pid = body.get("id") if isinstance(body, dict) else None
    log("setup", bool(pid), f"pid={pid}")
    if not pid:
        return done()

    # A. 无文献提问 —— 最终 content 不得出现 [KB]
    raw, final, _ = sse("/chat", {
        "project_id": pid, "message": "自注意力机制相比 RNN 的主要优势是什么？"}, token)
    body_text = final or raw
    log("A 无文献: 最终内容无 [KB]", "[KB]" not in body_text,
        f"raw含KB={'[KB]' in raw} final含KB={'[KB]' in (final or '')} len={len(body_text)}")
    log("A 无文献: 无重复标记行", not dup_tag_lines(body_text), f"dup={dup_tag_lines(body_text)[:3]}")
    log("A 无文献: 出现 [WEB]/[AI]", ("[WEB]" in body_text or "[AI]" in body_text),
        f"web={'[WEB]' in body_text} ai={'[AI]' in body_text}")

    # B. 上传文献后提问 —— 允许 [KB]
    log("B 上传", True, upload(pid, token))
    time.sleep(6)
    raw2, final2, src2 = sse("/chat", {
        "project_id": pid, "message": "根据上传文献，Transformer 在 WMT 2014 英德任务上的 BLEU 是多少？"}, token)
    t2 = final2 or raw2
    log("B 有文献: 命中 [KB]", "[KB]" in t2, f"kb={'[KB]' in t2} hit28.4={'28.4' in t2}")
    log("B 有文献: 无重复标记行", not dup_tag_lines(t2), f"dup={dup_tag_lines(t2)[:3]}")
    log("B 有文献: sources 返回", bool(src2), f"n={len(src2) if isinstance(src2, list) else 0}")

    # C. 章节生成 —— 不得残留占位参考文献
    code, body = req("POST", "/sections", {
        "project_id": pid, "name": "引言", "style": "学术正式", "target_length": 600,
        "citation_density": "正常", "agent": "writer", "requirements": "自注意力机制研究背景",
    }, token, timeout=420)
    content = body.get("content", "") if isinstance(body, dict) else ""
    hits = [ln.strip()[:120] for ln in content.split("\n") if PLACEHOLDER.search(ln)]
    log("C 章节: 无占位参考文献", code == 200 and not hits, f"{code} len={len(content)} hits={hits[:3]}")
    log("C 章节: 无重复标记行", not dup_tag_lines(content), f"dup={dup_tag_lines(content)[:3]}")
    print("\n--- 章节末尾 300 字 ---\n" + content[-300:], flush=True)
    return done()


def done():
    print("\n===== SUMMARY =====", flush=True)
    f = [x for x in R if not x[1]]
    for n, ok, d in R:
        print(f"{'PASS' if ok else 'FAIL'}\t{n}\t{d[:300]}", flush=True)
    print(f"\ntotal={len(R)} pass={len(R)-len(f)} fail={len(f)}", flush=True)
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
