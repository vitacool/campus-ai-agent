# API 文档

默认服务地址：

```text
http://127.0.0.1:8000
```

## GET /api/health

健康检查和基础统计。

响应示例：

```json
{
  "ok": true,
  "knowledge_count": 5,
  "chat_count": 12,
  "feedback_count": 3,
  "average_latency_ms": 4.2,
  "tool_usage": [
    { "tool": "notice_search", "count": 5 }
  ]
}
```

## GET /api/knowledge

返回当前校园知识库条目。

## POST /api/knowledge

新增知识库条目，并自动重建向量索引。

请求：

```json
{
  "id": "canteen-hours",
  "category": "校园服务",
  "title": "食堂开放时间",
  "content": "第一食堂每天7:00-21:00开放。",
  "keywords": ["食堂", "开放", "时间"]
}
```

## PUT /api/knowledge/{item_id}

更新知识库条目，并自动重建向量索引。

## DELETE /api/knowledge/{item_id}

删除知识库条目，并自动重建向量索引。

## POST /api/chat

提交用户问题，返回 Agent 回答、工具路由、检索来源和耗时。

请求：

```json
{
  "question": "AI讲座怎么报名？"
}
```

响应：

```json
{
  "id": 1,
  "answer": "根据校园知识库，我为你整理如下：...",
  "tool": "notice_search",
  "used_model": false,
  "latency_ms": 3,
  "retrieval": {
    "embedding_provider": "hashing",
    "index_backend": "numpy"
  },
  "sources": [
    {
      "id": "notice-ai-lecture",
      "title": "AI应用开发讲座",
      "category": "校园活动",
      "score": 5.108,
      "matched_terms": ["AI", "讲座", "报名"],
      "retrieval_mode": "hybrid"
    }
  ]
}
```

## POST /api/feedback

记录用户反馈，用于后续优化知识库和回答策略。

请求：

```json
{
  "chat_id": 1,
  "rating": "up",
  "comment": "回答清楚"
}
```

`rating` 支持：

- `up`
- `down`

## GET /api/stats

返回知识库数量、问答数量、反馈数量、平均耗时和工具调用分布。

## GET /api/chat/logs?limit=20

返回最近问答日志，默认最多 20 条，最大 100 条。
