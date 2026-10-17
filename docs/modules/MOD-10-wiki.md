# MOD-10 Wiki 관리


## 책임과 소유권

wiki builds/pages/claims/source_links/snapshots와 검수·게시 상태를 소유한다. 원문을 대체하거나 원문 업무 규정을 수정하지 않는다. Wiki는 사전 생성한 주제·절차·문서 관계 탐색 자료다.

## 공개 작업

BuildWiki(corpus_snapshot,scope,config,operator) → CT-15 초안/비용/오류 보고서. ValidateBuild → 링크/주장/누락 검사. PublishWiki(build) → 불변 snapshot. GetCandidates(query,actor,corpus_snapshot_id,wiki_snapshot_id,as_of_date,config,limit) → 읽기 허용 Wiki 후보. GetBuildStatus → 운영 상태. 실시간 대화 중 빌드하지 않는다. 지정 snapshot 대신 실행 도중의 최신 Wiki로 바꾸지 않는다. wiki_embeddings도 MOD-10 소유이며 원문과 같은 임베딩 모델/차원·거리로 주 실험의 exact vector 후보를 만든다.

## 협력과 게시

MOD-05의 ReadBuildSources로 명시 권한의 원문을 읽고 MOD-07의 구조화 생성/임베딩을 호출한다. 주장별 실제 edition/block/span 링크를 검증한다. 검수·준비가 끝난 전체 게시 단위만 짧은 트랜잭션으로 활성화한다. 생성 모델·프롬프트·설정·원문 hash·비용을 기록한다. 링크 존재 검사는 의미 충실성 검수를 대체하지 않는다.

## 권한·개정 규칙

- page를 구성한 모든 원문을 현재 사용자가 읽을 수 있어야 page 내용·제목·후보를 반환한다. 권한의 합집합으로 공개하지 않는다.
- 혼합 권한 문서는 권한별 별도 page로 나누거나 page 전체를 숨긴다. 첫 버전은 전체 교집합 검사를 사용한다.
- exact corpus snapshot에 결합한다. 새 corpus에서 오래된 Wiki를 묵시적으로 재사용하지 않는다.
- 판본별 주장에 시행 구간을 보존한다. 구간별 탐색 page로 분리해 as_of에 맞는 요약만 후보로 반환한다. 과거/현행 요약을 섞지 않으며 관계만으로 다른 시점 규칙을 확정하지 않는다.
- 원문 변경·철회·ACL 변경 시 영향 원문을 재검사한다. 내용 변경/링크 손상은 stale로 표시하고 재빌드한다.
- Wiki 정답은 평가 질문/정답으로부터 생성하지 않는다. 평가셋은 빌드 입력에서 제외한다.

## 실패·검토

draft→validated→published, failed/stale/retired 상태 구분. 원문 링크 무효·위조 인용·권한 누락은 게시 거절. 마지막 정상 snapshot은 보존하되 다른 corpus에 적용하지 않는다. T-24 주장/링크·비용, T-25 권한 교집합, T-26 stale/원자적 게시. FR-12 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

Wiki 탐색은 knowledge_as_of와 사건 날짜 두 축을 보존하고 guidance의 공개일을 사건 적용일로 쓰지 않는다. gold 정본은 PDF hash/page/quote anchor이며 block은 parser revision별 정렬 산출물이다.
