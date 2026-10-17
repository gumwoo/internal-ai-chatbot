"""MOD-09 공개 작업: Login/Logout/GetSession, ResolveActor, Authorize, ReloadActor, ChangeMembership,
ResolveOperatorActor, 데모 조직 적재.

- 세션 토큰은 무작위 32바이트. DB에는 SHA-256만 남긴다. CSRF 토큰은 세션 토큰의 HMAC이라 저장하지 않는다.
- actor는 매 요청 DB의 현재 부서·역할·revision으로 만든다. 브라우저·모델이 보낸 user_id·역할은 쓰지 않는다.
- Authorize는 요청 시작 때의 actor 사본이 오래됐으면(revision 불일치) 현재 값으로 다시 판정한다.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.modules.identity_access.passwords import hash_password, verify_password
from agent.modules.identity_access.policy import AccessDecision, ResourcePolicy, evaluate
from agent.modules.identity_access.tables import (
    auth_sessions,
    departments,
    membership_audit,
    role_capabilities,
    roles,
    user_departments,
    user_roles,
    users,
)
from agent.shared.actor import CAPABILITIES, ActorContext, ActorSource
from agent.shared.clock import Clock
from agent.shared.errors import AppError, ErrorCode

DEMO_ORG_PATH = Path(__file__).with_name("demo_org.json")
# 웹 세션 actor가 가질 수 있는 capability. 운영(ops.*)·평가(eval.*)는 CLI·평가 조립 지점 전용이라
# 직원 세션에서는 역할이 있어도 주지 않는다(CT-01: 직원 세션에서 운영자로 승격하지 않음, D-30).
_WEB_CAPABILITIES = frozenset(c for c in CAPABILITIES if not c.startswith(("ops.", "eval.")))
# 비밀번호 해시 계산(scrypt, 약 65ms)은 이벤트 루프 밖에서, 동시에 몇 개까지만 한다.
_HASH_CONCURRENCY = 4


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """세션 토큰에서 만든 CSRF 토큰.

    cookie는 HttpOnly라 스크립트가 읽지 못한다. 이 값은 로그인 응답과 GET /session으로만 받는다.
    """
    return hmac.new(session_token.encode("utf-8"), b"csrf-v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SessionView:
    user_id: str
    display_name: str
    capabilities: tuple[str, ...]
    expires_at: datetime


@dataclass(frozen=True)
class LoginResult:
    token: str
    view: SessionView


class IdentityService:
    def __init__(self, engine: AsyncEngine, clock: Clock, session_ttl_s: int = 8 * 3600) -> None:
        self._engine = engine
        self._clock = clock
        self._ttl = timedelta(seconds=session_ttl_s)
        self._hashing = asyncio.Semaphore(_HASH_CONCURRENCY)

    async def _verify(self, password: str, stored: str | None) -> bool:
        async with self._hashing:
            return await asyncio.to_thread(verify_password, password, stored)

    # --- 세션 ---

    async def login(self, username: str, password: str, previous_token: str | None = None) -> LoginResult:
        """성공하면 새 세션 토큰. 실패 사유(계정 없음·비밀번호 틀림·웹 로그인 없음·비활성)는 모두 같은 401."""
        async with self._engine.connect() as conn:
            row = (await conn.execute(select(users).where(users.c.id == username))).first()
        stored = row.password_hash if row is not None and row.web_login and row.active else None
        if not await self._verify(password, stored):
            raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
        now = self._clock.now()
        token = secrets.token_urlsafe(32)
        async with self._engine.begin() as conn:
            if previous_token:
                # 로그인 때 기존 세션을 회수하고 새 토큰을 발급한다(세션 고정 방지).
                await self._revoke(conn, previous_token, now)
            await conn.execute(
                auth_sessions.insert().values(
                    token_hash=token_hash(token), user_id=row.id, created_at=now, expires_at=now + self._ttl
                )
            )
            actor = await self._actor(conn, row.id, "local_session", token_hash(token))
        assert actor is not None  # noqa: S101 - 방금 확인한 활성 계정
        return LoginResult(token, self._view(row.display_name, actor, now + self._ttl))

    async def logout(self, token: str) -> None:
        async with self._engine.begin() as conn:
            await self._revoke(conn, token, self._clock.now())

    async def get_session(self, token: str) -> SessionView:
        actor, display_name, expires_at = await self._session(token)
        return self._view(display_name, actor, expires_at)

    async def resolve_actor(self, token: str | None) -> ActorContext:
        """ResolveActor(session) → CT-01.

        없거나 모르는 토큰은 401 AUTHENTICATION_REQUIRED, 만료·회수·비활성은 401 SESSION_EXPIRED.
        """
        if not token:
            raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
        actor, _, _ = await self._session(token)
        return actor

    async def _session(self, token: str) -> tuple[ActorContext, str, datetime]:
        now = self._clock.now()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(auth_sessions, users.c.display_name, users.c.active, users.c.web_login)
                    .join(users, users.c.id == auth_sessions.c.user_id)
                    .where(auth_sessions.c.token_hash == token_hash(token))
                )
            ).first()
            if row is None:
                raise AppError(ErrorCode.AUTHENTICATION_REQUIRED)
            if row.revoked_at is not None or row.expires_at <= now or not row.active or not row.web_login:
                raise AppError(ErrorCode.SESSION_EXPIRED)
            actor = await self._actor(conn, row.user_id, "local_session", row.token_hash)
        if actor is None:
            raise AppError(ErrorCode.SESSION_EXPIRED)
        return actor, row.display_name, row.expires_at

    async def _revoke(self, conn: AsyncConnection, token: str, now: datetime) -> None:
        await conn.execute(
            update(auth_sessions)
            .where(auth_sessions.c.token_hash == token_hash(token), auth_sessions.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def _view(self, display_name: str, actor: ActorContext, expires_at: datetime) -> SessionView:
        return SessionView(
            user_id=actor.user_id,
            display_name=display_name,
            capabilities=tuple(sorted(actor.capabilities)),
            expires_at=expires_at,
        )

    # --- actor·인가 ---

    async def reload_actor(self, actor: ActorContext) -> ActorContext | None:
        """ReloadActor: 현재 부서·역할·revision. 비활성·삭제 계정이나 회수·만료된 세션이면 None.

        테스트 대체 actor(test_stub·eval_fixture)는 그대로 둔다.
        """
        if actor.source not in ("local_session", "operator_cli"):
            return actor
        async with self._engine.connect() as conn:
            if actor.source == "local_session":
                session = (
                    await conn.execute(
                        select(auth_sessions).where(
                            auth_sessions.c.token_hash == (actor.session_ref or ""),
                            auth_sessions.c.user_id == actor.user_id,
                        )
                    )
                ).first()
                if (
                    session is None
                    or session.revoked_at is not None
                    or session.expires_at <= self._clock.now()
                ):
                    return None
            current = await self._actor(conn, actor.user_id, actor.source, actor.session_ref)
        if current is not None and actor.source == "operator_cli":
            current = _operator_only(current)
        return current

    async def authorize(
        self, actor: ActorContext, capability: str, policy: ResourcePolicy | None
    ) -> AccessDecision:
        """Authorize: 세션 회수·만료와 현재 revision을 확인하고(오래된 사본이면 현재 값으로) 판정한다."""
        current = await self.reload_actor(actor)
        return evaluate(current, capability, policy)

    async def resolve_operator_actor(self, user_id: str | None) -> ActorContext:
        """ResolveOperatorActor: 서버 설정의 운영 계정만. operator 역할이 없으면 거부한다(APP-03 전용)."""
        if not user_id:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        async with self._engine.connect() as conn:
            actor = await self._actor(conn, user_id, "operator_cli")
        if actor is None or "operator" not in actor.role_ids:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        return _operator_only(actor)

    async def change_membership(
        self,
        operator: ActorContext,
        user_id: str,
        *,
        department_ids: tuple[str, ...],
        role_ids: tuple[str, ...],
    ) -> int:
        """ChangeMembership(운영자, 변경) → 새 auth_revision. 감사 행을 남긴다."""
        decision = evaluate(
            await self.reload_actor(operator), "ops.membership_admin", ResourcePolicy("authenticated")
        )
        if operator.source != "operator_cli" or not decision.allowed:
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        now = self._clock.now()
        if len(set(department_ids)) != len(department_ids) or len(set(role_ids)) != len(role_ids):
            raise AppError(ErrorCode.INVALID_REQUEST)
        async with self._engine.begin() as conn:
            row = (await conn.execute(select(users).where(users.c.id == user_id).with_for_update())).first()
            if row is None:
                raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
            known_departments = set(
                (
                    await conn.scalars(select(departments.c.id).where(departments.c.id.in_(department_ids)))
                ).all()
            )
            known_roles = set((await conn.scalars(select(roles.c.id).where(roles.c.id.in_(role_ids)))).all())
            if known_departments != set(department_ids) or known_roles != set(role_ids):
                raise AppError(ErrorCode.INVALID_REQUEST)
            before = await _membership(conn, user_id)
            await conn.execute(delete(user_departments).where(user_departments.c.user_id == user_id))
            await conn.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
            for department_id in department_ids:
                await conn.execute(
                    user_departments.insert().values(user_id=user_id, department_id=department_id)
                )
            for role_id in role_ids:
                await conn.execute(user_roles.insert().values(user_id=user_id, role_id=role_id))
            revision = row.auth_revision + 1
            await conn.execute(update(users).where(users.c.id == user_id).values(auth_revision=revision))
            await conn.execute(
                membership_audit.insert().values(
                    actor_id=operator.user_id,
                    actor_source=operator.source,
                    user_id=user_id,
                    before=before,
                    after={"department_ids": sorted(department_ids), "role_ids": sorted(role_ids)},
                    auth_revision=revision,
                    changed_at=now,
                )
            )
        return revision

    async def _actor(
        self, conn: AsyncConnection, user_id: str, source: ActorSource, session_ref: str | None = None
    ) -> ActorContext | None:
        row = (await conn.execute(select(users).where(users.c.id == user_id))).first()
        if row is None or not row.active:
            return None
        membership = await _membership(conn, user_id)
        capabilities = (
            await conn.scalars(
                select(role_capabilities.c.capability)
                .where(role_capabilities.c.role_id.in_(membership["role_ids"]))
                .distinct()
            )
        ).all()
        # 닫힌 목록 밖의 값이 DB에 있어도 권한으로 쓰지 않는다. 웹 세션에는 운영·평가 권한을 주지 않는다.
        allowed = _WEB_CAPABILITIES if source == "local_session" else CAPABILITIES
        return ActorContext(
            user_id=row.id,
            department_ids=tuple(membership["department_ids"]),
            role_ids=tuple(membership["role_ids"]),
            capabilities=frozenset(capabilities) & allowed,
            auth_revision=row.auth_revision,
            source=source,
            session_ref=session_ref if source == "local_session" else None,
        )


def _operator_only(actor: ActorContext) -> ActorContext:
    """운영 CLI actor는 ops.* capability만 갖는다(직원 권한으로 업무 API를 쓰지 않게)."""
    return ActorContext(
        user_id=actor.user_id,
        department_ids=actor.department_ids,
        role_ids=actor.role_ids,
        capabilities=frozenset(c for c in actor.capabilities if c.startswith("ops.")),
        auth_revision=actor.auth_revision,
        source="operator_cli",
    )


async def _membership(conn: AsyncConnection, user_id: str) -> dict[str, list[str]]:
    department_ids = (
        await conn.scalars(
            select(user_departments.c.department_id)
            .where(user_departments.c.user_id == user_id)
            .order_by(user_departments.c.department_id)
        )
    ).all()
    role_ids = (
        await conn.scalars(
            select(user_roles.c.role_id).where(user_roles.c.user_id == user_id).order_by(user_roles.c.role_id)
        )
    ).all()
    return {"department_ids": list(department_ids), "role_ids": list(role_ids)}


async def load_demo_org(engine: AsyncEngine, now: datetime, path: Path = DEMO_ORG_PATH) -> dict[str, Any]:
    """데모 조직 fixture 적재(재실행해도 중복 없음). 부서·역할이 바뀐 계정은 auth_revision을 올린다.

    비밀번호는 원문을 DB에 넣지 않고 해시만 저장한다. 이미 있는 계정의 해시는 비밀번호가 바뀐 경우만 갱신한다.
    """
    data = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    report = {"departments": 0, "roles": 0, "users": 0, "revision_bumped": []}
    changed_roles: set[str] = set()
    async with engine.begin() as conn:
        for department in data["departments"]:
            await conn.execute(
                insert(departments)
                .values(id=department["id"], name=department["name"])
                .on_conflict_do_update(index_elements=["id"], set_={"name": department["name"]})
            )
            report["departments"] += 1
        for role in data["roles"]:
            unknown = set(role["capabilities"]) - CAPABILITIES
            if unknown:
                raise ValueError(f"닫힌 목록에 없는 capability: {sorted(unknown)}")
            role_existed = await conn.scalar(select(roles.c.id).where(roles.c.id == role["id"]))
            await conn.execute(
                insert(roles)
                .values(id=role["id"], name=role["name"])
                .on_conflict_do_update(index_elements=["id"], set_={"name": role["name"]})
            )
            current = set(
                (
                    await conn.scalars(
                        select(role_capabilities.c.capability).where(
                            role_capabilities.c.role_id == role["id"]
                        )
                    )
                ).all()
            )
            if role_existed is not None and current != set(role["capabilities"]):
                changed_roles.add(role["id"])
            await conn.execute(delete(role_capabilities).where(role_capabilities.c.role_id == role["id"]))
            for capability in role["capabilities"]:
                await conn.execute(
                    role_capabilities.insert().values(role_id=role["id"], capability=capability)
                )
            report["roles"] += 1
        for user in data["users"]:
            existing = (await conn.execute(select(users).where(users.c.id == user["id"]))).first()
            password = user.get("password")
            if user["web_login"] and not password:
                raise ValueError(f"웹 로그인 계정에 비밀번호가 없다: {user['id']}")
            keep_hash = (
                existing is not None
                and password
                and await asyncio.to_thread(verify_password, password, existing.password_hash)
            )
            password_hash = (
                existing.password_hash if keep_hash else (hash_password(password) if password else None)
            )
            wanted = {"department_ids": sorted(user["departments"]), "role_ids": sorted(user["roles"])}
            if existing is None:
                await conn.execute(
                    users.insert().values(
                        id=user["id"],
                        display_name=user["display_name"],
                        password_hash=password_hash,
                        web_login=user["web_login"],
                        active=True,
                        auth_revision=1,
                        created_at=now,
                    )
                )
                changed = True
            else:
                before = await _membership(conn, user["id"])
                changed = before != wanted
                # 활성 여부는 운영 상태라 fixture 재적재로 되살리지 않는다(비활성 계정 유지).
                await conn.execute(
                    update(users)
                    .where(users.c.id == user["id"])
                    .values(
                        display_name=user["display_name"],
                        password_hash=password_hash,
                        web_login=user["web_login"],
                        auth_revision=existing.auth_revision + 1 if changed else existing.auth_revision,
                    )
                )
                if password_hash != existing.password_hash or user["web_login"] != existing.web_login:
                    # 비밀번호·웹 로그인 여부가 바뀌면 기존 세션을 회수한다.
                    await conn.execute(
                        update(auth_sessions)
                        .where(auth_sessions.c.user_id == user["id"], auth_sessions.c.revoked_at.is_(None))
                        .values(revoked_at=now)
                    )
                if changed:
                    report["revision_bumped"].append(user["id"])
                    await conn.execute(
                        membership_audit.insert().values(
                            actor_id="seed-identity",
                            actor_source="operator_cli",
                            user_id=user["id"],
                            before=before,
                            after=wanted,
                            auth_revision=existing.auth_revision + 1,
                            changed_at=now,
                        )
                    )
            if changed:
                await conn.execute(delete(user_departments).where(user_departments.c.user_id == user["id"]))
                await conn.execute(delete(user_roles).where(user_roles.c.user_id == user["id"]))
                for department_id in wanted["department_ids"]:
                    await conn.execute(
                        user_departments.insert().values(user_id=user["id"], department_id=department_id)
                    )
                for role_id in wanted["role_ids"]:
                    await conn.execute(user_roles.insert().values(user_id=user["id"], role_id=role_id))
            report["users"] += 1
        if changed_roles:
            # 역할의 capability가 바뀌면 그 역할을 가진 계정의 actor 사본도 오래된 것이 된다.
            members = (
                await conn.scalars(
                    select(user_roles.c.user_id).where(user_roles.c.role_id.in_(changed_roles)).distinct()
                )
            ).all()
            for user_id in members:
                if user_id not in report["revision_bumped"]:
                    await conn.execute(
                        update(users)
                        .where(users.c.id == user_id)
                        .values(auth_revision=users.c.auth_revision + 1)
                    )
                    report["revision_bumped"].append(user_id)
    return report
