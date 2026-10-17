"""D-29 진행 상황 스트리밍(SSE). 과금 없음(가짜 모델 + 테스트 DB).

T-02 스트리밍 연결 끊김(실행 취소 없음)·만료 run의 늦은 progress 없음, T-04 progress 내용 최소화·result는
JSON 응답과 같음. 수락·409·replay 규칙은 JSON 요청과 같다(04-api-spec 진행 상황 스트리밍).
"""

import asyncio
import json
import uuid

from sqlalchemy.exc import OperationalError

from agent.app.conversations import _sse, _wants_stream
from agent.modules.conversation.progress import RunProgress, progress_events
from agent.modules.conversation.records import DbExecutionObserver
from agent.modules.conversation.service import ConversationService
from agent.modules.model_integration.fake import FakeModelClient
from agent.shared.clock import FixedClock
from agent.shared.contracts import ExecutionPolicy, ProgressStage
from agent.shared.errors import AppError, ErrorCode
from tests.conftest import api_client
from tests.test_conversation import (
    NEXT_WEEK,
    ORIGIN,
    _app,
    _BlockingModel,
    _new_conversation,
    _scalar,
    final,
    tool_turn,
)

SSE = {"Accept": "text/event-stream"}
STAGES = {s.value for s in ProgressStage}


async def _post_sse(client, conversation_id, content, key=None, accept="text/event-stream"):
    return await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(key or uuid.uuid4()), "Accept": accept},
    )


def _parse(body: str) -> list[tuple[str, object]]:
    """SSE 본문 → [(event, data)]. 주석 줄(heartbeat)은 ("comment", 내용)."""
    events = []
    for block in body.split("\n\n"):
        if not block:
            continue
        if block.startswith(":"):
            events.append(("comment", block[1:].strip()))
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_stream_sends_recorded_stages_then_one_result_equal_to_json(seeded_engine, migrated):
    key = uuid.uuid4()
    async with api_client(_app(migrated, FakeModelClient(NEXT_WEEK))) as client:
        conv = await _new_conversation(client)
        # 실행이 끝나면 heartbeat 주기(15초)를 기다리지 않고 바로 종료 이벤트를 보낸다.
        streamed = await asyncio.wait_for(_post_sse(client, conv, "다음 주 교육 알려줘", key), 5)
        replay = await client.post(
            f"/api/v1/conversations/{conv}/messages",
            json={"content": "다음 주 교육 알려줘"},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(key)},
        )
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.headers["cache-control"] == "private, no-store"
    events = _parse(streamed.text)
    progress = [data for kind, data in events if kind == "progress"]
    assert [p["stage"] for p in progress] == [
        "accepted",
        "model_waiting",
        "training_lookup",
        "model_waiting",
        "verifying",
    ]
    assert [p["seq"] for p in progress] == [1, 2, 3, 4, 5]
    run_id = replay.json()["run_id"]
    assert all(set(p) == {"run_id", "seq", "stage"} and p["run_id"] == run_id for p in progress)
    # 종료 이벤트는 정확히 하나이고 마지막이며, 같은 키 JSON replay(200)와 본문이 같다.
    terminal = [kind for kind, _ in events if kind in ("result", "error")]
    assert terminal == ["result"] and events[-1][0] == "result"
    assert replay.status_code == 200 and events[-1][1] == replay.json()
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 1


async def test_progress_has_no_arguments_titles_counts_or_answer(seeded_engine, migrated):
    """T-04: progress에는 도구 인자·교육 제목·결과 수·답변 일부가 없다."""
    lookup = tool_turn(("list_trainings", {"date_preset": "next_week", "query": "보안"}))
    script = [lookup, final("두 건입니다")]
    async with api_client(_app(migrated, FakeModelClient(script))) as client:
        conv = await _new_conversation(client)
        streamed = await _post_sse(client, conv, "다음 주 보안 교육")
    progress_lines = [line for line in streamed.text.split("\n\n") if line.startswith("event: progress")]
    assert progress_lines
    for line in progress_lines:
        data = json.loads(line.split("data: ", 1)[1])
        assert set(data) == {"run_id", "seq", "stage"} and data["stage"] in STAGES
        for leaked in ("next_week", "보안", "정보보안", "두 건", "count", "title"):
            assert leaked not in line


