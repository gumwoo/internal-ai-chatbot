"""Wiki 운영 CLI 조립(APP-03). 실시간 대화와 별개로 운영자가 빌드·검수·게시한다(MOD-10, 04-api-spec).

순서: draft-wiki-topics(제목만 보고 주제 계획 초안, 💰) → 사람/검수자가 계획 확인 → review-wiki-topics
→ build-wiki(page 생성·원문 대조·임베딩, 💰 + Gemini 무료 티어) → export-wiki-review → 의미 검수
→ apply-wiki-review → publish-wiki. 평가 질문·정답은 어느 단계의 입력에도 넣지 않는다.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.modules.model_integration.ports import (
    ChatModel,
    ModelCallError,
    ModelConfig,
    ModelMessage,
    ModelRequest,
)
from agent.modules.wiki import build as wb
from agent.shared.settings import REPO_ROOT

TOPIC_PLAN_PATH = REPO_ROOT / "data" / "wiki" / "topic-plan.json"
REVIEW_DIR = REPO_ROOT / "data" / "wiki" / "reviews"
TOPIC_PROMPT_VERSION = "wiki-topics-v1"
MAX_DOCS_PER_TOPIC = 8

TOPIC_SYSTEM = """사내 문서 목록을 탐색용 주제로 묶는다. 문서 본문은 보지 않고 제목·종류만 본다.
- 한 주제는 직원이 함께 찾을 만한 업무 절차·규정 묶음이다(예: 출장비 정산, 휴가 신청). 2~8개 문서.
- 모든 문서가 적어도 한 주제에 들어가야 한다. 한 문서는 최대 두 주제까지.
- topic_key는 영문 소문자·숫자·하이픈(예: travel-expense). title은 한국어 짧은 이름.
- 개정 전후 판본은 같은 문서 키라 한 번만 나온다. 문서 키를 지어내지 않는다."""

TOPIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_key": {"type": "string"},
                    "title": {"type": "string"},
                    "document_keys": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic_key", "title", "document_keys"],
            },
        }
    },
    "required": ["topics"],
}


def documents_by_domain(manifest: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """manifest의 문서 키 단위 목록(현행 판본 제목 우선). 본문은 넣지 않는다."""
    seen: dict[str, dict[str, str]] = {}
    for entry in manifest["files"]:
        if entry.get("edition_state") == "withdrawn":
            continue
        key = entry["document_key"]
        if key not in seen or entry.get("edition_state") == "current":
            seen[key] = {
                "document_key": key,
                "title": re.sub(r"\s*\[종전\]\s*$", "", entry["title"]),
                "document_type": entry.get("document_type", ""),
                "domain": entry.get("domain", ""),
            }
    grouped: dict[str, list[dict[str, str]]] = {}
    for doc in sorted(seen.values(), key=lambda d: d["document_key"]):
        grouped.setdefault(doc["domain"], []).append(doc)
    return grouped


async def draft_topic_plan(
    chat: ChatModel, config: ModelConfig, manifest: dict[str, Any], now: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    """도메인마다 한 번 호출해 주제 계획 초안(needs_review)을 만든다. 빠진 문서는 단독 주제로 채운다."""
    topics: list[dict[str, Any]] = []
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0}
    notes: list[str] = []
    used: set[str] = set()
    for domain, docs in documents_by_domain(manifest).items():
        keys = {d["document_key"] for d in docs}
        listing = "\n".join(f"- {d['document_key']} | {d['title']} | {d['document_type']}" for d in docs)
        request = ModelRequest(
            purpose="wiki_build",
            messages=(ModelMessage(role="user", text=f"도메인: {domain}\n문서 목록:\n{listing}"),),
            tools=(),
            output_contract=TOPIC_SCHEMA,
            timeout_s=60.0,
            model_config=config,
            system=TOPIC_SYSTEM,
        )
        usage["calls"] += 1
        try:
            response = await chat.complete_once(request)
        except ModelCallError as error:
            # 실패한 호출도 비용을 모른다고 남기고, 이 도메인 문서는 단독 주제로 채워 검수자가 보게 한다.
            usage["unknown_usage_calls"] += 1
            notes.append(f"{domain}: 주제 초안 호출 실패({error.kind.value}), 단독 주제로 채움")
            response = None
        if response is None:
            for doc in docs:
                key = _unique_key(f"doc-{doc['document_key'].lower()}", used)
                used.add(key)
                topics.append(
                    {
                        "topic_key": key,
                        "title": doc["title"],
                        "document_keys": [doc["document_key"]],
                        "domain": domain,
                    }
                )
            continue
        if response.usage.input_tokens is None or response.usage.output_tokens is None:
            usage["unknown_usage_calls"] += 1
        usage["input_tokens"] += response.usage.input_tokens or 0
        usage["output_tokens"] += response.usage.output_tokens or 0
        covered: set[str] = set()
        for item in (response.final_candidate or {}).get("topics", []):
            members = [k for k in dict.fromkeys(item.get("document_keys") or []) if k in keys]
            dropped = [k for k in item.get("document_keys") or [] if k not in keys]
            if dropped:
                notes.append(f"{domain}: 목록에 없는 문서 키 제외 {dropped}")
            key = _unique_key(str(item.get("topic_key", "")), used)
            if not members or not key:
                continue
            if len(members) > MAX_DOCS_PER_TOPIC:
                notes.append(f"{key}: 문서 {len(members)}개(상한 {MAX_DOCS_PER_TOPIC} 초과, 검수 때 나눌 것)")
            used.add(key)
            covered.update(members)
            topics.append(
                {
                    "topic_key": key,
                    "title": str(item.get("title", "")).strip() or key,
                    "document_keys": members,
                    "domain": domain,
                }
            )
        for doc in docs:
            if doc["document_key"] not in covered:
                key = _unique_key(f"doc-{doc['document_key'].lower()}", used)
                used.add(key)
                topics.append(
                    {
                        "topic_key": key,
                        "title": doc["title"],
                        "document_keys": [doc["document_key"]],
                        "domain": domain,
                    }
                )
                notes.append(f"{doc['document_key']}: 모델이 빠뜨려 단독 주제로 채움")
    plan = {
        "version": 1,
        "status": "needs_review",
        "generated_at": now.isoformat(),
        "drafted_by": {"model": config.model, "prompt_version": TOPIC_PROMPT_VERSION, "input": "titles_only"},
        "notes": notes,
        "topics": topics,
    }
    return plan, usage


def _unique_key(raw: str, used: set[str]) -> str:
    key = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")[:56]
    if not key or not re.match(r"^[a-z0-9]", key):
        return ""
    candidate, n = key, 2
    while candidate in used:
        candidate, n = f"{key}-{n}", n + 1
    return candidate


def review_topic_plan(
    plan: dict[str, Any], manifest: dict[str, Any], reviewer: str, now: datetime
) -> list[str]:
    """검수 표시 전 검사: 모든 문서가 주제에 있고, 없는 문서 키가 없고, 계획 형식이 맞아야 한다."""
    problems: list[str] = []
    known = {
        key for docs in documents_by_domain(manifest).values() for key in (d["document_key"] for d in docs)
    }
    used = {k for t in plan.get("topics", []) for k in t.get("document_keys", [])}
    if missing := sorted(known - used):
        problems.append(f"주제에 없는 문서: {missing}")
    if unknown := sorted(used - known):
        problems.append(f"manifest에 없는 문서 키: {unknown}")
    if not reviewer.strip():
        problems.append("검수자 이름이 없다")
    try:
        wb.load_topic_plan({**plan, "status": "reviewed"})
    except wb.TopicPlanError as error:
        problems.append(str(error))
    if not problems:
        plan["status"] = "reviewed"
        plan["reviewed_by"] = reviewer
        plan["reviewed_at"] = now.isoformat()
    return problems


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
