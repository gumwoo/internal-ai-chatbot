"""M2 MOD-01 대화·실행(실제 앱 + 테스트 DB + 가짜 모델). 과금 없음.

T-01 격리, T-02 동시 수락·lazy 만료·늦은 완료·시작 회수, T-03 기록/최종 저장 장애, T-05 멱등 재전송,
T-07 원장 밖 참조, T-08 장애와 0건 구분, M1-4 검증된 사본만 모델 문맥에.
"""

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from agent.app.main import create_app
from agent.modules.conversation.records import DbExecutionObserver
from agent.modules.conversation.service import ConversationService
from agent.modules.identity_access.test_stub import TestStubCurrentActor
from agent.modules.model_integration.fake import FakeModelClient
from agent.modules.model_integration.ports import ModelCallError, ModelFailure, ModelResponse, Usage
from agent.modules.training.service import TrainingService
from agent.shared.actor import ActorContext
from agent.shared.clock import FixedClock
from agent.shared.contracts import RequiredRecordError, ToolCallProposal
from tests.conftest import api_client, make_settings

ORIGIN = "http://localhost:5190"
SEC = "11111111-1111-4111-8111-111111111101"
COLLAB = "11111111-1111-4111-8111-111111111102"
USAGE = Usage(input_tokens=100, output_tokens=10, complete=True)


def tool_turn(*calls: tuple[str, dict]) -> ModelResponse:
    proposals = tuple(
        ToolCallProposal(name=name, arguments=args, provider_call_id=f"toolu_{uuid.uuid4().hex[:8]}")
        for name, args in calls
    )
    return ModelResponse(proposals, None, "fake", "agent_answer", "test", USAGE)


def final(answer="답", outcome="answered", ids=(), selected=None) -> ModelResponse:
    candidate = {
        "answer": answer,
        "outcome": outcome,
        "training_ids": list(ids),
        "selected_training_id": selected,
    }
    return ModelResponse((), candidate, "fake", "agent_answer", "test", USAGE)


NEXT_WEEK = [
    tool_turn(("list_trainings", {"date_preset": "next_week"})),
    final("두 건입니다", ids=(SEC, COLLAB)),
]


def _app(migrated, model, clock=None, actor_id="test-a", actor=None):
    return create_app(
        make_settings(database_url=migrated, allowed_origins=ORIGIN),
        current_actor=actor or TestStubCurrentActor(actor_id),
        clock=clock or FixedClock(),
        chat_model=model,
    )


async def _new_conversation(client) -> str:
    response = await client.post(
        "/api/v1/conversations", json={"title": "테스트"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _post(client, conversation_id, content, key=None):
    return await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(key or uuid.uuid4())},
    )


async def _scalar(engine, sql, **params):
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


def _turn(request) -> str:
    """현재 사용자 턴(대화 자료 블록 포함, P-13 B)."""
    return request.messages[-1].text or ""


# --- 정상 흐름과 M1-4 ---


async def test_message_runs_tools_and_persists_everything(seeded_engine, migrated):
    model = FakeModelClient(NEXT_WEEK)
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "다음 주 교육 알려줘")
        body = response.json()
        assert response.status_code == 200, body
        assert response.headers["cache-control"] == "private, no-store"
        assert (body["status"], body["outcome"], body["error"]) == ("completed", "answered", None)
        assert [r["code"] for r in body["training_refs"]] == ["TR-SEC-001", "TR-COLLAB-001"]

        history = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()
        assert [m["role"] for m in history["items"]] == ["user", "assistant"]
        run = (await client.get(f"/api/v1/runs/{body['run_id']}")).json()
        assert run["status"] == "completed" and run["tools"] == [
            {"ordinal": 1, "name": "list_trainings", "attempt": 1, "ok": True, "error_code": None}
        ]
        assert (await client.get(f"/api/v1/conversations/{conv}")).json()["active_run_id"] is None
    assert await _scalar(seeded_engine, "SELECT count(*) FROM tool_result_receipts") == 1


