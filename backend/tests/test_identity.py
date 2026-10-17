"""MOD-09 로컬 세션·인가(T-22 로그인/세션/CSRF/회수, T-23 기본 거부·역할 변경·actor 위조). 과금 없음."""

import uuid

import pytest
from sqlalchemy import text

from agent.app.main import create_app
from agent.modules.identity_access.passwords import hash_password, verify_password
from agent.modules.identity_access.policy import ResourcePolicy, evaluate
from agent.modules.identity_access.service import IdentityService, load_demo_org
from agent.modules.model_integration.fake import FakeModelClient
from agent.shared.actor import ActorContext
from agent.shared.clock import FIXTURE_NOW, FixedClock
from agent.shared.errors import AppError, ErrorCode
from tests.conftest import api_client, make_settings
from tests.test_conversation import NEXT_WEEK

ORIGIN = "http://localhost:5190"
PASSWORDS = {
    "emp-sales": "demo-emp-sales-1017",
    "emp-dev": "demo-emp-dev-1017",
    "head-sales": "demo-head-sales-1017",
    "hr-staff": "demo-hr-staff-1017",
    "it-support": "demo-it-support-1017",
}


@pytest.fixture
async def org_engine(seeded_engine):
    await load_demo_org(seeded_engine, FIXTURE_NOW)
    return seeded_engine


def _session_app(migrated, clock=None, model=None, **settings):
    return create_app(
        make_settings(
            database_url=migrated,
            allowed_origins=ORIGIN,
            auth_mode="local_session",
            test_actor_id=None,
            **settings,
        ),
        clock=clock or FixedClock(),
        chat_model=model or FakeModelClient([]),
    )


async def _login(client, user="emp-sales", password=None):
    return await client.post(
        "/api/v1/session",
        json={"username": user, "password": password or PASSWORDS[user]},
        headers={"Origin": ORIGIN},
    )


# --- 비밀번호·정책(순수) ---


def test_password_hash_roundtrip_and_format():
    stored = hash_password("비밀-1")
    assert stored.startswith("scrypt$") and "비밀-1" not in stored
    assert verify_password("비밀-1", stored)
    assert not verify_password("비밀-2", stored)
    assert not verify_password("비밀-1", None)
    assert not verify_password("x", "md5$abc")
    assert not verify_password("x", "scrypt$broken")


ACTOR = ActorContext(
    "u1", ("dept-sales",), ("employee",), frozenset({"knowledge.search"}), 1, "local_session"
)


@pytest.mark.parametrize(
    ("policy", "allowed", "reason"),
    [
        (ResourcePolicy("authenticated"), True, "allowed"),
        (ResourcePolicy("restricted"), False, "not_in_audience"),  # 빈 restricted는 아무도 허용하지 않음
        (ResourcePolicy("restricted", allowed_user_ids=frozenset({"u1"})), True, "allowed"),
        (ResourcePolicy("restricted", allowed_department_ids=frozenset({"dept-sales"})), True, "allowed"),
        (
            ResourcePolicy("restricted", allowed_department_ids=frozenset({"dept-hr"})),
            False,
            "not_in_audience",
        ),
        (ResourcePolicy("restricted", allowed_role_ids=frozenset({"employee"})), True, "allowed"),
        (ResourcePolicy("restricted", allowed_role_ids=frozenset({"hr_staff"})), False, "not_in_audience"),
        (
            ResourcePolicy("authenticated", required_capabilities=frozenset({"ticket.read_all"})),
            False,
            "missing_capability",
        ),
        (ResourcePolicy("public"), False, "invalid_policy"),
        (None, False, "invalid_policy"),
    ],
)
def test_policy_default_deny_and_union(policy, allowed, reason):
    decision = evaluate(ACTOR, "knowledge.search", policy)
    assert (decision.allowed, decision.reason) == (allowed, reason)


def test_policy_requires_action_capability_and_actor():
    assert evaluate(ACTOR, "training.read", ResourcePolicy("authenticated")).reason == "missing_capability"
    assert evaluate(ACTOR, "admin", ResourcePolicy("authenticated")).reason == "missing_capability"
    assert evaluate(None, "knowledge.search", ResourcePolicy("authenticated")).reason == "unauthenticated"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"audience": "everyone"},
        {"audience": "authenticated", "admin": True},  # 모르는 키
        {"audience": "restricted", "required_capabilities": ["superuser"]},
        {"audience": "restricted", "revision": "x"},
        {"audience": "restricted", "allowed_role_ids": "hr_staff"},  # 목록이 아닌 문자열
    ],
)
def test_unknown_or_malformed_stored_policy_is_rejected(raw):
    assert ResourcePolicy.from_mapping(raw) is None


