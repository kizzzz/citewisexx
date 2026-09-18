# CiteWise — 记忆工程设计

> 版本：V1.0 | 更新：2026-04-02
> 定位：面试展示用，体现对 LLM 应用记忆系统的系统化设计能力

---

## 1. 设计目标

> **维度说明**：本文档描述的 3 层记忆体系（Global/Project/Working）是从**数据持久化**角度对信息的分层管理。这与 Prompt Engine 文档（`01-prompt-design.md`）中的 Layer 1-5 体系不同——Layer 1-5 是**运行时 Prompt 组装**的分层架构。两者是不同维度的划分：记忆关注"数据存在哪里、活多久"，Prompt 层次关注"运行时按什么顺序组装给 LLM"。

CiteWise 的记忆系统要解决一个核心问题：**让 AI "认识" 用户**。

| 没有记忆 | 有记忆 |
|----------|--------|
| 每次对话从零开始 | 系统知道你的研究领域 |
| 每个项目重新配置 | 自动沿用历史偏好 |
| 不了解你的写作习惯 | 按你的风格生成 |
| 无法跨项目复用知识 | 字段模板、框架一键复用 |

---

## 2. 三层记忆架构

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: 全局用户画像（Global Profile）                   │
│ 生命周期：永久（跨项目）                                   │
│ 存储：JSON 文件                                           │
│ 内容：研究领域、关注方向、字段模板库、写作偏好              │
├─────────────────────────────────────────────────────────┤
│ Layer 2: 项目记忆（Project Memory）                       │
│ 生命周期：项目存续期间                                     │
│ 存储：SQLite                                              │
│ 内容：文献列表、提取结果、框架、生成状态、会话摘要          │
├─────────────────────────────────────────────────────────┤
│ Layer 3: 工作记忆（Working Memory）                       │
│ 生命周期：当前会话                                        │
│ 存储：内存                                                │
│ 内容：焦点论文、当前任务、对话上下文、临时状态              │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Layer 1：全局用户画像

### 3.1 画像数据结构

```json
{
  "user_id": "user_001",
  "created_at": "2026-04-02",
  "last_active": "2026-04-02",

  "research_profile": {
    "field": "城市规划与交通",
    "sub_fields": ["电动汽车", "空间分析", "政策评估"],
    "research_level": "博士",
    "common_methodologies": ["MGWR", "面板数据", "空间计量"]
  },

  "field_templates": [
    {
      "template_id": "tpl_001",
      "name": "交通领域默认模板",
      "fields": ["研究方法", "数据集", "空间范围", "核心指标", "创新点"],
      "usage_count": 3,
      "last_used": "2026-03-28"
    },
    {
      "template_id": "tpl_002",
      "name": "方法对比模板",
      "fields": ["方法名称", "输入特征", "输出指标", "优势", "局限性"],
      "usage_count": 1,
      "last_used": "2026-03-20"
    }
  ],

  "writing_preferences": {
    "style": "academic_formal",
    "language": "zh-CN",
    "citation_style": "APA",
    "avg_section_length": 1200,
    "prefer_charts": true,
    "framework_preference": "IMRaD"
  },

  "interaction_patterns": {
    "typical_workflow": ["upload → summarize → framework → generate"],
    "frequent_modifications": ["调整方法分类", "增加对比图表"],
    "common_queries": ["方法对比", "数据来源", "创新点总结"]
  }
}
```

### 3.2 画像更新机制

```
显式更新（用户主动告知）：
  用户: "我是做城市规划的"
  → 更新 research_profile.field

  用户: "字段加上'研究区域'"
  → 更新 field_templates

隐式更新（系统自动学习）：
  - 用户连续 3 次使用相同字段模板 → 标记为默认模板
  - 用户总在修改"方法"相关段落 → 记录 frequent_modifications
  - 用户的项目主题集中在某领域 → 更新 sub_fields
```