async def test_running_replay_with_sse_accept_is_json_202(seeded_engine, migrated):
    model = _BlockingModel(NEXT_WEEK)
    key = uuid.uuid4()
    async with api_client(_app(migrated, model)) as client:
        conv = await _new_conversation(client)
        first = asyncio.create_task(_post_sse(client, conv, "다음 주 교육 알려줘", key))
        await asyncio.wait_for(model.started.wait(), 5)
        running = await _post_sse(client, conv, "다음 주 교육 알려줘", key)
        busy = await _post_sse(client, conv, "다른 질문")
        conflict = await _post_sse(client, conv, "다른 내용", key)
        model.release.set()
        done = await first
        finished_replay = await _post_sse(client, conv, "다음 주 교육 알려줘", key)
    # 실행 중 replay는 SSE를 다시 열지 않는다.
    assert running.status_code == 202 and running.headers["content-type"].startswith("application/json")
    assert running.json()["status"] == "running"
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "CONVERSATION_BUSY")
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "MESSAGE_IDEMPOTENCY_CONFLICT")
    assert done.headers["content-type"].startswith("text/event-stream")
    # 종료 replay도 새 스트림이 아니라 JSON 200이다(원래 입력·run을 새로 만들지 않음).
    assert finished_replay.status_code == 200
    assert finished_replay.json() == _parse(done.text)[-1][1]
    assert await _scalar(seeded_engine, "SELECT count(*) FROM agent_runs") == 1


async def test_other_users_conversation_is_same_404_without_stream(seeded_engine, migrated):
    async with api_client(_app(migrated, FakeModelClient(NEXT_WEEK))) as owner:
        conv = await _new_conversation(owner)
    async with api_client(_app(migrated, FakeModelClient([]), actor_id="test-b")) as other:
        foreign = await _post_sse(other, conv, "다음 주 교육 알려줘")
        missing = await _post_sse(other, str(uuid.uuid4()), "다음 주 교육 알려줘")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"]
    assert foreign.headers["content-type"].startswith("application/json")


async def test_failed_run_streams_one_error_envelope_with_run_id(seeded_engine, migrated):
    forged = [final("있음", ids=("11111111-1111-4111-8111-999999999999",))]
    async with api_client(_app(migrated, FakeModelClient(forged))) as client:
        conv = await _new_conversation(client)
        streamed = await _post_sse(client, conv, "다음 주 교육 알려줘")
    events = _parse(streamed.text)
    terminal = [(kind, data) for kind, data in events if kind in ("result", "error")]
    assert len(terminal) == 1 and terminal[0][0] == "error" and events[-1][0] == "error"
    envelope = terminal[0][1]
    assert envelope["error"]["code"] == "MODEL_OUTPUT_INVALID"
    assert envelope["run_id"] == next(d for k, d in events if k == "progress")["run_id"]
    assert set(envelope) == {"error", "request_id", "run_id"}


async def test_disconnect_does_not_cancel_run(seeded_engine, migrated):
    """T-02: 스트림을 중간에 닫아도(연결 끊김) 실행·완료 commit은 계속된다. 이후 replay로 결과를 받는다."""
    model = _BlockingModel(NEXT_WEEK)
    app = _app(migrated, model)
    key = uuid.uuid4()
    async with api_client(app) as client:
        conv = await _new_conversation(client)
        service = app.state.conversations
        actor = await app.state.current_actor.resolve(None)
        events = await service.stream_message(actor, uuid.UUID(conv), "다음 주 교육 알려줘", key, "req-1")
        first = await anext(events)
        await asyncio.wait_for(model.started.wait(), 5)
        await events.aclose()  # 클라이언트가 떠남
        model.release.set()
        await service.drain()
        replay = await client.post(
            f"/api/v1/conversations/{conv}/messages",
            json={"content": "다음 주 교육 알려줘"},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(key)},
        )
    assert first == ("progress", {"run_id": first[1]["run_id"], "seq": 1, "stage": "accepted"})
    assert replay.status_code == 200 and replay.json()["answer"] == "두 건입니다"
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "completed"
    assert await _scalar(seeded_engine, "SELECT count(*) FROM messages WHERE role = 'assistant'") == 1


async def test_heartbeat_while_waiting(seeded_engine, migrated):
    model = _BlockingModel(NEXT_WEEK)
    app = _app(migrated, model)
    async with api_client(app) as client:
        conv = await _new_conversation(client)
        service = app.state.conversations
        service._heartbeat_s = 0.02
        actor = await app.state.current_actor.resolve(None)
        events = await service.stream_message(actor, uuid.UUID(conv), "다음 주 교육", uuid.uuid4(), "req-1")
        seen = []
        async for kind, _payload in events:
            seen.append(kind)
            if kind == "heartbeat":
                model.release.set()
        await service.drain()
    assert "heartbeat" in seen and seen[-1] == "result" and seen.count("result") == 1
    chunks = [chunk async for chunk in _sse(_events([("heartbeat", None)]), "req-1")]
    assert chunks == [": heartbeat\n\n"]


