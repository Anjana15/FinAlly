"""The one error shape: {"error": <code>, "detail": <message>}, never nested under HTTPException.detail."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Body/query field → contract error code when Pydantic rejects it.
FIELD_CODES = {
    "ticker": "invalid_ticker",
    "side": "invalid_side",
    "quantity": "invalid_quantity",
    "message": "empty_message",
}


def error_response(status_code: int, code: str, detail: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "detail": detail, **extra})


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Map FastAPI's default 422 to a 400 with the contract's error code for the first bad field."""
    errors = exc.errors()
    for err in errors:
        loc = err.get("loc", ())
        field = loc[-1] if loc else None
        if err.get("type") == "json_invalid":
            return error_response(400, "invalid_request", "Request body is not valid JSON")
        if isinstance(field, str) and field in FIELD_CODES:
            return error_response(400, FIELD_CODES[field], f"{field}: {err.get('msg', 'invalid value')}")
    first = errors[0] if errors else {}
    where = ".".join(str(p) for p in first.get("loc", ()))
    return error_response(400, "invalid_request", f"{where}: {first.get('msg', 'invalid request')}")
