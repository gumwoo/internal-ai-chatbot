# Enterprise Knowledge & Work Agent

가상 회사의 사내 통합 업무지원 AI Agent다. 무엇을 만들지는 `docs/`의 명세가 기준이며, 이 파일은 명세의 위치와 작업 규칙만 담는다.

## 현재 상태

- M3 코드까지 있다(`backend/`). M3: 로컬 세션·인가(MOD-09), PDF 파싱·청크·임베딩(MOD-06), 게시·권한 검색·근거(MOD-05), raw 검색(MOD-11), 문서 인용. 개발 DB 문서 게시는 P-15, 빈 답 보정은 P-16, 사건 날짜 근원 검증은 P-17 결정 대기. 이전 단계: MOD-04 교육 조회, MOD-07 Anthropic 어댑터(thinking 끔), MOD-03 도구 2개, MOD-02 실행 반복·상한·근거 원장, MOD-01 대화 저장·멱등 재전송·만료 회수·영속 observer·검증된 사본(CP-07 최소형)·진행 상황 스트리밍(SSE, D-29). RAG·Wiki·티켓·프런트는 아직 없다(`docs/08-development-plan.md`).
- 실제 모델 호출은 과금된다. `ask --live`와 `pytest -m live_model`은 사용자 승인 후에만 실행한다.
- 도구는 uv · SQLAlchemy 2 + Alembic · psycopg 3 · pytest · ruff, 프런트는 Vite + React + TS다(D-26). 서버는 비동기(D-28), Python 3.13.
- 코드 위치: 공통 계약은 `backend/src/agent/shared/`, 업무 모듈은 `backend/src/agent/modules/<패키지>/`, 앱 조립은 `backend/src/agent/app/`. 모듈 import 방향은 `tests/test_module_boundaries.py`가 검사한다.
- 모델은 대화 Claude Haiku 5.5, 임베딩 `gemini-embedding-2`, judge Gemini 무료 티어다(D-25·D-27). 키는 사용자가 `.env`에 넣으며 키 이름은 `.env.example`을 따른다.

## 명세 위치

필요한 파일만 읽는다. 기억이나 추측으로 답하지 않는다.

| 알고 싶은 것 | 파일 |
|---|---|
| 범위·요구사항 | `docs/00-project-overview.md`, `docs/01-requirements.md` |
| 모듈 경계·허용 의존 | `docs/architecture/04-module-map.md`, `docs/modules/MOD-01~12` |
| 공통 계약(CT·CP) | `docs/contracts/00-shared-contracts.md`, `docs/contracts/01~05` |
| HTTP·오류 코드 | `docs/04-api-spec.md`, `docs/contracts/03-errors.md` |
| 확정 결정(D)·미정(O) | `docs/10-decisions-and-open-questions.md` |
| 정책 선택 이력(P) | `docs/15-policy-options.md` |
| 테스트 ID(T)·첫 구간 | `docs/07-test-and-evaluation.md`, `docs/12-first-milestone-spec.md` |

P-xx(정책)와 CP-xx(공통 포트)는 다른 체계다.

## 작업 규칙

- PDF 원본(`data/raw/pdfs/`)과 `.env`는 훅이 막는다. 막히면 우회하지 말고 사용자에게 알린다.
- O-xx로 남은 값은 임의로 정하지 않는다. 선택지와 trade-off를 `docs/15-policy-options.md`에 적고 묻는다.
- 계약을 바꾸면 그 계약을 참조하는 문서(`00-shared-contracts`, `04-api-spec`, 해당 MOD, `04-module-map`, `07-test-and-evaluation`)를 함께 고치고, 확정은 D 표·미정은 O 표에 남긴다.
- 문서 수정 뒤에는 명세 검사를 돌린다. 코드에는 해당 T ID의 테스트를 함께 쓴다.

## 반복 처리

- 같은 지적을 두 번 받으면 CLAUDE.md 수정안을 보여주고, 승인받은 뒤 반영한다.
- 같은 절차를 세 번 요청받으면 `.claude/skills/` skill 초안을 보여주고, 승인받은 뒤 만든다.
- 매번 반드시 지켜야 하는 규칙이 보이면 hook 초안과 시험 결과를 보여주고, 승인받은 뒤 등록한다.
- `[반복 감지 훅]` 알림은 제안의 근거일 뿐 자동 반영의 근거가 아니다. 감지는 글자 조각 비교라 다른 표현의 반복은 놓칠 수 있다.

## 명령

명세 검사(결과는 저장소 밖에 쓴다):

```bash
SPEC_RESULTS_DIR="$TEMP/spec-results" python -B scripts/check_specs.py
```

정적 시안 테스트: `prototypes/work-assistant/tests/README.md` 참조(`PROTOTYPE_RESULTS_DIR`는 저장소 밖).

백엔드(`backend/`에서 실행). DB 호스트는 `localhost`가 아니라 `127.0.0.1`로 쓴다(이 PC에서 `localhost`는 IPv6 접속이 멈춘다). Windows에서는 psycopg async 때문에 Selector 루프가 필요하다.

```bash
docker compose up -d db                      # 저장소 루트에서. PostgreSQL 18 + pgvector, 127.0.0.1:5440
uv run alembic upgrade head                  # 개발 DB(agent_dev)
uv run alembic -x target=test upgrade head   # 테스트 DB(agent_test)
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                             # TEST_DATABASE_URL 없으면 DB 테스트는 건너뜀
uv run uvicorn agent.app.main:create_app --factory --host 127.0.0.1 --port 8010 --loop asyncio:SelectorEventLoop
uv run python -m agent.cli seed-trainings --anchor 2026-10-16 --mode fixed_status   # 개발 DB 교육 fixture(재실행해도 중복 없음)
uv run python -m agent.cli ask "다음 주 교육 알려줘" --fixed-clock               # dry-run: 보낼 요청만 출력, 호출 없음
uv run python -m agent.cli seed-identity                                       # 데모 조직·계정(D-30), 해시만 저장
uv run python -m agent.cli draft-manifest [--force]                            # manifest 초안(needs_review), 기존 파일은 --force 없이 덮어쓰지 않음
uv run python -m agent.cli validate-manifest --release                         # T-18 구성·경로·hash 검사
```

💰 과금되는 명령(승인 후에만): `ask ... --live`(실제 Haiku 호출), `uv run pytest -m live_model -v`(교육 8개 + 문서 6개, 결과는 `LIVE_RESULTS_DIR` 또는 임시 폴더의 `live-smoke/`). 문서 smoke는 Gemini 무료 티어 임베딩도 쓴다(분당 100건, `data/staging/embeddings/` 캐시 재사용).

API 컨테이너 확인: `docker compose --profile api up -d --build api`(마이그레이션은 자동 실행하지 않는다). 포트: API 8010, 웹 5190(8000·5173·5180은 다른 프로그램이 사용 중).

프런트 실행/테스트: M1 이후 추가.
