"""자원 정책 판정(Authorize의 순수 부분, CT-01 AccessDecision).

- 인증·행위 capability·자원 허용 범위가 모두 충족돼야 한다.
- 기본 거부. 비어 있거나 알 수 없는 정책은 거부. 전사 공개도 명시적인 audience=authenticated다.
- restricted는 허용 사용자·부서·역할 집합의 합집합으로 판정하고, required_capabilities를 모두 요구한다.
- 거부 사유에 자원 제목·내용을 넣지 않는다(reason은 닫힌 짧은 코드).
"""

from dataclasses import dataclass, field
from typing import Any

from agent.shared.actor import CAPABILITIES, ActorContext

AUDIENCES = frozenset({"authenticated", "restricted"})


@dataclass(frozen=True)
class ResourcePolicy:
    audience: str
    allowed_user_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_department_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_role_ids: frozenset[str] = field(default_factory=frozenset)
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    revision: int = 1

    @classmethod
    def from_mapping(cls, raw: Any) -> "ResourcePolicy | None":
        """저장된 정책(dict) → ResourcePolicy. 모르는 키·값이 있으면 None(거부 대상)."""
        if not isinstance(raw, dict):
            return None
        known = {
            "audience",
            "allowed_user_ids",
            "allowed_department_ids",
            "allowed_role_ids",
            "required_capabilities",
            "revision",
        }
        audience = raw.get("audience")
        if set(raw) - known or not isinstance(audience, str) or audience not in AUDIENCES:
            return None
        lists = ("allowed_user_ids", "allowed_department_ids", "allowed_role_ids", "required_capabilities")
        # 집합 값은 목록이어야 한다. 문자열 하나("hr_staff")를 글자 집합으로 풀어 허용하지 않게 한다.
        if any(not isinstance(raw.get(key, []), list | tuple) for key in lists):
            return None
        try:
            sets = {
                key: frozenset(str(v) for v in raw.get(key) or ())
                for key in (
                    "allowed_user_ids",
                    "allowed_department_ids",
                    "allowed_role_ids",
                    "required_capabilities",
                )
            }
            revision = int(raw.get("revision", 1))
        except (TypeError, ValueError):
            return None
        if not sets["required_capabilities"] <= CAPABILITIES:
            return None
        return cls(audience=raw["audience"], revision=revision, **sets)


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str  # allowed / missing_capability / not_in_audience / invalid_policy / unauthenticated
    policy_revision: int | None = None


def evaluate(actor: ActorContext | None, capability: str, policy: ResourcePolicy | None) -> AccessDecision:
    if actor is None:
        return AccessDecision(False, "unauthenticated")
    if capability not in CAPABILITIES or capability not in actor.capabilities:
        return AccessDecision(False, "missing_capability", policy.revision if policy else None)
    if policy is None or policy.audience not in AUDIENCES:
        return AccessDecision(False, "invalid_policy")
    if not policy.required_capabilities <= actor.capabilities:
        return AccessDecision(False, "missing_capability", policy.revision)
    if policy.audience == "authenticated":
        return AccessDecision(True, "allowed", policy.revision)
    member = (
        actor.user_id in policy.allowed_user_ids
        or bool(policy.allowed_department_ids & set(actor.department_ids))
        or bool(policy.allowed_role_ids & set(actor.role_ids))
    )
    # 허용 집합이 모두 비어 있는 restricted는 아무도 허용하지 않는다(빈 정책 거부).
    return AccessDecision(member, "allowed" if member else "not_in_audience", policy.revision)
