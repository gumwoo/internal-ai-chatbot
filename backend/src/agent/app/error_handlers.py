"""모든 오류를 CT-12 envelope로 바꾼다. 내부 원인·스택은 응답에 넣지 않는다."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent.shared.errors import AppError, ErrorCode
from agent.shared.request_id import request_id_of

logger = logging.getLogger(__name__)


def _response(error: AppError, request: Request) -> JSONResponse:
    request_id = request_id_of(request.scope)
    return JSONResponse(
        error.to_envelope(request_id),
        status_code=error.http_status,
        headers={"Cache-Control": "private, no-store", "X-Request-Id": request_id},
    )


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return _response(exc, request)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 필드 이름만 돌려준다. 입력값·검증 메시지는 넣지 않는다.
    names = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")})
    return _response(AppError(ErrorCode.INVALID_REQUEST, details={"field_names": names}), request)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 라우터 수준 404/405는 자원 미존재와 같은 모양으로 정규화한다.
    code = ErrorCode.RESOURCE_NOT_FOUND if exc.status_code in (404, 405) else ErrorCode.INVALID_REQUEST
    return _response(AppError(code), request)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("처리되지 않은 오류 request_id=%s", request_id_of(request.scope))
    return _response(AppError(ErrorCode.SERVICE_UNAVAILABLE), request)


def install(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
