"""파싱 수락 검사(docs/06-rag-design "파싱 수락 기준"). 결과는 검수 보고서에 남기고 게시 여부는 검수가 정한다.

- 숫자 일치: pdfplumber 기본 텍스트 추출(extract_text)의 숫자·금액·날짜 토큰이 block 원문에 모두 있는가.
- 인용 역추적: 청크의 모든 span이 페이지 원문의 같은 위치를 가리키는가.
- 줄바꿈 결합 표본: 자동 줄바꿈으로 붙인 곳의 앞뒤 글자(사람이 대조할 표본).
- 페이지 경계: 다음 페이지로 이어진 단위(조항·FAQ·표) 목록.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from agent.modules.ingestion.chunker import Chunk
from agent.modules.ingestion.parser import ParsedDocument

# 1,500,000 / 2026.10.01 / 12만원 / 7영업일 같은 토큰. 쉼표·점이 붙은 숫자를 한 토큰으로 본다.
_NUMBER_RE = re.compile(r"\d[\d,.]*\d|\d")


@dataclass
class ParseCheck:
    numbers_missing: list[tuple[int, str]] = field(default_factory=list)
    span_errors: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    cross_page_units: list[tuple[int, list[int]]] = field(default_factory=list)
    empty_form_tables: int = 0

    @property
    def ok(self) -> bool:
        return not self.numbers_missing and not self.span_errors


def check_document(path: Path, document: ParsedDocument, chunks: tuple[Chunk, ...]) -> ParseCheck:
    check = ParseCheck()
    with pdfplumber.open(path) as pdf:
        for page, parsed in zip(pdf.pages, document.pages, strict=True):
            raw = Counter(_NUMBER_RE.findall(page.extract_text() or ""))
            ours = Counter(_NUMBER_RE.findall(parsed.text.replace(" | ", " ")))
            for token, count in raw.items():
                if ours[token] < count:
                    check.numbers_missing.append((parsed.page, token))
    pages = {p.page: p for p in document.pages}
    for chunk in chunks:
        for span in chunk.spans:
            page = pages.get(span.page)
            if page is None or not (0 <= span.start <= span.end <= len(page.text)):
                check.span_errors.append(f"chunk {chunk.ordinal}: span 범위 밖 {span}")
                continue
            if page.text[span.start : span.end] not in chunk.text:
                check.span_errors.append(f"chunk {chunk.ordinal}: span 원문이 청크에 없음 {span}")
        span_pages = sorted({s.page for s in chunk.spans})
        if len(span_pages) > 1:
            check.cross_page_units.append((chunk.ordinal, span_pages))
        if chunk.kind == "table" and any(
            "|  |" in line or line.endswith("| ") for line in chunk.text.split("\n")
        ):
            check.empty_form_tables += 1
    for page in document.pages:
        for block in page.blocks:
            lines = block.text.split("\n")
            for wrapped, before, after in zip(block.soft_wraps[:-1], lines, lines[1:], strict=False):
                if wrapped and before and after:
                    check.joins.append(f"p{page.page} …{before[-6:]}⏎{after[:6]}…")
    return check
