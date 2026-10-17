import re
from pathlib import Path

import pytest

from agent.shared.errors import ERROR_TABLE, AppError, ErrorCode

ERRORS_DOC = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "03-errors.md"


def test_every_code_has_stage_and_status():
    assert set(ERROR_TABLE) == set(ErrorCode)


def _spec_table() -> dict[str, tuple[str, int]]:
    """03-errors.md 표의 `| 코드, 코드 | stage | HTTP |` 행을 읽는다."""
    table: dict[str, tuple[str, int]] = {}
    for line in ERRORS_DOC.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\|\s*([A-Z_, ]+?)\s*\|\s*([a-z]+)\s*\|\s*(\d{3})\s*\|", line.strip())
        if match:
            for code in match.group(1).split(","):
                table[code.strip()] = (match.group(2), int(match.group(3)))
    return table


def test_dictionary_matches_spec_table():
    spec = _spec_table()
    code_table = {code.value: (stage.value, status) for code, (stage, status) in ERROR_TABLE.items()}
    assert len(spec) > 30
    assert code_table == spec


def test_envelope_hides_internal_cause():
    error = AppError(ErrorCode.MODEL_UPSTREAM_ERROR, retryable=True, internal_cause_id="cause-1")
    envelope = error.to_envelope("req-1")
    assert envelope == {
        "error": {
            "code": "MODEL_UPSTREAM_ERROR",
            "message": error.safe_message,
            "stage": "model",
            "retryable": True,
            "details": None,
        },
        "request_id": "req-1",
    }
    assert "cause-1" not in str(envelope)


def test_details_whitelist():
    AppError(ErrorCode.INVALID_REQUEST, details={"field_names": ["x"]})
    with pytest.raises(ValueError):
        AppError(ErrorCode.INVALID_REQUEST, details={"value": "secret"})
    with pytest.raises(ValueError):
        AppError(ErrorCode.RESOURCE_NOT_FOUND, details={"title": "제한 문서"})


def test_not_found_messages_are_identical():
    """미존재와 불허가 같은 404 문구를 쓴다."""
    messages = {AppError(code).safe_message for code, (_, status) in ERROR_TABLE.items() if status == 404}
    assert len(messages) == 1


@pytest.mark.parametrize(
    ("code", "details"),
    [
        (ErrorCode.RESOURCE_NOT_FOUND, {}),
        (ErrorCode.INVALID_REQUEST, {}),
        (ErrorCode.INVALID_REQUEST, {"field_names": "title"}),
        (ErrorCode.INVALID_REQUEST, {"field_names": []}),
        (ErrorCode.ACTION_SUPERSEDED, {"current_action_id": "a"}),
        (ErrorCode.ACTION_SUPERSEDED, {"current_action_id": "a", "head_revision": "2"}),
    ],
)
def test_details_must_match_allowed_keys_and_types(code, details):
    """M0 검증 P3-7: 빈 details·일부 키·잘못된 형식을 거절한다(미존재/불허는 details=null)."""
    with pytest.raises(ValueError):
        AppError(code, details=details)


def test_full_head_details_are_accepted():
    error = AppError(ErrorCode.ACTION_SUPERSEDED, details={"current_action_id": "a", "head_revision": 2})
    assert error.details == {"current_action_id": "a", "head_revision": 2}
