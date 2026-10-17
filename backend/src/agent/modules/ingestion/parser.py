"""PDF → 페이지별 원문 block(MOD-06 추출). pdfplumber(MIT, D-33)를 쓴다.

원문 대응을 잃지 않는 것이 목표다.
- 페이지 원문(page_text)은 block 텍스트를 줄바꿈으로 이은 것이다. block마다 page_text 안의 Unicode 시작/끝
  offset과 bbox(PDF 좌표, pt)를 남긴다. 물리 페이지는 1부터.
- block 텍스트는 원문 줄을 그대로 둔다(한국어 줄바꿈을 일괄로 붙이거나 띄우지 않는다, docs/06-rag-design).
  검색용 정규화는 chunker가 따로 하고 정규화 규칙을 설정 ID로 남긴다.
- 반복 머리말·꼬리말은 지우지 않고 kind=header/footer로 표시한다(청크에서만 뺀다).
- 표는 kind=table로 행·셀을 보존하고, 바로 위의 표 제목 줄을 caption으로 붙인다.
- 빈 추출·글리프 미해석(cid)·한글 비율 이상은 품질 지표로 보고하고, 게시 여부는 검수 단계가 판단한다.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pdfplumber

PARSER_REVISION = "pdfplumber-0.11-blocks-v1"
BlockKind = Literal["header", "footer", "heading", "paragraph", "table"]

# 머리말·꼬리말 영역(pt). 수령 PDF는 A4(842pt)이고 머리말 top≈31, 꼬리말 top≈806이다.
_HEADER_MAX_TOP = 50.0
_FOOTER_MIN_TOP_FROM_BOTTOM = 50.0
# 조항·절·FAQ 문항·별표 같은 제목 줄. 이 줄에서 새 block을 시작한다.
HEADING_RE = re.compile(
    r"^(제\s*\d+\s*장\b|제\s*\d+\s*조(의\s*\d+)?\s*\(|부\s*칙\b|별표\s*\d*|별지\s*제?\s*\d*|붙임\s*\d*|별첨\b|"
    r"표\s*\d+\.|Q\d+\.|업무 처리 기준|업무상 유의사항|자주 묻는 질문)"
)
# "1." "3.1" 같은 번호 제목. 줄바꿈된 본문이 날짜("2026.10.01.")로 시작할 수도 있어
# 앞 줄이 짧게 끝났을 때만 제목으로 본다.
NUMBERED_RE = re.compile(r"^\d{1,2}\.(\d{1,2}\.?)*\s")
_CAPTION_RE = re.compile(r"^(별표|별지|붙임|표\s*\d+|\[표)")
_HANGUL = re.compile(r"[가-힣]")


@dataclass(frozen=True)
class Block:
    block_id: str
    page: int
    kind: BlockKind
    text: str
    bbox: tuple[float, float, float, float]
    start: int
    end: int
    # 줄마다 오른쪽 여백까지 찼는지(줄바꿈이 문단 안의 자동 줄바꿈인지). 검색용 정규화에만 쓴다.
    soft_wraps: tuple[bool, ...] = ()
    rows: tuple[tuple[str, ...], ...] | None = None
    caption: str | None = None


@dataclass(frozen=True)
class ParsedPage:
    page: int
    width: float
    height: float
    text: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ParsedDocument:
    sha256: str
    page_count: int
    pages: tuple[ParsedPage, ...]
    parser_revision: str = PARSER_REVISION
    quality: dict = field(default_factory=dict)


@dataclass
class _Line:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pdf(path: Path) -> ParsedDocument:
    """PDF 하나를 파싱한다. 원본 파일은 읽기만 한다."""
    pages: list[ParsedPage] = []
    quality = {"empty_pages": [], "cid_pages": [], "low_hangul_pages": [], "tables": 0}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parsed = _parse_page(page)
            pages.append(parsed)
            body = "".join(b.text for b in parsed.blocks if b.kind not in ("header", "footer"))
            if not body.strip():
                quality["empty_pages"].append(parsed.page)
            if "(cid:" in parsed.text:
                quality["cid_pages"].append(parsed.page)
            letters = [c for c in body if c.isalpha()]
            if letters and len(_HANGUL.findall(body)) / len(letters) < 0.3:
                quality["low_hangul_pages"].append(parsed.page)
            quality["tables"] += sum(1 for b in parsed.blocks if b.kind == "table")
    return ParsedDocument(sha256=sha256_of(path), page_count=len(pages), pages=tuple(pages), quality=quality)


def _parse_page(page) -> ParsedPage:
    number = page.page_number
    tables = [(t.bbox, t.extract()) for t in page.find_tables()]
    lines = [
        _Line(raw["text"], raw["x0"], raw["x1"], raw["top"], raw["bottom"])
        for raw in page.extract_text_lines(return_chars=False)
        if raw["text"].strip()
    ]
    body_lines = [
        line
        for line in lines
        if not _in_header(line, page.height) and not _in_any_table(line, [bbox for bbox, _ in tables])
    ]
    right_edge = max((line.x1 for line in body_lines), default=page.width)

    pending: list[tuple[float, BlockKind, list[_Line], tuple | None]] = []
    for line in lines:
        if _in_header(line, page.height):
            kind: BlockKind = "header" if line.top < _HEADER_MAX_TOP else "footer"
            pending.append((line.top, kind, [line], None))
    for bbox, rows in tables:
        pending.append((bbox[1], "table", [], (bbox, rows)))
    for group in _paragraphs(body_lines, right_edge):
        first = group[0].text.strip()
        is_heading = bool(HEADING_RE.match(first) or NUMBERED_RE.match(first))
        kind: BlockKind = "heading" if is_heading and len(group) == 1 else "paragraph"
        if is_heading and len(group) > 1:
            # 제목 줄 뒤에 본문이 바로 이어지는 경우(예: "Q2. ...?" 다음 줄 답변)는 제목만 따로 둔다.
            pending.append((group[0].top, "heading", [group[0]], None))
            group = group[1:]
            kind = "paragraph"
        pending.append((group[0].top, kind, group, None))
    pending.sort(key=lambda item: (item[0], 0 if item[1] == "header" else 1))

    blocks: list[Block] = []
    offset = 0
    for index, (_, kind, group, table) in enumerate(pending):
        if table is not None:
            bbox, rows = table
            clean_rows = tuple(tuple(_cell(c) for c in row) for row in rows if any(_cell(c) for c in row))
            text = "\n".join(" | ".join(row) for row in clean_rows)
            caption = _caption_for(blocks)
            wraps: tuple[bool, ...] = ()
        else:
            text = "\n".join(line.text for line in group)
            bbox = (
                min(line.x0 for line in group),
                min(line.top for line in group),
                max(line.x1 for line in group),
                max(line.bottom for line in group),
            )
            clean_rows, caption = None, None
            wraps = tuple(line.x1 >= right_edge - 12 for line in group)
        if blocks:
            offset += 1  # 앞 block과의 줄바꿈
        blocks.append(
            Block(
                block_id=f"p{number}-b{index + 1}",
                page=number,
                kind=kind,
                text=text,
                bbox=tuple(round(v, 1) for v in bbox),
                start=offset,
                end=offset + len(text),
                soft_wraps=wraps,
                rows=clean_rows,
                caption=caption,
            )
        )
        offset += len(text)
    page_text = "\n".join(b.text for b in blocks)
    assert all(page_text[b.start : b.end] == b.text for b in blocks)  # noqa: S101 - offset 불변식
    return ParsedPage(number, float(page.width), float(page.height), page_text, tuple(blocks))


def _paragraphs(lines: list[_Line], right_edge: float) -> list[list[_Line]]:
    """제목 줄·큰 세로 간격·앞 줄이 짧게 끝난 곳에서 문단을 나눈다."""
    groups: list[list[_Line]] = []
    heights = sorted(line.bottom - line.top for line in lines) or [10.0]
    line_height = heights[len(heights) // 2]
    for line in lines:
        if not groups:
            groups.append([line])
            continue
        previous = groups[-1][-1]
        gap = line.top - previous.bottom
        previous_short = previous.x1 < right_edge - 12
        text = line.text.strip()
        starts_heading = bool(HEADING_RE.match(text)) or (previous_short and bool(NUMBERED_RE.match(text)))
        if starts_heading or gap > line_height * 0.9 or previous_short:
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


def _caption_for(blocks: list[Block]) -> str | None:
    """표 바로 앞 block이 표 제목 줄이면 caption으로 쓴다."""
    for block in reversed(blocks):
        if block.kind in ("header", "footer"):
            continue
        first = block.text.strip().splitlines()[0] if block.text.strip() else ""
        return first if block.kind == "heading" and _CAPTION_RE.match(first) else None
    return None


def _in_header(line: _Line, page_height: float) -> bool:
    return line.top < _HEADER_MAX_TOP or line.top > page_height - _FOOTER_MIN_TOP_FROM_BOTTOM


def _in_any_table(line: _Line, bboxes: list[tuple[float, float, float, float]]) -> bool:
    middle = (line.top + line.bottom) / 2
    return any(
        x0 - 2 <= line.x0 and line.x1 <= x1 + 2 and top <= middle <= bottom for x0, top, x1, bottom in bboxes
    )


def _cell(value: str | None) -> str:
    return " ".join((value or "").split())
