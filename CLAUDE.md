# Enterprise Knowledge & Work Agent

가상 회사의 사내 통합 업무지원 AI Agent다. 무엇을 만들지는 `docs/`의 명세가 기준이며, 이 파일은 명세의 위치와 작업 규칙만 담는다.

## 현재 상태

- M1~M6 코드와 최종 평가까지 끝났다(`backend/`, `frontend/`, `docs/report/final-evaluation.md`). 개발 DB에 100개 문서·Wiki(문서 43개 범위)가 게시돼 있다. holdout 100문항 규칙 정답 A raw 0.60 · B wiki_assisted 0.42 · 전체 문맥 기준선 0.59(실측, D-58). 평가 결과 파일은 `data/staging/eval-results/`, holdout 예산 동결은 `freeze.json`(4000). 날짜 검증은 표지 v5(D-56). 단계별 기록은 `docs/08-development-plan.md`. 그 뒤 원문 검색 개선 실험(D-60~D-66)을 했고, 효과는 새 검증셋 `eval/cases/holdout2.jsonl`(95문항, split `holdout2`)로 잰다: 규칙 정답 0.39→0.47, judge 37→41(실측, 최종 보고서 9절). 옛 holdout은 오답 분석에 썼으므로 개선 비교에 쓰지 않는다. 최신 측정은 holdout5(68문항, D-81)와 holdout6(37문항, D-84). holdout5를 같은 코드로 두 번 돌리니 규칙 정답이 1차 30→37, 2차 36→32로 방향이 뒤집혔다(실행마다 18~25% 문항의 판정이 바뀜). holdout6은 규칙 9→6·judge 11→17로 반대 방향이고 둘 다 유의하지 않다(실측, 보고서 9.13·9.15·9.16). 그 뒤 D-86(판본·날짜 되묻기 재호출, 마감일 인용)을 holdout7(47문항, D-87)로 개선 전후 세 번씩 쟀다: 규칙 정답 49→54/141(짝 비교 8:7, 차이 없음), 되묻기 26→13(보고서 9.18, judge는 Gemini 오류로 미완). 이어지는 턴의 검색 재호출 D-88을 holdout8(46문항, D-89)로 세 번씩 쟀다: 규칙 정답 83→100/138(짝 비교 15:3, p≈0.0075), 이어지는 질문 42→58/87(보고서 9.20). 첫 측정은 Gemini 장애로 무효였다. 실측 전에 한 문항으로 검색이 되는지 먼저 확인한다. judge(gemini-3.8-flash)는 무료 키에서 시간 초과·429로 holdout7·8 판정을 끝내지 못했다. 인젝션 실측은 보고서 9.14·9.17(공격 19개 모두 실패).
- 실제 모델 호출은 과금된다. `ask --live`와 `pytest -m live_model`은 사용자 승인 후에만 실행한다.
- 도구는 uv · SQLAlchemy 2 + Alembic · psycopg 3 · pytest · ruff, 프런트는 Vite + React + TS다(D-26). 서버는 비동기(D-28), Python 3.13.
- 코드 위치: 공통 계약은 `backend/src/agent/shared/`, 업무 모듈은 `backend/src/agent/modules/<패키지>/`, 앱 조립은 `backend/src/agent/app/`. 모듈 import 방향은 `tests/test_module_boundaries.py`가 검사한다.
- 모델은 대화 Claude Haiku 5.5, 임베딩 `gemini-embedding-2`(유료 계정, D-53), judge `gemini-3.8-flash`(D-54, `JUDGE_MODEL` 환경 변수)다. 키는 사용자가 `.env`에 넣으며 키 이름은 `.env.example`을 따른다.

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

- 사용자에게 보이는 글은 모두 한국어로 쓴다. 진행 메시지, 표, 다음 단계 상자의 요약·질문·버튼 문구까지 포함한다(코드·명령·식별자는 원 표기).
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
uv run python -m agent.cli validate-manifest --release                         # T-18 구성·경로·hash·관계 형식 검사
uv run python -m agent.cli ingest --release --label dev                        # 검수 manifest로 개발 DB 게시(Gemini 무료 티어, 캐시 재사용)
uv run python -m agent.cli wiki-status                                         # Wiki 게시 상태(stale 여부)
uv run python -m agent.cli review-manifest [--force]                           # D-36·D-40 규칙으로 검수본 작성(원문은 읽기만)
```

평가(APP-04): `eval-run --strategy raw|wiki_assisted --split dev|holdout [--budget N] --live`(💰 Haiku + Gemini 질의 임베딩, 질의는 `data/staging/embeddings/eval-query-cache.jsonl` 재사용), `eval-score --results …`(과금 없음), `eval-judge --results … --live`(Gemini 무료 티어). 평가셋 기계 검사: `python -B scripts/check_eval.py`(원문 내보내기 `data/staging/eval-sources/` 필요).

💰 과금되는 명령(승인 후에만): `eval-run --live`, `draft-wiki-topics`·`build-wiki`(Haiku로 Wiki 생성, build-wiki는 Gemini 임베딩도 씀), `ask ... --live`(실제 Haiku 호출), `uv run pytest -m live_model -v`(교육 8개 + 문서 6개 + 티켓 3개, 결과는 `LIVE_RESULTS_DIR` 또는 임시 폴더의 `live-smoke/`). 문서 smoke는 Gemini 무료 티어 임베딩도 쓴다(분당 100건, `data/staging/embeddings/` 캐시 재사용).

API 컨테이너 확인: `docker compose --profile api up -d --build api`(마이그레이션은 자동 실행하지 않는다). 포트: API 8010, 웹 5190(8000·5173·5180은 다른 프로그램이 사용 중).

프런트(`frontend/`에서 실행):

```bash
npm ci
npm run typecheck && npm run build
npm run dev                                   # 127.0.0.1:5190, /api → 127.0.0.1:8010(API_ORIGIN으로 변경)
npx playwright test                           # T-20/21 E2E. E2E 백엔드(127.0.0.1:8011, 가짜 모델·시험 DB)를 자동으로 띄운다
```

재현 데모(Docker): `docker compose --profile demo up -d --build db seed api web`(AUTH_MODE=local_session을 .env에 둔다). 웹 http://127.0.0.1:5190. 문서 검색은 100개 게시 뒤에 동작한다.