async def test_follow_up_uses_verified_copy_in_model_context(seeded_engine, migrated):
    model = FakeModelClient([*NEXT_WEEK, final("3층 교육장입니다", ids=(SEC,), selected=SEC)])
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        await _post(client, conv, "다음 주 교육 알려줘")
        response = await _post(client, conv, "그중 보안교육 장소는?")
    assert response.status_code == 200, response.json()
    assert [r["code"] for r in response.json()["training_refs"]] == ["TR-SEC-001"]
    follow_up = model.requests[-1]
    assert "TR-SEC-001" in _turn(follow_up) and "3층 교육장" in _turn(follow_up)  # 서버가 검증한 사본
    # P-13 B: 자료는 system이 아니라 현재 사용자 턴 앞 자료 블록에 있다. system에는 규칙만 있다.
    assert "TR-SEC-001" not in follow_up.system and _turn(follow_up).startswith("[대화 자료]")
    assert _turn(follow_up).endswith("[사용자 질문]\n그중 보안교육 장소는?")
    assert [m.role for m in follow_up.messages] == ["user", "assistant", "user"]


async def test_copy_without_receipt_is_not_trusted(seeded_engine, migrated):
    """CP-07: receipt와 맞지 않는 업무 상태(조작·실패 run)의 교육은 사본으로 쓰지 않는다."""
    model = FakeModelClient([final("보안 교육", ids=(SEC,), selected=SEC)])
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        forged = json.dumps({"training_cache": {SEC: {"id": SEC, "starts_at": "2026-10-20T14:00:00+09:00"}}})
        async with seeded_engine.begin() as conn:
            await conn.execute(
                text("UPDATE conversations SET business_state = CAST(:s AS jsonb) WHERE id = :id"),
                {"s": forged, "id": conv},
            )
        response = await _post(client, conv, "그 교육 장소?")
    assert (response.status_code, response.json()["error"]["code"]) == (502, "MODEL_OUTPUT_INVALID")
    assert _turn(model.requests[0]).startswith("[대화 자료] 없음")


# --- T-05 멱등 재전송 ---


async def test_same_key_replays_without_new_execution(seeded_engine, migrated):
    model = FakeModelClient(NEXT_WEEK)
    key = uuid.uuid4()
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        first = await _post(client, conv, "다음 주 교육 알려줘", key)
        again = await _post(client, conv, "다음 주 교육 알려줘", key)
        conflict = await _post(client, conv, "다른 질문", key)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(model.requests) == 2  # 재전송은 모델을 다시 부르지 않는다
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "MESSAGE_IDEMPOTENCY_CONFLICT")
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 1
    assert await _scalar(seeded_engine, "SELECT count(*) FROM messages WHERE role = 'user'") == 1


class _BlockingModel(FakeModelClient):
    """release가 set될 때까지 첫 응답을 붙잡는다. 실행 중 상태를 재현한다."""

    def __init__(self, script):
        super().__init__(script)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete_once(self, request):
        self.started.set()
        await self.release.wait()
        return await super().complete_once(request)


async def test_running_replay_is_202_and_other_key_is_busy(seeded_engine, migrated):
    model = _BlockingModel(NEXT_WEEK)
    key = uuid.uuid4()
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        first = asyncio.create_task(_post(client, conv, "다음 주 교육 알려줘", key))
        await asyncio.wait_for(model.started.wait(), 5)
        running = await _post(client, conv, "다음 주 교육 알려줘", key)
        busy = await _post(client, conv, "다른 질문")
        model.release.set()
        done = await first
        replay = await _post(client, conv, "다음 주 교육 알려줘", key)
    assert running.status_code == 202
    assert running.json()["status"] == "running" and running.json()["run_id"] == done.json()["run_id"]
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "CONVERSATION_BUSY")
    assert done.status_code == replay.status_code == 200
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 1


async def test_concurrent_new_messages_accept_only_one(seeded_engine, migrated):
    model = _BlockingModel(NEXT_WEEK)
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        tasks = [asyncio.create_task(_post(client, conv, f"질문 {i}")) for i in range(5)]
        await asyncio.wait_for(model.started.wait(), 5)
        await asyncio.sleep(0.2)
        model.release.set()
        results = await asyncio.gather(*tasks)
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409, 409]
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 1


# --- T-01 격리 ---


