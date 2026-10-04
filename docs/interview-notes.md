# 面试讲法

## 1. 项目一句话

这是一个面向校园服务场景的 AI Agent 问答系统，使用 FastAPI 提供接口，通过混合向量检索和 Agent 工具路由回答校园通知、部门电话、宿舍报修、教务流程等问题，并提供后台维护知识库。

## 2. 为什么做这个项目

校园里的通知、教务、后勤和部门信息分散在不同入口，学生经常重复询问相同问题。这个项目把高频信息沉淀成知识库，再用 RAG 和 Agent 做统一问答入口。

## 3. RAG 体现在哪里

用户问题不会直接丢给大模型，而是先召回知识库条目。项目支持三种 embedding 来源：

- OpenAI Embedding
- sentence-transformers
- 本地 hashing embedding fallback

向量索引优先使用 FAISS，不可用时回退到 NumPy 余弦检索。同时保留关键词检索作为 fallback，提升可运行性和稳定性。

## 4. Agent 体现在哪里

系统会根据问题意图选择不同工具：

- `notice_search`：通知、活动、报名、讲座
- `department_lookup`：电话、地址、办公室、联系方式
- `repair_helper`：宿舍、网络、空调、水电报修
- `academic_helper`：选课、退课、课表、教务
- `campus_qa`：通用问答

## 5. 工程化体现在哪里

- FastAPI 后端
- RESTful API
- SQLite 问答日志和反馈记录
- 后台知识库 CRUD
- 保存知识后自动重建向量索引
- 单元测试
- GitHub Actions CI
- API 文档和架构文档

## 6. 可以继续优化什么

- 用 MySQL 替换 JSON 文件和 SQLite
- 增加管理员登录和权限控制
- 将 embedding 缓存持久化，避免启动时重建
- 增加批量导入知识库
- 加入真实校园系统接口或工单流转
