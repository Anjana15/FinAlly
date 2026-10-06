"""Small helpers shared by the db modules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """ISO-8601 UTC with microseconds and a `Z` suffix (sorts lexically = chronologically)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id() -> str:
    return str(uuid.uuid4())