async def test_other_user_sees_same_404_and_new_conversation_is_empty(seeded_engine, migrated):
    model_a = FakeModelClient(NEXT_WEEK)
    async with api_client(_app(migrated, model_a)) as client_a:
        conv = await _new_conversation(client_a)
        run_id = (await _post(client_a, conv, "다음 주 교육 알려줘")).json()["run_id"]

    model_b = FakeModelClient([final("어느 교육인가요?", outcome="needs_clarification")])
    async with api_client(_app(migrated, model_b, actor_id="test-b")) as client_b:
        missing = uuid.uuid4()
        for path in (f"/api/v1/conversations/{conv}", f"/api/v1/conversations/{missing}"):
            response = await client_b.get(path)
            assert (response.status_code, response.json()["error"]["code"]) == (404, "CONVERSATION_NOT_FOUND")
        assert (await client_b.get(f"/api/v1/conversations/{conv}/messages")).status_code == 404
        assert (await _post(client_b, conv, "그 교육 장소?")).status_code == 404
        run = await client_b.get(f"/api/v1/runs/{run_id}")
        assert (run.status_code, run.json()["error"]["code"]) == (404, "RUN_NOT_FOUND")
        assert (await client_b.get("/api/v1/conversations")).json()["total"] == 0

        own = await _new_conversation(client_b)
        response = await _post(client_b, own, "그 교육 장소 어디야?")
    assert response.json()["outcome"] == "needs_clarification"
    assert _turn(model_b.requests[0]).startswith(
        "[대화 자료] 없음"
    )  # 다른 사용자·대화의 후보를 가져오지 않는다
    assert [m.role for m in model_b.requests[0].messages] == ["user"]


# --- T-02 만료·늦은 완료·시작 회수 ---


async def _insert_running(engine, conv, accepted_at, deadline_at):
    run_id, message_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content, run_id, created_at)"
                " VALUES (:m, :c, 'user', '이전 질문', :r, :t)"
            ),
            {"m": message_id, "c": conv, "r": run_id, "t": accepted_at},
        )
        await conn.execute(
            text(
                "INSERT INTO agent_runs (id, conversation_id, request_id, user_message_id, status,"
                " accepted_at, deadline_at, prompt_version, model, retrieval_context)"
                " VALUES (:r, :c, 'old', :m, 'running', :a, :d, 'p', 'fake', '{}'::jsonb)"
            ),
            {"r": run_id, "c": conv, "m": message_id, "a": accepted_at, "d": deadline_at},
        )
        await conn.execute(
            text("UPDATE conversations SET active_run_id = :r WHERE id = :c"), {"r": run_id, "c": conv}
        )
    return run_id


async def test_lazy_expiry_on_next_accept_but_not_before_deadline(seeded_engine, migrated):
    clock = FixedClock()
    model = FakeModelClient(NEXT_WEEK)
    async with api_client(_app(migrated, model, clock=clock)) as client:
        conv = await _new_conversation(client)
        now = clock.now()
        alive = await _insert_running(
            seeded_engine, conv, now - timedelta(seconds=30), now + timedelta(seconds=30)
        )
        busy = await _post(client, conv, "새 질문")
        assert (busy.status_code, busy.json()["error"]["code"]) == (409, "CONVERSATION_BUSY")
        assert (await client.get(f"/api/v1/runs/{alive}")).json()["status"] == "running"

        clock.advance(31)  # 이전 run의 deadline이 지났다
        accepted = await _post(client, conv, "새 질문")
        old = (await client.get(f"/api/v1/runs/{alive}")).json()
    assert accepted.status_code == 200
    assert (old["status"], old["error_code"]) == ("expired", "RUN_TIMEOUT")


async def test_get_run_recovers_expired_run(seeded_engine, migrated):
    clock = FixedClock()
    async with api_client(_app(migrated, FakeModelClient([]), clock=clock)) as client:
        conv = await _new_conversation(client)
        now = clock.now()
        stale = await _insert_running(
            seeded_engine, conv, now - timedelta(seconds=90), now - timedelta(seconds=30)
        )
        run = (await client.get(f"/api/v1/runs/{stale}")).json()
        conversation = (await client.get(f"/api/v1/conversations/{conv}")).json()
    assert run["status"] == "expired"
    assert conversation["active_run_id"] is None


async def test_late_completion_does_not_overwrite_expiry(seeded_engine, migrated):
    clock = FixedClock()

    class LateModel(FakeModelClient):
        async def complete_once(self, request):
            clock.advance(61)  # 답이 deadline 뒤에 도착한다
            return await super().complete_once(request)

    model = LateModel([final("늦은 답")])
    async with api_client(_app(migrated, model, clock=clock)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "안녕")
        history = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()
    assert (response.status_code, response.json()["error"]["code"]) == (504, "RUN_TIMEOUT")
    assert [m["role"] for m in history["items"]] == ["user"]  # 늦은 답은 저장되지 않는다
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "expired"


async def test_startup_recovers_expired_runs(seeded_engine, migrated):
    clock = FixedClock()
    async with api_client(_app(migrated, FakeModelClient([]), clock=clock)) as client:
        conv = await _new_conversation(client)
    now = clock.now()
    stale = await _insert_running(
        seeded_engine, conv, now - timedelta(seconds=90), now - timedelta(seconds=30)
    )
    app = _app(migrated, FakeModelClient([]), clock=clock)
    async with api_client(app):
        for _ in range(50):
            if (
                await _scalar(seeded_engine, "SELECT status FROM agent_runs WHERE id = :r", r=stale)
                == "expired"
            ):
                break
            await asyncio.sleep(0.05)
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs WHERE id = :r", r=stale) == "expired"
    assert (
        await _scalar(seeded_engine, "SELECT active_run_id FROM conversations WHERE id = :c", c=conv) is None
    )


# --- 실패: T-03 / T-07 / T-08 ---


async def test_model_failure_is_stored_and_replayed_without_state(seeded_engine, migrated):
    model = FakeModelClient([ModelCallError(ModelFailure.NOT_CONFIGURED)])
    key = uuid.uuid4()
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        first = await _post(client, conv, "안녕", key)
        again = await _post(client, conv, "안녕", key)
    assert first.status_code == again.status_code == 503
    assert first.json()["error"]["code"] == again.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    assert len(model.requests) == 1
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "failed"
    assert await _scalar(seeded_engine, "SELECT business_state::text FROM conversations") == "{}"


async def test_forged_training_id_is_not_saved(seeded_engine, migrated):
    model = FakeModelClient([final("지어낸 교육", ids=("11111111-1111-4111-8111-999999999999",))])
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "교육 알려줘")
        history = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()
    assert (response.status_code, response.json()["error"]["code"]) == (502, "MODEL_OUTPUT_INVALID")
    assert [m["role"] for m in history["items"]] == ["user"]


async def test_tool_db_failure_is_error_not_zero_results(seeded_engine, migrated, monkeypatch):
    async def broken(self, search, now):
        raise OperationalError("SELECT", {}, Exception("db down"))

    monkeypatch.setattr(TrainingService, "list_trainings", broken)
    model = FakeModelClient([tool_turn(("list_trainings", {})), final("없습니다", outcome="no_results")])
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "교육 있어?")
    assert (response.status_code, response.json()["error"]["code"]) == (502, "TOOL_EXECUTION_FAILED")
    assert len(model.requests) == 1  # 장애를 모델에 넘겨 "0건"으로 포장하지 않는다
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "failed"
    assert await _scalar(seeded_engine, "SELECT count(*) FROM tool_calls") == 2  # 시도 2번(재시도 1회) 기록
    assert await _scalar(seeded_engine, "SELECT count(*) FROM messages WHERE role = 'assistant'") == 0


async def test_required_record_failure_stops_run(seeded_engine, migrated, monkeypatch):
    async def broken(self, record):
        raise RequiredRecordError("기록 장애")

    monkeypatch.setattr(DbExecutionObserver, "record_tool_call", broken)
    model = FakeModelClient([tool_turn(("list_trainings", {})), final()])
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "교육 있어?")
    assert (response.status_code, response.json()["error"]["code"]) == (503, "PERSISTENCE_FAILED")
    assert len(model.requests) == 1
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "failed"


async def test_final_commit_failure_is_not_reported_as_success(seeded_engine, migrated, monkeypatch):
    async def broken(self, *args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("commit lost"))

    monkeypatch.setattr(ConversationService, "_complete", broken)
    clock = FixedClock()
    model = FakeModelClient([final("답")])
    async with api_client(_app(migrated, model, clock=clock)) as client:
        conv = await _new_conversation(client)
        response = await _post(client, conv, "안녕")
        running = (await client.get(f"/api/v1/conversations/{conv}")).json()["active_run_id"]
        clock.advance(61)
        recovered = (await client.get(f"/api/v1/conversations/{conv}")).json()["active_run_id"]
        history = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()
    assert (response.status_code, response.json()["error"]["code"]) == (503, "PERSISTENCE_FAILED")
    assert running is not None and recovered is None  # deadline 뒤 회수된다
    assert [m["role"] for m in history["items"]] == ["user"]


# --- 입력 경계와 이력 가림 ---