def test_stored_policy_roundtrip():
    policy = ResourcePolicy.from_mapping(
        {"audience": "restricted", "allowed_role_ids": ["hr_staff", "dept_head"], "revision": 3}
    )
    assert policy == ResourcePolicy(
        "restricted", allowed_role_ids=frozenset({"hr_staff", "dept_head"}), revision=3
    )


# --- T-22 로그인·세션·CSRF·회수 ---


async def test_login_sets_httponly_strict_cookie_and_session_view(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        response = await _login(client)
        session = await client.get("/api/v1/session")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "agent_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1" in cookie and "Secure" not in cookie  # 로컬(test)에서는 Secure 없음
    body = response.json()
    assert set(body) == {"user_id", "display_name", "capabilities", "expires_at", "csrf_token"}
    assert body["user_id"] == "emp-sales"
    assert body["capabilities"] == ["knowledge.search", "ticket.read_own", "training.read"]
    assert response.headers["cache-control"] == "private, no-store"
    # 응답에 세션 토큰·해시가 없다.
    token = client.cookies.get("agent_session")
    assert token not in response.text and session.status_code == 200
    assert session.json() == body
    rows = await _scalar(org_engine, "SELECT count(*) FROM auth_sessions WHERE token_hash = :t", t=token)
    assert rows == 0  # 원문 토큰은 저장하지 않는다


async def _scalar(engine, sql, **params):
    async with engine.connect() as conn:
        return await conn.scalar(text(sql), params)


async def test_secure_cookie_in_production(org_engine, migrated):
    async with api_client(_session_app(migrated, app_env="production")) as client:
        response = await _login(client)
    assert "Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("user", "password"),
    [("emp-sales", "wrong"), ("nobody", "x"), ("ops-admin", "x"), ("ops-admin", "")],
)
async def test_login_failures_are_same_401(org_engine, migrated, user, password):
    async with api_client(_session_app(migrated)) as client:
        response = await client.post(
            "/api/v1/session",
            json={"username": user, "password": password or "y"},
            headers={"Origin": ORIGIN},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert "set-cookie" not in response.headers


async def test_login_requires_origin_and_json(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        no_origin = await client.post(
            "/api/v1/session", json={"username": "emp-sales", "password": PASSWORDS["emp-sales"]}
        )
        form = await client.post(
            "/api/v1/session",
            content="username=emp-sales&password=demo-emp-sales-1017",
            headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
        )
        extra = await client.post(
            "/api/v1/session",
            json={"username": "emp-sales", "password": PASSWORDS["emp-sales"], "role": "admin"},
            headers={"Origin": ORIGIN},
        )
    assert (no_origin.status_code, no_origin.json()["error"]["code"]) == (403, "CSRF_FAILED")
    assert form.status_code == 422 and "set-cookie" not in form.headers
    assert extra.status_code == 422


async def test_write_without_session_or_csrf_is_rejected(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        anonymous = await client.post("/api/v1/conversations", json={}, headers={"Origin": ORIGIN})
        anonymous_read = await client.get("/api/v1/conversations")
        await _login(client)
        no_csrf = await client.post("/api/v1/conversations", json={}, headers={"Origin": ORIGIN})
        bad_csrf = await client.post(
            "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": "0" * 64}
        )
        csrf = (await client.get("/api/v1/session")).json()["csrf_token"]
        ok = await client.post(
            "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
        )
        read = await client.get("/api/v1/conversations")  # 읽기는 CSRF 불필요
    assert (anonymous.status_code, anonymous.json()["error"]["code"]) == (401, "AUTHENTICATION_REQUIRED")
    assert anonymous_read.status_code == 401
    assert (no_csrf.status_code, no_csrf.json()["error"]["code"]) == (403, "CSRF_FAILED")
    assert bad_csrf.status_code == 403
    assert ok.status_code == 201 and read.status_code == 200
    assert await _scalar(org_engine, "SELECT count(*) FROM conversations") == 1


async def test_logout_revokes_session_and_requires_csrf(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        login = await _login(client)
        token = client.cookies.get("agent_session")
        no_csrf = await client.delete("/api/v1/session", headers={"Origin": ORIGIN})
        logout = await client.delete(
            "/api/v1/session", headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
        )
        assert "agent_session" in logout.headers.get("set-cookie", "")
        # 회수된 토큰을 다시 보내도 쓸 수 없다.
        client.cookies.set("agent_session", token, path="/api/v1")
        after = await client.get("/api/v1/conversations")
    assert no_csrf.status_code == 403
    assert logout.status_code == 204
    assert (after.status_code, after.json()["error"]["code"]) == (401, "SESSION_EXPIRED")


async def test_expired_session_is_401_session_expired(org_engine, migrated):
    clock = FixedClock()
    async with api_client(_session_app(migrated, clock=clock, session_ttl_s=60)) as client:
        await _login(client)
        before = await client.get("/api/v1/session")
        clock.advance(60)
        after = await client.get("/api/v1/session")
    assert before.status_code == 200
    assert (after.status_code, after.json()["error"]["code"]) == (401, "SESSION_EXPIRED")


async def test_relogin_rotates_token_and_revokes_old(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        await _login(client)
        first = client.cookies.get("agent_session")
        await _login(client, "emp-dev")
        second = client.cookies.get("agent_session")
        client.cookies.set("agent_session", first, path="/api/v1")
        old = await client.get("/api/v1/session")
    assert first != second
    assert old.status_code == 401


async def test_unknown_cookie_is_401_and_session_routes_absent_in_test_stub(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        client.cookies.set("agent_session", "forged", path="/api/v1")
        forged = await client.get("/api/v1/session")
    stub = create_app(
        make_settings(database_url=migrated, allowed_origins=ORIGIN), chat_model=FakeModelClient([])
    )
    async with api_client(stub) as client:
        absent = await client.post(
            "/api/v1/session", json={"username": "emp-sales", "password": "x"}, headers={"Origin": ORIGIN}
        )
    assert (forged.status_code, forged.json()["error"]["code"]) == (401, "AUTHENTICATION_REQUIRED")
    assert absent.status_code == 404


# --- T-23 기본 거부·역할 변경·actor 위조·운영 actor ---


async def test_actor_from_session_ignores_forged_identity_fields(org_engine, migrated):
    model = FakeModelClient(NEXT_WEEK)
    async with api_client(_session_app(migrated, model=model)) as client:
        login = await _login(client)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"], "X-User-Id": "hr-staff"}
        conv = await client.post("/api/v1/conversations?user_id=hr-staff", json={}, headers=headers)
        forged_body = await client.post(
            "/api/v1/conversations", json={"owner_user_id": "hr-staff"}, headers=headers
        )
    assert conv.status_code == 201
    assert forged_body.status_code == 422  # 알 수 없는 필드 거절
    assert await _scalar(org_engine, "SELECT owner_user_id FROM conversations") == "emp-sales"


async def test_membership_change_bumps_revision_and_authorize_uses_current(org_engine):
    clock = FixedClock()
    identity = IdentityService(org_engine, clock)
    login = await identity.login("emp-sales", PASSWORDS["emp-sales"])
    stale = await identity.resolve_actor(login.token)
    hr_policy = ResourcePolicy("restricted", allowed_role_ids=frozenset({"hr_staff", "dept_head"}))
    assert not (await identity.authorize(stale, "knowledge.search", hr_policy)).allowed
    operator = await identity.resolve_operator_actor("ops-admin")
    revision = await identity.change_membership(
        operator, "emp-sales", department_ids=("dept-sales",), role_ids=("employee", "dept_head")
    )
    assert revision == stale.auth_revision + 1
    # 요청 시작 때 받은 사본(stale)이라도 Authorize는 현재 역할로 판정한다.
    assert (await identity.authorize(stale, "knowledge.search", hr_policy)).allowed
    current = await identity.resolve_actor(login.token)
    assert current.auth_revision == revision and "dept_head" in current.role_ids
    # 역할을 빼면 즉시 다시 거부된다(과거 권한 부활 없음).
    await identity.change_membership(
        operator, "emp-sales", department_ids=("dept-sales",), role_ids=("employee",)
    )
    assert not (await identity.authorize(current, "knowledge.search", hr_policy)).allowed
    audit = await _scalar(org_engine, "SELECT count(*) FROM membership_audit WHERE user_id = 'emp-sales'")
    assert audit == 2


async def test_deactivated_user_is_denied_even_with_valid_session(org_engine):
    identity = IdentityService(org_engine, FixedClock())
    login = await identity.login("emp-dev", PASSWORDS["emp-dev"])
    actor = await identity.resolve_actor(login.token)
    async with org_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET active = false WHERE id = 'emp-dev'"))
    with pytest.raises(AppError) as error:
        await identity.resolve_actor(login.token)
    assert error.value.code is ErrorCode.SESSION_EXPIRED
    assert (await identity.authorize(actor, "knowledge.search", ResourcePolicy("authenticated"))).reason == (
        "unauthenticated"
    )


async def test_operator_actor_only_from_server_config(org_engine):
    identity = IdentityService(org_engine, FixedClock())
    operator = await identity.resolve_operator_actor("ops-admin")
    assert operator.source == "operator_cli"
    assert operator.capabilities and all(c.startswith("ops.") for c in operator.capabilities)
    for user_id in (None, "", "emp-sales", "hr-staff", "nobody"):
        with pytest.raises(AppError) as error:
            await identity.resolve_operator_actor(user_id)
        assert error.value.code is ErrorCode.ACTION_NOT_ALLOWED
    # 직원 세션 actor는 운영 변경을 할 수 없다.
    login = await identity.login("hr-staff", PASSWORDS["hr-staff"])
    employee = await identity.resolve_actor(login.token)
    with pytest.raises(AppError):
        await identity.change_membership(
            employee, "emp-dev", department_ids=("dept-dev",), role_ids=("dept_head",)
        )


async def test_demo_org_reload_is_idempotent_and_detects_changes(org_engine, tmp_path):
    again = await load_demo_org(org_engine, FIXTURE_NOW)
    assert again["revision_bumped"] == [] and again["users"] == 6
    hashes = await _scalar(org_engine, "SELECT count(DISTINCT password_hash) FROM users WHERE web_login")
    assert hashes == 5
    plain = await _scalar(org_engine, "SELECT count(*) FROM users WHERE password_hash LIKE '%demo-%'")
    assert plain == 0
    # 역할 capability가 바뀌면 그 역할 계정의 revision이 오른다.
    import json

    from agent.modules.identity_access.service import DEMO_ORG_PATH

    data = json.loads(DEMO_ORG_PATH.read_text(encoding="utf-8"))
    for role in data["roles"]:
        if role["id"] == "it_support":
            role["capabilities"].remove("ticket.read_support_scope")
    changed = tmp_path / "org.json"
    changed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = await load_demo_org(org_engine, FIXTURE_NOW, changed)
    assert report["revision_bumped"] == ["it-support"]
    bad = json.loads(DEMO_ORG_PATH.read_text(encoding="utf-8"))
    bad["roles"][0]["capabilities"].append("superuser")
    changed.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="capability"):
        await load_demo_org(org_engine, FIXTURE_NOW, changed)


async def test_users_are_isolated_across_sessions(org_engine, migrated):
    """T-01을 실제 세션으로: 다른 계정의 대화는 같은 404."""
    async with api_client(_session_app(migrated)) as owner:
        csrf = (await _login(owner)).json()["csrf_token"]
        conv = (
            await owner.post(
                "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
            )
        ).json()["id"]
    async with api_client(_session_app(migrated)) as other:
        await _login(other, "emp-dev")
        foreign = await other.get(f"/api/v1/conversations/{conv}")
        missing = await other.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"] == missing.json()["error"]


async def test_login_rejects_json_body_sent_as_text_plain(org_engine, migrated):
    """교차 사이트 폼·text/plain 전송(사전 요청 없음)으로는 로그인할 수 없다."""
    async with api_client(_session_app(migrated)) as client:
        plain = await client.post(
            "/api/v1/session",
            content='{"username": "emp-sales", "password": "demo-emp-sales-1017"}',
            headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
        )
    assert plain.status_code == 422 and "set-cookie" not in plain.headers


async def test_operator_role_never_reaches_web_session_or_employee_rights(org_engine, migrated):
    identity = IdentityService(org_engine, FixedClock())
    operator = await identity.resolve_operator_actor("ops-admin")
    # 운영 계정에 직원 역할을 더해도 운영 actor는 ops.*만 갖는다.
    await identity.change_membership(
        operator, "ops-admin", department_ids=("dept-mgmt",), role_ids=("operator", "employee")
    )
    operator = await identity.resolve_operator_actor("ops-admin")
    assert all(c.startswith("ops.") for c in operator.capabilities)
    # 비밀번호 해시가 생겨도 web_login=false면 웹 로그인 불가.
    async with org_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET password_hash = :h WHERE id = 'ops-admin'"), {"h": hash_password("p")}
        )
    with pytest.raises(AppError):
        await identity.login("ops-admin", "p")
    # 직원 계정이 operator 역할을 얻어도 웹 세션 actor에는 ops.*가 없다(직원 세션에서 운영자로 승격하지 않음).
    await identity.change_membership(
        operator, "emp-dev", department_ids=("dept-dev",), role_ids=("employee", "operator")
    )
    login = await identity.login("emp-dev", PASSWORDS["emp-dev"])
    assert not any(c.startswith("ops.") for c in login.view.capabilities)
    web_actor = await identity.resolve_actor(login.token)
    assert not any(c.startswith(("ops.", "eval.")) for c in web_actor.capabilities)
    # 같은 사람이라도 운영 actor는 ops.*만 갖는다.
    assert "ops.membership_admin" not in (await identity.reload_actor(web_actor)).capabilities
    with pytest.raises(AppError):
        await identity.change_membership(
            web_actor, "emp-sales", department_ids=("dept-sales",), role_ids=("dept_head",)
        )


# --- 검증 에이전트 지적 회귀(2026-10-17) ---


async def test_authorize_denies_after_logout_or_session_expiry(org_engine):
    """Authorize는 세션 회수·만료를 다시 확인한다. 요청 시작 때의 actor 사본으로 계속 허용하지 않는다."""
    clock = FixedClock()
    identity = IdentityService(org_engine, clock, session_ttl_s=60)
    policy = ResourcePolicy("authenticated")
    login = await identity.login("emp-sales", PASSWORDS["emp-sales"])
    actor = await identity.resolve_actor(login.token)
    assert actor.session_ref and (await identity.authorize(actor, "knowledge.search", policy)).allowed
    await identity.logout(login.token)
    assert (await identity.authorize(actor, "knowledge.search", policy)).reason == "unauthenticated"
    second = await identity.login("emp-sales", PASSWORDS["emp-sales"])
    actor2 = await identity.resolve_actor(second.token)
    clock.advance(60)
    assert not (await identity.authorize(actor2, "knowledge.search", policy)).allowed
    # 세션 참조가 없거나 다른 사람의 세션을 가리키는 사본도 거부한다.
    forged = ActorContext(
        actor2.user_id, actor2.department_ids, actor2.role_ids, actor2.capabilities, 1, "local_session", None
    )
    assert not (await identity.authorize(forged, "knowledge.search", policy)).allowed


async def test_inactive_user_cannot_login_even_with_right_password(org_engine):
    async with org_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET active = false WHERE id = 'emp-dev'"))
    identity = IdentityService(org_engine, FixedClock())
    with pytest.raises(AppError) as error:
        await identity.login("emp-dev", PASSWORDS["emp-dev"])
    assert error.value.code is ErrorCode.AUTHENTICATION_REQUIRED
    # fixture를 다시 적재해도 비활성 계정을 되살리지 않는다.
    await load_demo_org(org_engine, FIXTURE_NOW)
    with pytest.raises(AppError):
        await identity.login("emp-dev", PASSWORDS["emp-dev"])


async def test_cookie_max_age_matches_session_ttl(org_engine, migrated):
    async with api_client(_session_app(migrated, session_ttl_s=120)) as client:
        response = await _login(client)
    assert "Max-Age=120" in response.headers["set-cookie"]


async def test_login_rejects_json_like_content_type_that_is_not_application_json(org_engine, migrated):
    """application/*+json은 FastAPI가 JSON으로 읽지만 로그인은 application/json만 받는다(방어 이중화)."""
    async with api_client(_session_app(migrated)) as client:
        response = await client.post(
            "/api/v1/session",
            content='{"username": "emp-sales", "password": "demo-emp-sales-1017"}',
            headers={"Origin": ORIGIN, "Content-Type": "application/merge-patch+json"},
        )
    assert response.status_code == 422 and "set-cookie" not in response.headers


def test_restricted_policy_still_requires_capabilities():
    policy = ResourcePolicy(
        "restricted",
        allowed_role_ids=frozenset({"employee"}),
        required_capabilities=frozenset({"ticket.read_all"}),
    )
    assert evaluate(ACTOR, "knowledge.search", policy).reason == "missing_capability"


async def test_csrf_token_is_bound_to_its_own_session_and_must_match_exactly(org_engine, migrated):
    async with api_client(_session_app(migrated)) as other:
        other_csrf = (await _login(other, "emp-dev")).json()["csrf_token"]
    async with api_client(_session_app(migrated)) as client:
        mine = (await _login(client)).json()["csrf_token"]
        foreign = await client.post(
            "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": other_csrf}
        )
        truncated = await client.post(
            "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": mine[:-1]}
        )
        non_ascii = await client.post(
            "/api/v1/conversations", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": "토큰".encode()}
        )
        no_origin_logout = await client.delete("/api/v1/session", headers={"X-CSRF-Token": mine})
        still = await client.get("/api/v1/session")
    assert foreign.status_code == truncated.status_code == non_ascii.status_code == 403
    assert non_ascii.json()["error"]["code"] == "CSRF_FAILED"
    assert (no_origin_logout.status_code, no_origin_logout.json()["error"]["code"]) == (403, "CSRF_FAILED")
    assert still.status_code == 200


async def test_login_rejects_nul_and_malformed_policy_types(org_engine, migrated):
    async with api_client(_session_app(migrated)) as client:
        nul = await client.post(
            "/api/v1/session",
            json={"username": "emp\u0000sales", "password": "x"},
            headers={"Origin": ORIGIN},
        )
    assert nul.status_code == 422
    assert ResourcePolicy.from_mapping({"audience": []}) is None
    assert ResourcePolicy.from_mapping({"audience": None}) is None


async def test_reload_password_change_revokes_sessions_and_new_password_works(org_engine, tmp_path):
    import json

    from agent.modules.identity_access.service import DEMO_ORG_PATH

    identity = IdentityService(org_engine, FixedClock())
    login = await identity.login("emp-sales", PASSWORDS["emp-sales"])
    data = json.loads(DEMO_ORG_PATH.read_text(encoding="utf-8"))
    for user in data["users"]:
        if user["id"] == "emp-sales":
            user["password"] = "changed-password-1"
            user["roles"] = ["employee", "approver"]
    changed = tmp_path / "org.json"
    changed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    await load_demo_org(org_engine, FIXTURE_NOW, changed)
    with pytest.raises(AppError) as error:
        await identity.resolve_actor(login.token)
    assert error.value.code is ErrorCode.SESSION_EXPIRED
    with pytest.raises(AppError):
        await identity.login("emp-sales", PASSWORDS["emp-sales"])
    assert (await identity.login("emp-sales", "changed-password-1")).view.user_id == "emp-sales"
    audit = await _scalar(
        org_engine,
        "SELECT count(*) FROM membership_audit WHERE user_id = 'emp-sales' AND actor_id = 'seed-identity'",
    )
    assert audit == 1


async def test_change_membership_rejects_unknown_or_duplicate_ids(org_engine):
    identity = IdentityService(org_engine, FixedClock())
    operator = await identity.resolve_operator_actor("ops-admin")
    for departments, roles in [
        (("dept-x",), ("employee",)),
        (("dept-dev",), ("superuser",)),
        (("dept-dev",), ("employee", "employee")),
    ]:
        with pytest.raises(AppError) as error:
            await identity.change_membership(operator, "emp-dev", department_ids=departments, role_ids=roles)
        assert error.value.code is ErrorCode.INVALID_REQUEST


async def test_login_hashing_does_not_block_event_loop(org_engine):
    """scrypt는 스레드에서 돈다. 동시 로그인 중에도 이벤트 루프가 크게 멈추지 않는다."""
    import asyncio
    import time

    identity = IdentityService(org_engine, FixedClock())
    gaps: list[float] = []
    stop = False

    async def ticker():
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    results = await asyncio.gather(
        *(identity.login("emp-sales", "wrong") for _ in range(8)), return_exceptions=True
    )
    stop = True
    await task
    assert all(isinstance(r, AppError) for r in results)
    assert max(gaps) < 0.06  # scrypt 1회(약 65ms)보다 짧다
