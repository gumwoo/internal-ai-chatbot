"""GET /trainings, /trainings/{id}(docs/04-api-spec.md). 도구와 같은 MOD-04 작업을 호출한다."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from agent.app.deps import require_capability
from agent.modules.training.models import TrainingDetail, TrainingPage, TrainingSearchInput
from agent.shared.actor import ActorContext

router = APIRouter(prefix="/trainings", tags=["trainings"])

TrainingReader = Annotated[ActorContext, Depends(require_capability("training.read"))]


@router.get("", response_model=TrainingPage)
async def list_trainings(
    request: Request, _actor: TrainingReader, search: Annotated[TrainingSearchInput, Query()]
) -> TrainingPage:
    app = request.app
    return await app.state.training_service.list_trainings(search, app.state.clock.now())


@router.get("/{training_id}", response_model=TrainingDetail)
async def get_training(request: Request, _actor: TrainingReader, training_id: UUID) -> TrainingDetail:
    return await request.app.state.training_service.get_training(training_id)
