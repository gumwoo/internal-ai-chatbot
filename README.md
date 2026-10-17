# Enterprise Knowledge & Work Agent

가상 회사의 **사내 통합 업무지원 AI Agent** 설계 저장소입니다. 교육 일정 조회를 업무 모듈로 유지하고, 여러 부서의 PDF 규정 검색과 IT 지원 요청으로 확장합니다.

현재 상태는 **설계·정적 UI 시안 단계**입니다. 백엔드·색인기·위키·평가 실행기가 구현됐다는 의미가 아닙니다. 최신 설계·시안 정리: 2026-10-17. 시안 사건 날짜는 재현을 위해 2026-10-16 등 고정 예시를 사용합니다.

## 이번에 확정한 범위

- 사용자 제공 PDF 100개: 현행 91개 + 구버전 9개, 논리 문서 91종.
- 지식 계층: PDF 원본 → 페이지·구간이 보존된 원문 → 원문 링크를 가진 LLM Wiki.
- 비교: A 원문 RAG / B Wiki 보조 원문 RAG. 두 방식의 최종 근거는 원문 PDF.
- 문서별 접근 권한, 특정 날짜 기준 조회, 개정 전후 비교, 과거 대화의 권한 재검증.
- 업무 API: 교육 목록·상세, IT 티켓 목록·상세·등록 준비·사용자 확인 후 등록.
- 평가 목표 150문항. 문항과 정답은 PDF 검수 후 별도 제작.

## 읽는 순서

1. [프로젝트 범위](docs/00-project-overview.md)와 [요구사항](docs/01-requirements.md).
2. [설계 검토 안내](docs/architecture/00-review-guide.md): 인프라 → 애플리케이션 → 레이어 → 모듈 → 협력.
3. [12개 모듈 지도](docs/architecture/04-module-map.md), [공통 계약](docs/contracts/00-shared-contracts.md), [협력 시나리오](docs/architecture/05-collaboration.md).
4. [PDF 100개 목록](docs/corpus/00-document-inventory.md), [문서 메타데이터·제작 인계 기준](docs/corpus/01-metadata-contract.md).
5. [RAG·Wiki 설계](docs/06-rag-design.md), [A/B 비교 프로토콜](docs/13-retrieval-comparison.md), [티켓 확인 흐름](docs/14-ticket-workflow.md).
6. [개발 순서](docs/08-development-plan.md), [첫 구현 구간](docs/12-first-milestone-spec.md).

HTTP는 [API 명세](docs/04-api-spec.md), 데이터 소유권은 [데이터 모델](docs/03-data-model.md), 검증 기준은 [테스트·평가](docs/07-test-and-evaluation.md)를 따릅니다. 클래스·SQL 예제는 [구현 참고](docs/implementation-notes/README.md)로 분리합니다.

2026-10-17 검토 반영: [실행 수락·재전송·복구](docs/contracts/01-run-lifecycle.md), [사건 날짜 전달](docs/contracts/02-business-dates.md), [티켓 수정·확인·입력 출처](docs/14-ticket-workflow.md)를 추가/보완했습니다. [A/B 주 실험](docs/13-retrieval-comparison.md)은 동일 벡터 채널로 통제합니다. 첫 구간은 서버 고정 test_stub·KST00시 구간·주 단위 anchor 이동과 단계별 테스트 범위를 명시합니다. 이는 설계 계약이며 backend가 구현됐다는 뜻이 아닙니다.

## PDF를 넣을 위치

**`data/raw/pdfs/`**에 사용자 PDF100개가 수령됐습니다(총248쪽). [수령 관리정보 목록](docs/corpus/02-received-register.md)과 [실제 PDF 반영 설계 보정](docs/corpus/03-received-pdf-adjustments.md)을 추가했습니다. [입력 안내](data/raw/pdfs/README.md)를 먼저 확인합니다. 원본 PDF·사내 규정 본문·실제 평가 문항은 이번 설계 개정에서 만들지 않았습니다. 버전·시행일·권한 등 아직 제공되지 않은 값도 임의로 확정하지 않았습니다.

## UI 시안

[통합 업무지원 화면 시안](prototypes/work-assistant/README.md)은 기존 배치·색감을 유지하고 규정/PDF 출처, 사건 날짜 기준의 과거 규정, IT 요청 입력·확인·접수 예시를 클릭할 수 있게 확장했습니다. [사용 순서](docs/ui/02-prototype-walkthrough.md)와 [화면 요구사항](docs/ui/01-screen-proposal.md)을 확인합니다. 실제 AI·인증·DB·접수 기능은 없습니다. React·TypeScript / FastAPI / PostgreSQL·pgvector / Docker Compose 방향을 유지합니다.

## 3차 검토 보정

[정책 선택 기록](docs/15-policy-options.md), [닫힌 오류 사전](docs/contracts/03-errors.md), [입력 출처 계약](docs/contracts/04-field-origins.md), [안내 판본·경과조항·검색 병합](docs/contracts/05-retrieval-assembly.md)을 추가했다. 최종 근거5개 고정 상한은 폐지하고 필요한 조건/예외의 support_group과 공통 token 예산을 사용한다. [시안 회귀 테스트](prototypes/work-assistant/tests/README.md)는 결과 경로를 명시해 과거 보고서를 보존한다.
