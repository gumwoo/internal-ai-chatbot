# MOD-04 교육 조회


## 책임과 소유권

trainings의 단일 쓰기 소유자. 날짜 해석·교육 목록/상세·개발 fixture를 담당한다. 교육 관련 PDF 규정은 MOD-05 소유이며 교육 신청은 이번 MVP에서 제외한다.

## 공개 작업

ListTrainings(CT-04,server_now) → CT-05 Page. GetTraining(uuid) → CT-05 Detail. LoadDemoTrainings(anchor_date, fixture_mode) → 적재 보고서(개발/테스트 CLI 전용). fixture_mode는 fixed_status/live_clock이며 기본값 없이 설정에 명시한다. HTTP와 도구가 같은 작업을 사용한다.

## 업무 정책

- KST, 주 시작 월요일, 시작 포함·종료 제외. 기본 next_30_days, 최대90일.
- today/this_week/next_week/next_30_days/custom 지원. custom만 두 날짜를 받는다.
- today=[오늘00시,내일00시), this_week=[이번 월요일00시,다음 월요일00시), next_week는그다음7일, next_30_days=[오늘00시,오늘+30일00시). 현재 시각 이후 필터는 자동 추가하지 않는다.
- 목록 기본 status=scheduled, 시작 시각 기준 정렬 후 ID로 안정 정렬. 취소/완료는 기본 목록 제외, 상세는 실제 상태 반환.
- 제목은 대소문자 무시 부분 일치, query 최대100자. limit1~20, offset>=0.
- 이 샘플 교육은 로그인 직원에게 공개한다. 문서 권한이 교육 일정까지 자동 상속되는 것은 아니다.
- 0건은 정상, 잘못된 UUID는 입력 오류, 없는 UUID는 TRAINING_NOT_FOUND.
- 고정 seed는 code/ID 기준 재실행 가능, 테스트 날짜와 실제 데모 anchor를 구분한다.
- 데모 anchor의 주 월요일과2026-10-12의 차이만큼 모든 fixture 날짜를 함께 이동한다. 시각·기간·요일은 유지한다. status는 fixture_mode에 따른다. fixed_status는 status_override를 유지하고 live_clock은 이동한 시각과 서버 clock으로 다시 계산한다. [첫 구간](../12-first-milestone-spec.md)의 표와 경계 사례가 기준이다.

## 협력·검토

다른 업무 모듈에 직접 의존하지 않는다. 현재 사용자 확인은 진입 어댑터에서 하고 clock/DB 포트를 주입한다. T-11 날짜·페이지·0건·상태, T-12 상세·fixture 재실행. 상세 fixture는 [첫 구현 구간](../12-first-milestone-spec.md). FR-01/02 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.
