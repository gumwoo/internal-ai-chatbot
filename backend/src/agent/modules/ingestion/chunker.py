"""원문 block → 검색 청크(MOD-06 분할). 설정 ID: CHUNK_CONFIG.

- 단위(unit): 제목(조항·FAQ 문항·번호 절·별표 등)과 그 뒤 본문. 페이지를 넘어가도 같은 단위로 잇고
  모든 페이지 span을 남긴다. 표는 표 제목(caption)과 함께 따로 단위가 된다. 다음 페이지에서 같은 열 헤더로
  다시 시작하는 표는 같은 단위로 잇는다. 바로 다른 제목이 이어지는 제목(장·큰 절)은 경로(section_path)로만
  쓴다.
- 같은 단위에서 나온 청크는 support_group이 같다. 검색은 청크로 찾고, 답변 문맥에는 support_group 전체를
  넣는다(docs/06-rag-design의 parent document 방식).
- text(근거 본문)는 원문 줄을 그대로 둔다. embed_text(임베딩 입력)는 문서 제목·경로를 앞에 붙이고,
  오른쪽 여백까지 찬 줄(자동 줄바꿈)만 이어 붙인다. 공백을 일괄로 넣거나 빼지 않는다.
- 너무 긴 단위는 block 경계로 나눈다. 표는 행 단위로 나누고 나눈 조각마다 제목과 열 헤더 행을 다시 붙인다.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from agent.modules.ingestion.parser import Block, ParsedDocument

CHUNK_CONFIG = "units-v1-max1500"
MAX_CHARS = 1500
_ARTICLE_WITH_BODY = re.compile(r"^제\s*\d+\s*조(의\s*\d+)?\s*\([^)]*\)\s*\S")
_CHAPTER_RE = re.compile(r"^(제\s*\d+\s*장|부\s*칙|업무 처리 기준|자주 묻는 질문|별첨)")


@dataclass(frozen=True)
class Span:
    page: int
    block_id: str
    start: int
    end: int


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    support_group: int
    kind: Literal["text", "table"]
    heading: str | None
    section_path: tuple[str, ...]
    text: str
    embed_text: str
    spans: tuple[Span, ...]


@dataclass
class _Unit:
    heading: Block | None
    path: tuple[str, ...]
    blocks: list[Block]
    tables: list[Block] = field(default_factory=list)
    caption: str | None = None


def chunk_document(document: ParsedDocument, title: str) -> tuple[Chunk, ...]:
    units = _units([b for page in document.pages for b in page.blocks if b.kind not in ("header", "footer")])
    chunks: list[Chunk] = []
    for group, unit in enumerate(units, start=1):
        pieces = _table_pieces(unit) if unit.tables else _text_pieces(unit)
        for kind, heading, text, embed_body, spans in pieces:
            prefix = " > ".join([title, *unit.path, *([heading] if heading else [])])
            chunks.append(
                Chunk(
                    ordinal=len(chunks) + 1,
                    support_group=group,
                    kind=kind,
                    heading=heading,
                    section_path=unit.path,
                    text=text,
                    embed_text=f"{prefix}\n{embed_body}",
                    spans=tuple(spans),
                )
            )
    return tuple(chunks)


def _level(first_line: str) -> int:
    """경로 깊이: 장·큰 절 0, "1." 1, "1.1" 2 …, 그 밖의 제목 1."""
    if _CHAPTER_RE.match(first_line):
        return 0
    numbered = re.match(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s", first_line)
    return numbered.group(1).count(".") + 1 if numbered else 1


def _units(blocks: list[Block]) -> list[_Unit]:
    units: list[_Unit] = []
    path: list[tuple[int, str]] = []
    current: _Unit | None = None

    def push(first_line: str) -> None:
        level = _level(first_line)
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, first_line))

    def names() -> tuple[str, ...]:
        return tuple(name for _, name in path)

    for index, block in enumerate(blocks):
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        previous = blocks[index - 1] if index else None
        if block.kind == "heading":
            first_line = block.text.strip().splitlines()[0]
            if following is not None and following.kind == "table" and following.caption == first_line:
                current = None  # 표 제목은 표 단위가 가져간다
                continue
            if _ARTICLE_WITH_BODY.match(first_line) and not _CHAPTER_RE.match(first_line):
                # "제1조(시행일) 이 규정은 …시행한다."처럼 제목 줄에 본문이 붙은 조문은 그 자체로 단위다.
                current = None
                units.append(_Unit(block, names(), [block]))
                continue
            if following is None or following.kind == "heading" or _CHAPTER_RE.match(first_line):
                # 장·큰 절: 경로로만 쓴다.
                if following is None:
                    # 문서 끝의 제목(예: 부칙 시행일 한 줄)도 본문으로 남긴다.
                    units.append(_Unit(block, names(), [block]))
                else:
                    push(first_line)
                current = None
                continue
            current = _Unit(block, names(), [block])
            units.append(current)
            continue
        if block.kind == "table":
            last = units[-1] if units else None
            continued = (
                last is not None
                and last.tables
                and previous is not None
                and previous.page < block.page
                and previous is last.tables[-1]
                and block.rows
                and last.tables[-1].rows
                and block.rows[0] == last.tables[-1].rows[0]
            )
            if continued:
                # 다음 페이지로 이어진 표(같은 열 헤더로 시작): 같은 단위·제목으로 잇는다.
                last.tables.append(block)
                last.blocks.append(block)
            else:
                units.append(_Unit(None, names(), [block], tables=[block], caption=block.caption))
            current = None
            continue
        if current is None:
            current = _Unit(None, names(), [])
            units.append(current)
        current.blocks.append(block)
    return [unit for unit in units if unit.blocks]


def _text_pieces(unit: _Unit):
    heading = unit.heading.text.strip().splitlines()[0] if unit.heading else None
    pieces, blocks, size = [], [], 0
    for block in unit.blocks:
        if blocks and size + len(block.text) > MAX_CHARS:
            pieces.append(blocks)
            blocks, size = [], 0
        blocks.append(block)
        size += len(block.text) + 1
    if blocks:
        pieces.append(blocks)
    out = []
    for part in pieces:
        text = "\n".join(b.text for b in part)
        body = [b for b in part if not (unit.heading is not None and b is unit.heading)]
        embed = "\n".join(_normalized(b) for b in body)
        spans = [Span(b.page, b.block_id, b.start, b.end) for b in part]
        out.append(("text", heading, text, embed or text, spans))
    return out


def _table_pieces(unit: _Unit):
    """표를 행 단위로 나눈다. 조각마다 표 제목과 열 헤더 행을 다시 붙이고, 헤더·행의 원문 span을 남긴다."""
    caption = unit.caption
    out = []
    for table in unit.tables:
        lines = table.text.split("\n")
        starts, cursor = [], table.start
        for line in lines:
            starts.append(cursor)
            cursor += len(line) + 1
        header_span = Span(table.page, table.block_id, starts[0], starts[0] + len(lines[0]))
        groups: list[list[int]] = []
        current: list[int] = []
        size = len(lines[0])
        for row in range(1, len(lines)):
            if current and size + len(lines[row]) > MAX_CHARS:
                groups.append(current)
                current, size = [], len(lines[0])
            current.append(row)
            size += len(lines[row]) + 1
        if current or not groups:
            groups.append(current)
        for rows in groups:
            text = "\n".join([*([caption] if caption else []), lines[0], *(lines[r] for r in rows)])
            spans = [header_span]
            if rows:
                first, last = rows[0], rows[-1]
                spans.append(Span(table.page, table.block_id, starts[first], starts[last] + len(lines[last])))
            out.append(("table", caption, text, text, spans))
    return out


def _normalized(block: Block) -> str:
    """검색용 정규화: 자동 줄바꿈(오른쪽 여백까지 찬 줄)만 붙이고 나머지 줄바꿈은 그대로 둔다."""
    lines = block.text.split("\n")
    if not block.soft_wraps or len(block.soft_wraps) != len(lines):
        return block.text
    out = lines[0]
    for wrapped, line in zip(block.soft_wraps[:-1], lines[1:], strict=True):
        out += line if wrapped else "\n" + line
    return out
