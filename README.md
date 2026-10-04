# 校园智能问答 Agent

一个面向校园服务场景的小型 AI 应用项目，支持校园通知查询、部门信息查询、宿舍报修指引和教务流程问答。项目默认使用本地知识库检索和规则化工具路由；配置 `OPENAI_API_KEY` 后，可自动调用大模型生成更自然的回答。

## 项目亮点

- 使用 Python 实现后端服务，提供 `/api/chat`、`/api/knowledge` 等 RESTful API。
- 内置轻量 RAG 检索：从校园知识库中召回相关内容，再生成可执行回答。
- 设计 Agent 工具路由：根据问题类型选择通知查询、部门查询、报修助手或通用问答工具。
- 使用 SQLite 记录问答历史，便于后续做用户画像、热门问题统计和效果分析。
- 提供可交互 Web 页面，方便演示完整 AI 应用闭环。

## 运行方式

```powershell
cd campus-ai-agent
python app.py
```

然后打开：

```text
http://127.0.0.1:8000
```

## 可选：接入真实大模型

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="gpt-4o-mini"
```

如使用兼容 OpenAI 接口的其他平台，可配置：

```powershell
$env:OPENAI_BASE_URL="https://your-provider.example.com/v1/chat/completions"
```

## 测试

```powershell
cd campus-ai-agent
python -m unittest discover -s tests
```

## 后续扩展

- 将 SQLite 替换为 MySQL，适配真实业务数据。
- 将关键词检索替换为向量检索，提升语义召回效果。
- 增加管理员后台，支持知识库增删改查。
- 接入校园数字化平台，实现统一登录和服务工单流转。
