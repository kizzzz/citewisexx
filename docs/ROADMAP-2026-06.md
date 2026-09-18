# CiteWise 3.0 优化路线图 (2026-06)

> 本文件是 P0 Sprint 0 合入 main 后的权威迭代计划。
> P0 提交 (ce76d7c) 在 message 中引用的 `docs/plan-woolly-bouncing-forest.md` 已丢失(当时未纳入 git),本文件替代之并作为后续唯一 roadmap。
>
> **审计来源**: 2026-06-15 由 4 个并行 agent 独立产出
> - security-reviewer: P1×8 / P2×6 / P3×1
> - python-reviewer: HIGH×10 / MEDIUM×5 / LOW×5
> - architect: 综合 2.9/5,5 个架构债
> - code-explorer: 六字流程功能矩阵 + Top 8 功能空白
>
> **设计初衷**: AI 产品经理面试核心项目,围绕"**找读记聊写投**"全流程,展示 Prompt + RAG + Agent + Context + Memory 五大能力。

---

## 🔴 三处交叉印证的根因(最高优先级)

四份独立审计都指向同一组根因 —— 这些不是孤立 bug,而是架构选择,必须系统性修。

### 根因 1: 全局 LLM 单例 `set_override` (P0.2 只止了血)
- **security P1#8**: 用户 A 的 api_key 在并发 await 点可能服务用户 B 的请求
- **quality HIGH#1, #5**: `set_override` 替换 `self.client` 会丢弃飞行中的旧客户端句柄(连接泄漏);try/finally 无法阻止线程/协程切换期间另一协程读到中间状态
- **architect 债#2**: "用户级配置走进程级单例" 反模式,asyncio 下尤其严重
- **根因修复**: 删除 `set_override`/`clear_override`,改用 `contextvars.ContextVar` 承载 api_key/base_url,或参数逐层透传到 `achat`/`achat_stream`(llm.py 已支持)

### 根因 2: LangGraph 双流程定义(主路径绕过图)
- **architect 债#1**: `async_graph.stream_chat_response` 手写编排,`graph.py` 声明式图形同虚设;LangGraph 的 checkpoint/replay 能力在主对话路径上完全失效
- **quality HIGH#3**: async 路径里 `WriterAgent`/`AnalystAgent` 调用同步 `self._llm.chat(...)`,阻塞事件循环
- **影响**: 每次流程改动需双写,新增 Agent 必有一处漏改
- **根因修复**: 主路径改用 `graph.astream_events(version="v2")` 订阅,节点改 async,LLM 用 LangChain `ChatModel` 包装以触发 `on_chat_model_stream`

### 根因 3: 部署配置割裂(上线即崩 / 上线即泄)
- **security P1#6**: `/docs` 与 `/openapi.json` 在生产暴露 29 个接口
- **security P1#7**: `render.yaml` 未声明 `JWT_SECRET`,启动崩或被迫硬编码到镜像
- **architect 评**: 前端 `app.js` 硬编码生产域名 `citewise-w9op.onrender.com`;三份部署清单(Render/Vercel/Docker)配置不一致
- **根因修复**: 环境变量集中校验 + 生产关闭 docs + `.dockerignore` 排除 `.env` + 前端 API_BASE 走配置

---

## 📋 Sprint 1: P1 安全收口(立即,面试演示前必做)

> 目标: 消除跨用户数据泄漏与"上线即崩"风险。预估 2-3 天。

