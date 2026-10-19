# MOD-11 검색 전략 조정


## 책임과 소유권

온라인 A/B 전략과 원문 최종 근거 조립·검색 진단을 담당한다. 문서/Wiki 저장소는 소유하지 않는다. MOD-03에는 같은 search_documents 계약을 제공하고 MOD-01에는 실행 설정 고정·참조 재검증을 제공한다.

## 공개 작업

ResolveRetrievalContext(conversation_strategy,server_config) → CT-13. Search(CT-13,SearchRequest,actor) → CT-14. SearchRequest는 MOD-02가 확인한 business_dates/question_context를 서버 경계에서 받는다. CheckEvidenceVisibility(actor,resource_ids) → 현재 판정. snapshot 고정이 불가능한 설정은 요청 시작 전에 실패시킨다.

## 전략

- raw: MOD-05 SearchOriginal→공통 최종 근거 선택.
- wiki_assisted: 고정 wiki_snapshot_id의 MOD-10 exact vector 후보 탐색→허용 원문 링크를 MOD-05로 확장→공통 최종 근거 선택. 주 실험은 A/B 모두 벡터 검색이며 B에만 키워드/hybrid를 추가하지 않는다. 후보·확장 상한은 [비교 프로토콜](../13-retrieval-comparison.md)을 따른다.
- full_context_reference(APP-04 평가 전용): 같은 날짜 해석 뒤 검색 대신 MOD-05.ReadAllowedCorpus로 사건별 허용 passage 전체를 반환한다. 운영 설정에서는 비활성이다.
- 같은 원문 정렬·중복 제거·packing_order를 적용한다. 한 호출 안에서는 후보·그룹·support_group만 구성하고, 여러 호출에 걸친 최종 token 예산 조립은 MOD-02가 [검색 조립 계약](../contracts/05-retrieval-assembly.md)의 같은 규칙으로 한다. 재정렬을 쓰는 비교에서는 같은 reranker를 A의 원문 후보와 B의 확장 원문 후보에 적용한다. 상세 알고리즘은 설정 버전으로 고정하고 실험 전에 확정한다.
- 최종 모델에 제공하는 사실 근거는 CT-08 원문뿐이다. Wiki 탐색 텍스트를 최종 답변의 독립 근거로 넣지 않는다.

## 시점·권한·fallback

현재 ACL·게시·knowledge_as_of를 후보 탐색과 원문 확장 모두에 적용한다. normative는 사건 시행 구간, guidance는 공개 시점·문장 조건·원규정 연결로 검사한다. [사건 날짜 계약](../contracts/02-business-dates.md)에 따라 business_dates의 종류·근원과 application_basis를 검증한다. 누락/모순/사건 모호성은 CT-14 resolution=needs_clarification으로 반환하고 수락일로 대체하지 않는다. 원문0건은 resolved+빈 passages다. 비교 질문은 두 시점으로 별도 검색한다. Wiki의 다른 시점 링크를 현재 규정처럼 쓰지 않는다. 판본 안 비교표·경과조치의 적용 조건도 보존하며 누락 원문은 추정해 복구하지 않는다.

운영 B의 Wiki 미게시/stale/해당 범위 후보 없음은 raw fallback을 허용하되 원인을 기록한다. 엄격 B 실험에서는 fallback을 실패로 집계한다. 비정상 모듈 장애도 성공한 Wiki 검색으로 위장하지 않는다. 권한 제한 때문에 후보가 없는 경우의 내부 진단을 사용자에게 노출하지 않는다.

## 진단·검토

요청/실제 전략, corpus/wiki/config ID, 기준일, 허용 후보 수, 최종 원문 ID/순위, 단계별 시간·usage·fallback을 run에 전달한다. T-27 A/B 같은 원문 조건, T-28 strict/fallback·snapshot 혼합 방지, T-29 최종 원문 인용·시점. FR-05/11/13 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

날짜 미확정이면 MOD-05.LookupApplicableBasis 메타데이터를 조회한 뒤 되묻는다. knowledge_as_of와 사건 as_of_date, normative/guidance 필터,90일 이내 예정 사건 및 CT-14 unsupported 매핑은 사건 날짜 계약을 따른다.

## 3차 검토 보정

guidance의 유효 안내 판본 선택→기본 규범→검수 경과조항 확장→사건별 evidence_group/support_group 병합의 순서를 적용한다. 최종 개수5개 고정 상한을 폐지하고 공통 token 예산과 조건 보존을 따른다. 여러 query의 거리 점수를 직접 합산하지 않는다. [검색 조립](../contracts/05-retrieval-assembly.md)이 공개 협력 기준이다.

## 2026-10-17 M3 구현 메모

