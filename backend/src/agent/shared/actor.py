"""CT-01 ActorContext와 CP-02 CurrentActor 포트.

actor는 서버가 만든다. 브라우저·모델·요청 헤더가 actor를 바꾸지 못한다.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from starlette.requests import Request

ActorSource = Literal["local_session", "test_stub", "operator_cli", "eval_fixture"]

# CT-01의 닫힌 capability 이름. 어느 역할에 무엇을 줄지는 O-01/O-10에서 정한다.
CAPABILITIES = frozenset(
    {
        "training.read",
        "knowledge.search",
        "ticket.read_own",
        "ticket.read_support_scope",
        "ticket.read_all",
        "ticket.prepare",
        "ticket.submit",
        "ops.corpus_ingest",
        "ops.corpus_publish",
        "ops.wiki_build",
        "ops.access_admin",
        "ops.membership_admin",
        "eval.run",
    }
)


@dataclass(frozen=True)
class ActorContext:
    user_id: str
    department_ids: tuple[str, ...]
    role_ids: tuple[str, ...]
    capabilities: frozenset[str]
    auth_revision: int
    source: ActorSource

    def __post_init__(self) -> None:
        unknown = self.capabilities - CAPABILITIES
        if unknown:
            raise ValueError(f"닫힌 목록에 없는 capability: {sorted(unknown)}")


class CurrentActor(Protocol):
    """요청에서 현재 actor를 해석한다. 해석할 수 없으면 AUTHENTICATION_REQUIRED를 던진다."""

    async def resolve(self, request: Request) -> ActorContext: ...