| ID | 问题 | 文件:行 | 修复方向 | 工作量 | 关联根因 |
|----|------|---------|----------|--------|----------|
| S1.1 | papers 越权读/改(IDOR) | `api/routes/papers.py:252,327` | 取到 paper 后立即 `verify_project_owner(paper["project_id"], user["user_id"])` | S | - |
| S1.2 | submit 三接口无项目归属校验 | `api/routes/submit.py:14,33,53` | 三个 handler 取 `req.project_id` 后立即 `verify_project_owner(...)` | S | - |
| S1.3 | SSRF + API Key 外泄 | `api/routes/apikeys.py:64-93` | (a) 强制 https; (b) `ipaddress` 拒私网/回环; (c) `allow_redirects=False`; (d) 不把用户 key 转发到 custom base_url | M | - |
| S1.4 | `/api/eval/*` 完全未鉴权 | `src/eval/dashboard.py:19,28,35` | 三个 endpoint 加 `Depends(require_auth)`,project_id 非空时 `verify_project_owner` | S | - |
| S1.5 | sub-chat 跨项目检索 | `src/core/agents/researcher.py:34` | `hybrid_search(..., project_id=project_id)` 传项目过滤 | S | - |
| S1.6 | `/docs` 生产暴露 | `api/main.py:98` | `docs_url=None if ENV=="production" else "/docs"` | S | 根因3 |
| S1.7 | render.yaml 缺 JWT_SECRET | `render.yaml:6-18` | 加 `- key: JWT_SECRET sync: false`;CI 启动断言;`.dockerignore` 排除 `.env` | S | 根因3 |
| S1.8 | LLM 单例并发泄漏 | `src/core/llm.py:51-63`, `coordinator.py:60-77` | 删 `set_override`,改 contextvar 或参数透传 | M | **根因1** |
| S1.9 | BM25 全局可变状态竞态 | `src/core/bm25_store.py:32-43`, `retriever.py:24` | `threading.RLock` 保护 add/build/search,或 COW 原子替换 | M | - |

**完成标准**: 12/12 P0 回归 + 9 条 P1 验证脚本全过。

---

## 🎯 Sprint 2: 六字流程功能补齐(高 ROI,面试讲故事)

> 目标: 把"半成品闭环"补成"完整闭环"。按价值×工作量选 5 条。预估 1-2 周。

按 code-explorer 盘点,当前:
- ✅ **找**: 检索栈完整(改写 → HyDE → 多查询 → BM25+向量 → RRF → 三档 rerank → 父扩展 → 缓存)
- ✅ **读**: Docling+pdfplumber 双层解析,L0-L2 层级切片
- ⚠️ **记**: 三层记忆扎实,**缺 Episodic 层**(MEMORY.md 承诺四层);`GlobalProfile.get_reusable_assets` 是**死代码**
- ✅ **聊**: LangGraph + SSE + Timeline 是最强演示面(但 PRD 号称 ReAct,实际是固定路由)
- ⚠️ **写**: 引用 `[作者,年份]` 在正文里有,**文末参考文献章节完全缺失**
- ⚠️ **投**: 期刊推荐完整,**Word/LaTeX 导出 + 投稿追踪完全空白**

### Top 5 功能补齐(按 ROI 排序)

| # | 六字 | 功能 | 价值 | 工作量 | 面试故事点 |
|---|------|------|------|--------|------------|
| F1 | 写 | **参考文献章节自动生成** | 5 | S(1-2天) | 当前是"半成品论文";补齐后讲"闭环 vs 开环"。复用 `retriever.validate_citations` 已有的作者-年份数据,聚合去重按 APA/GB7714 排版 |
| F2 | 投 | **Word (.docx) 导出** | 4 | M(2-4天) | PRD P1 承诺。`python-docx` 按章节标题+引用+表格,补 `GET /sections/export?format=docx`。研究者最终交付物 |
| F3 | 记 | **Episodic Memory 持久化** | 5 | M(3-5天) | 三层 → 四层,故事完整度+1。复用 `session_summaries` 表 + LLM 摘要,跨会话召回"半月前的项目不冷启动" |
| F4 | 记 | **激活跨项目复用(死代码)** | 3 | S(1-2天) | `GlobalProfile.get_reusable_assets` 已存在但无路由调用;激活后新建项目弹"沿用模板/框架/风格",工作量极低故事点很高 |
| F5 | 读 | **多文档对比视图** | 4 | M(3-5天) | `extraction` 已有结构化字段,补 `/extraction/compare?paper_ids=...` + 前端 diff 表;研究者"对比阅读"高频场景 |

