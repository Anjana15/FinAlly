"""POST /api/chat. backend-api mounts this in main.py."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .service import handle_chat

router = APIRouter()


def _error(code: str, detail: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


@router.post("/api/chat")
async def post_chat(request: Request):
    """Body {"message": str}. Parsed by hand so every 4xx uses the contract error shape (no 422s)."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    message = body.get("message") if isinstance(body, dict) else None
    text = message.strip() if isinstance(message, str) else ""
    if not text:
        return _error("empty_message", 'Send a JSON body like {"message": "..."} with non-empty text.')
    return await handle_chat(request.app, text)
