"""API errors: one JSON shape {"error": {"code", "message", "detail"}}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.data.scoped import ScopeFileError
from app.db.engine import DatabaseUnavailable
from app.security.policy import PolicyError


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.headers = headers


def _resp(status: int, code: str, message: str, detail: dict | None = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "detail": detail or {}}},
                        headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_r: Request, exc: ApiError):
        return _resp(exc.status, exc.code, exc.message, exc.detail, exc.headers)

    @app.exception_handler(PolicyError)
    async def _policy(_r: Request, exc: PolicyError):
        return _resp(exc.status, exc.code, exc.message, exc.detail)

    @app.exception_handler(DatabaseUnavailable)
    async def _db(_r: Request, exc: DatabaseUnavailable):
        return _resp(503, "DATABASE_UNAVAILABLE", "The database is busy or not available. Try again.", headers={"Retry-After": "2"})

    @app.exception_handler(ScopeFileError)
    async def _scope(_r: Request, exc: ScopeFileError):
        print(f"scope file error: {exc}", flush=True)
        return _resp(503, "SCOPE_FILE_UNAVAILABLE", "Your data is not available now (fail closed). Contact an administrator.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError):
        errs = [{"loc": [str(x) for x in e.get("loc", [])], "msg": str(e.get("msg", ""))[:300]} for e in exc.errors()[:10]]
        return _resp(422, "INVALID_REQUEST", "The request is not valid.", {"errors": errs})
