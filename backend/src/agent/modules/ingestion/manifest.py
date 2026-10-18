"""manifest 검증(ValidateInput, T-18)과 초안 작성(MOD-06).

검증
- 입력 루트 안의 PDF만(상위 경로·URL·절대 경로 거절), 파일 존재·SHA-256 일치, 파일 ID·파일명·hash 유일.
- 100파일·91 논리 키·종전 9건(release일 때), 같은 문서 키 개정 쌍의 대체 관계, 규범 적용 구간 겹침 없음.
- 필수 필드·닫힌 값. 미검수(review_status != reviewed)는 "게시 불가"로 보고한다(검증 자체는 통과할 수 있다).

초안(draft)
- 수령 목록(docs/corpus/02-received-register.md)과 PDF 본문에서 근거가 있는 값만 채운다.
  값마다 근거(page·quote)를 남긴다.
- 원문으로 정할 수 없는 값(available_from·guidance 판본 구간·경과조항 관계)은 비워 두고
  review_status=needs_review다.
- ACL은 D-31(사용자 결정)을 그대로 적는다. 문서 영역만 보고 소관·권한을 추정하지 않는다.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from agent.modules.ingestion.parser import ParsedDocument
from agent.modules.knowledge.contracts import APPLICATION_BASIS, EditionMetadata
from agent.shared.clock import KST

REQUIRED_FIELDS = (
    "source_file_id",
    "document_key",
    "version",
    "filename",
    "title",
    "domain",
    "document_type",
    "source_document_number",
    "document_role",
    "application_basis",
    "basis_evidence",
    "available_from",
    "effective_from",
    "effective_to",
    "guidance_valid_from",
    "guidance_valid_to",
    "transition_relations",
    "supersedes_source_file_id",
    "edition_state",
    "owning_department",
    "classification",
    "access_policy",
    "access_policy_source",
    "related_document_keys",
    "authority_relations",
    "review_status",
    "sha256",
)
REVIEW_STATUSES = frozenset({"reviewed", "needs_review"})
# 관계 형식(D-40, docs/corpus/01-metadata-contract.md)
AUTHORITY_KINDS = frozenset({"defers_to", "precedes", "limited_by"})
TRANSITION_EFFECTS = frozenset({"current_rules_apply", "past_reference_current_recheck"})
EVENT_COMPARES = frozenset({"before", "on_or_after"})
DOMAINS = {
    "HR": "인사·근태",
    "ED": "교육·연수",
    "IT": "IT 지원",
    "SEC": "정보보안·개인정보",
    "GA": "총무·재무",
    "CM": "공통 업무·문서 관리",
}


@dataclass
class ManifestReport:
    errors: list[str] = field(default_factory=list)
    not_publishable: list[str] = field(default_factory=list)
    files: int = 0
    document_keys: int = 0
    superseded: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_hash(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def validate_manifest(
    manifest: dict[str, Any], input_root: Path, *, release: bool, check_hash: bool = True
) -> ManifestReport:
    report = ManifestReport()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        report.errors.append("files가 비어 있거나 목록이 아님")
        return report
    root = input_root.resolve()
    ids, names, hashes, versions = set(), set(), set(), set()
    keys: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        label = str(entry.get("source_file_id", "?"))
        missing = [name for name in REQUIRED_FIELDS if name not in entry]
        if missing:
            report.errors.append(f"{label}: 필수 필드 없음 {missing}")
            continue
        if label in ids:
            report.errors.append(f"{label}: 파일 ID 중복")
        ids.add(label)
        filename = entry["filename"]
        path = _safe_path(root, filename)
        if path is None:
            report.errors.append(f"{label}: 입력 루트 밖이거나 PDF가 아닌 경로({filename})")
            continue
        if filename.lower() in names:
            report.errors.append(f"{label}: 파일명 중복 매핑")
        names.add(filename.lower())
        if not path.is_file():
            report.errors.append(f"{label}: 파일 없음({filename})")
            continue
        if check_hash:
            actual = _sha256(path)
            if actual != entry["sha256"]:
                report.errors.append(f"{label}: SHA-256 불일치")
            if actual in hashes:
                report.errors.append(f"{label}: 같은 내용의 파일이 다른 ID로 중복")
            hashes.add(actual)
        version_key = (entry["document_key"], entry["version"])
        if version_key in versions:
            report.errors.append(f"{label}: 문서 키+판본 중복")
        versions.add(version_key)
        if entry["document_role"] not in ("normative", "guidance"):
            report.errors.append(f"{label}: document_role 값 오류")
        if entry["application_basis"] not in APPLICATION_BASIS:
            report.errors.append(f"{label}: application_basis 값 오류")
        if entry["edition_state"] not in ("current", "superseded", "withdrawn"):
            report.errors.append(f"{label}: edition_state 값 오류")
        if entry["review_status"] not in REVIEW_STATUSES:
            report.errors.append(f"{label}: review_status 값 오류")
        elif entry["review_status"] != "reviewed":
            report.not_publishable.append(f"{label}: 미검수({entry['review_status']})")
        try:
            effective_from = _date(entry["effective_from"])
            effective_to = _date(entry["effective_to"])
            _datetime(entry["available_from"])
        except ValueError as exc:
            report.errors.append(f"{label}: 날짜 형식 오류({exc})")
            continue
        if entry["document_role"] == "normative" and effective_from is None:
            report.errors.append(f"{label}: 규범 판본에 effective_from 없음")
        if effective_from and effective_to and effective_to <= effective_from:
            report.errors.append(f"{label}: 적용 구간이 비어 있음")
        if entry["available_from"] is None and entry["review_status"] == "reviewed":
            report.errors.append(f"{label}: 검수됨인데 available_from 없음")
        keys.setdefault(entry["document_key"], []).append(entry)
    report.files = len(ids)
    report.errors.extend(check_relations([e for e in entries if all(n in e for n in REQUIRED_FIELDS)]))
    report.document_keys = len(keys)
    report.superseded = sum(1 for e in entries if e.get("edition_state") == "superseded")
    for key, editions in keys.items():
        _check_editions(key, editions, ids, report)
        policies = {json.dumps(e["access_policy"], sort_keys=True) for e in editions}
        if len(policies) > 1:
            report.errors.append(f"{key}: 판본끼리 access_policy가 다름")
    if release:
        if report.files != 100:
            report.errors.append(f"release는 100파일이어야 함(현재 {report.files})")
        if report.document_keys != 91:
            report.errors.append(f"release는 논리 문서 91종이어야 함(현재 {report.document_keys})")
        if report.superseded != 9:
            report.errors.append(f"release는 종전 판본 9건이어야 함(현재 {report.superseded})")
    return report


def _check_editions(key: str, editions: list[dict[str, Any]], ids: set[str], report: ManifestReport) -> None:
    current = [e for e in editions if e["edition_state"] == "current"]
    if len(current) > 1:
        report.errors.append(f"{key}: 현행 판본이 둘 이상")
    for entry in editions:
        supersedes = entry["supersedes_source_file_id"]
        if supersedes is not None and supersedes not in {e["source_file_id"] for e in editions}:
            report.errors.append(f"{entry['source_file_id']}: 대체 대상이 같은 문서 키에 없음({supersedes})")
        if supersedes is not None and supersedes not in ids:
            report.errors.append(f"{entry['source_file_id']}: 대체 대상 파일 없음")
    windows = sorted(
        (
            (_date(e["effective_from"]), _date(e["effective_to"]), e["source_file_id"])
            for e in editions
            if e["document_role"] == "normative" and e["effective_from"]
        ),
        key=lambda w: w[0],
    )
    for (_, end_a, file_a), (start_b, _, file_b) in zip(windows, windows[1:], strict=False):
        if end_a is None or end_a > start_b:
            report.errors.append(f"{key}: 규범 적용 구간 겹침({file_a}, {file_b})")


def to_metadata(entry: dict[str, Any]) -> EditionMetadata:
    return EditionMetadata(
        source_file_id=entry["source_file_id"],
        document_key=entry["document_key"],
        version=entry["version"],
        filename=entry["filename"],
        title=entry["title"],
        domain=entry["domain"],
        document_type=entry["document_type"],
        source_document_number=entry["source_document_number"],
        document_role=entry["document_role"],
        application_basis=entry["application_basis"],
        basis_evidence=tuple(entry["basis_evidence"]),
        available_from=_datetime(entry["available_from"]),
        effective_from=_date(entry["effective_from"]),
        effective_to=_date(entry["effective_to"]),
        guidance_valid_from=_datetime(entry["guidance_valid_from"]) if entry["guidance_valid_from"] else None,
        guidance_valid_to=_datetime(entry["guidance_valid_to"]) if entry["guidance_valid_to"] else None,
        supersedes_source_file_id=entry["supersedes_source_file_id"],
        edition_state=entry["edition_state"],
        owning_department=entry["owning_department"],
        access_policy=entry["access_policy"],
        access_policy_source=entry["access_policy_source"],
        review_status=entry["review_status"],
        transition_relations=tuple(entry["transition_relations"]),
        authority_relations=tuple(entry["authority_relations"]),
        related_document_keys=tuple(entry["related_document_keys"]),
    )


def _safe_path(root: Path, filename: Any) -> Path | None:
    if not isinstance(filename, str) or not filename or "://" in filename or "\\" in filename:
        return None
    pure = PurePosixPath(filename)
    # 드라이브 문자("C:")·상위 경로·절대 경로를 모두 거절한다.
    # Windows에서 "C:/x"는 POSIX 경로로는 상대 경로처럼 보인다.
    if filename != pure.as_posix() or filename.startswith("./"):
        return None  # "./x.pdf", "a//b.pdf" 같은 다른 표기로 같은 파일을 가리키지 않게
    if pure.is_absolute() or ".." in pure.parts or any(":" in part for part in pure.parts):
        return None
    if pure.suffix.lower() != ".pdf":
        return None
    path = (root / Path(*pure.parts)).resolve()
    return path if root in path.parents else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _date(value: Any) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("시간대가 없는 시각")
    return parsed


# --- 초안 ---

_REGISTER_ROW = re.compile(
    r"^\| (PDF-\d{3}) \| (DOC-\d{3}) \| (GW-[A-Z]+-\d{3})<br>(\S+\.pdf) \| (\d+) \| (현행|종전) \| "
    r"([\d.]+) \| ([^|]+) \| ([^|]+) \|$"
)
_EFFECTIVE_ARTICLE = re.compile(r"제1조\(시행일\) 이 규정은 (\d{4})년 (\d{2})월 (\d{2})일부터 시행한다")
_EFFECTIVE_TABLE = re.compile(r"시행일 \| (\d{4})\.(\d{2})\.(\d{2})")
_END_MARK = re.compile(
    r"(?:적용\s?종료\s*(\d{4})\.(\d{2})\.(\d{2})\.?|(\d{4})\.(\d{2})\.(\d{2})\.\s*적용\s?종료)"
)
_OWNER_TABLE = re.compile(r"작성·관리 \| ([^|]+) \|")
_TYPE_SUFFIX = re.compile(
    r"(규정|운영지침|지침|기준|정책|매뉴얼|업무매뉴얼|FAQ|안내|가이드|절차|업무절차|체크리스트)(\s*\(.*\))?$"
)

# docs/corpus/03-received-pdf-adjustments.md "규정 적용일" 표에 근거가 있는 문서군만 사건 기준을 제안한다.
_BASIS_BY_FILE = {
    "ED-021": ("training_start", "ED-021 제12/20조(교육회차 시작일)"),
    "ED-022": ("training_start", "ED-022(교육회차 시작일)"),
    "ED-030": ("training_start", "ED-030 제5조/유의사항(교육 시작일)"),
    "ED-031": ("training_start", "ED-031 제3조(교육 시작일)"),
    "ED-034": ("training_start", "ED-034 제12조(교육회차 시작일)"),
    "GA-081": ("trip_start", "GA-081 제4조(출장 시작일)"),
    "GA-082": ("trip_start", "GA-082 제2조(출장 시작일)"),
    "CM-091": ("approval_date", "CM-091(최종 결재일, CM-092와 대조)"),
    "CM-092": ("approval_date", "CM-092 제2/9조(최종 결재일·경과조건)"),
    "IT-041": ("processing_date", "IT-041(처리일)"),
    "IT-042": ("processing_date", "IT-042(처리일)"),
    "SEC-062": ("processing_date", "SEC-062(처리일)"),
    "GA-090": ("per_claim", "GA-090 1.2(교육비는 교육 시작일, 출장비는 출장 시작일)"),
}
# 원문에 열람 제한이 적힌 문서(D-31). 나머지는 사용자 결정으로 audience=authenticated.
_RESTRICTED = {
    "HR-013": ["hr_staff", "dept_head"],
    "HR-014": ["hr_staff", "dept_head"],
    "CM-093": ["dept_head", "approver", "auditor"],
}


def parse_register(path: Path) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _REGISTER_ROW.match(line.strip())
        if match:
            keys = (
                "source_file_id",
                "document_key",
                "number",
                "filename",
                "pages",
                "state",
                "date",
                "version",
                "owner",
            )
            rows.append(dict(zip(keys, (g.strip() for g in match.groups()), strict=True)))
    return rows


def draft_entry(row: dict[str, str], document: ParsedDocument, sha256: str) -> dict[str, Any]:
    """수령 목록 한 행 + 파싱 결과 → manifest 초안 항목. 근거 없는 값은 비워 둔다."""
    prefix = row["filename"].split("_", 1)[0]
    pages = [(p.page, p.text) for p in document.pages]
    title = _title(document)
    review_notes: list[str] = ["available_from: 원문으로 정할 수 없음(O-02, P-15)"]
    evidence: list[dict[str, Any]] = []

    effective_from, from_quote = (
        _find_date(pages, _EFFECTIVE_ARTICLE)
        or _find_date(pages, _EFFECTIVE_TABLE)
        or (
            None,
            None,
        )
    )
    if from_quote:
        evidence.append({"field": "effective_from", **from_quote})
    else:
        review_notes.append("effective_from: 원문에서 시행일을 찾지 못함")
    effective_to = None
    end = _find_end(pages)
    if end is not None:
        end_date, quote = end
        effective_to = date.fromordinal(end_date.toordinal() + 1)  # "까지"(포함) → 종료 제외 날짜
        evidence.append({"field": "effective_to", "rule": "종료일 포함 표기 → 다음날(종료 제외)", **quote})

    structured = any(_EFFECTIVE_ARTICLE.search(text) for _, text in pages)
    role = "normative" if structured else "guidance"
    review_notes.append(f"document_role: 구조로 제안({'부칙 시행일 조항' if structured else '문서 정보 표'})")
    basis, basis_note = _BASIS_BY_FILE.get(prefix, ("general_reference", None))
    if basis_note:
        evidence.append(
            {
                "field": "application_basis",
                "source": "docs/corpus/03-received-pdf-adjustments.md",
                "note": basis_note,
            }
        )
    else:
        review_notes.append("application_basis: 사건 기준 근거 없음, general_reference 제안")
    owner = _owner(row, pages)
    restricted = _RESTRICTED.get(prefix)
    policy = (
        {"audience": "restricted", "allowed_role_ids": restricted}
        if restricted
        else {"audience": "authenticated"}
    )
    period = _find_period(pages)
    if period:
        review_notes.append(f"적용 기간 표기 있음({period}): guidance_valid 또는 effective 구간 검수 필요")
    if prefix in ("HR-003", "HR-005"):
        review_notes.append(
            "application_basis: 보정 문서에 '신청·처리일 또는 근무일, 질문 사건에 따라 확인'으로 적혀 있어 "
            "닫힌 값 하나로 정할 수 없음(검수 필요)"
        )
    if prefix in ("CM-092", "IT-041"):
        review_notes.append(
            "transition_relations: 원문 경과조항 있음(CM-092 제9조/IT-041 제13조), 사건 조건 매핑 미검수"
        )
    entry = {
        "source_file_id": row["source_file_id"],
        "document_key": row["document_key"],
        "version": row["version"],
        "filename": row["filename"],
        "title": title,
        "domain": DOMAINS[prefix.split("-")[0]],
        "document_type": _document_type(title),
        "source_document_number": row["number"],
        "document_role": role,
        "application_basis": basis,
        "basis_evidence": evidence,
        "available_from": None,
        "effective_from": effective_from.isoformat() if effective_from else None,
        "effective_to": effective_to.isoformat() if effective_to else None,
        "guidance_valid_from": None,
        "guidance_valid_to": None,
        "transition_relations": [],
        "supersedes_source_file_id": None,
        "edition_state": "current" if row["state"] == "현행" else "superseded",
        "owning_department": owner,
        "classification": "대외비" if prefix == "CM-093" else None,
        "access_policy": policy,
        "access_policy_source": "user_decision:D-31"
        + (" (원문 열람 제한 표기)" if restricted else " (기본 authenticated)"),
        "related_document_keys": [],
        "authority_relations": [],
        "review_status": "needs_review",
        "review_notes": review_notes,
        "sha256": sha256,
    }
    return entry


def link_supersession(entries: list[dict[str, Any]]) -> None:
    """같은 문서 키의 현행본이 종전본을 대체한다고 적는다(수령 목록의 현행/종전 표기 근거)."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_key.setdefault(entry["document_key"], []).append(entry)
    for editions in by_key.values():
        current = [e for e in editions if e["edition_state"] == "current"]
        old = [e for e in editions if e["edition_state"] == "superseded"]
        if len(current) == 1 and len(old) == 1:
            current[0]["supersedes_source_file_id"] = old[0]["source_file_id"]