```python
class UserProfileManager:
    """全局用户画像管理器"""

    def __init__(self, profile_path: str):
        self.profile_path = profile_path
        self.profile = self._load()

    def update_from_interaction(self, interaction: dict):
        """从用户交互中隐式更新画像"""
        updates = []

        # 检测模板复用
        if interaction["type"] == "field_extraction":
            template_key = tuple(interaction["fields"])
            usage = self._count_template_usage(template_key)
            if usage >= 3:
                updates.append("frequent_template")
                self._mark_as_default(template_key)

        # 检测修改偏好
        if interaction["type"] == "rewrite":
            topic = interaction["modification_topic"]
            self._record_modification(topic)
            if self._is_frequent_modification(topic):
                updates.append("frequent_modification")

        # 检测研究领域
        if interaction["type"] == "project_create":
            topics = interaction["paper_topics"]
            self._update_research_fields(topics)
            updates.append("field_update")

        return updates

    def get_reusable_assets(self) -> dict:
        """获取可跨项目复用的资产"""
        return {
            "default_template": self._get_default_template(),
            "last_framework": self.profile.get("last_used_framework"),
            "writing_style": self.profile["writing_preferences"],
            "suggested_fields": self._suggest_fields()
        }

    def _suggest_fields(self) -> list[str]:
        """根据研究领域推荐字段"""
        field = self.profile["research_profile"]["field"]
        # 基于历史使用频率排序
        all_fields = self._get_all_used_fields()
        return sorted(all_fields, key=lambda f: f["count"], reverse=True)[:5]
```

---

## 4. Layer 2：项目记忆

### 4.1 数据模型

```sql
-- 项目表
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    topic TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',  -- active, archived, deleted
    config TEXT  -- JSON: 框架、字段模板等
);

-- 文献表
CREATE TABLE papers (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    title TEXT,
    authors TEXT,
    year INTEGER,
    file_path TEXT,
    chunk_count INTEGER,
    indexed_at DATETIME,
    metadata TEXT  -- JSON: DOI, 期刊, 等
);

-- 提取结果表
CREATE TABLE extractions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    paper_id TEXT REFERENCES papers(id),
    template_id TEXT,
    fields TEXT,  -- JSON: {field_name: value}
    confidence TEXT,  -- JSON: {field_name: level}
    created_at DATETIME
);

-- 生成记录表
CREATE TABLE generated_sections (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    section_name TEXT,
    content TEXT,
    word_count INTEGER,
    citations TEXT,  -- JSON: [citation_list]
    generated_at DATETIME
);

-- 会话摘要表
CREATE TABLE session_summaries (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    session_id TEXT,
    summary TEXT,
    key_decisions TEXT,  -- JSON
    created_at DATETIME
);
```

### 4.2 项目状态机

```
项目创建
    │
    ▼
[知识库构建] ──→ 上传PDF → 解析 → 切片 → 向量化 → 完成
    │
    ▼
[结构化总结] ──→ 定义字段 → 批量提取 → 生成表格 → 完成
    │
    ▼
[框架讨论] ──→ 系统分析 → 推荐框架 → 用户确认 → 完成
    │
    ▼
[分节生成] ──→ 逐章生成 → 用户审阅 → 局部修改 → 完成
    │
    ▼
[导出交付] ──→ 格式化 → 导出 → 归档
```

```python
PROJECT_PHASES = {
    "knowledge_building": {
        "next": "summarization",
        "required": ["papers_indexed"]
    },
    "summarization": {
        "next": "framework_discussion",
        "required": ["extraction_done"]
    },
    "framework_discussion": {
        "next": "section_generation",
        "required": ["framework_confirmed"]
    },
    "section_generation": {
        "next": "export",
        "required": ["all_sections_generated"]
    },
    "export": {
        "next": None,
        "required": ["export_file_created"]
    }
}
```

---

## 5. Layer 3：工作记忆

### 5.1 会话状态

```python
@dataclass
class WorkingMemory:
    """当前会话的工作记忆"""
    # 当前焦点
    current_task: str = None          # 当前任务类型
    focus_paper: str = None           # 焦点论文 ID
    focus_section: str = None         # 焦点章节

    # 临时状态
    pending_confirmation: dict = None # 等待用户确认的操作
    last_tool_result: dict = None     # 最近一次工具调用结果

    # 对话上下文
    turn_count: int = 0               # 当前对话轮次
    last_user_intent: str = None      # 最近用户意图

    def snapshot(self) -> dict:
        """生成当前状态的快照"""
        return {
            "current_task": self.current_task,
            "focus_paper": self.focus_paper,
            "focus_section": self.focus_section,
            "turn_count": self.turn_count,
            "last_user_intent": self.last_user_intent
        }
```

### 5.2 会话结束时的持久化