async def test_message_input_validation(seeded_engine, migrated):
    async with api_client(_app(migrated, FakeModelClient([]))) as client:
        conv = await _new_conversation(client)
        url = f"/api/v1/conversations/{conv}/messages"
        no_key = await client.post(url, json={"content": "안녕"}, headers={"Origin": ORIGIN})
        bad_key = await client.post(
            url, json={"content": "안녕"}, headers={"Origin": ORIGIN, "Idempotency-Key": "not-uuid"}
        )
        too_long = await _post(client, conv, "가" * 4001)
        extra = await client.post(
            url,
            json={"content": "안녕", "user_id": "test-b"},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid.uuid4())},
        )
        no_origin = await client.post(
            url, json={"content": "안녕"}, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
    assert no_key.status_code == bad_key.status_code == too_long.status_code == extra.status_code == 422
    assert no_key.json()["error"]["details"] == {"field_names": ["Idempotency-Key"]}
    assert extra.json()["error"]["details"] == {"field_names": ["user_id"]}
    assert (no_origin.status_code, no_origin.json()["error"]["code"]) == (403, "CSRF_FAILED")
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 0


async def test_history_is_redacted_when_reader_cannot_view(seeded_engine, migrated):
    async with api_client(_app(migrated, FakeModelClient(NEXT_WEEK))) as client:
        conv = await _new_conversation(client)
        await _post(client, conv, "다음 주 교육 알려줘")
    no_caps = ActorContext("test-a", (), (), frozenset(), 1, "test_stub")

    class NoCaps:
        async def resolve(self, request):
            return no_caps

    async with api_client(_app(migrated, FakeModelClient([]), actor=NoCaps())) as client:
        items = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()["items"]
    assistant = items[1]
    assert assistant["visibility"] == "redacted"
    assert assistant["training_refs"] == [] and "TR-SEC" not in str(assistant)


@pytest.mark.parametrize("limit", [0, 51])
async def test_paging_bounds(seeded_engine, migrated, limit):
    async with api_client(_app(migrated, FakeModelClient([]))) as client:
        response = await client.get("/api/v1/conversations", params={"limit": limit})
    assert response.status_code == 422


async def test_all_response_times_use_kst_and_list_shows_active_run(seeded_engine, migrated):
    model = _BlockingModel(NEXT_WEEK)
    async with api_client(_app(migrated, model)) as client:
        created = (
            await client.post("/api/v1/conversations", json={"title": "시각"}, headers={"Origin": ORIGIN})
        ).json()
        conv = created["id"]
        task = asyncio.create_task(_post(client, conv, "다음 주 교육 알려줘"))
        await asyncio.wait_for(model.started.wait(), 5)
        listed = (await client.get("/api/v1/conversations")).json()["items"][0]
        model.release.set()
        run_id = (await task).json()["run_id"]
        fetched = (await client.get(f"/api/v1/conversations/{conv}")).json()
        message = (await client.get(f"/api/v1/conversations/{conv}/messages")).json()["items"][0]
        run = (await client.get(f"/api/v1/runs/{run_id}")).json()
    assert listed["active_run_id"] == run_id  # 실행 중에는 목록에도 활성 run이 보인다
    for value in (
        created["created_at"],
        fetched["created_at"],
        message["created_at"],
        run["accepted_at"],
        run["deadline_at"],
        run["finished_at"],
    ):
        assert value.endswith("+09:00"), value


async def test_untitled_conversation_is_listed_by_first_question(seeded_engine, migrated):
    question = "다음 주   교육 알려줘. 신입사원 교육이랑 협업 도구 교육 중 무엇을 먼저 들어야 하나요"
    model = FakeModelClient(NEXT_WEEK * 3)
    async with api_client(_app(migrated, model)) as client:
        untitled = (await client.post("/api/v1/conversations", headers={"Origin": ORIGIN})).json()
        assert untitled["title"] is None
        empty = (await client.get(f"/api/v1/conversations/{untitled['id']}")).json()
        assert empty["title"] is None  # 질문이 없으면 화면이 생성 시각으로 표시한다

        titled = await _new_conversation(client)
        await _post(client, titled, "다른 질문")
        await _post(client, untitled["id"], question)
        await _post(client, untitled["id"], "두 번째 질문은 이름에 쓰지 않는다")

        items = {c["id"]: c for c in (await client.get("/api/v1/conversations")).json()["items"]}
        fetched = (await client.get(f"/api/v1/conversations/{untitled['id']}")).json()
    expected = " ".join(question.split())[:40].rstrip() + "…"
    assert items[untitled["id"]]["title"] == expected == fetched["title"]
    assert items[titled]["title"] == "테스트"  # 정한 제목은 그대로
