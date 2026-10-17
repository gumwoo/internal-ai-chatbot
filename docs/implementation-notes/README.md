# 구현 참고 — 이전 교육 조회 설계 자료

이 폴더의4개 예제는 **개정2 이전** 교육 조회/공개 문서 중심 자료다. 현재의 ACL·과거 판본·PDF provenance·corpus/Wiki snapshot·티켓 확인 계약을 완전하게 반영하지 않는다. 그대로 복사해 현재 스키마/실행 정책으로 사용하지 않는다.

검토/승인 대상은 [아키텍처](../architecture/00-review-guide.md), [공통 계약](../contracts/00-shared-contracts.md), [모듈](../architecture/04-module-map.md)이다. 이 폴더는 내부 구현을 강제하지 않는다.

- [이전 SQL 예제](01-sql-schema-example.md).
- [이전 Agent 반복 예제](02-agent-loop-example.md).
- [이전 벡터 쿼리 예제](03-vector-query-example.md).
- [이전 패키지 배치](04-previous-package-layout.md).

구현할 때 선택한 ORM·SDK·파서·마이그레이션에 맞춰 새 예제를 검증한다. 모듈 간 쓰기 소유권·현재 권한·원문 근거·확인 쓰기의 불변식을 먼저 만족해야 한다.
