"""CT-11 메모리 observer(M1). M2에서 MOD-01 영속 구현으로 같은 포트를 교체한다."""

from agent.shared.contracts import ProgressStage, ToolCallRecord, TrainingResultReceipt


class InMemoryObserver:
    """(run_id, ordinal[, attempt])로 멱등 기록한다. 같은 키의 재기록은 덮어쓰지 않는다."""

    def __init__(self) -> None:
        self.tool_calls: dict[tuple[str, int, int], ToolCallRecord] = {}
        self.training_results: dict[tuple[str, int], TrainingResultReceipt] = {}
        self.stages: list[tuple[str, ProgressStage]] = []

    async def record_tool_call(self, record: ToolCallRecord) -> None:
        self.tool_calls.setdefault((record.run_id, record.ordinal, record.attempt), record)

    async def record_training_result(self, receipt: TrainingResultReceipt) -> None:
        self.training_results.setdefault((receipt.run_id, receipt.ordinal), receipt)

    async def record_stage(self, run_id: str, stage: ProgressStage) -> None:
        self.stages.append((run_id, stage))
