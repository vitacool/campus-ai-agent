import json
import math
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "knowledge.json"
DB_FILE = BASE_DIR / "campus_agent.db"
STATIC_DIR = BASE_DIR / "static"


def tokenize(text: str) -> set[str]:
    words = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    cjk_text = "".join(char for char in text if "\u4e00" <= char <= "\u9fff")
    cjk_terms = {
        cjk_text[index : index + size]
        for size in (2, 3)
        for index in range(max(len(cjk_text) - size + 1, 0))
    }
    return words | cjk_terms


def now_ts() -> int:
    return int(time.time())


class KnowledgeAgent:
    def __init__(self, data_file: Path = DATA_FILE, db_file: Path = DB_FILE) -> None:
        self.data_file = data_file
        self.db_file = db_file
        self.knowledge = self._load_knowledge()
        self._init_db()

    def _load_knowledge(self) -> list[dict[str, Any]]:
        with self.data_file.open("r", encoding="utf-8") as file:
            return json.load(file)

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

    def retrieve(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
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
            score = self._score_item(question, item, matched_terms, doc_tokens)

            if score > 0:
                enriched = dict(item)
                enriched["score"] = round(score, 3)
                enriched["matched_terms"] = matched_terms[:8]
                scored.append((score, enriched))

        scored.sort(key=lambda row: row[0], reverse=True)
        if not scored:
            return []

        top_score = scored[0][0]
        min_score = max(0.75, top_score * 0.18)
        filtered = [(score, item) for score, item in scored if score >= min_score]
        return [item for _, item in filtered[:limit]]

    def _score_item(
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
            "sources": [
                {
                    "id": source["id"],
                    "title": source["title"],
                    "category": source["category"],
                    "score": source["score"],
                    "matched_terms": source["matched_terms"],
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


agent = KnowledgeAgent()


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        route = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(route.query)

        if route.path == "/":
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif route.path == "/static/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        elif route.path == "/static/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        elif route.path == "/api/health":
            self._json({"ok": True, **agent.stats()})
        elif route.path == "/api/knowledge":
            self._json(agent.knowledge)
        elif route.path == "/api/stats":
            self._json(agent.stats())
        elif route.path == "/api/chat/logs":
            limit = int(query.get("limit", ["20"])[0])
            self._json(agent.recent_logs(limit=limit))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/chat":
                result = agent.ask(payload.get("question", ""))
                self._json(result)
            elif self.path == "/api/feedback":
                result = agent.add_feedback(
                    chat_id=int(payload.get("chat_id", 0)),
                    rating=str(payload.get("rating", "")),
                    comment=str(payload.get("comment", "")),
                )
                self._json(result, status=201)
            else:
                self.send_error(404)
        except ValueError as error:
            self._json({"error": str(error)}, status=400)
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body or "{}")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Campus AI Agent running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
