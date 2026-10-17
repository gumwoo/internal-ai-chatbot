# MOD-03 도구 실행


## 책임과 소유권

정적 도구 등록부·인자 스키마·분배·결과 정규화를 소유한다. DB를 소유하지 않는다. 도구별 업무 정책이나 재시도 판단을 복제하지 않는다.

## 공개 작업

DescribeAllowedTools(context) → 모델용 명세. ExecuteOnce(context, ToolExecutionInput{proposal,call_ordinal,field_origins?,observer}) → CT-06. field_origins는 prepare_it_ticket에서만 MOD-12로 전달하고, observer로 교육 결과 receipt를 기록한다. 등록 이름만 허용하고 추가 필드는 거절한다. timeout은 실행 남은 예산 이하다.

| 도구 | 실행 대상 |
|---|---|
| list_trainings / get_training | MOD-04 |
| search_documents | MOD-11 |
| list_it_tickets / get_it_ticket / prepare_it_ticket | MOD-12 |

모델에 confirm/create/cancel 티켓 도구, 임의 HTTP·SQL·파일 읽기·문서 게시·Wiki 빌드 도구를 노출하지 않는다. 사용자에게 허용된 capability에 맞춰 명세를 제한하되 실행 대상 모듈에서도 재검증한다.

## 결과·실패

한 시도만 수행한다. 검증 실패도 ordinal을 소비하고 TOOL_ARGUMENT_INVALID 또는 TOOL_NOT_REGISTERED를 반환한다. MOD-02가 필요시 모델 보정/읽기 재시도를 조정한다. 원문 passage에는 ordinal+결과번호로 실행 내 고유 citation_id를 부여한다. 여러 시점/여러 검색 간 ID 충돌을 금지한다. 공급자 전용 객체·비밀·내부 예외 본문을 결과에 넣지 않는다.

prepare_it_ticket는 실제 티켓을 만들지 않는 멱등 준비 작업이다. `(run_id,ordinal)`로 같은 준비 재시도가 새 action을 늘리지 않는다. 실제 확인 작업을 도구 재시도로 실행할 수 없다.

## 검토·테스트

T-09 미등록/무효/권한 위조 인자, T-10 분배·인용 ID·단일 시도. FR-03과 NFR-01/11 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

MOD-04의 실제 결과를 CT-11 RecordTrainingResult로 저장한 뒤 모델에 전달한다. receipt는 run/ordinal/training ID/starts_at/hash이며 기록 실패는 실행 실패다. prepare_it_ticket은 draft만 반환한다.

CT-06 origin_candidates는 비신뢰 제안으로 분리해 MOD-02의 구간 계산→MOD-12의 CP-07 재검증에 전달한다. 닫힌 오류 사전의 모듈 오류와 외곽 HTTP status를 혼동하지 않는다.