### 次优(Nice to have)

| # | 六字 | 功能 | 价值 | 工作量 |
|---|------|------|------|--------|
| F6 | 找 | arXiv/OpenAlex/CrossRef 直搜+一键导入 | 4 | M(3-5天) |
| F7 | 聊 | Agent Tool Calling 协议化(真 ReAct) | 3 | L(5-8天) |
| F8 | 投 | 投稿追踪状态机 + Cover Letter 生成 | 3 | M(3-5天) |

---

## 🏗️ Sprint 3: 架构债(面试能讲透,不被追问倒)

> 目标: 把架构债转成"洞察"。这些不是 P0/P1 那种"必须修",而是"被追问时必须能答"。预估 1-2 周。

| ID | 债 | 文件 | 处理方式 | 面试讲法 |
|----|-----|------|----------|----------|
| A1 | LangGraph 双流程定义 | `async_graph.py:214-507` | 主路径改 `astream_events` 订阅 | "技术诚实度:astream_events 在同步节点上拿不到 chat_model_stream,故手写;现已用 ChatModel 包装统一" |
| A2 | AgentState 25+ 字段膨胀 | `graph_state.py` | 拆 `InputState`/`ExecutionState`/`OutputState` | "节点只声明依赖的子集,类型检查能 catch 拼写错误" |
| A3 | `graph.py` 上帝模块 | `graph.py` | 抽 `section_parser.py` / `export_service.py` | "SRP,新增章节类型不改图文件" |
| A4 | `memory.py` 886 行混合 5 职责 | `src/core/memory.py` | 拆 `global_profile.py`/`project_memory.py`/`working_memory.py`/`migrations.py`;改 8 次 `try/except: pass` 用 `PRAGMA table_info` 预检 | "5 职责拆 4 文件,静默吞错改预检" |
| A5 | `agent.py` 647 行死代码 | `src/core/agent.py` | 删除(`async_graph` 已是唯一入口) | "主动清死代码,降认知负担" |
| A6 | Tool 抽象缺失(开闭原则) | `src/core/agents/researcher.py` | `web_search/rag/cove` 包装成 `BaseTool`,Agent `bind_tools` | "新工具零改动接入" |

---

## 🔧 Sprint 4: P2 代码质量与防御(长期)

> 目标: 工程化基线。可与 Sprint 2/3 穿插。预估 1 周。

### 安全 P2 (security)
- [P2] `auth.py` 登录/注册独立限流(`slowapi` 5 req/min/用户名) + 统一模糊错误消息防枚举
- [P2] `api/main.py:35-40` X-Forwarded-For 信任白名单(只信任 Render 反代),否则限流可绕过
- [P2] `sections.py:152-156` 导出文件名 `secure_filename` 白名单清洗(CRLF/路径穿越)
- [P2] `papers.py:58-77` 文件上传加 `python-magic` magic bytes 校验 + filename 长度限制
- [P2] `sections.py:106` / `submit.py:30,49,68` 错误信息脱敏(对外通用提示 + trace_id,细节只进日志)
- [P2] `chat.py:34-51` SSE 加心跳(15s ping) + 单连接 5 分钟超时 + 每用户并发上限(3)

### 质量 HIGH (python-reviewer,未在 S1 覆盖的)
- [HIGH] `chat.py:34-49` SSE 错误处理:鉴权/参数校验放生成器外,区分 `HTTPException`(透传状态码)与 `Exception`(兜底)
- [HIGH] `async_graph.py:144-208` async 节点统一用 `await achat`,禁止 `.chat` 同步调用
- [HIGH] `api/main.py:43-63` `_is_rate_limited` 清理移出锁,或改 `cachetools.TTLCache`
- [HIGH] `src/eval/metrics.py:95-114` SQL f-string 改参数化(`?` 占位)
- [HIGH] `api/routes/notes.py:76-78` `paper_row or {}` 防御 None
- [HIGH] `chat.py:75-82` `/chat/sub` 加 `asyncio.wait_for(..., timeout=120)`

