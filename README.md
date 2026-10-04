# 校园智能问答 Agent

一个面向校园服务场景的 AI 应用项目，覆盖 **RAG 检索、Agent 工具路由、RESTful API、SQLite 持久化、用户反馈闭环和可交互前端演示**。项目默认零依赖运行；配置 `OPENAI_API_KEY` 后，可自动接入大模型生成更自然的回答。

## 项目定位

校园信息通常分散在通知、教务、后勤、部门页面里，学生经常重复询问“活动怎么报名”“宿舍网络坏了怎么办”“学生事务中心电话是多少”等问题。本项目把这些高频服务沉淀为知识库，并通过 Agent 自动选择查询工具，最终给出可执行回答。

## 核心能力

- **轻量 RAG 检索**：基于中英文 token、中文短语和关键词加权召回校园知识条目。
- **Agent 工具路由**：根据问题意图选择 `notice_search`、`department_lookup`、`repair_helper`、`academic_helper` 或通用问答。
- **可解释来源**：接口返回来源、得分和命中词，前端展示回答依据，降低“黑盒回答”感。
- **大模型增强**：支持 OpenAI 兼容接口；无 API Key 时自动降级为本地检索回答。
- **数据闭环**：SQLite 记录问答日志、来源 ID、耗时和用户反馈，支持后续统计与优化。
- **工程化展示**：提供 API 文档、架构说明、单元测试和 GitHub Actions CI。

## 技术栈

- Python 标准库 HTTP Server
- SQLite
- HTML / CSS / JavaScript
- RESTful API
- Optional: OpenAI-compatible LLM API

## 项目结构

```text
campus-ai-agent
├── app.py                    # 后端服务、Agent、检索、数据持久化
├── data/knowledge.json       # 校园知识库
├── static/                   # 前端演示页面
├── tests/test_agent.py       # 单元测试
├── docs/api.md               # API 文档
├── docs/architecture.md      # 架构说明
├── examples/chat.http        # 接口调用示例
└── resume-description.md     # 简历项目描述
```

## 快速运行

```powershell
cd campus-ai-agent
python app.py
```

打开：

```text
http://127.0.0.1:8000
```

## 接入真实大模型

```powershell
$env:OPENAI_API_KEY="your_api_key"
$env:OPENAI_MODEL="gpt-4o-mini"
```

如使用兼容 OpenAI 接口的其他平台：

```powershell
$env:OPENAI_BASE_URL="https://your-provider.example.com/v1/chat/completions"
```

## 常用接口

```http
POST /api/chat
Content-Type: application/json

{
  "question": "AI讲座怎么报名？"
}
```

```http
POST /api/feedback
Content-Type: application/json

{
  "chat_id": 1,
  "rating": "up"
}
```

更多接口见 [docs/api.md](docs/api.md)。

## 测试

```powershell
python -m unittest discover -s tests
```

## 可继续扩展

- 将知识库检索升级为向量检索。
- 将 SQLite 替换为 MySQL，适配真实业务数据。
- 增加后台知识库管理和导入功能。
- 接入校园统一认证和工单系统。
- 使用 FastAPI 重构服务层并生成 OpenAPI 文档。
