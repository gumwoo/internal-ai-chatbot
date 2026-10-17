"""근거·PDF HTTP(docs/04-api-spec.md 근거·PDF — MOD-05). 매 요청 현재 ACL을 다시 확인한다.

미존재·접근 불가·철회는 같은 404. 응답은 Cache-Control: private, no-store이며 공개 정적 경로를 쓰지 않는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from agent.app.deps import current_actor
from agent.shared.actor import ActorContext

router = APIRouter(tags=["evidence"])
Actor = Annotated[ActorContext, Depends(current_actor)]
_NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/evidence/{passage_id}")
async def get_evidence(request: Request, actor: Actor, passage_id: str) -> JSONResponse:
    passage = await request.app.state.knowledge.get_evidence(actor, passage_id)
    body = {
        "passage_id": passage.passage_id,
        "document_key": passage.document_key,
        "source_file_id": passage.source_file_id,
        "title": passage.title,
        "version": passage.version,
        "document_role": passage.document_role,
        "edition_state": passage.edition_state,
        "available_from": passage.available_from.isoformat(),
        "effective_from": passage.effective_from.isoformat() if passage.effective_from else None,
        "effective_to": passage.effective_to.isoformat() if passage.effective_to else None,
        "heading": passage.heading,
        "section_path": list(passage.section_path),
        "text": passage.text,
        "page_spans": list(passage.page_spans),
        "pdf_url": f"/api/v1/source-files/{passage.source_file_id}/pdf",
    }
    return JSONResponse(body, headers=_NO_STORE)


@router.get("/source-files/{source_file_id}/pdf")
async def get_source_pdf(request: Request, actor: Actor, source_file_id: str) -> FileResponse:
    path = await request.app.state.knowledge.open_source_pdf(actor, source_file_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={**_NO_STORE, "Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )
