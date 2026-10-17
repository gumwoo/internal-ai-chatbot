# MOD-05 원문 지식·카탈로그


## 책임과 소유권

PDF 불변 원본, 논리 문서·업무 판본·파싱 artifact, 페이지/block/chunk/embedding, corpus snapshot과 자원 ACL 바인딩의 단일 쓰기 소유자. 원문 검색·근거/PDF 제공·현재 권한 재검증을 담당한다. Wiki 내용은 소유하지 않는다.

## 공개 작업

| 작업 | 계약 |
|---|---|
| StagePreparedEdition / PublishCorpus | CT-09 검증→준비 등록→원자적 snapshot 전환 |
| LookupApplicableBasis | query·actor·knowledge_as_of·snapshot → 허용 메타데이터의 사건 종류/원규정 관계; 답변 passage 제외 |
| SearchOriginal | query·현재 actor·knowledge_as_of·사건 as_of_date·고정 corpus·검색 설정→CT-08 목록 |
| ExpandTransitionEvidence | actor·snapshot·knowledge_as_of·기본 edition·verified_events(사건 종류별 검증 날짜 목록)→검수 transition_relations의 경과조항과 참조 조항 CT-08 목록(source_role 포함). event_conditions의 모든 사건이 확인될 때만 반환 |
| ReadAllowedCorpus | actor·snapshot·knowledge_as_of·사건별 date_basis/as_of_date→사건마다 허용된 normative 적용 판본·유효 안내 판본·검수 경과조항의 passage 전체(CT-08). APP-04의 전체 문맥 기준선 전용이며 직원 요청 경로에는 노출하지 않음 |
| GetPassages / GetEvidence / OpenSourcePdf | 원문 ID+현재 actor→허용된 원문/원본 |
| ReadBuildSources | 운영자·범위·snapshot→Wiki 빌드용 원문·정책 |
| CheckSourceVisibility | actor·문서/판본 ID 목록→모두 허용 여부, 안전한 표시 데이터 |
| UpdateResourceAccess | 권한 있는 운영자·정책→ACL revision 증가 |

## 정책

- MOD-09에 자원 정책과 현재 actor를 전달해 판정한다. 검색 전에 ACL·게시·지식 공개 시각을 제한하고 normative에는 사건 적용 구간을 적용한다. 먼저 검색하고 최종 화면에서만 숨기지 않는다.
- 과거 판본도 published 상태로 유지한다. normative는 사건 as_of_date에 유효한 판본, guidance는 지식 공개 시점·안내 판본 유효 구간(guidance_valid)과 문장 조건으로 선택하고 현재 ACL을 적용한다. 미공개 미래 지식/기간 공백/충돌은 추측하지 않는다.
- corpus는 불변 membership과 manifest/config hash. 새 snapshot 게시까지 기존 snapshot을 유지한다. ACL 변경은 불변 과거 snapshot보다 현재 정책이 우선한다.
- 인용은 PDF 실제 물리 페이지·block/offset으로 추적 가능해야 한다. 페이지 복원이 안 된 파일은 준비 상태로 남긴다.
- PDF 경로/해시는 서버가 관리한다. 원본을 공개 정적 파일로 노출하지 않는다.
- 우선순위는 운영자가 제공한 문서 관계/효력 정보로 해석한다. FAQ/공지/규정이 충돌하면 임의 제목 분류만으로 우열을 정하지 않는다.

## 협력·실패

MOD-07로 검색 임베딩을 한 번 호출하고 MOD-09로 권한을 판정한다. 임베딩 모델/차원 불일치·잘못된 판본 구간·링크 누락·파싱 미검수는 게시 거절. 검색 0건은 정상. 단일 파일 실패가 기존 게시본을 지우지 않는다. 저장·원본 파일 참조의 일관성을 게시 전에 검증한다.

## 검토·테스트

T-13 파싱 provenance, T-14 snapshot 원자성, T-15 시점/개정, T-16 ACL/출처/PDF/철회, T-17 충돌. FR-05/09/10/11 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

LookupApplicableBasis는 현재 ACL/게시/knowledge_as_of를 적용한 검수 메타데이터 조회다. 사건 날짜 미확정에서 답변용 원문을 반환하지 않는다. normative는 사건 적용 구간, guidance는 공개 시각과 문장 조건/원규정 연결로 판정한다.

## 3차 검토 보정

ExpandTransitionEvidence와 ReadAllowedCorpus는 위 공개 작업 표가 기준이다. guidance_valid 구간·transition_relations의 저장/검수는 MOD-05 책임이며 [검색 조립](../contracts/05-retrieval-assembly.md)을 따른다.
