"""manifest 검수 규칙 적용(D-36·D-40, docs/15-policy-options.md P-15·P-19).

- D-36: available_from = 시행일 00:00 KST(가상 회사 설정 값). 안내 개정 쌍의 guidance 판본 구간도 같은 규칙.
  나머지 초안 제안값은 일괄 승인한다(검사에서 걸리는 것만 고친다).
- D-40: 문서 우선관계(authority_relations)는 현행 문서 본문에서 다른 문서 번호를 명시한 문장으로 초안을 쓰고,
  근거 문장을 그대로 남긴다. 경과조항(transition_relations)은 원문 조항을 읽고 사건 조건을 닫힌 값으로 옮긴
  아래 TRANSITIONS를 쓴다. 닫힌 값으로 옮길 수 없는 조항은 넣지 않는다(목록 밖은 적용하지 않음).
원문에서 관계를 "추정"하지 않는다. 문장에 적힌 관계만 옮기고, 그 문장을 근거로 남긴다.
"""

import re
from datetime import date
from typing import Any

from agent.modules.ingestion.manifest import kst_midnight
from agent.modules.ingestion.parser import ParsedDocument

REVIEW_RULE = "D-36·D-40 일괄 승인(2026-10-18, 사용자 결정)"

# 원문 경과조항(D-40). 사건 표현 → 닫힌 값:
# "상신" → request_date, "최종 승인" → approval_date, "처리" → processing_date.
TRANSITIONS: tuple[dict[str, Any], ...] = (
    {
        "from_source_file_id": "PDF-091",
        "to_source_file_id": "PDF-092",
        "clause_anchor": "제9조(미결 문서)",
        "application_basis": "approval_date",
        "event_conditions": [
            {"event": "request_date", "compare": "before", "date": "2026-10-01"},
            {"event": "approval_date", "compare": "on_or_after", "date": "2026-10-01"},
        ],
        "authority_relation": "current_rules_apply",
        "basis_evidence": (
            "PDF-092 제9조: 2026년 9월 30일 이전에 상신했으나 10월 1일 이후 최종 승인되는 문서는 개정된 "
            "승인 확인·이력 기준에 따라 재검토한다. 상신→request_date, 최종 승인→approval_date(D-40)"
        ),
    },
    {
        "from_source_file_id": "PDF-042",
        "to_source_file_id": "PDF-041",
        "clause_anchor": "제13조(종전 기준과의 관계)",
        "application_basis": "processing_date",
        "event_conditions": [{"event": "processing_date", "compare": "before", "date": "2026-10-01"}],
        "authority_relation": "past_reference_current_recheck",
        "basis_evidence": (
            "PDF-041 제13조: 2026년 9월 30일까지 처리된 계정 업무의 경과 확인에는 당시의 운영기준을 "
            "참고하되, "
            "현재 활성 상태의 인증 및 접근통제는 현행 정책에 따라 재점검한다. 처리→processing_date(D-40)"
        ),
    },
)

_CODE = re.compile(r"(?<![A-Z0-9])((?:HR|ED|IT|SEC|GA|CM)-\d{3})(?!\d)((?:[·~]\d{3}(?!\d))*)")
_LIMITED = re.compile(r"범위 안에서만")
_PRECEDES = re.compile(r"우선 확인|먼저 거친다|먼저 확인")
_DEFERS = re.compile(r"따른다|따라|적용한다|을 따르|를 따르|함께 적용")


