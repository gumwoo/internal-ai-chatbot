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

## 구현 메모(M4, 2026-10-18)

- 코드: `backend/src/agent/modules/wiki/`(build.py 순수 단계, service.py 빌드·검수·게시·후보, tables.py), 마이그레이션 0009, 운영 CLI `draft-wiki-topics`·`review-wiki-topics`·`build-wiki`·`export-wiki-review`·`apply-wiki-review`·`publish-wiki`·`wiki-status`(`backend/src/agent/app/wiki_ops.py`).
- 주제 계획(D-45): `data/wiki/topic-plan.json`. 모델이 제목·종류만 보고 도메인별 초안을 쓰고(needs_review), 모든 문서가 들어 있는지 검사한 뒤 검수 표시한다. 검수 전 계획으로는 빌드하지 않는다.
- page = 주제 × 권한 등급(같은 접근 정책) × (규범 시행 구간 | 안내 유효 기간). 안내 문서는 규범 구간 page에 넣지 않는다. 기여 원문은 page 입력 판본 전체다.
- 생성: purpose=wiki_build, 원문 passage를 `<passage label=…>`로 감싸 넣고 원문 속 지시는 자료라고 명시(T-34 M4 부분). 출력은 title·summary·claims·relations(각 항목에 passage 라벨과 원문 그대로의 인용).
- 자동 대조: 라벨이 입력 passage인지, 인용이 그 passage의 연속 구간인지(공백 정규화), 주장마다 링크가 있는지. 실패하면 문제를 알려 1회 재생성, 다시 실패하면 page를 `excluded`(problems)로 남긴다. 통과한 page만 원문과 같은 임베딩 모델·차원·입력 형식(document)으로 임베딩한다.
- 비용 기록: build·page마다 호출 수·입력/출력 token·사용량 미확인 호출 수·임베딩 요청/입력 수. 모델·프롬프트·설정 ID·주제 계획 hash·원문 hash(page별 source_hash)를 남긴다.
- 의미 검수(D-48): `export-wiki-review` 파일에 page·주장·인용·원문 passage 본문을 담고, 검수자가 approved/rejected·reviewer·reviewer_kind를 채워 `apply-wiki-review`로 반영한다. pending이 남으면 게시하지 않는다.
- 게시: build가 validated이고 묶인 corpus가 현재 게시본이며 승인 page가 있을 때, 승인 page만 snapshot·포인터를 한 트랜잭션으로 바꾼다. 실패하면 이전 snapshot·포인터가 그대로다. 이전 build는 retired로 바뀌지만 snapshot은 남는다.
- stale: 저장하지 않고 판정한다. 포인터의 snapshot이 묶인 corpus와 현재 corpus 게시본이 다르면 stale. run의 corpus와 다른 Wiki snapshot은 후보를 내지 않는다.
- 후보(GetCandidates): 사건 날짜가 page 구간 안, 지식 시점이 기여 원문 공개 이후·안내 유효 기간 안인 page를 거리순으로 보고, MOD-05 `visible_editions`로 기여 판본이 모두 보이는 page만 5개까지 낸다(순위는 보이는 page 안에서만). ACL 변경·철회는 즉시 반영된다.

### 독립 검증 반영(2026-10-18)

- 주제 제목을 page 생성 입력에서 뺐다. 주제 계획은 권한 등급이 다른 문서 제목으로 만들어질 수 있어, page 제목·탐색 문장에 그 page가 받지 않은 제한 문서 이름이 섞였다(제목은 후보 계약에 포함되므로 누출로 본다).
- 공개 날짜가 다른 안내는 page를 나눈다. 원문 값은 이스케이프해 `<passage>` 구조를 위조하지 못하게 하고, 인용 대조는 이스케이프를 되돌려 원문 글자로 한다. 숫자 중간에서 끊은 인용("1,100,000원"의 "00,000원")은 거절한다.
- 재생성: 원문 대조 문제·잘린 출력(OUTPUT_INVALID)은 문제를 알려 1회 재생성, 일시 오류(rate limit 등)는 재생성 기회와 따로 1회 재시도. 빌드 도중 예외는 build를 failed로 바꾸고 그때까지의 사용량을 남긴다. 실패한 임베딩 요청도 시도 수에 센다.
- 게시는 advisory lock으로 직렬화한다(동시 게시에서 두 build가 published가 되지 않게). 검수 결정에는 reviewer_kind(human/model)가 있어야 한다. 검수 파일은 build가 묶인 corpus의 원문으로 만든다.
- health `/health/ready`의 capability: knowledge는 corpus 게시본이 있으면 ready, wiki는 ready/stale, 아니면 disabled.