def _title(document: ParsedDocument) -> str:
    for block in document.pages[0].blocks:
        if block.kind in ("header", "footer") or block.kind == "table":
            continue
        return block.text.strip().splitlines()[0]
    return ""


def _document_type(title: str) -> str:
    match = _TYPE_SUFFIX.search(title.replace("[종전]", "").strip())
    return match.group(1) if match else "기타"


def _find_date(pages: list[tuple[int, str]], pattern: re.Pattern) -> tuple[date, dict[str, Any]] | None:
    for page, text in pages:
        match = pattern.search(text)
        if match:
            year, month, day = (int(g) for g in match.groups()[:3])
            return date(year, month, day), {"page": page, "quote": match.group(0)}
    return None


def _find_end(pages: list[tuple[int, str]]) -> tuple[date, dict[str, Any]] | None:
    for page, text in pages[:1]:
        match = _END_MARK.search(text)
        if match:
            groups = [g for g in match.groups() if g]
            year, month, day = (int(g) for g in groups[:3])
            return date(year, month, day), {"page": page, "quote": match.group(0)}
    return None


_PERIOD = re.compile(r"적용\s?기간\s*[:|]?\s*(\d{4}\.\d{2}\.\d{2}\.?\s*~\s*(?:\d{4}\.\d{2}\.\d{2}\.?)?)")