- raw만 구현했다(config `raw-exact-cosine-v1`, 후보 20). 임베딩은 질의도 MOD-05가 MOD-07로 만든다(MOD-11은 MOD-07을 직접 부르지 않는다).
- LookupApplicableBasis는 날짜 필터 없이 가장 가까운 판본 1개의 검수 메타데이터만 본다(처음 3개로 두었다가 실제 모델 smoke에서 관련 없는 규정 때문에 되묻기가 과해 줄였다). 그 판본이 규범이고 사건 기준(교육 시작일 등)을 요구하는데 date_basis가 current/explicit_date면 needs_clarification(missing_date)을 돌려준다. 상위 몇 개를 볼지는 구현 설정이며 dev 실험에서 조정할 수 있다.
- 사건 기준 규범은 질문의 date_basis가 대응표와 맞을 때만 남긴다. current 질문에 사건 기준 규범이 걸리고 MOD-02가 `assume_today`를 허용하면(D-61), 검색 요청을 그 사건 기준·오늘 날짜로 바꿔 같은 규칙으로 고른다. general_reference·per_claim 규범과 안내는 날짜 기준과 무관하게 남긴다.
- 그룹(support_group)은 대표 후보의 코사인 거리 순, 같은 거리는 passage ID 순이다. 경과조항 확장(ExpandTransitionEvidence)은 검수된 transition_relations가 아직 없어(P-15) 구현하지 않았다.
- 규범 공백(T-17, 2026-10-18): 판본 후보 전체에서 이 날짜 기준에 대응하는 가장 가까운 규범(per_claim 제외)이 그 날짜를 포함하는 공개 판본을 갖지 않으면 `normative_gap`을 결과에 표시한다. 사건 기준 질문에 그 기준의 규범이 없고 다른 사건 기준 규범만 있으면 basis_mismatch로 되묻는다. 안내 passage는 남기고 결론 보류는 MOD-02가 한다. 우선관계(authority_relations) 표시와 경과조항 확장은 D-40으로 구현했다(아래).
- 경과조항 확장·우선관계(D-40, 2026-10-18): 기본 그룹의 판본에 transition_relations가 있고 그 application_basis가 이번 date_basis와 같으면, 알려진 사건 조건이 맞을 때만 진행한다. 빠진 사건 날짜는 되묻고, 모두 맞으면 반대편 판본 조항을 같은 그룹에 source_role=transition으로 붙인다. 결과의 authority_relations는 대상 문서가 보이는 관계만이다(제한 문서의 존재를 드러내지 않음).

## 구현 메모(M4 wiki_assisted, 2026-10-18)

- `RetrievalService.search(..., strategy, wiki_snapshot_id, strict)`. 날짜 검증·LookupApplicableBasis·규범 공백 판정·support_group·경과조항·우선관계는 A와 같고, 원문 직접 후보 단계만 바뀐다(D-46).
- B: MOD-10 GetCandidates(page 5개) → 링크 passage를 MOD-05 `passages_by_ids`로 펼친다. raw 검색과 같은 SQL 필터(권한·게시·지식 시점·규범 적용 구간)를 다시 거치고 같은 원문 거리로 정렬해 20개. Wiki 거리는 원문 순서에 쓰지 않는다. Wiki 본문은 결과에 넣지 않는다.
- 운영 B: Wiki 미준비·stale·후보 0개 → raw fallback, `effective_strategy=raw`, `fallback_reason`. 엄격 B: fallback 없이 `strict_failure`와 빈 결과. 펼친 passage가 필터에서 모두 빠지면 실패가 아니라 B의 0건 결과다.
- 진단: `RetrievalResult.trace()`(요청/실제 전략·이유·Wiki 후보 ID와 거리·snapshot·retriever_config_id)를 MOD-03이 `ToolResult.trace`로 넘기고 MOD-01이 `tool_calls.retrieval_trace`에 저장한다. 모델이 보는 도구 결과 형식은 A/B가 같다.

- 진단 보강(독립 검증 반영): trace에 resolution·date_basis·as_of_date·knowledge_as_of·패킹 전 후보(그룹 ID·순위·대표 거리·passage ID, Recall@pool)를 넣고, 운영 fallback이면 실제로 실행한 `raw-exact-cosine-v1`을 retriever_config_id로 남긴다. 예산 안에 실제로 들어간 passage(Recall@budget)는 MOD-02가 run 단위로 `agent_runs.evidence_trace`에 남긴다.
- 전체 문맥 기준선(D-50): `strategy=full_context_reference`는 eval_fixture actor만 쓴다(그 밖은 RETRIEVAL_NOT_READY, 대화 생성도 INVALID_REQUEST). 날짜 검증·되묻기·규범 공백·경과조항·우선관계는 A와 같고, 후보 단계에서 같은 검색 SQL을 LIMIT 100,000으로 불러 그 사건 날짜에 허용된 passage 전체를 넣는다. support_group은 다시 조회하지 않고 passage의 ordinal로 묶는다. retriever_config_id `full-context-reference-v1`.

