# 架构说明

## 数据流

```text
用户问题
  -> 意图识别与工具路由
  -> 混合 RAG 检索（向量召回 + 关键词 fallback）
  -> 可选大模型生成
  -> 回答与来源返回
  -> SQLite 记录日志
  -> 用户反馈沉淀
```

## 模块说明

- `KnowledgeAgent.pick_tool`：根据问题关键词路由到通知查询、部门查询、报修助手、教务助手或通用问答。
- `KnowledgeAgent.retrieve`：合并向量检索和关键词检索结果，生成可解释来源。
- `VectorIndex`：支持 OpenAI Embedding、sentence-transformers、本地 hashing embedding；有 FAISS 时使用 FAISS，否则使用 NumPy 余弦检索。
- `KnowledgeAgent.create_knowledge/update_knowledge/delete_knowledge`：维护知识库文件，并在变更后重建向量索引。
- `call_llm`：在配置 API Key 后调用 OpenAI 兼容接口；调用失败时自动回退本地回答。
- `chat_logs`：记录问题、回答、工具、来源、耗时和是否使用模型。
- `feedback`：记录用户对回答的正负反馈。

## 为什么保留零依赖实现

项目面向实习岗位展示，优先保证克隆后可以直接运行和验证。核心后端使用 FastAPI，向量检索依赖采用渐进增强：有 OpenAI/sentence-transformers/FAISS 就使用更强能力，否则保持本地可运行。

## 后续生产化路径

1. 将 `knowledge.json` 替换为 MySQL 知识库表。
2. 增加管理员鉴权、操作日志和批量导入。
3. 将 embedding 缓存持久化，避免每次启动重建索引。
4. 将用户反馈转为知识库优化和 prompt 优化流程。
5. 增加鉴权、限流、日志追踪和部署脚本。
