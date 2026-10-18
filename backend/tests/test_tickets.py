"""T-30~33 IT 지원 티켓(docs/14-ticket-workflow.md). 과금 없음(가짜 모델).

T-30 조회 범위·동일 404, T-31 준비·입력 출처·부적격 run·확인 전 무생성, T-32 멱등·경쟁·head 직렬화,
T-33 응답 유실·상태별 응답·권한 철회·commit 실패 원자성.
"""

import asyncio
import json
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select, text

from agent.app.main import create_app
from agent.modules.identity_access.service import load_demo_org
from agent.modules.it_support.service import load_support_scopes
from agent.modules.it_support.tables import ticket_action_heads, ticket_actions, tickets
from agent.modules.model_integration.fake import FakeModelClient
from agent.modules.model_integration.ports import ModelResponse, Usage
from agent.shared.actor import ActorContext
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.contracts import ToolCallProposal
from tests.conftest import api_client, make_settings

ORIGIN = "http://localhost:5190"
USAGE = Usage(input_tokens=10, output_tokens=5, complete=True)
EMPLOYEE_CAPS = frozenset(
    {"training.read", "knowledge.search", "ticket.read_own", "ticket.prepare", "ticket.submit"}
)


def actor(user_id: str, departments: tuple[str, ...], extra: frozenset[str] = frozenset()) -> ActorContext:
    roles = ("employee", "it_support") if "ticket.read_support_scope" in extra else ("employee",)
    return ActorContext(user_id, departments, roles, EMPLOYEE_CAPS | extra, 1, "test_stub")


SALES = actor("emp-sales", ("dept-sales",))
DEV = actor("emp-dev", ("dept-dev",))
SUPPORT = actor("it-support", ("dept-it",), frozenset({"ticket.read_support_scope"}))


class Scripted(FakeModelClient):
    """응답 자리에 함수를 넣으면 그 요청(직전 도구 결과 포함)을 보고 응답을 만든다."""

    async def complete_once(self, request):
        self.requests.append(request)
        item = self._script.popleft()
        return item(request) if callable(item) else item


class Switch:
    def __init__(self, current: ActorContext) -> None:
        self.current = current

    async def resolve(self, request) -> ActorContext:
        return self.current


def tool(name: str, args: dict) -> ModelResponse:
    proposal = ToolCallProposal(name=name, arguments=args, provider_call_id=f"toolu_{uuid.uuid4().hex[:8]}")
    return ModelResponse((proposal,), None, "fake", "agent_answer", "test", USAGE)


def final(answer="답", outcome="answered", action_id=None, ticket_ids=()) -> ModelResponse:
    return ModelResponse(
        (),
        {
            "answer": answer,
            "outcome": outcome,
            "training_ids": [],
            "selected_training_id": None,
            "citation_ids": [],
            "ticket_ids": list(ticket_ids),
            "action_id": action_id,
        },
        "fake",
        "agent_answer",
        "test",
        USAGE,
    )


def last_result(request) -> dict:
    results = [r for m in request.messages for r in m.tool_results]
    return json.loads(results[-1].content)


def adopt(request) -> ModelResponse:
    payload = last_result(request)
    return final("아래 내용을 확인해 주세요", "action_pending", action_id=payload["data"]["action_id"])


VPN_MESSAGE = "VPN이 안 돼요. 오늘 오전 9시 30분부터 접속이 끊겨서 업무를 못 하고 있어요"
VPN_ARGS = {
    "subject": "IT 지원 요청",
    "description": "VPN이 안 돼요",
    "request_type": "incident",
    "category": "network",
    "target_service": "VPN",
    "occurred_at": "2026-10-16T09:30:00+09:00",
    "origin_candidates": [
        {"field": "subject", "template_id": "ticket.subject.generic.v1"},
        {"field": "description", "quote": "VPN이 안 돼요"},
        {"field": "request_type", "quote": "VPN이 안 돼요"},
        {"field": "category", "quote": "VPN이 안 돼요"},
        {"field": "target_service", "quote": "VPN"},
        {"field": "occurred_at", "quote": "오늘 오전 9시 30분"},
    ],
}
COMPLETE = {
    "subject": "VPN 접속 오류",
    "description": "VPN이 안 돼요",
    "request_type": "incident",
    "category": "network",
    "target_service": "사내 VPN",
    "occurred_at": "2026-10-16T09:30:00+09:00",
    "impact_scope": "본인 1명",
    "urgent_work": False,
    "urgency_reason": None,
    "asset_identifier": None,
}


@pytest.fixture
async def org(seeded_engine):
    await load_demo_org(seeded_engine, FIXTURE_NOW)
    await load_support_scopes(seeded_engine)
    return seeded_engine


def build(migrated, script: list, switch: Switch, clock: FixedClock):
    return create_app(
        make_settings(database_url=migrated, allowed_origins=ORIGIN),
        current_actor=switch,
        clock=clock,
        chat_model=Scripted(script),
        embedding_model=FakeModelClient(),
    )


