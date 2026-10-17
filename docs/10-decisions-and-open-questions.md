# 결정 기록과 미정 항목

설계 개정2 · 2026-10-16. 아래 확정은 이번 대화에서 채택한 범위다. 미정 값은 구현/문서 인계 전에 구체화하되 임의로 사실처럼 채우지 않는다.

## 확정

| ID | 결정 | 이유·적용 |
|---|---|---|
| D-01 | 교육을 포함한 사내 통합 업무지원 Agent | 문서 연결과 업무 API를 함께 검증 |
| D-02 | 사용자 제공 PDF100=현행91+이전9 | 논리 문서91종, 개정 쌍 고정 |
| D-03 | A 원문 / B Wiki 보조 원문 비교 | 양쪽 최종 근거는 PDF 원문 |
| D-04 | 문서별 권한·과거 시점 지원 | 현재 ACL, PDF·Wiki·이력·캐시까지 적용 |
| D-05 | 업무는 교육 조회·IT 조회/확인 등록 | 문서 범위와 변경 기능 범위를 구분 |
| D-06 | 모듈형 모놀리스·12모듈 | 기존8개 유지+권한/Wiki/검색전략/IT |
| D-07 | FastAPI·PostgreSQL/pgvector·React/TS·Compose | 기존 방향 유지. 공급자는 D-27에 따라 대화 Anthropic, 임베딩·judge Google 두 곳 |
| D-08 | SDK 반복 먼저, LangGraph/MCP는 후속 | 도구/상태 원리부터 검증 |
| D-09 | 평가150, dev50/holdout100 | 유형별 원문 gold 검수·누수 방지 |
| D-10 | PC 우선·기본 모바일 | 기존 화면 구성/시각 원칙 유지 |
| D-11 | 로컬 데모 세션 | 권한 테스트 가능, 실제 SSO는 별도 |
| D-12 | 구현 내부와 모듈 계약 분리 | 검토 단위는 인프라→앱→레이어→모듈/협력 |
| D-13 | 영속 run 만료/복구·메시지 멱등·동일 키 결과 replay | 실패/응답 유실에서 단일 실행 |
| D-14 | Agent draft와 UI pending 분리 | 실패 run이 이전 준비를 취소하지 않음 |
| D-15 | CP-07 원문/교육 receipt 읽기 포트 | 실제 검증 경로와 저장소 소유권 |
| D-16 | 지식 공개 시점과 사건 적용일 분리 | 현행 FAQ의 과거 사례 해설·예정 교육 지원 |
| D-17 | PDF hash/page/quote gold 정본 | 파서 revision 변경과 정답 분리 |
| D-18 | 독립 root draft 여러 개+대화별 head 하나 | 사용자 확인, 입력 출처와 밀려난 head 관계 분리 |
| D-19 | 원규정 공백의 금액/권리/의무 결론 보류 | 사용자 확인, guidance 절차 안내와 구분 |
| D-20 | 최종 근거5개 고정 상한 폐지 | 사용자 요구: 필수 근거 보존, 공통 token 예산·누락 평가 |
| D-21 | 근거 예산은 dev 예산 스윕으로 정하고 회수는 예산 기준 지표로 측정 | 사용자 확인: 공개 연구·실무 조사 반영. Recall@pool/Recall@budget·evidence-in-context·hard negative 오답, packing_order 고정 |
| D-22 | 전체 문맥 기준선만 먼저 계획, 공통 재정렬은 hard negative 오답 확인 시 추가 | 사용자 확인(P-04 B). 기준선은 actor별 token 실측 뒤 한도 안에서만 실행, 재정렬은 별도 비교 ID |
| D-23 | 4차 재검증 기술 보정 | 사용자 요청. 기준선은 평가 전용 strategy·MOD-05.ReadAllowedCorpus·passage 단위 인용, lazy 만료는 head_revision 미증가, 여러 검색의 최종 예산 조립은 MOD-02, CT-06 ToolExecutionInput으로 field_origins/observer 전달, capability 닫힌 목록과 eval_fixture source, support_scopes는 MOD-12 소유 |
| D-24 | 연도 생략 날짜는 시제로 추론해 표시(P-05 B), 티켓 수정 사슬 상한 없음(P-06 A), 표/문장 단위 적용 조건은 모델 판단+측정 후 조건부 열·행 분리(P-07 A) | 사용자 확인. 근거는 [정책 선택](15-policy-options.md) |
| D-25 | 대화(답변) 모델은 A/B·평가 실행을 포함해 Claude Haiku 5.5(`claude-haiku-5-5`), SDK는 Anthropic 공식 Python SDK | 사용자 확인(예산). judge는 D-27로 변경([정책 선택](15-policy-options.md) P-08) |
| D-26 | 백엔드 도구: uv(패키지·잠금), SQLAlchemy 2 + Alembic, psycopg 3, pytest, ruff. 프런트엔드: Vite + React + TypeScript | 사용자 확인. O-03 해소 |
| D-27 | 임베딩은 Google `gemini-embedding-2`(무료 티어부터), judge는 Gemini Flash 계열 무료 티어 | 사용자 확인(예산). 조건: 청크마다 별도 입력으로 임베딩, 차원은 768/1536 중 선택(O-04), 평가 때 호출 한도에 걸리면 유료 전환, 무료 티어 입력은 Google 제품 개선에 쓰이므로 가상 문서에만 사용, judge 모델 ID·날짜는 holdout 전 고정 |
| D-28 | 비동기 서버: FastAPI async 엔드포인트 + SQLAlchemy 2 async + psycopg 3 async, Python 3.13 | 사용자 확인. 모델 응답을 최대60초 기다리는 동안 다른 요청을 처리하고 NFR-03 동시성 테스트를 자연스럽게 하기 위함. 3.14는 라이브러리 지원을 확인하지 않아 보류 |
| D-29 | M2 이후 진행 상황 스트리밍: 같은 메시지 POST에 `Accept: text/event-stream`, 서버가 기록한 단계만 progress로 보내고 답변 본문은 검사·commit 뒤 result로 한 번 | 사용자 확인([정책 선택](15-policy-options.md) P-09 A). 토큰 단위 스트리밍은 권한 재확인·인용 검증 원칙과 충돌해 쓰지 않음 |
| D-30 | 데모 조직·역할·계정: 부서는 등록부 소관(인사팀·IT지원팀(IT운영 포함)·정보보안팀·경영지원팀·재무팀·총무팀)과 열람 부서(영업팀·개발팀). 역할은 employee·dept_head·hr_staff·approver·auditor·it_support·operator(CLI 전용). 시험 계정 emp-sales·emp-dev·head-sales·hr-staff·it-support·ops-admin(웹 로그인 없음). capability는 employee=training.read·knowledge.search·ticket.read_own(준비·제출은 M5), it_support는 +ticket.read_support_scope, operator=ops.* | 사용자 확인(2026-10-17, M3 진행 결정). O-01·O-10의 데모 값. 시험 비밀번호는 seed 파일에 둔다(가상 데모 계정). HR-014의 "평가권자"는 부서장으로 본다(가정) |
| D-31 | 문서 ACL: 기본은 전 문서 audience=authenticated이며 manifest에 "사용자 명시 결정"으로 남긴다. 원문에 열람 제한이 적힌 HR-013·HR-014는 hr_staff·dept_head, CM-093은 dept_head·approver·auditor로 제한. 부서 단위 제한은 시험 전용 가짜 문서로만 시험 | 사용자 확인(2026-10-17). O-02의 ACL 부분 해소. 원문에 근거가 없는 제한을 지어내지 않기 위함 |
| D-32 | 임베딩 차원 1536(`gemini-embedding-2`)으로 시작. 768과 작은 표본에서 비교해 선택 근거로만 기록(평가 결과로 쓰지 않음) | 사용자 확인(2026-10-17). O-04의 차원 부분 해소 |
| D-33 | PDF 파서 pdfplumber(MIT). PyMuPDF(AGPL)는 쓰지 않음. 100개 전에 15~20개 파일럿으로 한국어 추출 확인 | 사용자 확인(2026-10-17). O-05의 파서 선택 해소. OCR·표 복원 한계는 파일럿 보고에 남김 |
| D-34 | P-12는 B(명세대로 CP-07 포트를 MOD-02에 주입, MOD-01의 권한 선필터는 첫 겹으로 유지). P-13은 B(문서 passage는 tool_result로, 검증된 대화 자료는 system에서 빼 현재 사용자 턴 앞의 표시된 자료 블록으로, system에는 규칙만) | 사용자 확인(2026-10-17). O-16·O-17 해소. 근거는 [정책 선택](15-policy-options.md) P-12·P-13 |
| D-35 | M3 진행 규칙: Anthropic 비용 상한은 이번 진행 전체 $1이며 그 안에서는 호출마다 묻지 않음. Gemini는 무료 티어만(유료 필요 시 중단). 단계마다 테스트·lint·검증 에이전트 지적 수정·포트폴리오 갱신 뒤 커밋, push는 마일스톤 끝(SSE 뒤, M3 뒤). 비용 초과·새 정책 결정 필요·보호 파일 접근 필요·명세 충돌 시 중단 | 사용자 확인(2026-10-17) |

