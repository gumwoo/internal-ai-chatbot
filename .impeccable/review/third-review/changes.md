# 3차 재검증 수정 기록

범위: 정적 HTML/JS 시안, 문서, 회귀 스크립트. 실제 backend/DB/RAG/MCP 구현과 PDF 수정은 하지 않았다.

## 시안과 테스트

- prototypes/education-agent/app.js: 모든 날짜 후보의 사건 역할·연도 해석, 서울/경기, 명시 의도와 재질문 탈출, 지원 범위 밖 답변, 날짜 조건의 교육 목록/교육비 후속 문맥 분리. 만료 확인 안내, 배경 대화 접수 완료 알림, 오래된 초안 충돌 입력 보존과 명시적 재준비, message별 편집 포커스.
- prototypes/education-agent/tests/browser-flows.cjs: 기존 약한3검사를 실제 head ID/payload·입력·상태로 보강,37개 검사 추가. 저장소 밖 PROTOTYPE_RESULTS_DIR를 명시해 실행하고 출력 경로를 먼저 표시.
- prototypes/education-agent/tests/README.md: 외부 결과 경로 설정과 재현 방법. scripts/check_specs.py: 문서 검사 결과 경로 분리, 기존 PDF 해시 baseline 읽기.

## 명세 변경 파일과 이유

| 파일 | 이유 |
|---|---|
| docs/14-ticket-workflow.md, docs/03-data-model.md | prepared_from/displaced_head 관계 분리, 독립 root 여러 개/head 하나, conversation 유일키·세대·첫 삽입 경쟁·취소 후 ID |
| docs/modules/MOD-08-chat-ui.md | 변경 없는 draft도 revise,202 종료 후 동일 POST replay, 입력/포커스/완료 표시 |
| docs/contracts/04-field-origins.md, docs/05-agent-execution.md | origin 후보→서버 code point span 계산→재검증, 고정 template 닫힌 목록 |
| docs/contracts/03-errors.md, docs/04-api-spec.md | 닫힌 code/stage, details 허용 필드·우선순위·도구와 HTTP 구분 |
| docs/contracts/05-retrieval-assembly.md, docs/contracts/02-business-dates.md | guidance 판본·원규정 공백·경과조항 회수, basis 대응, 사건별 병합 |
| docs/corpus/01-metadata-contract.md | guidance 자체 판본 구간·transition 관계·검수 기준 |
| docs/contracts/00-shared-contracts.md | 변경한 DTO/포트와 처리 사건, 비활성 검색 provider, 최종5개 제한 폐지 |
| docs/06-rag-design.md, docs/13-retrieval-comparison.md | 필수 근거 보존/token 예산, gold 전체·holdout 전 Wiki/프롬프트 동결·judge 블라인딩 |
| docs/10-decisions-and-open-questions.md, docs/15-policy-options.md | 사용자 선택·trade-off 기록, O-02 metadata/IT-038·055 확인 항목 |
| docs/12-first-milestone-spec.md, docs/architecture/02-applications.md, docs/architecture/05-collaboration.md | fixture 상태 모드와 anchor 일관성, M1/M2 DisabledRetrievalContextProvider의 조립 주체 |
| docs/modules/MOD-02/03/05/07/11/12 문서 | 실제 소비/검증/확장 책임을 변경한 공통 계약과 연결 |
| docs/07-test-and-evaluation.md, README.md | 기존35개 T ID 안의 세부 수락 기준과 신규 계약 탐색 링크 |

## 사용자 결정

독립 draft 여러 개/head 하나와 원규정 공백 결론 보류를 사용자 답변으로 확정했다.5개 상한은 필수 근거를 자르면 안 된다는 사용자 피드백에 따라 폐지했다. 실제 available_from/ACL/IT-038·055의 작성 의도 등 확인되지 않은 원문 metadata는 O-02에 남겼으며 임의 채우지 않았다.

## 검증 범위

브라우저91개(기존54+추가37) 통과, 예외0건. 1440×900/1280×720/390×844의12캡처는 form 상단/하단 내부 스크롤 구간을 구분했다. 결과는 저장소 밖 임시 경로에서 실행한 후 이 폴더에 명시적으로 복사했다. 기존 state-contract54개 결과는 덮지 않았다. 닫힌 계약/링크 검사는 의미적 증명이 아니며 실제 DB 경쟁·모델 정확도·권한 구현은 미검증이다.

기존 detector의11px 보조 주석 경고1건은 시각 체계/토큰 변경 범위 밖으로 기록했다. 새 검색 상한 정책이 실제 품질을 보장한다는 주장은 하지 않는다.

독립 검토의 만료 수정/취소 무응답과 비교 날짜 유실을 추가 수정했다. 최초83개 증거는 initial-83에 보존하고 최종91개 결과/12캡처는 이 폴더에 저장했다.
