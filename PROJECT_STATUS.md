# CiteWise 项目状态

> 最后更新: 2026-04-08
> 状态: **V3.1 LangGraph 多 Agent 架构已完成**

## 项目概况
- 目标: AI产品经理面试核心项目 — 从文献梳理到论文产出的全流程智能助手
- 技术栈: FastAPI + LangGraph + 智谱 GLM-4.7 + embedding-3 + Chroma + Tailwind CSS SPA
- API: 智谱 (base_url=open.bigmodel.cn)

## V3.1 架构 — LangGraph Supervisor 模式

```
用户输入 → [Supervisor] → 路由意图
  ├── [Researcher] → RAG+联网 → [Responder] (explore/websearch)
  ├── [Researcher] → RAG → [Writer] (generate/modify/framework)
  ├── [Researcher] → RAG → [Analyst] (analyze/chart)
  └── 直接 → [Writer] (export)
```

- `src/core/graph_state.py` — AgentState TypedDict (19字段)
- `src/core/graph.py` — StateGraph + MemorySaver (持久化会话)
- `api/routes/chat.py` — `astream_events` 实时推送 agent_start/agent_end
- `static/js/agent-timeline.js` — 右侧 Agent Timeline 可视化面板

## 已实现功能
- [x] LangGraph Supervisor 多 Agent 编排 (声明式图结构)
- [x] 前端 Agent Timeline 实时可视化
- [x] PDF上传解析 + 层级切片(L0/L1/L2)
- [x] 混合检索(BM25+向量+RRF融合+重排)
- [x] 主对话(全局记忆) + 子对话(章节级)
- [x] 程序化来源标注(📖RAG蓝/🌐联网绿/🧠推理紫)
- [x] 联网搜索(DuckDuckGo API)
- [x] 结构化总结(自定义字段 + Excel导出)
- [x] 侧边栏章节管理 + 自然语言管理章节
- [x] 6篇测试论文已入库
- [x] AgentEval 评估面板

## 项目结构
```
~/CiteWise/
├── run.py                    # 启动入口 (uvicorn)
├── Procfile                  # 部署配置
├── api/
│   ├── main.py              # FastAPI app 入口 + 限流
│   └── routes/
│       ├── chat.py          # LangGraph astream_events SSE
│       ├── projects.py
│       ├── papers.py
│       ├── sections.py
│       ├── extraction.py
│       └── search.py
├── static/
│   ├── index.html           # Tailwind CSS SPA + Agent Timeline 侧栏
│   ├── js/
│   │   ├── app.js           # 前端逻辑 + agent 事件解析
│   │   └── agent-timeline.js # Timeline 组件
│   └── css/
├── src/
│   ├── core/
│   │   ├── graph_state.py   # AgentState TypedDict
│   │   ├── graph.py         # LangGraph StateGraph 编排
│   │   ├── llm.py           # LLM 调用层 (OpenAI 兼容)
│   │   ├── rag.py           # PDF 解析+层级切片
│   │   ├── embedding.py     # Embedding + Chroma
│   │   ├── retriever.py     # 混合检索
│   │   ├── prompt.py        # Prompt 模板
│   │   ├── memory.py        # 三层记忆
│   │   ├── source_annotation.py # 来源标注
│   │   └── agents/
│   │       ├── base.py      # Agent 基类
│   │       ├── coordinator.py # 兼容层 (graph.invoke)
│   │       ├── router.py    # 意图路由
│   │       ├── researcher.py # RAG 检索
│   │       ├── writer.py    # 章节生成
│   │       └── analyst.py   # 数据分析
│   └── tools/web_search.py  # 联网搜索
├── data/db/                  # SQLite + Chroma
├── papers/                   # 上传的 PDF
└── docs/                     # 技术设计文档
```

## 待完成
1. **LLM 异步流式**: 让 LLM 调用异步化，实现逐字流式输出
2. **CoVe 验证**: 新建 src/core/cove.py，实现验证问题生成+交叉校验
3. **高级PDF解析**: 集成 LlamaParse/Docling
4. **部署上线**: Render 或 Vercel
5. **面试Demo脚本**: 按 docs/09-demo-script.md 演练