def apply_review(manifest: dict[str, Any], documents: dict[str, ParsedDocument]) -> list[str]:
    """manifest를 제자리에서 검수 상태로 바꾸고 바꾼 내용을 요약해 돌려준다."""
    files = manifest["files"]
    notes: list[str] = []
    codes = {e["source_document_number"].removeprefix("GW-"): e["document_key"] for e in files}
    for entry in files:
        if entry["available_from"] is None and entry["effective_from"]:
            entry["available_from"] = kst_midnight(date.fromisoformat(entry["effective_from"]))
    notes.append("available_from: 시행일 00:00 KST(D-36)")
    by_key: dict[str, list[dict[str, Any]]] = {}
    for entry in files:
        by_key.setdefault(entry["document_key"], []).append(entry)
    for editions in by_key.values():
        guidance = sorted(
            (e for e in editions if e["document_role"] == "guidance"), key=lambda e: e["effective_from"] or ""
        )
        for index, entry in enumerate(guidance):
            if entry["guidance_valid_from"] is None:
                entry["guidance_valid_from"] = entry["available_from"]
            if index + 1 < len(guidance) and entry["guidance_valid_to"] is None:
                entry["guidance_valid_to"] = guidance[index + 1]["available_from"]
    relations = 0
    for entry in files:
        if entry["edition_state"] == "current" and entry["source_file_id"] in documents:
            own = entry["source_document_number"].removeprefix("GW-")
            entry["authority_relations"] = draft_authority_relations(
                documents[entry["source_file_id"]], own, codes
            )
            relations += len(entry["authority_relations"])
    notes.append(f"authority_relations: 본문 명시 문장 {relations}건(D-40)")
    ids = {e["source_file_id"]: e for e in files}
    for relation in TRANSITIONS:
        base = ids.get(relation["from_source_file_id"])
        if base is not None and relation["to_source_file_id"] in ids:
            base["transition_relations"] = [
                *[
                    r
                    for r in base["transition_relations"]
                    if r.get("clause_anchor") != relation["clause_anchor"]
                ],
                dict(relation),
            ]
    notes.append(f"transition_relations: 원문 경과조항 {len(TRANSITIONS)}건(D-40)")
    for entry in files:
        entry["review_status"] = "reviewed"
        if REVIEW_RULE not in entry["review_notes"]:
            entry["review_notes"].append(REVIEW_RULE)
    manifest["status"] = "reviewed"
    manifest["note"] = (
        "MOD-06 초안에 D-36(공개 시각=시행일 00:00 KST, 제안값 일괄 승인)과 D-40(원문 명시 관계)을 적용한 "
        "검수본이다. 근거는 basis_evidence·review_notes·관계별 quote/basis_evidence에 있다."
    )
    return notes


def draft_authority_relations(
    document: ParsedDocument, own_code: str, codes: dict[str, str]
) -> list[dict[str, Any]]:
    """다른 문서 번호와 관계 표현이 함께 있는 본문 문장(표·머리말 제외, FAQ 예시 답변 제외)."""
    own_key = codes.get(own_code)  # 현행본이 자기 종전본 번호를 말해도 자기 문서 관계로 만들지 않는다
    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for page in document.pages:
        for block in page.blocks:
            if block.kind in ("header", "footer", "table"):
                continue
            for sentence in re.split(r"(?<=다\.)\s*", block.text.replace("\n", "")):
                sentence = sentence.strip()
                if not sentence or sentence.startswith("답변"):
                    continue
                kind = (
                    "limited_by"
                    if _LIMITED.search(sentence)
                    else "precedes"
                    if _PRECEDES.search(sentence)
                    else "defers_to"
                    if _DEFERS.search(sentence)
                    else None
                )
                if kind is None:
                    continue
                for code in _codes(sentence):
                    key = codes.get(code)
                    if key is None or code == own_code or key == own_key or (key, kind) in seen:
                        continue
                    seen.add((key, kind))
                    relations.append(
                        {
                            "kind": kind,
                            "target_document_key": key,
                            "target_code": code,
                            "page": page.page,
                            "quote": sentence[:300],
                        }
                    )
    return relations


def _codes(sentence: str) -> list[str]:
    """ "SEC-065~067"·"SEC-063·064"처럼 줄여 쓴 번호도 펼친다."""
    out: list[str] = []
    for match in _CODE.finditer(sentence):
        first = match.group(1)
        prefix, number = first.rsplit("-", 1)
        out.append(first)
        for sep, tail in re.findall(r"([·~])(\d{3})", match.group(2)):
            if sep == "~":
                out.extend(f"{prefix}-{n:03d}" for n in range(int(number) + 1, int(tail) + 1))
            else:
                out.append(f"{prefix}-{tail}")
            number = tail
    return out
