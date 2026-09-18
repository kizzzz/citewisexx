"""API 请求/响应模型"""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    project_id: str = Field(..., min_length=1, description="项目ID")
    session_id: str = Field("", description="对话会话 ID（为空则创建新会话）")
    api_key: str = Field("", description="用户自带 API Key（可选）")
    base_url: str = Field("", description="用户自定义 Base URL（可选）")
    model: str = Field("", description="模型名称（可选）")


class SubChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    project_id: str = Field(..., min_length=1, description="项目ID")
    section_name: str = Field(..., min_length=1, description="章节名称")
    section_id: str = Field("", description="章节 ID（持久化协作面板对话用）")
    content: str = Field("", description="当前章节内容")
    api_key: str = Field("", description="用户自带 API Key（可选）")
    base_url: str = Field("", description="用户自定义 Base URL（可选）")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    topic: str = Field("", max_length=500, description="研究主题")


class SectionCreate(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目ID")
    name: str = Field(..., min_length=1, max_length=100, description="章节名称")
    style: str = Field("学术正式", description="写作风格：学术正式/通俗/报告/严谨")
    target_length: int = Field(1000, description="目标字数")
    citation_density: str = Field("正常", description="引用密度：高/正常/低")
    agent: str = Field("writer", description="负责 Agent ID")
    system_prompt: str = Field("", description="用户自建 Agent 的系统提示词")
    requirements: str = Field("", description="章节要求：简述、重点、格式等")


class SectionUpdate(BaseModel):
    content: str = Field(..., description="章节内容")


class ExtractionRequest(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目ID")
    fields: list[str] = Field(..., min_length=1, description="提取字段列表")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="搜索查询")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="TTS文本")


class FieldsRequest(BaseModel):
    fields: list[str] = Field(..., min_length=1, description="字段列表")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class ApiKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API Key")


class ApiKeyVerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=1, description="API Key")
    provider: str = Field("zhipu", description="供应商 ID")
    base_url: str = Field("", description="自定义 Base URL")


class JournalRecommendRequest(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目ID")
    research_topic: str = Field("", max_length=500, description="补充研究主题（可选）")
    top_k: int = Field(8, description="推荐数量")


class FormatCheckRequest(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目ID")
    journal_name: str = Field(..., min_length=1, max_length=200, description="目标期刊名称")


class FormatApplyRequest(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目ID")
    section_name: str = Field(..., min_length=1, description="章节名称")
    suggestions: list[dict] = Field(..., min_length=1, description="用户选中的格式修改项")


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="新标题")