### 质量 MEDIUM/LOW
- [MED] `api/routes/*.py` 56 个 handler 补返回类型注解(85% 缺失),`BaseModel` 响应模型
- [MED] 引用正则抽 `src/core/citations.py`(4 处共用: `agent.py`/`retriever.py`/`source_annotation.py`/`graph.py`)
- [MED] `embedding.py:90-104` 完全失败时 `raise RuntimeError`,不要返回 `[]` 静默
- [MED] JWT 升 RS256/EdDSA + 支持 `JWT_SECRET_FILE` 热加载
- [LOW] `embedding.py:34` MD5 → `blake2b`(非加密用途,但避扫描告警)
- [LOW] `auth.py:93-95` 删除裸 `except Exception`(PyJWT 错误都是 `PyJWTError` 子类)
- [LOW] `async_graph.py:544-548` `get_async_graph` 补双重检查锁(对齐同步版)
- [LOW] 抽 `src/utils/timing.py` 统一 `elapsed_ms_since(start)`(10+ 处重复)

### 安全 P3
- [P3] `auth.py:66-74` JWT 加 `jti` + 服务端 revoked 表;access token 缩到 15min + refresh 7 天

---

## ✅ 立即执行的 Top 10(按优先级)

如果只有时间做 10 件事,按此顺序:

1. **S1.8** LLM contextvar(根因1,三方独立印证)
2. **S1.5** sub-chat 传 project_id(跨项目数据泄漏)
3. **S1.1 + S1.2** papers/submit IDOR 收口(两条一起,同一 `verify_project_owner` 模式)
4. **S1.3** apikeys SSRF + key 外泄(最严重的外向风险)
5. **S1.4** eval 路由加鉴权
6. **S1.6 + S1.7** 部署配置收口(/docs + JWT_SECRET,同一 PR)
7. **S1.9** BM25 加锁
8. **F1** 参考文献章节(写闭环,工作量小)
9. **F4** 激活跨项目复用死代码(记,工作量极小)
10. **F2** Word 导出(投闭环,PRD 承诺)

**预估**: Top 10 共约 8-12 个工作日,覆盖安全收口 + 六字闭环核心。

---

## 📊 健康度评分(architect)

| 维度 | 分 | 评语 |
|---|---|---|
| 模块化 | 3.5/5 | core/agents vs core/ 边界清晰,但 graph.py 上帝模块 |
| 状态管理 | 2.5/5 | AgentState 膨胀 + 全局 LLM 单例 |
| 可扩展性 | 3.0/5 | 新增 Agent 需改 4 处(图/router/timeline 白名单/前端) |
| 流式架构 | 2.5/5 | 双流程定义,SSE 错误恢复薄 |
| 前端 SPA | 2.0/5 | 单文件 app.js,无模块化 |
| 部署适配 | 3.0/5 | 三份清单 + 前端硬编码生产域名 |
| **综合** | **2.9/5** | **面试原型合格,生产不及格** |

## 🎤 面试"会被追问"清单(必须能答)

- "MemorySaver 多用户怎么隔离?" → `thread_id=project_id`;**主动补**: 内存级,进程重启即失,生产换 Postgres checkpointer
- "为什么 stream 绕过 LangGraph?" → **坦诚**: astream_events 在同步节点拿不到 chat_model_stream;**给迁移路径**(Sprint 3 A1)
- "用户 A 的 Key 会漏给 B 吗?" → 讲 set_override + try/finally;**主动补**: 更彻底是 contextvar(Sprint 1 S1.8)
- "AgentState 为什么这么胖?" → 别辩,承认技术债,讲拆三段计划(Sprint 3 A2)
- "前端为什么不用框架?" → "原型阶段优先验证 AI 能力",说清迁移路径

---

**文档维护**: 每完成一条,勾选 `[x]` 并在 PR 描述中引用本文件的对应 ID。新发现追加到对应 Sprint 末尾。
