import json
import os
import re
import sqlite3
import time
import urllib.error
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
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def retrieve(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        query_tokens = tokenize(question)
        scored: list[tuple[int, dict[str, Any]]] = []

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
            score = len(query_tokens & doc_tokens)

            for keyword in item.get("keywords", []):
                if keyword.lower() in question.lower():
                    score += 3
            if item["title"] in question:
                score += 5

            if score:
                scored.append((score, item))

        scored.sort(key=lambda row: row[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def pick_tool(self, question: str) -> str:
        if any(word in question for word in ["通知", "活动", "报名", "讲座"]):
            return "notice_search"
        if any(word in question for word in ["电话", "联系", "地址", "地点", "办公室"]):
            return "department_lookup"
        if any(word in question for word in ["报修", "宿舍", "空调", "网络", "水电"]):
            return "repair_helper"
        return "campus_qa"

    def fallback_answer(self, question: str, sources: list[dict[str, Any]], tool: str) -> str:
        if not sources:
            return (
                "我暂时没有在校园知识库中找到明确答案。建议补充更具体的问题，"
                "例如部门名称、业务类型或活动名称。"
            )

        lines = ["根据校园知识库，我为你整理如下："]
        for index, source in enumerate(sources, start=1):
            lines.append(f"{index}. {source['title']}：{source['content']}")

        if tool == "repair_helper":
            lines.append("建议先准备宿舍号、设备类型、故障现象和联系电话，便于后勤快速处理。")
        elif tool == "notice_search":
            lines.append("如果需要报名，请优先确认截止时间、地点和负责部门。")
        return "\n".join(lines)

    def ask(self, question: str) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise ValueError("question is required")

        tool = self.pick_tool(question)
        sources = self.retrieve(question)
        llm_answer = call_llm(question, sources, tool)
        answer = llm_answer or self.fallback_answer(question, sources, tool)

        with closing(sqlite3.connect(self.db_file)) as conn:
            conn.execute(
                "INSERT INTO chat_logs(question, answer, tool, created_at) VALUES (?, ?, ?, ?)",
                (question, answer, tool, int(time.time())),
            )
            conn.commit()

        return {
            "answer": answer,
            "tool": tool,
            "used_model": bool(llm_answer),
            "sources": [
                {
                    "id": source["id"],
                    "title": source["title"],
                    "category": source["category"],
                }
                for source in sources
            ],
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
        if self.path == "/":
            self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif self.path == "/static/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        elif self.path == "/static/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
        elif self.path == "/api/health":
            self._json({"ok": True, "knowledge_count": len(agent.knowledge)})
        elif self.path == "/api/knowledge":
            self._json(agent.knowledge)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            result = agent.ask(payload.get("question", ""))
            self._json(result)
        except ValueError as error:
            self._json({"error": str(error)}, status=400)
        except json.JSONDecodeError:
            self._json({"error": "invalid json"}, status=400)

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