## 초기 기본 정책 — 설정으로 명시

전체60초·모델6시도·도구4제안·추가읽기retry1, 로컬 세션 수명 8시간(SESSION_TTL_S), 최종 원문 개수 고정 상한 없음/초기4000token, draft/action 만료5분. 주 실험 A/B는 동일 임베딩/거리의 exact vector이며 A 원문20/B Wiki5→원문20에서 공통 최종 선택한다. 온라인 추가 LLM·B만의hybrid·reranker는 주 실험에서 제외한다. 4000token은 dev 예산 스윕의 시작점이다. 이 값의 변경은 테스트·실험 config 버전에 남긴다.

## 아직 정할 것

| ID | 항목 | 정하는 시점·주체 |
|---|---|---|
| O-01 | 조직·역할·부서는 D-30으로 데모 값 확정. 남은 것: 정책/예외·우선관계 | 사용자가 PDF 제작/인계할 때 |
| O-02 | (ACL은 D-31로 확정) 실제 판본 번호·시행/종료일·문서 종류·available_from/document_role/application_basis·guidance 판본 구간·IT-038/055 개정/시행일 확인, transition_relations의 사건 조건 매핑(예: CM-092 "상신"을 어느 닫힌 값으로 볼지)과 검수 주체 | manifest 검수 전, 사용자와 확인. 2026-10-17 초안 작성(`data/raw/document-manifest.json`, 100건 needs_review), available_from 결정 방법은 [P-15](15-policy-options.md#p-15) |
| O-03 | D-26으로 해소. 남은 것: 각 도구의 버전 고정(uv 잠금 파일에 기록) | M0 |
| O-04 | 모델·공급자는 D-25/D-27로 확정. 남은 것: 차원은 D-32로 1536 시작(768 비교 기록), 한국어 품질 확인(dev 질문으로 비교 후보 하나와 대조, 예: 로컬 `voyage-4-nano`), judge의 정확한 Gemini 모델 ID, 공급자별 사용 한도 설정 | 차원·한국어 확인은 M3 색인 전. 차원이 pgvector 컬럼에 고정되므로 바꾸면 재색인. judge ID는 holdout 전 |
| O-05 | 파서는 D-33(pdfplumber)으로 확정. 남은 것: OCR 지원·한계·표 복원·파일 상한 | M3 파일럿 검증 |
| O-06 | chunk/overlap·거리·후처리·Wiki 탐색 config | dev 실험 전 고정 |
| O-07 | 예산 스윕 후보 값(초기4000+더 큰 값 2개 이상)·모델 한도 검증·최종 dev 동결값·packing_order·반복 횟수·seed | 비교 실행 전에 필수 설정 |
| O-08 | Wiki 주제 분할·검수 항목·권한별 분할 필요 | M4 빌드 전 검토 |
| O-09 | 정답 근거·150문항 실물·검수자 | PDF 검수 후 |
| O-10 | 데모 계정·역할·capability는 D-30으로 확정. 남은 것: IT 담당 부서 support_department_ids 값(M5) | 인증/티켓 구현 전; 범위 정책은 아래 확정 |
| O-11 | 정식 이름·공개 배포·데이터 보존기간 | 최종 데모/공개 전 |
| O-12 | 방향은 D-22로 확정. 남은 것: actor별 허용 원문 token 실측 결과와 기준선 실행 가능 actor 범위, 재정렬 추가를 판단할 hard negative 오답 기준, 추가 시 후보 수·한국어 reranker 모델·지연 허용치 | 기준선은 M4 비교 설계 전, 재정렬은 dev 예산 스윕 결과 확인 후 사용자와 확인([정책 선택 P-04](15-policy-options.md)) |
| O-13 | 방향은 D-24로 확정. 남은 것: P-05 시제 판별 표현 목록·표시 문구, P-07에서 C로 넘어갈 hard negative 오답 기준(O-12와 같은 판단) | M3 날짜 검색 구현 전, dev 예산 스윕 결과 확인 후 사용자와 확인([정책 선택](15-policy-options.md)) |
| O-14 | live_clock 교육 상태를 seed 때 계산할지 조회 때 계산할지. 현재 구현은 seed 때 계산(임시) | 실제 시간 진행 데모 전 사용자와 확인([정책 선택 P-10](15-policy-options.md)) |
| O-15 | 모델 호출 시간 초과의 외부 오류 코드. 닫힌 사전에 전용 코드가 없어 현재 MODEL_UPSTREAM_ERROR(내부 kind=timeout, retryable)로 내보냄(임시) | UI 오류 문구 연결(M6) 전 사용자와 확인([정책 선택 P-11](15-policy-options.md)) |
| O-16 | D-34로 해소(P-12 B) | M3 사건 날짜 대조 설계 전 사용자와 확인([정책 선택 P-12](15-policy-options.md)) |
| O-17 | D-34로 해소(P-13 B) | M3 원문 주입·T-34 설계 전 사용자와 확인([정책 선택 P-13](15-policy-options.md)) |
| O-18 | 공백만 있는 제목·메시지 처리. 현재는 수락(임시), NUL은 422 | UI 연결(M6) 전 사용자와 확인([정책 선택 P-14](15-policy-options.md)) |

## 이번 변경에서 하지 않은 일

PDF/규정 본문·실제 manifest·평가 문항·백엔드·위키·DB 및 서버 테스트를 생성하지 않았다. 정적 시안 회귀 테스트는 별도로 저장했다. 2026-10-17 추가: 사용자 PDF100개/248쪽을 수령했고 실제 식별·사건 날짜·접수 필드를 보정했다. 기존 정적 시안에는 통합 업무 흐름을 추가했으며 실제 앱/백엔드 구현은 보류했다. 성능·정답률·비용·실제 공고 마감일은 새로 주장하지 않는다.

## 데모 지원 담당 범위

일반 직원은 본인 티켓만, support 역할은 manifest/fixture의 support_department_ids에 속한 요청자 티켓만 읽는다. 전사 지원 범위는 별도 명시 capability가 있을 때만 부여하며 빈 목록은 거부다. 공개 시안은 가상 단일 사용자이고 실제 권한 구현이 아니다. 실제 계정/부서 ID·비밀 값은 O-10에서 구현 전 확정한다.

선택지·trade-off와 사용자 답변의 반영은 [3차 정책 결정](15-policy-options.md)에 보존한다. 원문에서 알 수 없는 metadata/회사 정책 값은 이 결정으로 임의 생성하지 않는다.
