"""세션 HTTP(docs/04-api-spec.md 세션 — MOD-09). AUTH_MODE=local_session일 때만 붙는다.

POST /session은 Origin 검사(미들웨어)와 JSON 본문만 받는 것으로 로그인 CSRF를 막는다. 응답에는 세션 저장소
값·해시를 넣지 않는다. 모든 응답은 Cache-Control: private, no-store.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.modules.identity_access.service import SessionView, csrf_token_for
from agent.modules.identity_access.session_actor import SESSION_COOKIE, check_csrf
from agent.shared.clock import KST
from agent.shared.errors import AppError, ErrorCode

router = APIRouter(tags=["session"])
_NO_STORE = {"Cache-Control": "private, no-store"}


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username", "password")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        # PostgreSQL text는 NUL을 담지 못한다. 저장소 오류(503)가 아니라 입력 오류(422)로 거절한다.
        if "\x00" in value:
            raise ValueError("NUL 문자는 쓸 수 없다")
        return value


def _body(view: SessionView, token: str) -> dict:
    return {
        "user_id": view.user_id,
        "display_name": view.display_name,
        "capabilities": list(view.capabilities),
        "expires_at": view.expires_at.astimezone(KST).isoformat(),
        "csrf_token": csrf_token_for(token),
    }


@router.post("/session")
async def login(request: Request, body: Login) -> JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        # 폼 전송(사전 요청 없는 교차 사이트 POST)으로 로그인시키지 못하게 한다.
        raise AppError(ErrorCode.INVALID_REQUEST, details={"field_names": ["content-type"]})
    result = await request.app.state.identity.login(
        body.username, body.password, previous_token=request.cookies.get(SESSION_COOKIE)
    )
    response = JSONResponse(_body(result.view, result.token), headers=_NO_STORE)
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        result.token,
        max_age=settings.session_ttl_s,
        path="/api/v1",
        httponly=True,
        samesite="strict",
        secure=settings.app_env == "production",
    )
    return response


@router.get("/session")
async def get_session(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
    view = await request.app.state.identity.get_session(token)
    return JSONResponse(_body(view, token), headers=_NO_STORE)


@router.delete("/session", status_code=204)
async def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
    # 만료·회수된 세션도 CSRF가 맞으면 지운다. 다른 사이트가 사용자를 로그아웃시키지 못하게 CSRF는 확인한다.
    check_csrf(request, token)
    await request.app.state.identity.logout(token)
    response = Response(status_code=204, headers=_NO_STORE)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api/v1",
        httponly=True,
        samesite="strict",
        secure=request.app.state.settings.app_env == "production",
    )
    return response
