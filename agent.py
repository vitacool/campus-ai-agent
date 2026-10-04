import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

import numpy as np


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "knowledge.json"
DB_FILE = BASE_DIR / "campus_agent.db"
EMBEDDING_DIM = 384


def now_ts() -> int:
    return int(time.time())


def tokenize(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    cjk_text = "".join(char for char in text if "\u4e00" <= char <= "\u9fff")
    cjk_terms = {
        cjk_text[index : index + size]
        for size in (2, 3)
        for index in range(max(len(cjk_text) - size + 1, 0))
    }
    return words | cjk_terms


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


class EmbeddingProvider:
    name = "hashing"

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "hashing"

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            vector = np.zeros(self.dim, dtype=np.float32)
            for term in tokenize(text):
                digest = hashlib.sha256(term.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dim
                sign = 1 if digest[4] % 2 == 0 else -1
                vector[index] += sign * (1.0 + math.log(len(term) + 1, 2))
            vectors.append(normalize(vector))
        return np.vstack(vectors) if vectors else np.empty((0, self.dim), dtype=np.float32)


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    name = "sentence-transformers"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("SENTENCE_TRANSFORMER_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.base_url = os.getenv("OPENAI_EMBEDDING_BASE_URL", "https://api.openai.com/v1/embeddings")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")

    def embed(self, texts: list[str]) -> np.ndarray:
        payload = {"model": self.model, "input": texts}
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda row: row["index"])]
        return np.asarray([normalize(np.asarray(vector, dtype=np.float32)) for vector in vectors])


def create_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "auto").lower()
    if provider in {"openai", "auto"}:
        try:
            return OpenAIEmbeddingProvider()
        except Exception:
            if provider == "openai":
                raise
    if provider in {"sentence-transformers", "sentence_transformers", "auto"}:
        try:
            return SentenceTransformerEmbeddingProvider()
        except Exception:
            if provider in {"sentence-transformers", "sentence_transformers"}:
                raise
    return HashingEmbeddingProvider()


class VectorIndex:
    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider
        self.items: list[dict[str, Any]] = []
        self.vectors = np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        self.faiss_index: Any | None = None
        self.index_backend = "numpy"

    def rebuild(self, items: list[dict[str, Any]]) -> None:
        self.items = [dict(item) for item in items]
        docs = [self._document_text(item) for item in self.items]
        self.vectors = self.provider.embed(docs)
        self.faiss_index = None
        self.index_backend = "numpy"

        try:
            import faiss

            dim = self.vectors.shape[1]
            self.faiss_index = faiss.IndexFlatIP(dim)
            self.faiss_index.add(self.vectors.astype(np.float32))
            self.index_backend = "faiss"
        except Exception:
            self.faiss_index = None

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        if not self.items or self.vectors.size == 0:
            return []

        query_vector = self.provider.embed([query]).astype(np.float32)
        if self.faiss_index is not None:
            scores, indexes = self.faiss_index.search(query_vector, min(limit, len(self.items)))
            pairs = zip(scores[0].tolist(), indexes[0].tolist())
        else:
            scores = np.dot(self.vectors, query_vector[0])
            indexes = np.argsort(scores)[::-1][:limit]
            pairs = ((float(scores[index]), int(index)) for index in indexes)

        results = []
        for score, index in pairs:
            if index < 0:
                continue
            item = dict(self.items[index])
            item["vector_score"] = round(float(score), 3)
            item["retrieval_mode"] = "vector"
            results.append(item)
        return results

    def _document_text(self, item: dict[str, Any]) -> str:
        return " ".join(
            [
                item.get("title", ""),
                item.get("category", ""),
                item.get("content", ""),
                " ".join(item.get("keywords", [])),
            ]
        )


class KnowledgeAgent:
    def __init__(self, data_file: Path = DATA_FILE, db_file: Path = DB_FILE) -> None:
        self.data_file = data_file
        self.db_file = db_file
        self.knowledge = self._load_knowledge()
        self.embedding_provider = create_embedding_provider()
        self.vector_index = VectorIndex(self.embedding_provider)
        self.vector_index.rebuild(self.knowledge)
        self._init_db()

    def _load_knowledge(self) -> list[dict[str, Any]]:
        with self.data_file.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_knowledge(self) -> None:
        tmp_file = self.data_file.with_suffix(".json.tmp")
        with tmp_file.open("w", encoding="utf-8") as file:
            json.dump(self.knowledge, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_file.replace(self.data_file)
        self.vector_index.rebuild(self.knowledge)

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self.db_file)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    source_ids TEXT NOT NULL DEFAULT '[]',
                    used_model INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    rating TEXT NOT NULL,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY(chat_id) REFERENCES chat_logs(id)
                )
                """
            )
            self._ensure_column(conn, "chat_logs", "source_ids", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "chat_logs", "used_model", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "chat_logs", "latency_ms", "INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def list_knowledge(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.knowledge]

    def create_knowledge(self, item: dict[str, Any]) -> dict[str, Any]:
        item = self._clean_knowledge_item(item)
        if any(existing["id"] == item["id"] for existing in self.knowledge):
            raise ValueError("knowledge id already exists")
        self.knowledge.append(item)
        self._save_knowledge()
        return item

    def update_knowledge(self, item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        for index, item in enumerate(self.knowledge):
            if item["id"] == item_id:
                next_item = dict(item)
                next_item.update({key: value for key, value in updates.items() if value is not None})
                next_item["id"] = item_id
                next_item = self._clean_knowledge_item(next_item)
                self.knowledge[index] = next_item
                self._save_knowledge()
                return next_item
        raise ValueError("knowledge item not found")

    def delete_knowledge(self, item_id: str) -> dict[str, str]:
        before = len(self.knowledge)
        self.knowledge = [item for item in self.knowledge if item["id"] != item_id]
        if len(self.knowledge) == before:
            raise ValueError("knowledge item not found")
        self._save_knowledge()
        return {"id": item_id, "deleted": "true"}

    def _clean_knowledge_item(self, item: dict[str, Any]) -> dict[str, Any]:
        required = ["id", "category", "title", "content"]
        for key in required:
            if not str(item.get(key, "")).strip():
                raise ValueError(f"{key} is required")
        keywords = item.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [word.strip() for word in keywords.split(",") if word.strip()]
        return {
            "id": str(item["id"]).strip(),
            "category": str(item["category"]).strip(),
            "title": str(item["title"]).strip(),
            "content": str(item["content"]).strip(),
            "keywords": [str(keyword).strip() for keyword in keywords if str(keyword).strip()],
        }

    def retrieve(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        keyword_results = self._keyword_retrieve(question, limit=limit)
        vector_results = self.vector_index.search(question, limit=limit)
        merged: dict[str, dict[str, Any]] = {}

        for result in vector_results:
            merged[result["id"]] = result

        for result in keyword_results:
            if result["id"] in merged:
                merged[result["id"]].update(
                    {
                        "keyword_score": result["keyword_score"],
                        "matched_terms": result["matched_terms"],
                        "retrieval_mode": "hybrid",
                    }
                )
            else:
                merged[result["id"]] = result

        for item in merged.values():
            vector_score = float(item.get("vector_score", 0))
            keyword_score = float(item.get("keyword_score", 0))
            item["score"] = round(vector_score * 3 + keyword_score, 3)
            item.setdefault("matched_terms", [])

        ranked = sorted(merged.values(), key=lambda row: row["score"], reverse=True)
        if not ranked:
            return []

        top_score = ranked[0]["score"]
        min_score = max(0.75, top_score * 0.18)
        return [item for item in ranked if item["score"] >= min_score][:limit]

    def _keyword_retrieve(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        query_tokens = tokenize(question)
        scored: list[tuple[float, dict[str, Any]]] = []

        for item in self.knowledge:
            searchable = " ".join(
                [
                    item["title"],
                    item["category"],
                    item["content"],
                    " ".join(item.get("keywords", [])),
                ]
            )
            doc_tokens = tokenize(searchable)
            matched_terms = sorted(query_tokens & doc_tokens)
            score = self._score_keyword_item(question, item, matched_terms, doc_tokens)
            if score > 0:
                enriched = dict(item)
                enriched["keyword_score"] = round(score, 3)
                enriched["matched_terms"] = matched_terms[:8]
                enriched["retrieval_mode"] = "keyword"
                scored.append((score, enriched))

        scored.sort(key=lambda row: row[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def _score_keyword_item(
        self,
        question: str,
        item: dict[str, Any],
        matched_terms: list[str],
        doc_tokens: set[str],
    ) -> float:
        if not matched_terms:
            return 0

        score = 0.0
        for term in matched_terms:
            score += 1.0 + math.log(len(term) + 1, 2)

        for keyword in item.get("keywords", []):
            if keyword.lower() in question.lower():
                score += 4.0
        if item["title"] in question:
            score += 6.0

        return score / max(math.log(len(doc_tokens) + 2, 2), 1)

    def pick_tool(self, question: str) -> str:
        if any(word in question for word in ["通知", "活动", "报名", "讲座", "竞赛"]):
            return "notice_search"
        if any(word in question for word in ["电话", "联系", "地址", "地点", "办公室"]):
            return "department_lookup"
        if any(word in question for word in ["报修", "宿舍", "空调", "网络", "水电"]):
            return "repair_helper"
        if any(word in question for word in ["选课", "退课", "课表", "教务"]):
            return "academic_helper"
        return "campus_qa"

    def fallback_answer(self, sources: list[dict[str, Any]], tool: str) -> str:
        if not sources:
            return (
                "我暂时没有在校园知识库中找到明确答案。建议补充更具体的问题，"
                "例如部门名称、业务类型或活动名称。"
            )

        lines = ["根据校园知识库，我为你整理如下："]
        for index, source in enumerate(sources, start=1):
            lines.append(f"{index}. {source['title']}：{source['content']}")

        followups = {
            "repair_helper": "建议先准备宿舍号、设备类型、故障现象和联系电话，便于后勤快速处理。",
            "notice_search": "如果需要报名，请优先确认截止时间、地点和负责部门。",
            "department_lookup": "如果要现场办理，建议提前确认办公时间并携带学生证。",
            "academic_helper": "如果系统无法处理，建议在补选阶段或工作时间联系学院教务老师。",
        }
        if tool in followups:
            lines.append(followups[tool])
        return "\n".join(lines)

    def ask(self, question: str) -> dict[str, Any]:
        started_at = time.perf_counter()
        question = question.strip()
        if not question:
            raise ValueError("question is required")

        tool = self.pick_tool(question)
        sources = self.retrieve(question)
        llm_answer = call_llm(question, sources, tool)
        answer = llm_answer or self.fallback_answer(sources, tool)
        latency_ms = max(1, math.ceil((time.perf_counter() - started_at) * 1000))
        source_ids = [source["id"] for source in sources]

        with closing(sqlite3.connect(self.db_file)) as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_logs(
                    question, answer, tool, source_ids, used_model, latency_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question,
                    answer,
                    tool,
                    json.dumps(source_ids, ensure_ascii=False),
                    int(bool(llm_answer)),
                    latency_ms,
                    now_ts(),
                ),
            )
            conn.commit()
            chat_id = cursor.lastrowid

        return {
            "id": chat_id,
            "answer": answer,
            "tool": tool,
            "used_model": bool(llm_answer),
            "latency_ms": latency_ms,
            "retrieval": {
                "embedding_provider": self.embedding_provider.name,
                "index_backend": self.vector_index.index_backend,
            },
            "sources": [
                {
                    "id": source["id"],
                    "title": source["title"],
                    "category": source["category"],
                    "score": source["score"],
                    "matched_terms": source.get("matched_terms", []),
                    "retrieval_mode": source.get("retrieval_mode", "keyword"),
                }
                for source in sources
            ],
        }

    def add_feedback(self, chat_id: int, rating: str, comment: str = "") -> dict[str, Any]:
        rating = rating.strip().lower()
        if rating not in {"up", "down"}:
            raise ValueError("rating must be up or down")

        with closing(sqlite3.connect(self.db_file)) as conn:
            exists = conn.execute("SELECT id FROM chat_logs WHERE id = ?", (chat_id,)).fetchone()
            if not exists:
                raise ValueError("chat_id not found")
            cursor = conn.execute(
                "INSERT INTO feedback(chat_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, rating, comment.strip(), now_ts()),
            )
            conn.commit()
            return {"id": cursor.lastrowid, "chat_id": chat_id, "rating": rating}

    def recent_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with closing(sqlite3.connect(self.db_file)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, question, answer, tool, source_ids, used_model, latency_ms, created_at
                FROM chat_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) | {"source_ids": json.loads(row["source_ids"])} for row in rows]

    def stats(self) -> dict[str, Any]:
        with closing(sqlite3.connect(self.db_file)) as conn:
            conn.row_factory = sqlite3.Row
            chat_count = conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]
            feedback_count = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            avg_latency = conn.execute(
                "SELECT COALESCE(ROUND(AVG(latency_ms), 1), 0) FROM chat_logs"
            ).fetchone()[0]
            tool_rows = conn.execute(
                "SELECT tool, COUNT(*) AS count FROM chat_logs GROUP BY tool ORDER BY count DESC"
            ).fetchall()

        return {
            "knowledge_count": len(self.knowledge),
            "chat_count": chat_count,
            "feedback_count": feedback_count,
            "average_latency_ms": avg_latency,
            "tool_usage": [dict(row) for row in tool_rows],
            "embedding_provider": self.embedding_provider.name,
            "index_backend": self.vector_index.index_backend,
        }


def call_llm(question: str, sources: list[dict[str, Any]], tool: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    context = "\n".join(
        f"- {source['title']}（{source['category']}）：{source['content']}" for source in sources
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是校园服务智能助手。请只依据给定知识库回答，"
                    "答案要简洁、可执行，并在不确定时明确说明。"
                ),
            },
            {
                "role": "user",
                "content": f"工具类型：{tool}\n知识库：\n{context}\n\n用户问题：{question}",
            },
        ],
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except (KeyError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return None
