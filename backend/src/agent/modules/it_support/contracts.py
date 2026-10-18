"""MOD-12 공개 계약: CT-16 접수 필드 검증과 포트(CP-06 RunEligibility, CP-07 사용자 원문 읽기).

필드 표는 docs/corpus/03-received-pdf-adjustments.md의 IT 접수 필드를 따른다. pending의 필수 필드는 D-42.
"""

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequestType = Literal["incident", "service_request", "inquiry"]
Category = Literal["account", "network", "device", "software", "other"]
FIELD_NAMES = (
    "subject",
    "description",
    "request_type",
    "category",
    "target_service",
    "occurred_at",
    "impact_scope",
    "urgent_work",
    "urgency_reason",
    "asset_identifier",
)
# D-42: pending(확인 가능)에 꼭 있어야 하는 필드. 장애면 발생 시각, 긴급이면 사유도 필요하다.
REQUIRED_FOR_PENDING = ("subject", "description", "request_type", "category", "target_service", "urgent_work")


def _no_nul(value: Any) -> Any:
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("NUL 문자는 쓸 수 없다")
    return value


class TicketFields(BaseModel):
    """접수 필드. draft는 빠진 필드를 허용하고, pending은 missing_fields가 비어 있어야 한다."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    request_type: RequestType | None = None
    category: Category | None = None
    target_service: str | None = Field(default=None, min_length=1, max_length=120)
    occurred_at: datetime | None = None
    impact_scope: str | None = Field(default=None, min_length=1, max_length=500)
    urgent_work: bool | None = None
    urgency_reason: str | None = Field(default=None, min_length=1, max_length=500)
    asset_identifier: str | None = Field(default=None, min_length=1, max_length=120)

    _check = field_validator("*")(_no_nul)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("발생 시각에는 시간대가 있어야 한다(KST)")
        return value

    def missing_fields(self) -> list[str]:
        missing = [name for name in REQUIRED_FOR_PENDING if getattr(self, name) is None]
        if self.request_type == "incident" and self.occurred_at is None:
            missing.append("occurred_at")
        if self.urgent_work and self.urgency_reason is None:
            missing.append("urgency_reason")
        return missing

    def payload(self) -> dict[str, Any]:
        data = self.model_dump()
        data["occurred_at"] = self.occurred_at.isoformat() if self.occurred_at else None
        return data


class RunEligibility(Protocol):
    """CP-06(MOD-01 구현, 앱이 주입). run 자격만 답하고 대화 DB를 MOD-12에 열지 않는다."""

    async def check_prepare(self, actor_id: str, conversation_id: str, run_id: str) -> bool:
        """이 actor의 이 대화에서 아직 실행 중이고 deadline 전인 run인가."""
        ...

    async def adopted(self, actor_id: str, conversation_id: str, run_id: str, action_id: str) -> bool:
        """run이 completed이고 그 결과가 이 root draft를 채택했는가."""
        ...


class UserEvidenceReader(Protocol):
    """CP-07 ReadUserEvidence(MOD-01 구현). 본인·run 문맥의 user 메시지 원문만 돌려준다."""

    async def read_user_messages(
        self, actor_id: str, conversation_id: str, run_id: str, message_ids: set[str]
    ) -> dict[str, str]: ...
