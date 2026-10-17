"""문서 운영 CLI 조립(APP-03). 초기 MVP는 문서 업로드 HTTP를 만들지 않고 CLI로만 운영한다(04-api-spec).

- draft-manifest: 수령 목록 + PDF 본문 근거로 manifest 초안(needs_review)을 쓴다. 모델 호출 없음.
- validate-manifest: T-18 검사 결과를 출력한다.
- ingest: 검수된(reviewed) 항목만 파싱·분할·임베딩해 운영 actor로 게시한다. 💰 아님(Gemini 무료 티어),
  하지만 무료 티어 한도를 쓴다. 임베딩은 준비 산출물 캐시를 재사용한다.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from agent.modules.identity_access.service import IdentityService
from agent.modules.ingestion.chunker import CHUNK_CONFIG, chunk_document
from agent.modules.ingestion.embedding import EmbeddingCache, embed_texts
from agent.modules.ingestion.manifest import (
    draft_entry,
    link_supersession,
    load_manifest,
    manifest_hash,
    parse_register,
    to_metadata,
    validate_manifest,
)
from agent.modules.ingestion.parser import PARSER_REVISION, parse_pdf, sha256_of
from agent.modules.ingestion.quality import check_document
from agent.modules.knowledge.contracts import PreparedChunk, PreparedCorpus, PreparedEdition
from agent.modules.knowledge.service import KnowledgeService, validate_metadata
from agent.modules.knowledge.tables import EMBEDDING_DIM
from agent.modules.model_integration.gemini_embedding import EMBED_FORMAT, format_input
from agent.modules.model_integration.ports import EmbeddingConfig, EmbeddingModel
from agent.shared.clock import Clock
from agent.shared.settings import REPO_ROOT

INPUT_ROOT = REPO_ROOT / "data" / "raw" / "pdfs"
MANIFEST_PATH = REPO_ROOT / "data" / "raw" / "document-manifest.json"
REGISTER_PATH = REPO_ROOT / "docs" / "corpus" / "02-received-register.md"
STAGING = REPO_ROOT / "data" / "staging"


def draft_manifest(
    now: datetime, register: Path = REGISTER_PATH, input_root: Path = INPUT_ROOT
) -> dict[str, Any]:
    entries = []
    for row in parse_register(register):
        path = input_root / row["filename"]
        document = parse_pdf(path)
        entries.append(draft_entry(row, document, sha256_of(path)))
    link_supersession(entries)
    return {
        "manifest_version": 1,
        "status": "draft",
        "generated_at": now.isoformat(),
        "note": (
            "MOD-06 초안. 원문·수령 목록에 근거가 있는 값만 채웠고 근거는 basis_evidence에 있다. "
            "available_from 등 원문으로 정할 수 없는 값은 비어 있으며 "
            "모든 항목이 needs_review다(O-02, P-15). "
            "ACL은 D-31 사용자 결정이다. 검수 전에는 게시하지 않는다."
        ),
        "input_root": "data/raw/pdfs",
        "files": entries,
    }


async def prepare_corpus(
    manifest: dict[str, Any],
    embedder: EmbeddingModel,
    *,
    source_file_ids: list[str] | None,
    label: str,
    scope: str,
    input_root: Path = INPUT_ROOT,
    cache_dir: Path | None = STAGING / "embeddings",
    embed_per_minute: int = 100,
) -> tuple[PreparedCorpus, dict[str, Any]]:
    """PrepareCorpus: 선택 항목을 파싱·분할·임베딩해 CT-09로 만든다. 게시는 하지 않는다."""
    entries = [
        e for e in manifest["files"] if source_file_ids is None or e["source_file_id"] in source_file_ids
    ]
    config = EmbeddingConfig("gemini-embedding-2", EMBEDDING_DIM, "document")
    cache = EmbeddingCache.open(cache_dir, config, EMBED_FORMAT) if cache_dir is not None else None
    editions, report = [], {"files": {}, "embedding": None}
    parsed = []
    for entry in entries:
        path = input_root / entry["filename"]
        document = parse_pdf(path)
        chunks = chunk_document(document, entry["title"])
        check = check_document(path, document, chunks)
        report["files"][entry["source_file_id"]] = {
            "chunks": len(chunks),
            "numbers_missing": check.numbers_missing,
            "span_errors": check.span_errors,
            "cross_page_units": check.cross_page_units,
        }
        parsed.append((entry, document, chunks, check))
    texts = [format_input(c.embed_text, "document", e["title"]) for e, _, chunks, _ in parsed for c in chunks]
    vectors, embed_report = await embed_texts(embedder, texts, config, cache, per_minute=embed_per_minute)
    report["embedding"] = embed_report.__dict__
    cursor = 0
    for entry, document, chunks, check in parsed:
        prepared_chunks = []
        for chunk in chunks:
            prepared_chunks.append(
                PreparedChunk(
                    ordinal=chunk.ordinal,
                    support_group=chunk.support_group,
                    kind=chunk.kind,
                    heading=chunk.heading,
                    section_path=chunk.section_path,
                    text=chunk.text,
                    spans=tuple(
                        {"page": s.page, "block_id": s.block_id, "start": s.start, "end": s.end}
                        for s in chunk.spans
                    ),
                    vector=vectors[cursor],
                )
            )
            cursor += 1
        editions.append(
            PreparedEdition(
                metadata=to_metadata(entry),
                sha256=document.sha256,
                page_count=document.page_count,
                pages=tuple(
                    {
                        "page": page.page,
                        "text": page.text,
                        "blocks": [
                            {
                                "block_id": b.block_id,
                                "kind": b.kind,
                                "start": b.start,
                                "end": b.end,
                                "bbox": list(b.bbox),
                            }
                            for b in page.blocks
                        ],
                    }
                    for page in document.pages
                ),
                chunks=tuple(prepared_chunks),
                parser_revision=PARSER_REVISION,
                chunk_config=CHUNK_CONFIG,
                embedding_model=config.model,
                embedding_dim=config.dimension,
                embedding_format=EMBED_FORMAT,
                quality={
                    **document.quality,
                    "numbers_missing": len(check.numbers_missing),
                    "span_errors": len(check.span_errors),
                    "joins": len(check.joins),
                },
            )
        )
    config_hash = hashlib.sha256(
        f"{PARSER_REVISION}|{CHUNK_CONFIG}|{config.model}-{config.dimension}|{EMBED_FORMAT}".encode()
    ).hexdigest()
    corpus = PreparedCorpus(
        editions=tuple(editions),
        manifest_hash=manifest_hash(manifest),
        config_hash=config_hash,
        label=label,
        scope=scope,
    )
    return corpus, report


async def ingest(
    engine: AsyncEngine,
    clock: Clock,
    embedder: EmbeddingModel,
    operator_user_id: str | None,
    *,
    manifest_path: Path = MANIFEST_PATH,
    source_file_ids: list[str] | None,
    label: str,
    scope: str,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    check = validate_manifest(manifest, INPUT_ROOT, release=scope == "release")
    if not check.ok:
        return {"published": False, "errors": check.errors}
    operator = await IdentityService(engine, clock).resolve_operator_actor(operator_user_id)
    selected = [
        e for e in manifest["files"] if source_file_ids is None or e["source_file_id"] in source_file_ids
    ]
    # 메타데이터 검사를 임베딩(무료 티어 한도)보다 먼저 한다. 게시할 수 없으면 한도를 쓰지 않는다.
    metadata_problems = validate_metadata([to_metadata(e) for e in selected])
    if metadata_problems:
        return {"published": False, "errors": metadata_problems}
    corpus, report = await prepare_corpus(
        manifest, embedder, source_file_ids=source_file_ids, label=label, scope=scope
    )
    result = await KnowledgeService(engine, clock).publish(operator, corpus)
    return {
        "published": True,
        "snapshot_id": result.snapshot_id,
        "members": result.member_count,
        "report": report,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
