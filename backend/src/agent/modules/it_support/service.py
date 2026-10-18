"""MOD-12 공개 작업: ListTickets/GetTicket, PrepareTicket, GetAction, ReviseAction, ConfirmAction,
CancelAction, CheckTicketVisibility(docs/14-ticket-workflow.md, docs/modules/MOD-12-it-support.md).

핵심 규칙
- 인증·소유권부터 본다. 미존재·불허는 같은 404. 그 뒤 version·입력·멱등키를 본다.
- Agent prepare는 draft만 만들고 head를 바꾸지 않는다. UI revise만 새 pending과 head 교체를 만든다.
- revise·confirm·cancel은 대화별 head 행(ticket_action_heads, conversation_id UNIQUE)을 잠근 한 트랜잭션에서
  상태 검사·새 action·head 교체·감사·멱등 기록을 함께 commit한다. 실패하면 이전 상태가 그대로다.
- 만료는 lazy다(expires_at과 같은 clock). head_revision은 성공한 revise·confirm·현재 pending cancel마다만
  오른다.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Text, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.modules.identity_access.service import IdentityService
from agent.modules.it_support.contracts import (
    FIELD_NAMES,
    RunEligibility,
    TicketFields,
    UserEvidenceReader,
)
from agent.modules.it_support.tables import (
    idempotency_records,
    support_scopes,
    ticket_action_heads,
    ticket_actions,
    ticket_audit,
    ticket_prepare_receipts,
    tickets,
)
from agent.shared.actor import ActorContext
from agent.shared.clock import KST, Clock
from agent.shared.errors import AppError, ErrorCode
from agent.shared.ticket_origins import TEMPLATES, allowed_normalizations, normalize

logger = logging.getLogger(__name__)

ACTION_TTL = timedelta(minutes=5)
_LIVE = ("draft", "pending")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _not_found() -> AppError:
    return AppError(ErrorCode.RESOURCE_NOT_FOUND)


def _invalid(code: ErrorCode, fields: list[str]) -> AppError:
    return AppError(code, details={"field_names": sorted(set(fields))})


@dataclass(frozen=True)
class Outcome:
    status_code: int
    body: dict[str, Any]


class TicketService:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        identity: IdentityService,
        eligibility: RunEligibility,
        evidence: UserEvidenceReader,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._identity = identity
        self._eligibility = eligibility
        self._evidence = evidence

    # --- 조회(T-30) ---

    def _visible_clause(self, actor: ActorContext, scope: list[str]):
        """본인 티켓, 지원 범위 부서 요청자 티켓(ticket.read_support_scope), 전사(ticket.read_all)."""
        if "ticket.read_all" in actor.capabilities:
            return None
        clauses = []
        if "ticket.read_own" in actor.capabilities:
            clauses.append(tickets.c.requester_id == actor.user_id)
        if "ticket.read_support_scope" in actor.capabilities and scope:
            clauses.append(tickets.c.requester_department_ids.op("?|")(literal(scope, type_=ARRAY(Text))))
        return or_(*clauses) if clauses else False

    async def _scope(self, conn: AsyncConnection, actor: ActorContext) -> list[str]:
        if "ticket.read_support_scope" not in actor.capabilities:
            return []
        value = await conn.scalar(
            select(support_scopes.c.department_ids).where(support_scopes.c.user_id == actor.user_id)
        )
        return list(value or [])  # 빈 목록은 거부(D-41 데모 지원 범위)

    async def list_tickets(
        self, actor: ActorContext, *, status: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        async with self._engine.connect() as conn:
            clause = self._visible_clause(actor, await self._scope(conn, actor))
            query = select(tickets)
            if clause is not None:
                query = query.where(clause)
            if status is not None:
                query = query.where(tickets.c.status == status)
            total = await conn.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await conn.execute(
                    query.order_by(tickets.c.created_at.desc(), tickets.c.id).limit(limit).offset(offset)
                )
            ).all()
        return {
            "items": [_ticket(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(rows) < total,
        }

    async def get_ticket(self, actor: ActorContext, ticket_id: str) -> dict[str, Any]:
        try:
            ticket_uuid = UUID(ticket_id)
        except ValueError:
            raise _not_found() from None
        async with self._engine.connect() as conn:
            clause = self._visible_clause(actor, await self._scope(conn, actor))
            query = select(tickets).where(tickets.c.id == ticket_uuid)
            if clause is not None:
                query = query.where(clause)
            row = (await conn.execute(query)).first()
        if row is None:
            raise _not_found()
        return _ticket(row)

    async def visible_ticket_ids(self, actor: ActorContext, ids: set[str]) -> set[str]:
        """CP-05 CheckTicketVisibility: 이력·최종 응답의 티켓 참조를 지금 볼 수 있는가."""
        uuids = []
        for value in ids:
            try:
                uuids.append(UUID(value))
            except ValueError:
                continue
        if not uuids:
            return set()
        async with self._engine.connect() as conn:
            clause = self._visible_clause(actor, await self._scope(conn, actor))
            query = select(tickets.c.id).where(tickets.c.id.in_(uuids))
            if clause is not None:
                query = query.where(clause)
            return {str(r) for r in (await conn.scalars(query)).all()}

    # --- 준비(T-31) ---

    async def prepare(
        self,
        actor: ActorContext,
        *,
        conversation_id: str,
        run_id: str,
        ordinal: int,
        fields: dict[str, Any],
        field_origins: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if "ticket.prepare" not in actor.capabilities:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        if not await self._eligibility.check_prepare(actor.user_id, conversation_id, run_id):
            raise AppError(ErrorCode.RUN_NOT_ELIGIBLE)
        try:
            parsed = TicketFields.model_validate(fields)
        except ValidationError as exc:
            raise _invalid(
                ErrorCode.TOOL_ARGUMENT_INVALID, [str(e["loc"][0]) for e in exc.errors() if e["loc"]]
            ) from exc
        now = self._clock.now()
        rejected = await self._verify_origins(
            actor, conversation_id, run_id, parsed, field_origins, now.astimezone(KST).date()
        )
        if parsed.occurred_at is not None and parsed.occurred_at > now:
            rejected.add("occurred_at")  # 발생 시각은 과거다
        # D-43: 출처를 확인하지 못한 필드는 저장하지 않고 비운다(사용자 입력만 저장).
        # 초안 전체는 거절하지 않는다.
        parsed = TicketFields.model_validate(
            {k: v for k, v in parsed.model_dump().items() if k not in rejected and v is not None}
        )
        kept = {name for name in FIELD_NAMES if getattr(parsed, name) is not None}
        seen: set[str] = set()
        field_origins = [
            o
            for o in field_origins
            if o.get("field") in kept and not (o["field"] in seen or seen.add(o["field"]))
        ]
        reply = await self._identity.reply_channel(actor.user_id)
        if not reply:
            # 서버 프로필의 회신 수단이 없으면 준비할 수 없다(03-received-pdf-adjustments).
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        payload = parsed.payload()
        digest = _hash(payload)
        if not await self._eligibility.check_prepare(actor.user_id, conversation_id, run_id):
            raise AppError(ErrorCode.RUN_NOT_ELIGIBLE)  # 저장 직전에도 활성 run인지 다시 본다
        async with self._engine.begin() as conn:
            receipt = (
                await conn.execute(
                    select(ticket_prepare_receipts).where(
                        ticket_prepare_receipts.c.run_id == UUID(run_id),
                        ticket_prepare_receipts.c.ordinal == ordinal,
                    )
                )
            ).first()
            if receipt is not None:
                if receipt.payload_hash != digest:
                    raise AppError(ErrorCode.PREPARE_PAYLOAD_CONFLICT)
                return {
                    **await self._preview(conn, actor, receipt.draft_id, now),
                    "rejected_fields": sorted(rejected),
                }
            head = (
                await conn.execute(
                    select(ticket_action_heads).where(
                        ticket_action_heads.c.conversation_id == UUID(conversation_id)
                    )
                )
            ).first()
            if head is not None and head.head_action_id is not None:
                head_status = await conn.scalar(
                    select(ticket_actions.c.status).where(ticket_actions.c.id == head.head_action_id)
                )
                if head_status == "confirmed":
                    raise AppError(ErrorCode.ACTION_ALREADY_CONFIRMED)
            draft_id = uuid.uuid4()
            await conn.execute(
                ticket_actions.insert().values(
                    id=draft_id,
                    actor_id=actor.user_id,
                    conversation_id=UUID(conversation_id),
                    initiating_run_id=UUID(run_id),
                    origin="agent_prepare",
                    status="draft",
                    version=1,
                    payload=payload,
                    payload_hash=digest,
                    missing_fields=parsed.missing_fields(),
                    field_origins=field_origins,
                    expected_head_id=head.head_action_id if head else None,
                    expected_head_revision=head.head_revision if head else 0,
                    root_action_id=draft_id,
                    expires_at=now + ACTION_TTL,
                    created_at=now,
                    updated_at=now,
                )
            )
            await conn.execute(
                ticket_prepare_receipts.insert().values(
                    run_id=UUID(run_id), ordinal=ordinal, payload_hash=digest, draft_id=draft_id
                )
            )
            await _audit(
                conn,
                draft_id,
                actor.user_id,
                "prepared",
                {"run_id": run_id, "ordinal": ordinal, "rejected_fields": sorted(rejected)},
                now,
            )
            # rejected_fields: 출처를 확인하지 못해 비운 필드(모델이 사용자에게 다시 물어볼 대상).
            return {**await self._preview(conn, actor, draft_id, now), "rejected_fields": sorted(rejected)}

    async def _verify_origins(
        self,
        actor: ActorContext,
        conversation_id: str,
        run_id: str,
        fields: TicketFields,
        origins: list[dict[str, Any]],
        today: date,
    ) -> set[str]:
        """CP-07로 본인·run 문맥 user 원문을 읽어 field_origins의 구간·정규화·값을 다시 확인한다.

        확인하지 못한 필드 이름을 돌려준다(출처 없음·중복 출처·구간/정규화/값 불일치). 남는 출처는 무시한다.
        """
        by_field: dict[str, dict[str, Any]] = {}
        bad: list[str] = []
        for origin in origins:
            name = origin.get("field")
            if name in by_field or name not in FIELD_NAMES:
                bad.append(str(name))
            by_field[str(name)] = origin
        present = [name for name in FIELD_NAMES if getattr(fields, name) is not None]
        quote_ids = {
            str(o.get("source_message_id"))
            for o in by_field.values()
            if o.get("kind") == "user_quote" and o.get("source_message_id")
        }
        texts = (
            await self._evidence.read_user_messages(actor.user_id, conversation_id, run_id, quote_ids)
            if quote_ids
            else {}
        )
        for name in present:
            origin = by_field.get(name)
            value = getattr(fields, name)
            if origin is None:
                bad.append(name)
                continue
            if origin.get("kind") == "template":
                template = TEMPLATES.get(str(origin.get("template_id")))
                if template is None or template[0] != name or value != template[1]:
                    bad.append(name)
                continue
            normalization = origin.get("normalization")
            text = texts.get(str(origin.get("source_message_id")))
            start, end = origin.get("span_start"), origin.get("span_end")
            if (
                origin.get("kind") != "user_quote"
                or normalization not in allowed_normalizations(name)
                or text is None
                or not isinstance(start, int)
                or not isinstance(end, int)
                or not 0 <= start < end <= len(text)
            ):
                bad.append(name)
                continue
            try:
                expected = normalize(name, normalization, text[start:end], today)
            except ValueError:
                bad.append(name)
                continue
            actual = value.isoformat() if isinstance(value, datetime) else value
            if expected != actual:
                bad.append(name)
        return {name for name in bad if name in FIELD_NAMES}

    # --- 조회·수정·확인·취소(T-31~33) ---

    async def get_action(self, actor: ActorContext, action_id: str) -> dict[str, Any]:
        if not {"ticket.prepare", "ticket.submit"} & actor.capabilities:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        action_uuid = _uuid_or_404(action_id)
        async with self._engine.connect() as conn:
            row = await self._owned_action(conn, actor, action_uuid)
        # 채택되지 않은 draft(실패·만료 run, 답이 가리키지 않은 초안)는 화면에 공개하지 않는다.
        if row.origin == "agent_prepare" and not await self._eligibility.adopted(
            actor.user_id, str(row.conversation_id), str(row.initiating_run_id), str(row.root_action_id)
        ):
            raise _not_found()
        async with self._engine.begin() as conn:
            row = await self._owned_action(conn, actor, action_uuid)
            now = self._clock.now()
            await self._lazy_expire(conn, row, now)
            return await self._preview(conn, actor, action_uuid, now)

    async def revise(
        self, actor: ActorContext, action_id: str, *, version: int, fields: dict[str, Any], key: UUID
    ) -> Outcome:
        self._require_submit(actor)
        action_uuid = _uuid_or_404(action_id)
        request_hash = _hash({"version": version, "fields": fields})
        async with self._engine.connect() as conn:
            row = await self._owned_action(conn, actor, action_uuid)
        if version != row.version:
            raise AppError(ErrorCode.ACTION_VERSION_CONFLICT)
        try:
            parsed = TicketFields.model_validate(fields)
        except ValidationError as exc:
            raise _invalid(
                ErrorCode.INVALID_REQUEST, [str(e["loc"][0]) for e in exc.errors() if e["loc"]]
            ) from exc
        missing = parsed.missing_fields()
        if missing:
            raise _invalid(ErrorCode.INVALID_REQUEST, missing)
        async with self._engine.connect() as conn:
            replay = await self._replay(conn, actor, key, "revise", action_uuid, request_hash)
            if replay is not None:
                return Outcome(200, await self._preview(conn, actor, replay, self._clock.now()))
            await self._precheck(conn, row, "revise", self._clock.now())
        await self._require_adopted(actor, row)
        reply = await self._identity.reply_channel(actor.user_id)
        if not reply:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        payload = parsed.payload()
        try:
            async with self._engine.begin() as conn:
                head = await self._lock_head(conn, actor, row.conversation_id)
                # 잠금 안에서 한 번 더: 같은 키가 동시에 왔으면 먼저 끝난 결과를 돌려준다(성공 replay 우선).
                replay = await self._replay(conn, actor, key, "revise", action_uuid, request_hash)
                if replay is not None:
                    return Outcome(200, await self._preview(conn, actor, replay, self._clock.now()))
                now = self._clock.now()
                current = await self._locked_action(conn, action_uuid)
                await self._lazy_expire(conn, current, now)
                current = await self._locked_action(conn, action_uuid)
                head_status = await self._status_of(conn, head.head_action_id)
                await self._precheck(conn, current, "revise", now)
                if head_status == "confirmed":
                    raise AppError(ErrorCode.ACTION_ALREADY_CONFIRMED)
                if current.status == "draft" and (
                    current.expected_head_id,
                    current.expected_head_revision,
                ) != (
                    head.head_action_id,
                    head.head_revision,
                ):
                    raise self._conflict(
                        ErrorCode.ACTION_HEAD_CONFLICT, head.head_action_id, head.head_revision
                    )
                if current.status == "pending" and head.head_action_id != current.id:
                    raise self._conflict(ErrorCode.ACTION_SUPERSEDED, head.head_action_id, head.head_revision)
                new_id = uuid.uuid4()
                displaced = head.head_action_id if head.head_action_id not in (None, current.id) else None
                await conn.execute(
                    ticket_actions.insert().values(
                        id=new_id,
                        actor_id=actor.user_id,
                        conversation_id=current.conversation_id,
                        initiating_run_id=current.initiating_run_id,
                        origin="ui_revise",
                        status="pending",
                        version=1,
                        payload=payload,
                        payload_hash=_hash(payload),
                        missing_fields=[],
                        field_origins=[
                            {
                                "field": name,
                                "kind": "user_input",
                                "actor_id": actor.user_id,
                                "at": now.isoformat(),
                            }
                            for name in FIELD_NAMES
                            if getattr(parsed, name) is not None
                        ],
                        expected_head_id=head.head_action_id,
                        expected_head_revision=head.head_revision,
                        root_action_id=current.root_action_id,
                        prepared_from_action_id=current.id,
                        displaced_head_id=displaced,
                        expires_at=now + ACTION_TTL,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await conn.execute(
                    update(ticket_actions)
                    .where(ticket_actions.c.id == current.id)
                    .values(status="superseded", superseded_by_action_id=new_id, updated_at=now)
                )
                if displaced is not None and head_status == "pending":
                    # 밀려난 이전 pending도 superseded. cancelled·expired head는 상태를 바꾸지 않는다.
                    await conn.execute(
                        update(ticket_actions)
                        .where(ticket_actions.c.id == displaced)
                        .values(status="superseded", superseded_by_action_id=new_id, updated_at=now)
                    )
                await self._bump_head(conn, current.conversation_id, new_id)
                await self._remember(conn, actor, key, "revise", action_uuid, request_hash, new_id, 201, now)
                await _audit(
                    conn,
                    new_id,
                    actor.user_id,
                    "revised",
                    {
                        "from": str(current.id),
                        "displaced": str(displaced) if displaced else None,
                        "before": current.payload,
                        "after": payload,
                    },
                    now,
                )
                return Outcome(201, await self._preview(conn, actor, new_id, now))
        except IntegrityError:
            # 같은 키가 동시에 왔다. 먼저 commit된 결과를 그대로 돌려준다.
            return await self._replay_after_race(actor, key, "revise", action_uuid, request_hash)

    async def confirm(self, actor: ActorContext, action_id: str, *, version: int, key: UUID) -> Outcome:
        self._require_submit(actor)
        action_uuid = _uuid_or_404(action_id)
        request_hash = _hash({"version": version})
        async with self._engine.connect() as conn:
            row = await self._owned_action(conn, actor, action_uuid)
        if version != row.version:
            raise AppError(ErrorCode.ACTION_VERSION_CONFLICT)
        async with self._engine.connect() as conn:
            replay = await self._replay(conn, actor, key, "confirm", action_uuid, request_hash)
            if replay is not None:
                return Outcome(200, await self._confirmation(conn, actor, replay, recheck=True))
            if await self._precheck(conn, row, "confirm", self._clock.now()) == "converge":
                return Outcome(200, await self._confirmation(conn, actor, action_uuid, recheck=True))
        await self._require_adopted(actor, row)
        try:
            async with self._engine.begin() as conn:
                head = await self._lock_head(conn, actor, row.conversation_id)
                now = self._clock.now()
                current = await self._locked_action(conn, action_uuid)
                if current.status == "confirmed":
                    # 다른 키의 반복 확인도 같은 ticket으로 수렴한다(현재 열람 권한 확인 뒤).
                    await self._remember(
                        conn, actor, key, "confirm", action_uuid, request_hash, action_uuid, 200, now
                    )
                    return Outcome(200, await self._confirmation(conn, actor, action_uuid, recheck=True))
                await self._lazy_expire(conn, current, now)
                current = await self._locked_action(conn, action_uuid)
                await self._precheck(conn, current, "confirm", now)
                if head.head_action_id != current.id:
                    raise self._conflict(ErrorCode.ACTION_SUPERSEDED, head.head_action_id, head.head_revision)
                ticket_id = uuid.uuid4()
                payload = current.payload
                reply = await self._identity.reply_channel(actor.user_id)
                if not reply:
                    raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
                await conn.execute(
                    tickets.insert().values(
                        id=ticket_id,
                        action_id=current.id,
                        requester_id=actor.user_id,
                        requester_department_ids=list(actor.department_ids),
                        subject=payload["subject"],
                        description=payload["description"],
                        request_type=payload["request_type"],
                        category=payload["category"],
                        target_service=payload["target_service"],
                        occurred_at=datetime.fromisoformat(payload["occurred_at"])
                        if payload.get("occurred_at")
                        else None,
                        impact_scope=payload.get("impact_scope"),
                        urgent_work=bool(payload["urgent_work"]),
                        urgency_reason=payload.get("urgency_reason"),
                        asset_identifier=payload.get("asset_identifier"),
                        reply_channel=reply,
                        status="open",
                        created_at=now,
                    )
                )
                await conn.execute(
                    update(ticket_actions)
                    .where(ticket_actions.c.id == current.id)
                    .values(status="confirmed", ticket_id=ticket_id, updated_at=now)
                )
                await self._bump_head(conn, current.conversation_id, current.id)
                await self._remember(
                    conn, actor, key, "confirm", action_uuid, request_hash, action_uuid, 201, now
                )
                await _audit(conn, current.id, actor.user_id, "confirmed", {"ticket_id": str(ticket_id)}, now)
                return Outcome(201, await self._confirmation(conn, actor, action_uuid))
        except IntegrityError:
            return await self._replay_after_race(actor, key, "confirm", action_uuid, request_hash)

    async def cancel(self, actor: ActorContext, action_id: str, *, version: int) -> Outcome:
        self._require_submit(actor)
        action_uuid = _uuid_or_404(action_id)
        async with self._engine.connect() as conn:
            row = await self._owned_action(conn, actor, action_uuid)
        if version != row.version:
            raise AppError(ErrorCode.ACTION_VERSION_CONFLICT)
        async with self._engine.begin() as conn:
            head = await self._lock_head(conn, actor, row.conversation_id)
            now = self._clock.now()
            current = await self._locked_action(conn, action_uuid)
            await self._lazy_expire(conn, current, now)
            current = await self._locked_action(conn, action_uuid)
            if await self._precheck(conn, current, "cancel", now) == "repeat":
                return Outcome(200, await self._preview(conn, actor, action_uuid, now))
            await conn.execute(
                update(ticket_actions)
                .where(ticket_actions.c.id == current.id)
                .values(status="cancelled", updated_at=now)
            )
            if head.head_action_id == current.id:
                # 현재 pending 취소: head ID는 그대로 두고 revision만 올린다(14-ticket-workflow).
                await self._bump_head(conn, current.conversation_id, current.id)
            await _audit(conn, current.id, actor.user_id, "cancelled", {}, now)
            return Outcome(200, await self._preview(conn, actor, action_uuid, now))

    # --- 내부 ---

    def _require_submit(self, actor: ActorContext) -> None:
        if "ticket.submit" not in actor.capabilities:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)

    async def _require_adopted(self, actor: ActorContext, row: Any) -> None:
        """CP-06: 원본 run이 completed이고 그 결과가 이 계보의 root draft를 채택했는가."""
        if not await self._eligibility.adopted(
            actor.user_id, str(row.conversation_id), str(row.initiating_run_id), str(row.root_action_id)
        ):
            raise AppError(ErrorCode.RUN_NOT_ELIGIBLE)

    async def _owned_action(self, conn: AsyncConnection, actor: ActorContext, action_id: UUID) -> Any:
        row = (await conn.execute(select(ticket_actions).where(ticket_actions.c.id == action_id))).first()
        if row is None or row.actor_id != actor.user_id:
            raise _not_found()  # 미존재·불허는 같은 404(상태·version을 드러내지 않음)
        return row

    async def _locked_action(self, conn: AsyncConnection, action_id: UUID) -> Any:
        return (
            await conn.execute(
                select(ticket_actions).where(ticket_actions.c.id == action_id).with_for_update()
            )
        ).one()

    async def _lock_head(self, conn: AsyncConnection, actor: ActorContext, conversation_id: UUID) -> Any:
        """대화별 head 행을 만들거나 잠근다. 최초 경쟁도 UNIQUE 행 하나에서 직렬화된다."""
        await conn.execute(
            insert(ticket_action_heads)
            .values(
                conversation_id=conversation_id, actor_id=actor.user_id, head_action_id=None, head_revision=0
            )
            .on_conflict_do_nothing(index_elements=["conversation_id"])
        )
        head = (
            await conn.execute(
                select(ticket_action_heads)
                .where(ticket_action_heads.c.conversation_id == conversation_id)
                .with_for_update()
            )
        ).one()
        if head.actor_id != actor.user_id:
            raise _not_found()
        return head

    async def _bump_head(self, conn: AsyncConnection, conversation_id: UUID, head_id: UUID) -> None:
        await conn.execute(
            update(ticket_action_heads)
            .where(ticket_action_heads.c.conversation_id == conversation_id)
            .values(head_action_id=head_id, head_revision=ticket_action_heads.c.head_revision + 1)
        )

    async def _status_of(self, conn: AsyncConnection, action_id: UUID | None) -> str | None:
        if action_id is None:
            return None
        row = (await conn.execute(select(ticket_actions).where(ticket_actions.c.id == action_id))).first()
        if row is None:
            return None
        if row.status in _LIVE and row.expires_at <= self._clock.now():
            return "expired"
        return row.status

    async def _precheck(self, conn: AsyncConnection, row: Any, operation: str, now: datetime) -> str | None:
        """03-errors 상태 오류 순서: confirmed의 같은 confirm 결과 → superseded → cancelled → 만료 →
        draft confirm 불가. 확인된 confirm이면 "converge", 반복 cancel이면 "repeat"."""
        status = "expired" if row.status in _LIVE and row.expires_at <= now else row.status
        if status == "confirmed":
            if operation == "confirm":
                return "converge"
            raise AppError(ErrorCode.ACTION_ALREADY_CONFIRMED)
        if status == "superseded":
            head_revision = await conn.scalar(
                select(ticket_action_heads.c.head_revision).where(
                    ticket_action_heads.c.conversation_id == row.conversation_id
                )
            )
            raise AppError(
                ErrorCode.ACTION_SUPERSEDED,
                details={
                    "current_action_id": await self._current_action_id(conn, row),
                    "head_revision": head_revision or 0,
                },
            )
        if status == "cancelled":
            if operation == "cancel":
                return "repeat"
            raise AppError(ErrorCode.ACTION_CANCELLED)
        if status == "expired":
            raise AppError(ErrorCode.ACTION_EXPIRED)
        if status == "draft" and operation == "confirm":
            raise AppError(ErrorCode.ACTION_NOT_PREPARED)
        return None

    def _conflict(self, code: ErrorCode, head_id: UUID | None, revision: int) -> AppError:
        return AppError(
            code, details={"current_action_id": str(head_id) if head_id else None, "head_revision": revision}
        )

    async def _lazy_expire(self, conn: AsyncConnection, row: Any, now: datetime) -> None:
        if row.status in _LIVE and row.expires_at <= now:
            changed = await conn.execute(
                update(ticket_actions)
                .where(ticket_actions.c.id == row.id, ticket_actions.c.status.in_(_LIVE))
                .values(status="expired", updated_at=now)
            )
            if changed.rowcount:
                await _audit(conn, row.id, row.actor_id, "expired", {}, now)

    async def _replay(
        self,
        conn: AsyncConnection,
        actor: ActorContext,
        key: UUID,
        operation: str,
        target: UUID,
        request_hash: str,
    ) -> UUID | None:
        record = (
            await conn.execute(
                select(idempotency_records).where(
                    idempotency_records.c.actor_id == actor.user_id, idempotency_records.c.key == key
                )
            )
        ).first()
        if record is None:
            return None
        if (record.operation, record.target_action_id, record.request_hash) != (
            operation,
            target,
            request_hash,
        ):
            raise AppError(ErrorCode.IDEMPOTENCY_CONFLICT)
        return record.result_action_id

    async def _replay_after_race(
        self, actor: ActorContext, key: UUID, operation: str, target: UUID, request_hash: str
    ) -> Outcome:
        async with self._engine.begin() as conn:
            replay = await self._replay(conn, actor, key, operation, target, request_hash)
            if replay is None:
                raise AppError(ErrorCode.ACTION_HEAD_CONFLICT)
            if operation == "confirm":
                return Outcome(200, await self._confirmation(conn, actor, replay))
            return Outcome(200, await self._preview(conn, actor, replay, self._clock.now()))

    async def _remember(
        self,
        conn: AsyncConnection,
        actor: ActorContext,
        key: UUID,
        operation: str,
        target: UUID,
        request_hash: str,
        result: UUID,
        status_code: int,
        now: datetime,
    ) -> None:
        existing = await self._replay(conn, actor, key, operation, target, request_hash)
        if existing is not None:
            return
        await conn.execute(
            idempotency_records.insert().values(
                actor_id=actor.user_id,
                key=key,
                operation=operation,
                target_action_id=target,
                request_hash=request_hash,
                result_action_id=result,
                status_code=status_code,
                created_at=now,
            )
        )

    async def _current_action_id(self, conn: AsyncConnection, row: Any) -> str:
        """superseded 사슬을 따라 지금 유효한 action(본인 계보 안)."""
        current, seen = row, set()
        while current.superseded_by_action_id is not None and current.id not in seen:
            seen.add(current.id)
            nxt = (
                await conn.execute(
                    select(ticket_actions).where(ticket_actions.c.id == current.superseded_by_action_id)
                )
            ).first()
            if nxt is None or nxt.actor_id != row.actor_id:
                break
            current = nxt
        return str(current.id)

    async def _preview(
        self, conn: AsyncConnection, actor: ActorContext, action_id: UUID, now: datetime
    ) -> dict[str, Any]:
        row = (await conn.execute(select(ticket_actions).where(ticket_actions.c.id == action_id))).one()
        status = "expired" if row.status in _LIVE and row.expires_at <= now else row.status
        reply = await self._identity.reply_channel(actor.user_id)
        head_revision = await conn.scalar(
            select(ticket_action_heads.c.head_revision).where(
                ticket_action_heads.c.conversation_id == row.conversation_id
            )
        )
        return {
            "action_id": str(row.id),
            "version": row.version,
            "status": status,
            "expires_at": row.expires_at.astimezone(KST).isoformat(),
            "conversation_id": str(row.conversation_id),
            # CT-16: 접수 필드는 미리보기 최상위에 둔다(04-api-spec 예시). 빠진 값은 null과 missing_fields.
            **{name: row.payload.get(name) for name in FIELD_NAMES},
            "missing_fields": list(row.missing_fields),
            "reply_channel": reply,
            "root_action_id": str(row.root_action_id),
            "prepared_from_action_id": _str(row.prepared_from_action_id),
            "displaced_head_id": _str(row.displaced_head_id),
            "superseded_by_action_id": _str(row.superseded_by_action_id),
            "current_action_id": await self._current_action_id(conn, row),
            "ticket_id": _str(row.ticket_id),
            "head_revision": head_revision or 0,
        }

    async def _confirmation(
        self, conn: AsyncConnection, actor: ActorContext, action_id: UUID, *, recheck: bool = False
    ) -> dict[str, Any]:
        """recheck=True(replay·반복 확인)면 지금 그 ticket을 볼 수 있을 때만 돌려준다(14-ticket-workflow)."""
        row = (await conn.execute(select(ticket_actions).where(ticket_actions.c.id == action_id))).one()
        query = select(tickets).where(tickets.c.id == row.ticket_id)
        if recheck:
            clause = self._visible_clause(actor, await self._scope(conn, actor))
            if clause is not None:
                query = query.where(clause)
        ticket = (await conn.execute(query)).first()
        if recheck and ticket is None:
            raise _not_found()
        return {
            "action_id": str(row.id),
            "ticket_id": _str(row.ticket_id),
            "ticket": _ticket(ticket) if ticket is not None else None,
            "status": row.status,
        }


def _uuid_or_404(value: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError:
        raise _not_found() from None


def _str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _ticket(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "subject": row.subject,
        "description": row.description,
        "request_type": row.request_type,
        "category": row.category,
        "target_service": row.target_service,
        "occurred_at": row.occurred_at.astimezone(KST).isoformat() if row.occurred_at else None,
        "impact_scope": row.impact_scope,
        "urgent_work": row.urgent_work,
        "urgency_reason": row.urgency_reason,
        "asset_identifier": row.asset_identifier,
        "reply_channel": row.reply_channel,
        "status": row.status,
        "requester_id": row.requester_id,
        "created_at": row.created_at.astimezone(KST).isoformat(),
    }


async def _audit(
    conn: AsyncConnection, action_id: UUID, actor_id: str, event: str, details: dict[str, Any], now: datetime
) -> None:
    await conn.execute(
        ticket_audit.insert().values(
            action_id=action_id, actor_id=actor_id, event=event, details=details, created_at=now
        )
    )


SUPPORT_SCOPES_PATH = Path(__file__).with_name("support_scopes.json")


async def load_support_scopes(engine: AsyncEngine, path: Path = SUPPORT_SCOPES_PATH) -> int:
    """데모 지원 범위 fixture 적재(재실행해도 중복 없음, D-42)."""
    data = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    async with engine.begin() as conn:
        for scope in data["scopes"]:
            await conn.execute(
                insert(support_scopes)
                .values(user_id=scope["user_id"], department_ids=list(scope["department_ids"]))
                .on_conflict_do_update(
                    index_elements=["user_id"], set_={"department_ids": list(scope["department_ids"])}
                )
            )
    return len(data["scopes"])