async def ask(client, content, conversation=None):
    if conversation is None:
        conversation = (
            await client.post("/api/v1/conversations", json={}, headers={"Origin": ORIGIN})
        ).json()["id"]
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"content": content},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid.uuid4())},
    )
    return conversation, response


def post(client, path: str, body: dict, key: str | None = None):
    headers = {"Origin": ORIGIN}
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post(f"/api/v1{path}", json=body, headers=headers)


async def count(engine, table) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(table))


async def prepared(client) -> tuple[str, dict]:
    conversation, response = await ask(client, VPN_MESSAGE)
    assert response.status_code == 200, response.text
    return conversation, response.json()


def scripted_prepare(args: dict = VPN_ARGS, then: Callable = adopt) -> list:
    return [tool("prepare_it_ticket", args), then]


# --- T-31 준비 ---


async def test_agent_prepare_makes_only_a_draft_and_message_adopts_it(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        conversation, body = await prepared(client)
        preview = body["action_preview"]
        assert body["outcome"] == "action_pending" and preview["status"] == "draft"
        assert preview["missing_fields"] == ["urgent_work"]  # 말하지 않은 긴급 여부는 비워 둔다
        assert preview["impact_scope"] is None and preview["reply_channel"] == "사내 메신저 영업팀 직원"
        assert preview["occurred_at"] == "2026-10-16T09:30:00+09:00"
        assert await count(org, tickets) == 0  # 확인 전에는 티켓 0건
        async with org.connect() as conn:
            assert await conn.scalar(select(func.count()).select_from(ticket_action_heads)) == 0  # head 불변
        history = (await client.get(f"/api/v1/conversations/{conversation}/messages")).json()["items"]
        assert history[-1]["action_preview"]["action_id"] == preview["action_id"]
        # draft는 바로 확인할 수 없다(UI revise로 완전한 pending을 만든 뒤에만).
        confirm = await post(
            client, f"/ticket-actions/{preview['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        assert confirm.status_code == 409 and confirm.json()["error"]["code"] == "ACTION_NOT_PREPARED"


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (
            lambda a: a["origin_candidates"][1].__setitem__("quote", "VPN 설정 파일이 손상됐어요"),
            "description",
        ),
        (lambda a: a.__setitem__("occurred_at", "2026-10-16T10:00:00+09:00"), "occurred_at"),
        (lambda a: a["origin_candidates"].pop(4), "target_service"),
        (
            lambda a: a["origin_candidates"][0].__setitem__("template_id", "ticket.description.free.v1"),
            "subject",
        ),
        (lambda a: a.update(category="device"), "category"),
    ],
)
async def test_unverified_origins_are_not_stored(org, migrated, mutate, field):
    """D-43: 출처를 확인하지 못한 필드는 저장하지 않고 비운다(rejected_fields). 다른 필드로 초안은 만든다."""
    args = json.loads(json.dumps(VPN_ARGS))
    mutate(args)
    switch, clock = Switch(SALES), FixedClock()
    seen: dict = {}

    def capture(request):
        seen.update(last_result(request))
        return final("필요한 정보를 다시 알려 주세요", "needs_clarification")

    async with api_client(
        build(migrated, [tool("prepare_it_ticket", args), capture], switch, clock)
    ) as client:
        _, response = await ask(client, VPN_MESSAGE)
    assert response.status_code == 200
    data = seen["data"]
    assert seen["ok"] is True and field in data["rejected_fields"] and data[field] is None
    async with org.connect() as conn:
        payload, origins = (
            await conn.execute(select(ticket_actions.c.payload, ticket_actions.c.field_origins))
        ).one()
    assert payload[field] is None and field not in {o["field"] for o in origins}
    assert "VPN 설정 파일이 손상됐어요" not in json.dumps(payload, ensure_ascii=False)


