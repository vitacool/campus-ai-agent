import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import KnowledgeAgent


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Campus AI Agent",
    description="Campus Q&A agent with hybrid vector retrieval, tool routing and knowledge management.",
    version="2.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

agent = KnowledgeAgent()


@app.middleware("http")
async def disable_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)


class FeedbackRequest(BaseModel):
    chat_id: int
    rating: str
    comment: str = ""


class KnowledgeItem(BaseModel):
    id: str
    category: str
    title: str
    content: str
    keywords: list[str] = []


class KnowledgeUpdate(BaseModel):
    category: str | None = None
    title: str | None = None
    content: str | None = None
    keywords: list[str] | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, **agent.stats()}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    return agent.stats()


@app.get("/api/knowledge")
def list_knowledge() -> list[dict[str, Any]]:
    return agent.list_knowledge()


@app.post("/api/knowledge", status_code=201)
def create_knowledge(item: KnowledgeItem) -> dict[str, Any]:
    try:
        return agent.create_knowledge(model_to_dict(item))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.put("/api/knowledge/{item_id}")
def update_knowledge(item_id: str, item: KnowledgeUpdate) -> dict[str, Any]:
    try:
        return agent.update_knowledge(item_id, model_to_dict(item))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete("/api/knowledge/{item_id}")
def delete_knowledge(item_id: str) -> dict[str, str]:
    try:
        return agent.delete_knowledge(item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    try:
        return agent.ask(request.question)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/feedback", status_code=201)
def feedback(request: FeedbackRequest) -> dict[str, Any]:
    try:
        return agent.add_feedback(request.chat_id, request.rating, request.comment)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/chat/logs")
def chat_logs(limit: int = 20) -> list[dict[str, Any]]:
    return agent.recent_logs(limit=limit)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=False)
