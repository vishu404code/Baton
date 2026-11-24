"""Uniform error shape: {"error": {"code", "message", "details"}} (API contract §0.2)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "bad_request",
    409: "conflict",
    422: "validation_error",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, details: dict | None = None):
        self.status = status
        self.code = code or _STATUS_CODES.get(status, "internal")
        self.message = message
        self.details = details or {}


def not_found(what: str = "Not found.") -> ApiError:
    return ApiError(404, what)


def forbidden(message: str) -> ApiError:
    return ApiError(403, message)


def conflict(message: str, details: dict | None = None) -> ApiError:
    return ApiError(409, message, details=details)


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "internal")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        fields = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        first = fields[0] if fields else {"loc": [], "msg": "Invalid request."}
        message = f"{'.'.join(str(p) for p in first['loc'][1:]) or 'request'}: {first['msg']}"
        return JSONResponse(_body("validation_error", message, {"fields": fields}), status_code=422)

    @app.exception_handler(AgentError)
    async def _agent_error(_: Request, exc: AgentError):
        api = exc.to_api()
        return JSONResponse(_body(api.code, api.message), status_code=api.status)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        return JSONResponse(_body("internal", "Something went wrong on the server."), status_code=500)


class AgentError(Exception):
    """A rule violation with a short, actionable message an AI agent can follow.

    Raised by services; the MCP layer turns it into a tool error and REST turns it into ApiError.
    """

    HTTP = {"not_found": 404, "forbidden": 403, "conflict": 409, "bad_request": 400, "unauthorized": 401}

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_api(self) -> "ApiError":
        return ApiError(self.HTTP.get(self.code, 400), self.message, code=self.code)


def bad_request(message: str) -> ApiError:
    return ApiError(400, message)