async def test_assistant_text_and_model_approval_fields_are_not_origins(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    copied = dict(VPN_ARGS, description="VPN 재설치 방법을 안내했습니다")
    copied["origin_candidates"] = [
        *VPN_ARGS["origin_candidates"][:1],
        {"field": "description", "quote": "VPN 재설치 방법을 안내했습니다"},
        *VPN_ARGS["origin_candidates"][2:],
    ]
    results: list = []

    def capture(request):
        results.append(last_result(request))
        return final("다시 알려 주세요", "needs_clarification")

    script = [
        final("VPN 재설치 방법을 안내했습니다"),
        tool("prepare_it_ticket", copied),
        capture,
        tool("prepare_it_ticket", dict(VPN_ARGS, approved=True, requester_id="admin")),
        capture,
    ]
    async with api_client(build(migrated, script, switch, clock)) as client:
        conversation, _ = await ask(client, "VPN 어떻게 해요?")
        await ask(client, VPN_MESSAGE, conversation)
        await ask(client, VPN_MESSAGE, conversation)
    assert results[0]["data"]["description"] is None  # assistant 문장은 출처가 아니라 저장하지 않는다
    assert "description" in results[0]["data"]["rejected_fields"]
    assert results[1]["error"]["code"] == "TOOL_ARGUMENT_INVALID"  # 승인·요청자 위조 필드 거절
    async with org.connect() as conn:
        stored = await conn.scalar(select(ticket_actions.c.payload))
    assert "안내했습니다" not in json.dumps(stored, ensure_ascii=False)


async def test_code_point_span_after_emoji_is_verified(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, response = await ask(client, "😀 " + VPN_MESSAGE)
    assert response.json()["outcome"] == "action_pending"
    async with org.connect() as conn:
        origins = await conn.scalar(select(ticket_actions.c.field_origins))
    description = next(o for o in origins if o["field"] == "description")
    assert description["span_start"] == 2  # UTF-16이면 3


async def test_failed_run_draft_cannot_be_revised_and_old_pending_survives(org, migrated):
    """A pending → B run이 draft를 만든 뒤 실패 → B draft는 수정 불가, A는 여전히 확인 가능."""
    switch, clock = Switch(SALES), FixedClock()
    bad_final = lambda request: final("확인해 주세요", "action_pending", action_id=str(uuid.uuid4()))  # noqa: E731
    script = [*scripted_prepare(), *scripted_prepare(then=bad_final)]
    async with api_client(build(migrated, script, switch, clock)) as client:
        conversation, body = await prepared(client)
        a = body["action_preview"]
        revised = await post(
            client,
            f"/ticket-actions/{a['action_id']}/revise",
            {"version": 1, "fields": COMPLETE},
            str(uuid.uuid4()),
        )
        assert revised.status_code == 201
        a_pending = revised.json()
        _, failed = await ask(client, VPN_MESSAGE, conversation)
        assert failed.status_code == 502  # 이번 실행이 만들지 않은 action을 가리켜 무효 출력
        async with org.connect() as conn:
            b_id = await conn.scalar(
                select(ticket_actions.c.id)
                .where(ticket_actions.c.status == "draft")
                .order_by(ticket_actions.c.created_at.desc())
            )
        b = await post(
            client, f"/ticket-actions/{b_id}/revise", {"version": 1, "fields": COMPLETE}, str(uuid.uuid4())
        )
        assert b.status_code == 409 and b.json()["error"]["code"] == "RUN_NOT_ELIGIBLE"
        ok = await post(
            client, f"/ticket-actions/{a_pending['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        assert ok.status_code == 201 and ok.json()["ticket"]["subject"] == "VPN 접속 오류"


# --- T-32 멱등·경쟁 ---


async def test_revise_idempotency_and_supersession(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, body = await prepared(client)
        draft = body["action_preview"]["action_id"]
        key = str(uuid.uuid4())
        first = await post(client, f"/ticket-actions/{draft}/revise", {"version": 1, "fields": COMPLETE}, key)
        again = await post(client, f"/ticket-actions/{draft}/revise", {"version": 1, "fields": COMPLETE}, key)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["action_id"] == again.json()["action_id"]  # 같은 키는 같은 결과
        other = await post(
            client,
            f"/ticket-actions/{draft}/revise",
            {"version": 1, "fields": dict(COMPLETE, subject="다른 제목")},
            key,
        )
        assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        pending = first.json()
        assert pending["prepared_from_action_id"] == draft and pending["displaced_head_id"] is None
        # 원본 draft는 superseded, 다시 고치면 409와 현재 action 안내
        stale = await post(
            client, f"/ticket-actions/{draft}/revise", {"version": 1, "fields": COMPLETE}, str(uuid.uuid4())
        )
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "ACTION_SUPERSEDED"
        assert stale.json()["error"]["details"]["current_action_id"] == pending["action_id"]
        # pending → 새 pending: 이전 pending은 superseded, head 교체
        second = await post(
            client,
            f"/ticket-actions/{pending['action_id']}/revise",
            {"version": 1, "fields": dict(COMPLETE, impact_scope="팀 5명")},
            str(uuid.uuid4()),
        )
        assert second.status_code == 201
        assert (await client.get(f"/api/v1/ticket-actions/{pending['action_id']}")).json()[
            "status"
        ] == "superseded"
        assert (await client.get(f"/api/v1/ticket-actions/{draft}")).json()[
            "current_action_id"
        ] == second.json()["action_id"]
        version = await post(
            client, f"/ticket-actions/{second.json()['action_id']}/confirm", {"version": 2}, str(uuid.uuid4())
        )
        assert version.status_code == 409 and version.json()["error"]["code"] == "ACTION_VERSION_CONFLICT"


async def test_concurrent_confirms_make_one_ticket(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        path = f"/ticket-actions/{pending['action_id']}/confirm"
        results = await asyncio.gather(
            *(post(client, path, {"version": 1}, str(uuid.uuid4())) for _ in range(4))
        )
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    assert len({r.json()["ticket_id"] for r in results}) == 1  # 다른 키도 같은 ticket으로 수렴
    assert await count(org, tickets) == 1


async def test_confirm_and_revise_race_has_single_outcome(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        aid = pending["action_id"]
        confirm, revise = await asyncio.gather(
            post(client, f"/ticket-actions/{aid}/confirm", {"version": 1}, str(uuid.uuid4())),
            post(
                client,
                f"/ticket-actions/{aid}/revise",
                {"version": 1, "fields": dict(COMPLETE, subject="경쟁")},
                str(uuid.uuid4()),
            ),
        )
    codes = {confirm.status_code, revise.status_code}
    assert codes == {201, 409}  # 확인이 먼저면 교체 409, 교체가 먼저면 확인 409
    loser = confirm if confirm.status_code == 409 else revise
    assert loser.json()["error"]["code"] in ("ACTION_ALREADY_CONFIRMED", "ACTION_SUPERSEDED")
    assert await count(org, tickets) == (1 if confirm.status_code == 201 else 0)


async def test_two_drafts_racing_for_the_first_head(org, migrated):
    """같은 대화의 독립 draft 둘이 (null,0)을 기대값으로 동시에 revise해도 head는 하나만 생긴다."""
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(
        build(migrated, [*scripted_prepare(), *scripted_prepare()], switch, clock)
    ) as client:
        conversation, first = await prepared(client)
        _, second = await ask(client, VPN_MESSAGE + "!", conversation)
        drafts = [
            first.json()["action_preview"]["action_id"]
            if hasattr(first, "json")
            else first["action_preview"]["action_id"],
            second.json()["action_preview"]["action_id"],
        ]
        results = await asyncio.gather(
            *(
                post(
                    client,
                    f"/ticket-actions/{d}/revise",
                    {"version": 1, "fields": COMPLETE},
                    str(uuid.uuid4()),
                )
                for d in drafts
            )
        )
    assert sorted(r.status_code for r in results) == [201, 409]
    assert next(r for r in results if r.status_code == 409).json()["error"]["code"] == "ACTION_HEAD_CONFLICT"


async def test_prepare_receipt_binds_run_and_ordinal(org, migrated):
    from agent.app.main import create_app as _  # noqa: F401  (서비스만 직접 쓴다)
    from agent.modules.conversation.records import DbConversationEvidence, DbRunEligibility
    from agent.modules.identity_access.service import IdentityService
    from agent.modules.it_support.service import TicketService

    clock = FixedClock()

    class Always:
        async def check_prepare(self, *args):
            return True

        async def adopted(self, *args):
            return True

    service = TicketService(org, clock, IdentityService(org, clock), Always(), DbConversationEvidence(org))
    conversation, run = str(uuid.uuid4()), str(uuid.uuid4())
    fields = {"subject": "IT 지원 요청"}
    origins = [{"field": "subject", "kind": "template", "template_id": "ticket.subject.generic.v1"}]
    a = await service.prepare(
        SALES, conversation_id=conversation, run_id=run, ordinal=1, fields=fields, field_origins=origins
    )
    b = await service.prepare(
        SALES, conversation_id=conversation, run_id=run, ordinal=1, fields=fields, field_origins=origins
    )
    assert a["action_id"] == b["action_id"]  # 같은 (run, ordinal)·같은 payload는 같은 draft
    with pytest.raises(Exception) as exc:
        await service.prepare(
            SALES, conversation_id=conversation, run_id=run, ordinal=1, fields={}, field_origins=[]
        )
    assert getattr(exc.value, "code", None).value == "PREPARE_PAYLOAD_CONFLICT"
    assert DbRunEligibility  # 앱 조립용 구현이 import 가능한지(스모크)


# --- T-33 상태별 응답·유실·권한·원자성 ---


async def test_expired_cancelled_and_repeated_cancel(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(
        build(migrated, [*scripted_prepare(), *scripted_prepare()], switch, clock)
    ) as client:
        conversation, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        aid = pending["action_id"]
        first = await post(client, f"/ticket-actions/{aid}/cancel", {"version": 1})
        repeat = await post(client, f"/ticket-actions/{aid}/cancel", {"version": 1})
        assert (first.status_code, repeat.status_code) == (200, 200) and repeat.json()[
            "status"
        ] == "cancelled"
        dead = await post(client, f"/ticket-actions/{aid}/confirm", {"version": 1}, str(uuid.uuid4()))
        assert dead.status_code == 409 and dead.json()["error"]["code"] == "ACTION_CANCELLED"
        _, again = await ask(client, VPN_MESSAGE + " 다시", conversation)
        draft = again.json()["action_preview"]["action_id"]
        clock.advance(301)  # draft TTL 5분 경과
        assert (await client.get(f"/api/v1/ticket-actions/{draft}")).json()["status"] == "expired"
        for path, body_ in (
            ("revise", {"version": 1, "fields": COMPLETE}),
            ("confirm", {"version": 1}),
            ("cancel", {"version": 1}),
        ):
            response = await post(
                client,
                f"/ticket-actions/{draft}/{path}",
                body_,
                str(uuid.uuid4()) if path != "cancel" else None,
            )
            assert response.status_code == 410 and response.json()["error"]["code"] == "ACTION_EXPIRED", path


async def test_lost_response_replays_and_other_users_get_same_404(org, migrated):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        key = str(uuid.uuid4())
        created = await post(client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, key)
        replay = await post(client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, key)
        assert (created.status_code, replay.status_code) == (201, 200)
        assert created.json()["ticket_id"] == replay.json()["ticket_id"]
        ticket_id = created.json()["ticket_id"]
        mine = (await client.get("/api/v1/it-tickets")).json()
        assert [t["id"] for t in mine["items"]] == [ticket_id] and mine["items"][0][
            "requester_id"
        ] == "emp-sales"
        switch.current = DEV  # 다른 직원: 남의 action·ticket은 없는 것과 같은 404
        unknown = str(uuid.uuid4())
        for path in (
            f"/ticket-actions/{pending['action_id']}",
            f"/ticket-actions/{unknown}",
            f"/it-tickets/{ticket_id}",
            f"/it-tickets/{unknown}",
        ):
            response = await client.get(f"/api/v1{path}")
            assert response.status_code == 404 and response.json()["error"]["code"] == "RESOURCE_NOT_FOUND", (
                path
            )
        wrong_version = await post(
            client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 9}, str(uuid.uuid4())
        )
        assert wrong_version.status_code == 404  # 소유권 검사가 version보다 먼저
        assert (await client.get("/api/v1/it-tickets")).json()["total"] == 0
        switch.current = SUPPORT  # 지원 범위(요청자 부서 dept-sales 포함)는 볼 수 있다
        assert (await client.get(f"/api/v1/it-tickets/{ticket_id}")).status_code == 200
        switch.current = actor("hr-staff", ("dept-hr",), frozenset({"ticket.read_support_scope"}))
        assert (
            await client.get(f"/api/v1/it-tickets/{ticket_id}")
        ).status_code == 404  # 지원 범위 행 없음 = 거부


async def test_revoked_submit_capability_and_commit_failure_leave_no_ticket(org, migrated, monkeypatch):
    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, scripted_prepare(), switch, clock)) as client:
        _, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        switch.current = ActorContext(
            SALES.user_id,
            SALES.department_ids,
            SALES.role_ids,
            SALES.capabilities - {"ticket.submit"},
            2,
            "test_stub",
        )
        denied = await post(
            client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "ACTION_NOT_ALLOWED"
        switch.current = SALES
        import agent.modules.it_support.service as service_module

        original = service_module._audit

        async def boom(conn, action_id, actor_id, event, details, now):
            if event == "confirmed":
                raise RuntimeError("감사 기록 실패(시험)")
            return await original(conn, action_id, actor_id, event, details, now)

        monkeypatch.setattr(service_module, "_audit", boom)
        failed = await post(
            client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        assert failed.status_code >= 500
        monkeypatch.setattr(service_module, "_audit", original)
        assert await count(org, tickets) == 0  # 티켓·상태·멱등 기록이 함께 rollback
        assert (await client.get(f"/api/v1/ticket-actions/{pending['action_id']}")).json()[
            "status"
        ] == "pending"
        ok = await post(
            client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        assert ok.status_code == 201


async def test_history_hides_ticket_refs_when_the_ticket_is_no_longer_visible(org, migrated):
    """CP-05: 답이 기댄 티켓을 지금 볼 수 없으면 이력에서 가린다(T-30)."""
    switch, clock = Switch(SALES), FixedClock()

    def show(request):
        page = last_result(request)["data"]
        return final("티켓 1건", ticket_ids=[t["id"] for t in page["items"]])

    script = [*scripted_prepare(), tool("list_it_tickets", {}), show]
    async with api_client(build(migrated, script, switch, clock)) as client:
        conversation, body = await prepared(client)
        pending = (
            await post(
                client,
                f"/ticket-actions/{body['action_preview']['action_id']}/revise",
                {"version": 1, "fields": COMPLETE},
                str(uuid.uuid4()),
            )
        ).json()
        await post(
            client, f"/ticket-actions/{pending['action_id']}/confirm", {"version": 1}, str(uuid.uuid4())
        )
        _, listed = await ask(client, "내 티켓 보여줘", conversation)
        assert listed.json()["ticket_refs"][0]["subject"] == "VPN 접속 오류"
        async with org.begin() as conn:
            await conn.execute(text("UPDATE tickets SET requester_id = 'someone-else'"))
        history = (await client.get(f"/api/v1/conversations/{conversation}/messages")).json()["items"]
        assert history[-1]["visibility"] == "redacted" and history[-1]["ticket_refs"] == []


# --- 검증 에이전트 지적 회귀(2026-10-18) ---


def direct_service(engine, clock, evidence=None):
    from agent.modules.conversation.records import DbConversationEvidence
    from agent.modules.identity_access.service import IdentityService
    from agent.modules.it_support.service import TicketService

    class Always:
        async def check_prepare(self, *args):
            return True

        async def adopted(self, *args):
            return True

    return TicketService(
        engine, clock, IdentityService(engine, clock), Always(), evidence or DbConversationEvidence(engine)
    )


TEMPLATE_ONLY = (
    {"subject": "IT 지원 요청"},
    [{"field": "subject", "kind": "template", "template_id": "ticket.subject.generic.v1"}],
)


async def _draft(service, conversation, run, ordinal=1):
    fields, origins = TEMPLATE_ONLY
    return await service.prepare(
        SALES, conversation_id=conversation, run_id=run, ordinal=ordinal, fields=fields, field_origins=origins
    )


async def test_same_key_revise_replays_even_when_the_pre_lock_check_missed(org, monkeypatch):
    """같은 키 두 요청이 잠금 밖 replay·상태 검사를 함께 지나도, 잠금 안에서 먼저 끝난 결과를 돌려준다."""
    clock = FixedClock()
    service = direct_service(org, clock)
    draft = await _draft(service, str(uuid.uuid4()), str(uuid.uuid4()))
    barrier = asyncio.Barrier(2)
    original = service._require_adopted

    async def together(*args):
        await barrier.wait()  # 둘 다 잠금 밖 검사를 마친 뒤에 잠금을 다툰다
        return await original(*args)

    monkeypatch.setattr(service, "_require_adopted", together)
    key = uuid.uuid4()
    first, second = await asyncio.gather(
        service.revise(SALES, draft["action_id"], version=1, fields=COMPLETE, key=key),
        service.revise(SALES, draft["action_id"], version=1, fields=COMPLETE, key=key),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 201]
    assert first.body["action_id"] == second.body["action_id"]


async def test_error_precedence_state_before_root_eligibility(org, migrated):
    """03-errors: 상태 오류(취소·draft 확인 불가)가 root 자격(RUN_NOT_ELIGIBLE)보다 먼저다."""
    from agent.modules.conversation.records import DbConversationEvidence
    from agent.modules.identity_access.service import IdentityService
    from agent.modules.it_support.service import TicketService
    from agent.shared.errors import AppError

    class Never:
        async def check_prepare(self, *args):
            return True

        async def adopted(self, *args):
            return False

    clock = FixedClock()
    service = TicketService(org, clock, IdentityService(org, clock), Never(), DbConversationEvidence(org))
    draft = await _draft(service, str(uuid.uuid4()), str(uuid.uuid4()))
    with pytest.raises(AppError) as not_prepared:
        await service.confirm(SALES, draft["action_id"], version=1, key=uuid.uuid4())
    assert not_prepared.value.code.value == "ACTION_NOT_PREPARED"
    await service.cancel(SALES, draft["action_id"], version=1)
    with pytest.raises(AppError) as cancelled:
        await service.confirm(SALES, draft["action_id"], version=1, key=uuid.uuid4())
    assert cancelled.value.code.value == "ACTION_CANCELLED"
    with pytest.raises(AppError) as hidden:
        await service.get_action(SALES, draft["action_id"])  # 채택되지 않은 draft는 공개하지 않는다
    assert hidden.value.code.value == "RESOURCE_NOT_FOUND"


async def test_confirm_replay_rechecks_current_read_permission(org):
    from agent.shared.errors import AppError

    clock = FixedClock()
    service = direct_service(org, clock)
    draft = await _draft(service, str(uuid.uuid4()), str(uuid.uuid4()))
    pending = await service.revise(SALES, draft["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())
    key = uuid.uuid4()
    created = await service.confirm(SALES, pending.body["action_id"], version=1, key=key)
    assert created.status_code == 201
    blind = ActorContext(
        SALES.user_id,
        SALES.department_ids,
        SALES.role_ids,
        SALES.capabilities - {"ticket.read_own"},
        2,
        "test_stub",
    )
    for attempt in (key, uuid.uuid4()):  # 같은 키 replay와 다른 키 반복 확인 모두
        with pytest.raises(AppError) as exc:
            await service.confirm(blind, pending.body["action_id"], version=1, key=attempt)
        assert exc.value.code.value == "RESOURCE_NOT_FOUND"


async def test_head_lineage_displacement_cancel_revision_and_expiry(org):
    from agent.modules.it_support.tables import ticket_action_heads as heads
    from agent.shared.errors import AppError

    clock = FixedClock()
    service = direct_service(org, clock)
    conversation = str(uuid.uuid4())

    async def head():
        async with org.connect() as conn:
            return (await conn.execute(select(heads.c.head_action_id, heads.c.head_revision))).one()

    a = await _draft(service, conversation, str(uuid.uuid4()))
    pa = (await service.revise(SALES, a["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())).body
    b = await _draft(service, conversation, str(uuid.uuid4()))  # pa가 head일 때 준비(기대값 캡처)
    pb = (await service.revise(SALES, b["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())).body
    assert pb["displaced_head_id"] == pa["action_id"] and pb["prepared_from_action_id"] == b["action_id"]
    assert (await service.get_action(SALES, pa["action_id"]))["superseded_by_action_id"] == pb["action_id"]
    assert tuple(await head()) == (uuid.UUID(pb["action_id"]), 2)
    c = await _draft(service, conversation, str(uuid.uuid4()))  # (pb, 2) 캡처
    await service.cancel(SALES, pb["action_id"], version=1)
    assert tuple(await head()) == (uuid.UUID(pb["action_id"]), 3)  # 현재 pending 취소: ID 유지, revision 증가
    await service.cancel(SALES, pb["action_id"], version=1)
    assert (await head())[1] == 3  # 반복 취소는 revision을 올리지 않는다
    with pytest.raises(AppError) as stale:
        await service.revise(SALES, c["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())
    assert stale.value.code.value == "ACTION_HEAD_CONFLICT"
    assert set(stale.value.details) == {"current_action_id", "head_revision"}
    d = await _draft(service, conversation, str(uuid.uuid4()))  # (pb, 3) 캡처
    pd = (await service.revise(SALES, d["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())).body
    assert pd["displaced_head_id"] == pb["action_id"]
    assert (await service.get_action(SALES, pb["action_id"]))["status"] == "cancelled"  # cancelled는 그대로
    clock.advance(301)
    assert (await service.get_action(SALES, pd["action_id"]))["status"] == "expired"
    assert (await head())[1] == 4  # 만료는 revision을 올리지 않는다


async def test_duplicate_and_future_origins_drop_the_field(org):
    clock = FixedClock()
    service = direct_service(org, clock)
    fields, origins = TEMPLATE_ONLY
    for bad_fields, bad_origins, dropped in (
        (fields, origins * 2, "subject"),  # 같은 필드 출처 두 번
        ({**fields, "occurred_at": "2026-10-16T11:00:00+09:00"}, origins, "occurred_at"),  # 미래 시각
    ):
        preview = await service.prepare(
            SALES,
            conversation_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            ordinal=1,
            fields=bad_fields,
            field_origins=bad_origins,
        )
        assert preview[dropped] is None and dropped in preview["rejected_fields"]


async def test_cp07_reads_only_own_run_window_user_messages(org, migrated):
    """CP-07: 다른 대화·assistant·다른 사용자의 메시지는 돌려주지 않는다."""
    from agent.modules.conversation.records import DbConversationEvidence

    switch, clock = Switch(SALES), FixedClock()
    async with api_client(build(migrated, [final("첫 답"), *scripted_prepare()], switch, clock)) as client:
        first_conv, _ = await ask(client, "다른 대화의 VPN이 안 돼요")
        conversation, body = await prepared(client)
    async with org.connect() as conn:
        rows = (await conn.execute(text("SELECT id, conversation_id, role FROM messages"))).all()
        run_id = await conn.scalar(
            text("SELECT run_id FROM messages WHERE role = 'assistant' AND conversation_id = :c"),
            {"c": conversation},
        )
    ids = {str(r.id) for r in rows}
    reader = DbConversationEvidence(org)
    got = await reader.read_user_messages("emp-sales", conversation, str(run_id), ids)
    own_user = {str(r.id) for r in rows if str(r.conversation_id) == conversation and r.role == "user"}
    assert set(got) == own_user  # 같은 대화의 user 메시지만(다른 대화·assistant 제외)
    assert await reader.read_user_messages("emp-dev", conversation, str(run_id), ids) == {}  # 다른 사용자
    assert first_conv != conversation and body["outcome"] == "action_pending"


# --- 변이 생존 보강(2026-10-18) ---


async def test_concurrent_revises_against_an_existing_head_produce_one_pending(org, monkeypatch):
    """head 행이 이미 있을 때 두 draft가 같은 기대값으로 동시에 revise해도 하나만 head가 된다(잠금 직렬화)."""
    clock = FixedClock()
    service = direct_service(org, clock)
    conversation = str(uuid.uuid4())
    a = await _draft(service, conversation, str(uuid.uuid4()))
    await service.revise(SALES, a["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())
    b = await _draft(service, conversation, str(uuid.uuid4()))
    c = await _draft(service, conversation, str(uuid.uuid4()), ordinal=2)
    barrier = asyncio.Barrier(2)
    original = service._require_adopted

    async def together(*args):
        await barrier.wait()
        return await original(*args)

    monkeypatch.setattr(service, "_require_adopted", together)
    from agent.shared.errors import AppError

    async def attempt(draft):
        try:
            return (
                await service.revise(SALES, draft["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())
            ).status_code
        except AppError as exc:
            return exc.code.value

    results = await asyncio.gather(attempt(b), attempt(c))
    assert sorted(map(str, results)) == ["201", "ACTION_HEAD_CONFLICT"]
    async with org.connect() as conn:
        pendings = await conn.scalar(
            select(func.count()).select_from(ticket_actions).where(ticket_actions.c.status == "pending")
        )
    assert pendings == 1


async def test_revise_version_and_incident_time_and_prepare_eligibility(org):
    from agent.modules.conversation.records import DbConversationEvidence, DbRunEligibility
    from agent.modules.identity_access.service import IdentityService
    from agent.modules.it_support.contracts import TicketFields
    from agent.modules.it_support.service import TicketService
    from agent.shared.errors import AppError

    clock = FixedClock()
    service = direct_service(org, clock)
    draft = await _draft(service, str(uuid.uuid4()), str(uuid.uuid4()))
    with pytest.raises(AppError) as version:
        await service.revise(SALES, draft["action_id"], version=2, fields=COMPLETE, key=uuid.uuid4())
    assert version.value.code.value == "ACTION_VERSION_CONFLICT"
    # 장애는 발생 시각이 있어야 pending이 된다(D-42).
    assert "occurred_at" in TicketFields(**{**COMPLETE, "occurred_at": None}).missing_fields()
    assert (
        "occurred_at"
        not in TicketFields(**{**COMPLETE, "occurred_at": None, "request_type": "inquiry"}).missing_fields()
    )
    # 실제 CP-06: 실행 중이 아닌(없는) run에서는 준비할 수 없다.
    real = TicketService(
        org, clock, IdentityService(org, clock), DbRunEligibility(org, clock), DbConversationEvidence(org)
    )
    fields, origins = TEMPLATE_ONLY
    with pytest.raises(AppError) as ineligible:
        await real.prepare(
            SALES,
            conversation_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            ordinal=1,
            fields=fields,
            field_origins=origins,
        )
    assert ineligible.value.code.value == "RUN_NOT_ELIGIBLE"


async def test_support_scope_limits_departments(org):
    from agent.modules.it_support.tables import support_scopes

    clock = FixedClock()
    service = direct_service(org, clock)
    draft = await _draft(service, str(uuid.uuid4()), str(uuid.uuid4()))
    pending = await service.revise(SALES, draft["action_id"], version=1, fields=COMPLETE, key=uuid.uuid4())
    ticket_id = (await service.confirm(SALES, pending.body["action_id"], version=1, key=uuid.uuid4())).body[
        "ticket_id"
    ]
    narrow = actor("it-dev-only", ("dept-it",), frozenset({"ticket.read_support_scope"}))
    async with org.begin() as conn:
        await conn.execute(support_scopes.insert().values(user_id="it-dev-only", department_ids=["dept-dev"]))
    assert (await service.list_tickets(narrow, status=None, limit=10, offset=0))[
        "total"
    ] == 0  # 영업팀 요청자는 범위 밖
    assert await service.visible_ticket_ids(narrow, {ticket_id}) == set()
    assert await service.visible_ticket_ids(SUPPORT, {ticket_id}) == {ticket_id}


async def test_cp06_and_cp07_reject_wrong_runs_drafts_and_assistant_text(org, migrated):
    from agent.modules.conversation.records import DbConversationEvidence, DbRunEligibility

    switch, clock = Switch(SALES), FixedClock()
    async with api_client(
        build(migrated, [final("VPN은 재설치하세요"), *scripted_prepare()], switch, clock)
    ) as client:
        conversation, _ = await ask(client, "VPN 어떻게 해요?")
        _, body = await ask(client, VPN_MESSAGE, conversation)
    async with org.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, role, run_id FROM messages WHERE conversation_id = :c ORDER BY seq"),
                {"c": conversation},
            )
        ).all()
    second_run = str(rows[-1].run_id)
    ids = {str(r.id) for r in rows}
    got = await DbConversationEvidence(org).read_user_messages("emp-sales", conversation, second_run, ids)
    assert set(got) == {str(r.id) for r in rows if r.role == "user"}  # 이전 assistant 답은 출처가 아니다
    eligibility = DbRunEligibility(org, clock)
    action_id = body.json()["action_preview"]["action_id"]
    assert await eligibility.adopted("emp-sales", conversation, second_run, action_id) is True
    assert (
        await eligibility.adopted("emp-sales", conversation, second_run, str(uuid.uuid4())) is False
    )  # 다른 draft
    assert await eligibility.check_prepare("emp-sales", conversation, second_run) is False  # 이미 completed
