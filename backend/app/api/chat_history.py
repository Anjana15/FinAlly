"""GET /api/chat/history. (POST /api/chat lives in app.llm.router.)"""

from __future__ import annotations

from fastapi import APIRouter

from app import db

router = APIRouter()

HISTORY_DEFAULT = 50
HISTORY_MAX = 500


@router.get("/api/chat/history")
async def chat_history(limit: int = HISTORY_DEFAULT):
    limit = max(1, min(limit, HISTORY_MAX))
    return {"messages": db.get_recent_messages(db.get_conn(), limit=limit)}
