"""CT-12 AppError와 닫힌 오류 사전(docs/contracts/03-errors.md).

사전에 없는 code·stage는 만들 수 없다. retryable의 코드별 기본값은 명세에 없으므로 호출하는 쪽이 정한다.
"""

import re
from enum import StrEnum
from typing import Any


class ErrorStage(StrEnum):
    VALIDATION = "validation"
    AUTH = "auth"
    EXECUTION = "execution"
    SEARCH = "search"
    WIKI = "wiki"
    MODEL = "model"
    TOOL = "tool"
    PERSISTENCE = "persistence"
    CONFIRMATION = "confirmation"


class ErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    CSRF_FAILED = "CSRF_FAILED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    TRAINING_NOT_FOUND = "TRAINING_NOT_FOUND"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    TOOL_ARGUMENT_INVALID = "TOOL_ARGUMENT_INVALID"
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TICKET_FIELD_ORIGIN_INVALID = "TICKET_FIELD_ORIGIN_INVALID"
    CONVERSATION_BUSY = "CONVERSATION_BUSY"
    MESSAGE_IDEMPOTENCY_CONFLICT = "MESSAGE_IDEMPOTENCY_CONFLICT"
    RUN_NOT_ELIGIBLE = "RUN_NOT_ELIGIBLE"
    RUN_TIMEOUT = "RUN_TIMEOUT"
    AGENT_LIMIT_EXCEEDED = "AGENT_LIMIT_EXCEEDED"
    ACTION_VERSION_CONFLICT = "ACTION_VERSION_CONFLICT"
    ACTION_ALREADY_CONFIRMED = "ACTION_ALREADY_CONFIRMED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    ACTION_NOT_PREPARED = "ACTION_NOT_PREPARED"
    ACTION_SUPERSEDED = "ACTION_SUPERSEDED"
    ACTION_HEAD_CONFLICT = "ACTION_HEAD_CONFLICT"
    PREPARE_PAYLOAD_CONFLICT = "PREPARE_PAYLOAD_CONFLICT"
    ACTION_ORIGIN_INVALID = "ACTION_ORIGIN_INVALID"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    ACTION_EXPIRED = "ACTION_EXPIRED"
    MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    MODEL_UPSTREAM_ERROR = "MODEL_UPSTREAM_ERROR"
    UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    RETRIEVAL_NOT_READY = "RETRIEVAL_NOT_READY"
    WIKI_NOT_READY = "WIKI_NOT_READY"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


_S = ErrorStage
_C = ErrorCode

# code → (stage, HTTP status). 03-errors.md 표를 그대로 옮긴다.
ERROR_TABLE: dict[ErrorCode, tuple[ErrorStage, int]] = {
    _C.AUTHENTICATION_REQUIRED: (_S.AUTH, 401),
    _C.SESSION_EXPIRED: (_S.AUTH, 401),
    _C.CSRF_FAILED: (_S.AUTH, 403),
    _C.ACTION_NOT_ALLOWED: (_S.AUTH, 403),
    _C.CONVERSATION_NOT_FOUND: (_S.AUTH, 404),
    _C.RUN_NOT_FOUND: (_S.AUTH, 404),
    _C.TRAINING_NOT_FOUND: (_S.AUTH, 404),
    _C.RESOURCE_NOT_FOUND: (_S.AUTH, 404),
    _C.INVALID_REQUEST: (_S.VALIDATION, 422),
    _C.TOOL_ARGUMENT_INVALID: (_S.VALIDATION, 422),
    _C.TOOL_NOT_REGISTERED: (_S.VALIDATION, 422),
    _C.TICKET_FIELD_ORIGIN_INVALID: (_S.VALIDATION, 422),
    _C.CONVERSATION_BUSY: (_S.EXECUTION, 409),
    _C.MESSAGE_IDEMPOTENCY_CONFLICT: (_S.EXECUTION, 409),
    _C.RUN_NOT_ELIGIBLE: (_S.EXECUTION, 409),
    _C.RUN_TIMEOUT: (_S.EXECUTION, 504),
    _C.AGENT_LIMIT_EXCEEDED: (_S.EXECUTION, 504),
    _C.ACTION_VERSION_CONFLICT: (_S.CONFIRMATION, 409),
    _C.ACTION_ALREADY_CONFIRMED: (_S.CONFIRMATION, 409),
    _C.ACTION_CANCELLED: (_S.CONFIRMATION, 409),
    _C.ACTION_NOT_PREPARED: (_S.CONFIRMATION, 409),
    _C.ACTION_SUPERSEDED: (_S.CONFIRMATION, 409),
    _C.ACTION_HEAD_CONFLICT: (_S.CONFIRMATION, 409),
    _C.PREPARE_PAYLOAD_CONFLICT: (_S.CONFIRMATION, 409),
    _C.ACTION_ORIGIN_INVALID: (_S.CONFIRMATION, 409),
    _C.IDEMPOTENCY_CONFLICT: (_S.CONFIRMATION, 409),
    _C.ACTION_EXPIRED: (_S.CONFIRMATION, 410),
    _C.MODEL_NOT_CONFIGURED: (_S.MODEL, 503),
    _C.MODEL_OUTPUT_INVALID: (_S.MODEL, 502),
    _C.MODEL_UPSTREAM_ERROR: (_S.MODEL, 502),
    _C.UPSTREAM_RATE_LIMITED: (_S.MODEL, 429),
    _C.TOOL_EXECUTION_FAILED: (_S.TOOL, 502),
    _C.TOOL_TIMEOUT: (_S.TOOL, 504),
    _C.RETRIEVAL_NOT_READY: (_S.SEARCH, 503),
    _C.WIKI_NOT_READY: (_S.WIKI, 503),
    _C.PERSISTENCE_FAILED: (_S.PERSISTENCE, 503),
    _C.SERVICE_UNAVAILABLE: (_S.EXECUTION, 503),
}

