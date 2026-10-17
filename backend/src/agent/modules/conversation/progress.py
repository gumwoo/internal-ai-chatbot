"""StreamRunProgress(MOD-01): 실행 중인 run의 진행 단계를 같은 프로세스의 SSE 응답에 넘긴다.

- 채널은 SSE로 수락한 run에만 열린다. 열린 채널이 없으면 단계는 버린다(JSON 요청·replay).
- 채널에는 run_id·seq·stage만 담는다. 인자·제목·결과 수·답변 일부는 받지도 않는다(T-04).
- deadline이 지났거나 종료 저장 뒤 닫힌 채널에는 늦은 단계를 넣지 않는다(T-02).
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from agent.shared.clock import Clock
from agent.shared.contracts import ProgressStage


@dataclass
class _Channel:
    run_id: str
    deadline_monotonic: float
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    seq: int = 0
    closed: bool = False


class RunProgress:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._channels: dict[str, _Channel] = {}

    def open(self, run_id: str, deadline_monotonic: float) -> _Channel:
        channel = _Channel(run_id, deadline_monotonic)
        self._channels[run_id] = channel
        return channel

    def publish(self, run_id: str, stage: ProgressStage) -> None:
        channel = self._channels.get(run_id)
        if channel is None or channel.closed or self._clock.monotonic() >= channel.deadline_monotonic:
            return
        channel.seq += 1
        channel.queue.put_nowait({"run_id": run_id, "seq": channel.seq, "stage": ProgressStage(stage).value})

    def close(self, run_id: str) -> None:
        """종료 저장을 마쳤거나 구독자가 떠났다. 이후 단계는 받지 않는다."""
        channel = self._channels.pop(run_id, None)
        if channel is not None:
            channel.closed = True


async def progress_events(
    channel: _Channel, task: asyncio.Task, heartbeat_s: float
) -> AsyncIterator[dict[str, Any] | None]:
    """task가 끝날 때까지 진행 이벤트를 내보낸다. heartbeat_s 동안 이벤트가 없으면 None(heartbeat)을 낸다.

    호출자가 중간에 그만둬도(연결 끊김) task는 취소하지 않는다. 끝난 뒤 큐에 남은 단계는 종료 저장 전에
    기록된 것이라 모두 내보낸다.
    """
    while not task.done():
        getter = asyncio.ensure_future(channel.queue.get())
        try:
            done, _ = await asyncio.wait(
                {getter, task}, timeout=heartbeat_s, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            if not getter.done():
                getter.cancel()
        if getter in done:
            yield getter.result()
        elif not done:
            yield None
    while not channel.queue.empty():
        yield channel.queue.get_nowait()