def _find_period(pages: list[tuple[int, str]]) -> str | None:
    for _, text in pages:
        match = _PERIOD.search(text)
        if match:
            return match.group(1).strip()
    return None


def _owner(row: dict[str, str], pages: list[tuple[int, str]]) -> str | None:
    owner = row["owner"]
    if owner and owner != "별도 관리표 확인 필요":
        return owner
    for _, text in pages[:1]:
        match = _OWNER_TABLE.search(text)
        if match:
            return match.group(1).strip()
    return None


def kst_midnight(day: date) -> str:
    return datetime(day.year, day.month, day.day, tzinfo=KST).isoformat()


def check_relations(entries: list[dict[str, Any]]) -> list[str]:
    """관계 형식 검사(T-18 보강). 비어 있으면 통과한다."""
    errors: list[str] = []
    keys = {e["document_key"] for e in entries}
    by_id = {e["source_file_id"]: e for e in entries}
    for entry in entries:
        label = entry["source_file_id"]
        for relation in entry.get("authority_relations") or []:
            if relation.get("kind") not in AUTHORITY_KINDS:
                errors.append(f"{label}: authority_relations 종류 오류")
            if relation.get("target_document_key") == entry["document_key"]:
                errors.append(f"{label}: authority_relations가 자기 문서를 가리킴")
            if relation.get("target_document_key") not in keys:
                errors.append(
                    f"{label}: authority_relations 대상 문서 없음({relation.get('target_document_key')})"
                )
            if not str(relation.get("quote") or "").strip():
                errors.append(f"{label}: authority_relations 근거 문장 없음")
        for relation in entry.get("transition_relations") or []:
            target = by_id.get(relation.get("to_source_file_id"))
            if relation.get("from_source_file_id") != label:
                errors.append(f"{label}: transition_relations 기본 판본이 이 파일이 아님")
            if target is None or target["document_key"] != entry["document_key"] or target is entry:
                errors.append(f"{label}: transition_relations 반대편 판본 오류")
            if relation.get("application_basis") not in APPLICATION_BASIS:
                errors.append(f"{label}: transition_relations application_basis 오류")
            elif relation.get("application_basis") != entry["application_basis"]:
                errors.append(f"{label}: transition_relations application_basis가 기본 판본과 다름")
            if relation.get("authority_relation") not in TRANSITION_EFFECTS:
                errors.append(f"{label}: transition_relations 효력 값 오류")
            if not str(relation.get("clause_anchor") or "").strip():
                errors.append(f"{label}: transition_relations 조항 위치 없음")
            conditions = relation.get("event_conditions") or []
            if not conditions:
                errors.append(f"{label}: transition_relations 사건 조건 없음")
            for condition in conditions:
                try:
                    date.fromisoformat(condition.get("date") or "")
                except ValueError:
                    errors.append(f"{label}: transition_relations 조건 날짜 오류")
                if condition.get("event") not in APPLICATION_BASIS or condition.get("event") in (
                    "general_reference",
                    "per_claim",
                ):
                    errors.append(f"{label}: transition_relations 사건 종류 오류")
                if condition.get("compare") not in EVENT_COMPARES:
                    errors.append(f"{label}: transition_relations 비교 값 오류")
    return errors