```python
async def save_session_summary(session: WorkingMemory, project_id: str):
    """会话结束时保存摘要到项目记忆"""
    summary = await llm.summarize(
        f"将本次对话的关键信息压缩为摘要：\n"
        f"- 完成的任务：{session.tasks_completed}\n"
        f"- 用户偏好发现：{session.preferences_discovered}\n"
        f"- 待办事项：{session.pending_items}"
    )

    db.save_session_summary(
        project_id=project_id,
        summary=summary,
        key_decisions=session.key_decisions
    )

    # 同时更新全局画像
    profile_manager.update_from_session(session)
```

---

## 6. 跨项目复用

### 6.1 复用场景

```
用户创建新项目
    │
    ▼
系统检查全局画像
    │
    ├── 有历史字段模板？
    │     → "检测到您之前使用过 [方法, 数据集, 指标] 模板，是否沿用？"
    │
    ├── 有历史框架偏好？
    │     → "您上次选择了 IMRaD 框架，这次也用吗？"
    │
    ├── 有写作风格偏好？
    │     → "已应用您的学术写作风格偏好"
    │
    └── 有相关项目？
          → "您之前的'电动汽车政策'项目中有 5 篇文献也适用于这个项目，是否导入？"
```

### 6.2 推荐逻辑

```python
def recommend_reusable_assets(new_project: dict, user_profile: dict) -> list[dict]:
    """为新项目推荐可复用的资产"""
    recommendations = []

    # 推荐字段模板
    default_template = get_default_template(user_profile)
    if default_template:
        recommendations.append({
            "type": "field_template",
            "message": f"检测到您常用的字段模板：{default_template['name']}",
            "data": default_template,
            "confidence": "high"
        })

    # 推荐框架
    if user_profile.get("writing_preferences", {}).get("framework_preference"):
        recommendations.append({
            "type": "framework",
            "message": "推荐使用您偏好的论文框架",
            "data": {"framework": user_profile["writing_preferences"]["framework_preference"]},
            "confidence": "medium"
        })

    # 推荐相关文献
    related_papers = find_related_papers(new_project["topic"], user_profile)
    if related_papers:
        recommendations.append({
            "type": "related_papers",
            "message": f"发现 {len(related_papers)} 篇相关历史文献",
            "data": related_papers,
            "confidence": "medium"
        })

    return recommendations
```

---

## 7. 记忆与 Prompt 的集成

```python
def inject_memory_into_prompt(
    system_prompt: str,
    user_profile: dict,
    project_state: dict,
    working_memory: dict
) -> str:
    """将记忆信息注入 System Prompt"""

    # Layer 1: 全局画像
    profile_section = f"""
## 用户画像
- 研究领域：{user_profile['research_profile']['field']}
- 关注方向：{', '.join(user_profile['research_profile']['sub_fields'])}
- 常用方法：{', '.join(user_profile['research_profile']['common_methodologies'])}
- 写作风格：{user_profile['writing_preferences']['style']}
"""
    system_prompt += profile_section

    # Layer 2: 项目状态
    if project_state:
        project_section = f"""
## 当前项目
- 项目名称：{project_state['name']}
- 阶段：{project_state['phase']}
- 文献数量：{project_state['paper_count']}
- 已完成章节：{', '.join(project_state['completed_sections'])}
"""
        system_prompt += project_section

    # Layer 3: 工作记忆
    if working_memory.get("current_task"):
        work_section = f"""
## 当前任务
- 任务类型：{working_memory['current_task']}
- 焦点：{working_memory.get('focus_paper', '无')}
"""
        system_prompt += work_section

    return system_prompt
```

---

## 8. 面试展示要点

| 展示点 | 话术要点 |
|--------|----------|
| 三层架构 | "全局画像跨项目、项目记忆管单项目、工作记忆管当前会话，三层各有分工" |
| 显式+隐式 | "用户主动告知的信息显式更新，系统也从交互模式中隐式学习" |
| 跨项目复用 | "新项目创建时，自动推荐历史模板、框架和相关文献" |
| 状态机 | "项目有明确的阶段状态机，记忆系统跟踪每个阶段的进度" |
| 画像注入 | "用户画像动态注入到 System Prompt，LLM 每次都知道你是谁" |

---

## 9. 与其他模块的协作

```
记忆系统 → Prompt Engine：用户画像注入 System Prompt
记忆系统 → Agent：Agent 从记忆读取偏好，更新记忆
记忆系统 → 上下文工程：项目状态作为上下文层注入
记忆系统 → RAG：用户偏好影响检索过滤和排序
```
