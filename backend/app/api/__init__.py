"""REST routers (everything under /api except the market SSE stream and POST /api/chat)."""

from .chat_history import router as chat_history_router
from .portfolio import router as portfolio_router
from .watchlist import router as watchlist_router

__all__ = ["chat_history_router", "portfolio_router", "watchlist_router"]