async def _events(items):
    for item in items:
        yield item


async def test_expired_run_streams_timeout_error_and_no_late_progress(seeded_engine, migrated):
    """T-02: 실행 시간 초과로 만료된 run은 RUN_TIMEOUT 오류 하나로 끝나고, 만료 뒤 단계는 보내지 않는다."""
    model = _BlockingModel(NEXT_WEEK)
    app = _app(migrated, model)
    async with api_client(app) as client:
        conv = await _new_conversation(client)
        service = app.state.conversations
        service._policy = ExecutionPolicy(run_timeout_s=0.2)
        streamed = await _post_sse(client, conv, "다음 주 교육 알려줘")
    events = _parse(streamed.text)
    assert [d["stage"] for k, d in events if k == "progress"] == ["accepted", "model_waiting"]
    assert events[-1][0] == "error" and events[-1][1]["error"]["code"] == "RUN_TIMEOUT"
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "expired"


def test_channel_drops_stages_after_deadline_or_close():
    clock = FixedClock()
    progress = RunProgress(clock)
    channel = progress.open("r1", deadline_monotonic=10.0)
    progress.publish("r1", ProgressStage.ACCEPTED)
    progress.publish("other-run", ProgressStage.MODEL_WAITING)  # 열린 채널이 없는 run은 버린다
    clock.advance(10.0)
    progress.publish("r1", ProgressStage.MODEL_WAITING)  # deadline 뒤: 버림
    assert channel.queue.qsize() == 1
    clock2 = FixedClock()
    progress2 = RunProgress(clock2)
    channel2 = progress2.open("r2", deadline_monotonic=10.0)
    progress2.close("r2")
    progress2.publish("r2", ProgressStage.VERIFYING)  # 종료 저장 뒤: 버림
    assert channel2.queue.qsize() == 0


def test_accept_header_detection():
    assert _wants_stream("text/event-stream")
    assert _wants_stream("application/json, text/event-stream;q=0.9")
    assert not _wants_stream(None)
    assert not _wants_stream("application/json")
    assert not _wants_stream("text/event-streamx")
    assert not _wants_stream("text/event-stream;q=0, application/json")
    assert not _wants_stream("text/event-stream; q=0.0")
    assert not _wants_stream("text/event-stream;q=abc")
    assert _wants_stream("TEXT/EVENT-STREAM; Q=0.5")


def test_error_payload_must_be_app_error():
    error = AppError(ErrorCode.RUN_TIMEOUT, run_id="r1")
    chunks = asyncio.run(_collect(_sse(_events([("error", error)]), "req-9")))
    assert chunks[0].startswith("event: error\ndata: ")
    assert json.loads(chunks[0].split("data: ", 1)[1].strip())["run_id"] == "r1"


async def _collect(gen):
    return [chunk async for chunk in gen]


async def test_final_commit_failure_streams_error_not_result(seeded_engine, migrated, monkeypatch):
    """T-03과 같은 규칙: 최종 commit이 실패하면 result가 아니라 PERSISTENCE_FAILED 오류 하나로 끝난다."""

    async def broken(self, *args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("commit lost"))

    monkeypatch.setattr(ConversationService, "_complete", broken)
    async with api_client(_app(migrated, FakeModelClient([final("답")]))) as client:
        conv = await _new_conversation(client)
        streamed = await _post_sse(client, conv, "안녕")
    events = _parse(streamed.text)
    terminal = [(kind, data) for kind, data in events if kind in ("result", "error")]
    assert len(terminal) == 1 and terminal[0][0] == "error"
    assert terminal[0][1]["error"]["code"] == "PERSISTENCE_FAILED" and terminal[0][1]["run_id"]


async def test_stage_record_failure_does_not_fail_run(seeded_engine, migrated, monkeypatch):
    """진행 단계는 필수 기록이 아니다. 기록이 실패해도 실행은 정상 완료된다."""

    async def broken(self, run_id, stage):
        raise RuntimeError("progress down")

    monkeypatch.setattr(DbExecutionObserver, "record_stage", broken)
    async with api_client(_app(migrated, FakeModelClient(NEXT_WEEK))) as client:
        conv = await _new_conversation(client)
        streamed = await _post_sse(client, conv, "다음 주 교육 알려줘")
    events = _parse(streamed.text)
    # accepted는 MOD-01이 직접 남긴다. 실행 중 단계는 기록 실패로 빠지고 결과는 정상이다.
    assert [d["stage"] for k, d in events if k == "progress"] == ["accepted"]
    assert events[-1][0] == "result" and events[-1][1]["answer"] == "두 건입니다"


