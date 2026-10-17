"""서버 설정으로 고정한 test_stub actor(docs/12-first-milestone-spec.md).

요청 헤더·본문·쿼리는 읽지 않는다. 부서·역할 값은 O-01/O-10 확정 전 임시 fixture다.
"""

from typing import Literal

from starlette.requests import Request

from agent.shared.actor import ActorContext

TestActorId = Literal["test-a", "test-b"]

# 첫 구간 허용 도구는 교육 조회뿐이라 capability도 training.read만 준다.
_FIXTURES: dict[str, ActorContext] = {
    "test-a": ActorContext(
        user_id="test-a",
        department_ids=("dept-test-1",),
        role_ids=("employee",),
        capabilities=frozenset({"training.read"}),
        auth_revision=1,
        source="test_stub",
    ),
    "test-b": ActorContext(
        user_id="test-b",
        department_ids=("dept-test-2",),
        role_ids=("employee",),
        capabilities=frozenset({"training.read"}),
        auth_revision=1,
        source="test_stub",
    ),
}


class TestStubCurrentActor:
    __test__ = False  # pytest가 테스트 클래스로 수집하지 않게 한다.

    def __init__(self, actor_id: TestActorId) -> None:
        self._actor = _FIXTURES[actor_id]

    async def resolve(self, request: Request) -> ActorContext:
        return self._actor