# details에 허용하는 키. 표에 없는 코드는 details=None만 허용한다.
_HEAD_DETAILS = frozenset({"current_action_id", "head_revision"})
_FIELD_DETAILS = frozenset({"field_names"})
ALLOWED_DETAILS: dict[ErrorCode, frozenset[str]] = {
    _C.ACTION_SUPERSEDED: _HEAD_DETAILS,
    _C.ACTION_HEAD_CONFLICT: _HEAD_DETAILS,
    _C.INVALID_REQUEST: _FIELD_DETAILS,
    _C.TOOL_ARGUMENT_INVALID: _FIELD_DETAILS,
    _C.TICKET_FIELD_ORIGIN_INVALID: _FIELD_DETAILS,
}

# 사용자에게 보여 줄 안전한 문구. 404는 미존재와 불허를 같은 문구로 정규화한다(CT-12).
_SAFE_BY_STATUS = {
    401: "로그인이 필요합니다.",
    403: "이 작업을 수행할 수 없습니다.",
    404: "요청한 항목을 찾을 수 없습니다.",
    409: "현재 상태에서는 처리할 수 없습니다. 최신 상태를 확인해 주세요.",
    410: "확인 가능한 시간이 지났습니다. 새로 요청해 주세요.",
    422: "요청 내용을 확인해 주세요.",
    429: "요청이 많아 잠시 후 다시 시도해 주세요.",
    502: "외부 처리 중 문제가 생겼습니다.",
    503: "지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    504: "처리 시간이 초과되었습니다.",
}


_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
_REQUEST_SOURCES = frozenset({"body", "query", "header", "path", "cookie"})


def _check_details(code: ErrorCode, details: dict[str, Any]) -> None:
    """details는 코드별 허용 키와 정확히 일치해야 한다. 빈 dict·일부 키·다른 형식은 거절한다(03-errors.md)."""
    allowed = ALLOWED_DETAILS.get(code)
    if allowed is None or set(details) != allowed:
        raise ValueError(f"{code}에 허용되지 않은 details 키: {sorted(details)}")
    if "field_names" in details:
        names = details["field_names"]
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise ValueError("field_names는 비어 있지 않은 문자열 목록이어야 한다")
    if "head_revision" in details and not isinstance(details["head_revision"], int):
        raise ValueError("head_revision은 정수여야 한다")


def safe_field_names(errors: list[dict[str, Any]]) -> list[str]:
    """Pydantic 검증 오류에서 클라이언트에 돌려줄 필드 이름만 뽑는다.

    - HTTP 위치 접두어(body/query/…)를 떼고 첫 문자열 세그먼트를 쓴다. 목록 원소 오류는 목록 필드 이름이 된다.
    - 문법 오류처럼 필드가 없으면 위치 이름(body 등)을 쓴다.
    - 클라이언트가 보낸 알 수 없는 키는 안전한 식별자 모양일 때만 돌려주고, 아니면 unknown_field로 바꾼다.
    """
    names: set[str] = set()
    for error in errors:
        loc = list(error.get("loc") or ())
        source = loc.pop(0) if loc and loc[0] in _REQUEST_SOURCES else None
        name = next((part for part in loc if isinstance(part, str)), None)
        if name is None:
            names.add(str(source or "body"))
        elif error.get("type") == "extra_forbidden" and not _FIELD_NAME_RE.fullmatch(name):
            names.add("unknown_field")
        else:
            names.add(name)
    return sorted(names) or ["body"]


class AppError(Exception):
    """모듈이 던지는 공급자 중립 오류. HTTP로 나갈 때는 envelope로 변환한다."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        internal_cause_id: str | None = None,
    ) -> None:
        if code not in ERROR_TABLE:
            raise ValueError(f"닫힌 오류 사전에 없는 코드: {code}")
        if details is not None:
            _check_details(code, details)
        self.code = code
        self.stage, self.http_status = ERROR_TABLE[code]
        self.retryable = retryable
        self.details = details
        self.internal_cause_id = internal_cause_id
        self.safe_message = _SAFE_BY_STATUS[self.http_status]
        super().__init__(code.value)

    def to_envelope(self, request_id: str) -> dict[str, Any]:
        """HTTP 오류 envelope. internal_cause_id는 내보내지 않는다."""
        return {
            "error": {
                "code": self.code.value,
                "message": self.safe_message,
                "stage": self.stage.value,
                "retryable": self.retryable,
                "details": self.details,
            },
            "request_id": request_id,
        }
