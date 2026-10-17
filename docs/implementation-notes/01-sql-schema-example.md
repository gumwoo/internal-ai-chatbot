> **이전 설계 참고 자료:** 개정2 이전 예제다. 현재 ACL·시점·PDF/Wiki snapshot·티켓 계약은 [설계 검토 안내](../architecture/00-review-guide.md)를 따른다. 이 예제를 현재 명세로 사용하지 않는다.

# 구현 참고 01. SQL 스키마 예시

이 문서는 재구성 전 명세에 있던 SQL 예시를 보존한 참고 자료입니다. 모듈 검토의 필수 선행 문서가 아니며, 실제 마이그레이션도 아닙니다. 현재 설계 기준은 [논리 데이터 모델](../03-data-model.md)과 [모듈 지도](../architecture/04-module-map.md)입니다.

필드·제약·인덱스의 실제 구현 방식은 모듈 계약을 검토한 뒤 확정합니다. SQL의 테이블이 같은 DB에 있다고 다른 모듈에서 직접 접근해도 된다는 뜻은 아닙니다.

## 1. 사용자·교육

```sql
CREATE TABLE users (
    id uuid PRIMARY KEY,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE trainings (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    title text NOT NULL,
    description text NOT NULL,
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    location text NOT NULL,
    status text NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'cancelled', 'completed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at)
);

CREATE INDEX trainings_starts_at_id_idx ON trainings (starts_at, id);
```

## 2. 대화·메시지·실행

```sql
CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    title text NOT NULL DEFAULT '새 대화',
    context jsonb NOT NULL DEFAULT '{"version":1}'::jsonb,
    active_run_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_runs (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id),
    request_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    model_provider text,
    model_name text,
    prompt_version text,
    outcome text CHECK (outcome IN ('answered', 'needs_clarification', 'no_results', 'insufficient_evidence')),
    started_at timestamptz NOT NULL DEFAULT now(),
    deadline_at timestamptz NOT NULL,
    finished_at timestamptz,
    duration_ms integer CHECK (duration_ms >= 0),
    input_tokens bigint CHECK (input_tokens >= 0),
    output_tokens bigint CHECK (output_tokens >= 0),
    usage_complete boolean NOT NULL DEFAULT false,
    error_code text,
    error_stage text,
    CHECK (deadline_at > started_at),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status IN ('completed', 'failed') AND finished_at IS NOT NULL)
    )
);

ALTER TABLE conversations ADD CONSTRAINT conversations_active_run_fk
    FOREIGN KEY (active_run_id) REFERENCES agent_runs(id);

CREATE TABLE messages (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id),
    run_id uuid REFERENCES agent_runs(id),
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX messages_one_user_per_run_idx
    ON messages (run_id) WHERE role = 'user';
CREATE UNIQUE INDEX messages_one_assistant_per_run_idx
    ON messages (run_id) WHERE role = 'assistant';
CREATE INDEX conversations_owner_updated_idx
    ON conversations (user_id, updated_at DESC, id);
CREATE INDEX messages_conversation_created_idx
    ON messages (conversation_id, created_at, id);
CREATE INDEX agent_runs_conversation_started_idx
    ON agent_runs (conversation_id, started_at DESC);
```

## 3. 도구 기록

```sql
CREATE TABLE tool_calls (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES agent_runs(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    provider_call_id text,
    tool_name text NOT NULL,
    arguments jsonb NOT NULL,
    status text NOT NULL
        CHECK (status IN ('succeeded', 'validation_error', 'failed')),
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL,
    duration_ms integer NOT NULL CHECK (duration_ms >= 0),
    attempt_count integer NOT NULL DEFAULT 1 CHECK (attempt_count > 0),
    error_code text,
    error_stage text,
    UNIQUE (run_id, ordinal)
);
```

## 4. 규정·벡터

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id uuid PRIMARY KEY,
    document_key text NOT NULL,
    title text NOT NULL,
    version text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
    visibility text NOT NULL DEFAULT 'company'
        CHECK (visibility = 'company'),
    source_path text NOT NULL,
    content_hash text NOT NULL,
    chunking_version text NOT NULL,
    effective_from date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_key, version)
);

CREATE UNIQUE INDEX documents_one_published_version_idx
    ON documents (document_key) WHERE status = 'published';

CREATE TABLE document_chunks (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id),
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    section text NOT NULL,
    content text NOT NULL,
    source_start integer NOT NULL CHECK (source_start >= 0),
    source_end integer NOT NULL,
    token_count integer NOT NULL CHECK (token_count > 0),
    embedding_model text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions > 0),
    embedding vector NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index),
    CHECK (source_end > source_start),
    CHECK (vector_dims(embedding) = embedding_dimensions)
);
```