async def test_unconsumed_stream_channel_is_closed_after_run(seeded_engine, migrated):
    """스트림을 읽지 않아도(응답 전송 전 끊김) 실행이 끝나면 채널을 닫는다. 늦은 단계가 쌓이지 않는다."""
    model = _BlockingModel(NEXT_WEEK)
    app = _app(migrated, model)
    async with api_client(app) as client:
        conv = await _new_conversation(client)
        service = app.state.conversations
        actor = await app.state.current_actor.resolve(None)
        events = await service.stream_message(actor, uuid.UUID(conv), "다음 주 교육", uuid.uuid4(), "req-1")
        await asyncio.wait_for(model.started.wait(), 5)
        assert service._progress._channels  # 실행 중에는 열려 있다
        model.release.set()
        await service.drain()
        assert service._progress._channels == {}
        await events.aclose()


async def test_progress_events_drains_stages_recorded_before_completion():
    clock = FixedClock()
    progress = RunProgress(clock)
    channel = progress.open("r1", deadline_monotonic=10.0)
    for stage in (ProgressStage.ACCEPTED, ProgressStage.MODEL_WAITING, ProgressStage.VERIFYING):
        progress.publish("r1", stage)

    async def done():
        return True

    task = asyncio.create_task(done())
    await task
    seen = [event["stage"] async for event in progress_events(channel, task, heartbeat_s=1.0)]
    assert seen == ["accepted", "model_waiting", "verifying"]


async def test_unexpected_finalize_error_ends_both_paths_with_one_error_and_run_id(
    seeded_engine, migrated, monkeypatch
):
    """종료 저장 중 예상 밖 예외: SSE도 오류 이벤트 하나로 끝나고, JSON과 같은 run_id 붙은 오류다."""

    async def broken(self, *args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(ConversationService, "_complete", broken)
    async with api_client(_app(migrated, FakeModelClient([final("답"), final("답")]))) as client:
        conv = await _new_conversation(client)
        streamed = await _post_sse(client, conv, "안녕")
        other = await _new_conversation(client)
        plain = await client.post(
            f"/api/v1/conversations/{other}/messages",
            json={"content": "안녕"},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid.uuid4())},
        )
    events = _parse(streamed.text)
    assert events[-1][0] == "error" and [k for k, _ in events].count("error") == 1
    assert events[-1][1]["error"]["code"] == plain.json()["error"]["code"] == "PERSISTENCE_FAILED"
    assert events[-1][1]["run_id"] and plain.json()["run_id"]


async def test_stage_after_heartbeat_is_not_lost():
    """heartbeat 뒤 남은 대기(getter)가 다음 단계를 가로채지 않는다."""
    progress = RunProgress(FixedClock())
    channel = progress.open("r1", deadline_monotonic=10.0)
    task = asyncio.ensure_future(asyncio.get_running_loop().create_future())
    events = progress_events(channel, task, heartbeat_s=0.01)
    assert await anext(events) is None
    progress.publish("r1", ProgressStage.MODEL_WAITING)
    assert (await anext(events))["stage"] == "model_waiting"
    await events.aclose()
    task.cancel()


async def test_real_asgi_disconnect_during_wait_does_not_cancel_run(seeded_engine, migrated):
    """T-02: 서버(ASGI 2.3)가 http.disconnect를 받아 스트림을 취소해도 실행은 끝까지 간다."""
    model = _BlockingModel(NEXT_WEEK)
    app = _app(migrated, model)
    key = uuid.uuid4()
    async with api_client(app) as client:
        conv = await _new_conversation(client)
        body = json.dumps({"content": "다음 주 교육 알려줘"}).encode()
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await model.started.wait()  # 모델 대기 중에 연결이 끊긴다
            return {"type": "http.disconnect"}

        sent = []

        async def send(message):
            sent.append(message)

        path = f"/api/v1/conversations/{conv}/messages"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"origin", ORIGIN.encode()),
                (b"content-type", b"application/json"),
                (b"accept", b"text/event-stream"),
                (b"idempotency-key", str(key).encode()),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
            "state": {},
        }
        await asyncio.wait_for(app(scope, receive, send), 5)
        model.release.set()
        await app.state.conversations.drain()
        replay = await client.post(
            path,
            json={"content": "다음 주 교육 알려줘"},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(key)},
        )
    streamed = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    assert "event: progress" in streamed and "event: result" not in streamed
    assert replay.status_code == 200 and replay.json()["answer"] == "두 건입니다"
    assert await _scalar(seeded_engine, "SELECT status FROM agent_runs") == "completed"
