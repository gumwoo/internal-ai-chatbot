# 원문 RAG / Wiki 보조 원문 RAG 비교 프로토콜

## 검증 질문

같은 벡터 검색 조건에서 Wiki 탐색·원문 링크 확장을 추가하면 단일 사실·다문서 종합·예외·개정·근거 부족·권한 상황에서 원문 회수와 답변이 개선되는가? 개선이 있다면 온라인 비용과 구축·갱신 비용을 감안해도 의미가 있는가? 주 실험의 차이는 원문 직접 후보와 Wiki 후보→원문 확장 경로다. 모든 종류의 RAG 대비 Wiki의 보편적 우위를 주장하지 않는다.

## A/B 정의

| 항목 | A raw | B wiki_assisted |
|---|---|---|
| 탐색 | 원문 passage exact vector 검색 | 주제 Wiki exact vector 검색 후 링크된 원문 확장 |
| 최종 근거 | 원문 PDF passage | 원문 PDF passage |
| 최종 생성 | 동일 모델·프롬프트·예산 | 동일 모델·프롬프트·예산 |
| 온라인 추가 LLM 탐색·키워드 | 없음 | 없음; 주 실험에 B만의 keyword/hybrid 없음 |
| 실패 | 오류/빈 검색을 그대로 측정 | Wiki 미준비/stale/후보 없음은 strict 실패 |

B는 Wiki만 읽고 답하는 시스템이 아니다. Wiki 본문으로 최종 규정 답변을 생성하지 않는다. B의 탐색·링크 확장 설정 자체는 실험 변인이므로 버전·후보 수를 보고한다. 운영 B의 raw fallback 비율은 별도 보고하고 strict B 성능에 합치지 않는다.

## 초기 비교 설정

| 설정 | 주 실험의 초기값·규칙 |
|---|---|
| 비교 ID | wiki-contribution-vector-v1 |
| 임베딩·거리 | A 원문/B Wiki/확장 원문에 동일 모델·차원·정규화·거리, query vector 재사용 |
| raw_candidate_limit | A에서 허용 원문 최대20 passage |
| wiki_candidate_limit | B에서 허용 Wiki 최대5 page |
| expanded_passage_limit | B에서 유효 원문 링크를 펼친 뒤 중복 제거·공통 원문 거리 정렬로 초기20 passage(성능/회수 한계를 dev에서 검증) |
| 최종 선택 | 그룹 내부 같은 원문 거리·passage ID tie-break·중복 제거, 그룹 간 공통 round-robin·support_group 보존 |
| final_passage_limit | null: 최종 개수 고정 상한 없음, 여러 검색 합계는 공통 token 예산 적용 |
| final_context_token_limit | 답변용 원문 합계 초기4000 token. dev 예산 스윕(아래 절)으로 holdout 전 동결, 동일 tokenizer·실제 모델 한도 검증 |
| packing_order | 그룹 안 관련도 순으로 앞부터 배치, support_group은 연속 배치. 설정 ID로 고정하고 A/B 동일 |
| reranker | 주 실험 없음. 후속 공통 실험은 별도 비교 ID(아래 절) |

이 값은 품질 정답이 아닌 재현용 시작 설정이다. dev50에서 조정할 수 있지만 공통 설정 변경은 양쪽에 적용하고 B 전용 후보/확장 변경도 config ID·실험 버전에 남긴다. holdout 전에 최종 값을 동결한다. 결과가 유리한 설정만 사후 선택해 같은 실험으로 보고하지 않는다.

키워드/hybrid를 검토한다면 별도 비교 ID로 A_hybrid와 B_hybrid의 검색 채널을 함께 맞춘다. B만 hybrid인 결과는 ‘두 전체 시스템 비교’로 구분하며 Wiki 단독 효과로 해석하지 않는다. 한국어 키워드 분석기·정규화는 그 후속 실험에서 별도 검증한다.

## 통제 조건

- 동일 PDF corpus snapshot·parser/chunk/embedding 설정·현재 ACL fixture·사건별 적용 기준일과 date_basis.
- 대화 생성 시 requested_strategy를 서버 설정으로 고정하고 run마다 corpus/wiki snapshot/config를 고정한다. MOD-10.GetCandidates에도 고정 wiki_snapshot_id를 명시한다.
- 동일 질문/대화 입력·도구 목록·최종 생성 모델/파라미터·시스템/출력 프롬프트.
- 공통 원문 정렬/중복 제거·support_group 보존·원문 token 상한. 개별 검색 top_k는 retriever config의 범위이며 최종 passage 수는5개로 제한하지 않는다. 여러 도구 호출의 누적 결과는 사건별 그룹을 유지해 공통 예산으로 조립한다. 변경 시 설정 버전을 바꿔 양쪽에 적용한다.
- final_context_token_limit은 설정 파일의 필수 값으로 비교 시작 전에 확정한다. 미정인 채 실행하지 않는다. Wiki 구축 모델은 별도로 기록하며 동일 답변 모델이라는 표현에 혼동시키지 않는다.
- A/B 별도 대화·빈 캐시에서 시작한다. 여러 턴 시나리오는 같은 시나리오의 턴 순서를 각각 재현한다. 한 방식의 답변/선택 상태를 다른 방식에 전달하지 않는다.
- 도구 선택 차이는 end-to-end 결과에 포함한다. 검색기 자체 비교는 같은 검색 query·as_of로 별도 실행해 검색 효과와 Agent 효과를 분리한다.
- 실행 순서를 교차/섞고 실패·timeout을 제외하지 않는다. 반복 횟수/seed/워밍업은 시작 전 정해 기록한다. 단일 표본의 p95를 전체 서비스 수치처럼 말하지 않는다.

APP-04는 MOD-01.CreateConversation의 신뢰된 server_options 또는 평가 앱의 조립 설정으로 raw/wiki_assisted를 선택한다. 공개 모듈 포트이며 직원 HTTP에 strategy 입력을 추가하지 않는다. 같은 actor fixture를 가진 별도 대화를 만들고 같은 질문/턴을 실행한다.

## 150문항 구성과 분리

한 문항의 primary category는 하나로 하고 다중 태그를 허용한다. dev50은 설정/프롬프트 개선, holdout100은 최종 비교에 사용한다. 문항 생성/검수는 PDF를 받은 뒤 수행한다.

| 유형 | 전체 | dev | holdout |
|---|---:|---:|---:|
| 단일 문서 | 30 | 10 | 20 |
| 복수 문서 종합 | 40 | 13 | 27 |
| 예외·조건 | 25 | 8 | 17 |
| 과거·현행 비교 | 20 | 7 | 13 |
| 근거 없는 질문 | 15 | 5 | 10 |
| 접근 권한 | 20 | 7 | 13 |
| 합계 | 150 | 50 | 100 |

Gold에는 case_id·질문/턴·고정 날짜·actor profile·기준일·기대 결과 유형·필수 사실/예외·허용/금지 주장·근거 PDF SHA-256/source_file/edition/물리 page/정확 인용문/발생 순번·선택 bbox·검수자를 기록한다. 정답 근거를 Wiki나 현재 chunk ID로 정하지 않는다. 복수의 정답 근거 집합이 가능하면 대체 집합을 명시한다. FAQ 한 개에 종합 정답이 있으면 faq_sufficient 태그로 실제 다문서 회수 문항과 구분한다. 그럴듯하지만 이 문항에는 틀린 근거(종전 문서 표의 현행 열, 다른 금액을 말하는 현행 FAQ, 개정 쌍의 다른 판본 가이드 등)는 `hard_negative_anchors`로 정본과 같은 형식으로 기록한다. 교육/출장 사건별 날짜와 페이지 경계 예외는 [수령 보정](corpus/03-received-pdf-adjustments.md)을 따른다. 질문/정답을 Wiki 빌드 입력에 넣지 않는다. holdout을 본 뒤 수정하면 새 평가 버전임을 명시한다.

## 측정

| 구분 | 지표·해석 |
|---|---|
| 후보 회수 | Recall@pool=패킹 전 검색 후보(A 원문 후보, B 확장 원문 후보) 안의 필수 원문 근거 단위 비율. 고정 깊이 Recall@k는 검색기 진단값으로만 쓴다 |
| 문맥 회수 | Recall@budget=token 예산으로 실제 패킹해 답변 모델에 넣은 문맥 안의 필수 원문 근거 단위 비율, Hit@budget=하나 이상 포함. 정본 quote anchor를 해당 parser revision에 정렬한 span과 겹치는 passage로 판정 |
| 문맥 완결성 | 필요한 support_group이 패킹 후 완결된 형태로 남았는지(evidence-in-context), 예산 때문에 빠진 그룹 수, hard_negative anchor가 문맥에 들어간 비율과 그 근거로 틀린 주장을 한 비율. hard negative는 정답과 같은 support_group 안(예: 같은 표의 다른 판본 행)과 별도 그룹을 나눠 집계한다. 같은 그룹 안의 것은 정답 회수 때마다 들어오므로 "들어간 비율"이 아니라 "그것을 인용해 틀린 비율"로만 판단한다 |
| 종합 | 필요한 문서/사실의 충족률, 모든 필수 근거를 모았는지, 예외·조건 누락률 |
| 답변 | 사실 정확성·출처 충실성·지원되지 않은 주장 비율·인용 위치 일치 |
| 거절/부족 | 근거 부족을 올바르게 알렸는지, 답할 수 있는 질문에서 과도한 기권 |
| 시점/권한 | 유효 판본 정답률, 개정 양쪽 구분, 제한 문서/제목/내용 유출 건수 |
| 요청 비용 | 전체 모델/임베딩 시도·입출력 토큰·답변 1건당 문맥 원문 token·usage 미확인 비율·지연·오류 |
| 오프라인 비용 | 파싱/색인/Wiki 빌드·재빌드 시간·토큰·저장량, 변경 영향 범위 |

접근권한/근거 없음처럼 gold가 빈 항목에 Recall을 억지로0이나1로 넣지 않는다. 해당 지표는 N/A와 표본 수를 보고하고 안전/기권 지표로 평가한다. LLM judge는 보조 수단이며 사람의 정답/표본 검수와 불일치를 확인한다. 작은 표본에서 유의미한 우위를 자동 선언하지 않는다.

권한20문항은 문서 수가 아니라 actor×직접 조회/검색/Wiki/이력/확인 경로의 사례다. 제한 문서 수와 같은 문서를 공유하는 사례의 의존성을 별도 보고한다. 개정 경계가9쌍 모두 같은 날짜라는 한계도 보고한다. holdout의 유형별10~27개 결과는 탐색적 분석이며 작은 차이를 일반적 우위로 선언하지 않는다. 개별 paired 결과·표본 수·불확실성을 함께 제시한다.

## 결과 산출물

설정 manifest, 문항별 요청/실제 mode·snapshot·원문 순위·답변·판정·시간/비용, 유형별 집계, 실패 사례, 개선 전후 비교를 저장한다. 제한 원문·개인정보가 있는 로그는 공개 보고서에서 제거한다. 최종 보고서는 strict A/B와 운영 fallback 결과를 구분한다. 티켓 변경은 별도 폐기 가능한 DB의 기능 테스트로 검증하고 RAG 품질 점수에 섞지 않는다.

## 평가 정본·후보 상한·권한 층화

Gold 정본은 불변 PDF hash/물리 페이지/정확 인용문/동일 문구 발생 순번(필요하면 bbox)이다. parser block ID/offset은 별도 alignment artifact에 parser revision과 함께 기록한다. 파서를 바꾸면 정본 gold를 바꾸지 않고 다시 정렬·검증한다. 미일치/중복 모호성은 검수 전 평가 불가로 보고하며 정답을 자동 소실시키지 않는다.

기존 top5 최종 선택에서는20 후보가 같은 거리 정렬에 중복될 수 있었다. 현재는 최종 개수 고정 상한을 폐지했으므로 후보20도 token 예산·그룹 보존과 함께 회수 범위에 영향을 줄 수 있다. 성능과 Recall@pool/Recall@budget으로 검증하고 품질 개선을 사전 단정하지 않는다. B Wiki 후보5는 연결 가능한 원문 집합을 바꾸므로 별도 변수다. reranker·다양성 선택은 아래 절의 별도 비교 ID로만 추가한다.

Wiki 권한 교집합은 정보 노출을 막는 구조적 비용이며 완화하지 않는다. actor별 허용 원문 수·접근 가능한 Wiki page/원문 coverage·ACL 혼합 여부를 기록하고 공통 가용 집합과 전체 서비스 결과를 나눠 보고한다. strict B 실패는 제외하지 않고 fallback 결과와 구분한다. 권한 층화 없이 Wiki 품질만의 효과라고 해석하지 않는다. 두 지식 시점/사건 날짜·document_role 필터도 양쪽 동일하게 고정한다.

## K9 보정: gold 전체·holdout 동결·judge 블라인딩

필수 근거가5개를 넘는다는 이유로 gold를 줄이거나 문항을 제외하지 않는다. 문항별 대체 가능한 최소 충분 근거 집합과 조건/예외를 검수한다. 고정 깊이 Recall@k는 검색 진단값일 뿐 최종 답변 문맥의 크기 제한이 아니다. 최종 예산에서 실제 모은/사용한 전체 근거의 Recall@budget·support_group 완결성·budget_exceeding 표본 수·기권을 별도로 보고한다. 필요한 근거를 못 찾은 경우와 찾았지만 token 예산에 못 넣은 경우를 구분한다.

holdout 열람 전에 Wiki 주제 정의/분할, 빌드 프롬프트, 답변 프롬프트, 검색/링크 확장/경과조항/병합 설정, 모델/임베딩, 최종 token 예산과 judge rubric/model/prompt를 hash로 동결한다. 변경하면 새 평가 버전이며 같은 holdout을 보며 주제를 조정한 결과는 새 독립 평가라고 주장하지 않는다.

judge 입력은 익명 answer ID·질문·답변·원문 인용/필요 근거만 제공하고 A/B 라벨·검색 경로·Wiki 흔적·모델 이름·시간/비용을 숨긴다. 쌍의 순서를 무작위화하며 매핑/seed는 APP-04의 별도 기록에만 둔다. 동일 rubric·judge 설정을 적용하고 블라인딩 가능 여부와 사람 표본 검수 결과를 보고한다. 검색 경로는 품질 판정 뒤 비용 분석에서 합친다.

## 근거 예산·재정렬·전체 문맥 기준선

공개 연구·실무 사례에서 넣는 근거를 늘리면 답변 품질이 처음엔 오르다 떨어지고, 그럴듯한 오답 근거(hard negative)와 긴 문맥 중간 배치가 원인으로 보고됐다([참고 자료](11-references-and-portfolio.md)). 고정 개수 대신 token 예산을 쓰되 그 값은 이 코퍼스에서 측정해 정한다. 다른 corpus의 수치를 이 프로젝트의 적정값으로 옮기지 않는다.

**예산 스윕.** dev50에서 공통 예산 후보 여러 개로 A/B를 같은 조건에서 실행한다. 후보 값은 O-07에서 정하며 초기4000에 더 큰 값 2개 이상을 포함한다. 예산마다 Recall@pool·Recall@budget·evidence-in-context·답변 정확도·과도한 기권·hard negative 오답·지연·비용을 곡선으로 보고한다. 답변 정확도가 더 오르지 않거나 hard negative 오답이 늘기 시작하는 지점을 근거로 holdout 전 단일 예산을 동결하고 선택 근거를 기록한다. holdout은 동결한 예산으로만 주 결과를 낸다. 한 예산에서의 A/B 차이를 모든 예산의 우위로 일반화하지 않는다.

**패킹 순서.** 긴 문맥에서 중간에 놓인 근거를 덜 쓰는 현상이 보고됐으므로 packing_order를 설정 ID로 고정하고 A/B에 같은 규칙을 적용한다. 순서 효과는 dev에서 진단만 하며 holdout을 보고 순서를 바꾸지 않는다.

**재정렬(후속 공통 실험).** 주 실험(wiki-contribution-vector-v1)에는 reranker가 없다. 추가할 때는 별도 비교 ID로 넓은 후보 집합→같은 reranker 재정렬→같은 token 예산을 A의 원문 후보와 B의 확장 원문 후보에 똑같이 적용한다. 결과는 {A, B}×{재정렬 없음, 있음}으로 나눠 Wiki 효과와 재정렬 효과를 섞지 않는다. D-22에 따라 지금은 실행하지 않고, dev 예산 스윕에서 hard_negative anchor 인용 오답이 확인되면 사용자 확인 뒤 추가한다. holdout을 본 뒤 추가하지 않는다. 판단 기준·후보 수·reranker 모델·한국어 지원·지연은 O-12에서 정한다.

**전체 문맥 기준선(대조군, D-22로 계획).** 비교 ID는 full-context-reference-v1이다. 운영 전략이 아니라 "검색을 더 잘해도 넘기 어려운 수준"과 비용을 보는 대조군이다.

- 실행 경로: APP-04만 MOD-01.CreateConversation의 신뢰된 server_options로 `requested_strategy=full_context_reference`를 지정한다. 직원 HTTP·모델은 지정할 수 없고 운영 설정에서는 비활성이다.
- 날짜 해석: A/B와 같은 MOD-11 흐름(LookupApplicableBasis→resolved/needs_clarification/unsupported)을 그대로 거친다. 날짜가 미확정이면 기준선도 되묻는다.
- 원문 선택: 검색 대신 MOD-05.ReadAllowedCorpus가 사건(evidence_group)마다 현재 actor의 ACL·게시·knowledge_as_of를 통과하고, normative는 그 사건의 적용 판본, guidance는 [검색 조립 계약](contracts/05-retrieval-assembly.md)의 안내 판본 규칙을 만족하는 passage 전체를 반환한다. 검수된 transition_relations의 경과조항도 같은 규칙으로 포함한다. 사건이 둘 이상이면 사건별 집합을 각각의 evidence_group으로 넣는다.
- 인용: 문서를 통째로 넣지 않고 CT-08 passage 단위로 넣으며 MOD-03 규칙대로 citation ID를 붙인다. 그래서 인용 정확성과 hard_negative 인용 오답을 A/B와 같은 방식으로 잰다. 모든 허용 passage를 넣으므로 Recall@pool·Recall@budget은 쓰지 않는다.
- 상한과 순서: final_context_token_limit 대신 모델 입력 한도에서 시스템·도구·답변 예약분을 뺀 값만 상한으로 둔다. packing_order는 A/B와 같다.
- 실행 가능성: 먼저 문항별 actor×사건 조합의 허용 원문 token 수를 같은 tokenizer로 실측한다. 모델 입력 한도, 모델 호출 timeout 20초, run 60초 중 하나라도 넘으면 그 문항은 infeasible로 기록하고 품질 점수와 분리해 분모를 공개한다. 기준선을 위해 실행 상한이나 필터를 바꾸지 않는다.
- 캐시: 제한 원문은 actor 필터 뒤에만 넣는다. prompt cache는 같은 actor·snapshot·필터 조합 안에서만 재사용한다.
- 해석: 실측 결과와 실행 가능 범위는 O-12에 기록하며 A/B 결론을 대신하지 않는다.

**하지 않는 것.** 절대 유사도 임계값으로 근거를 자르지 않는다. 질문마다 근거 수를 자동으로 정하는 adaptive cutoff는 MVP 범위 밖이며 도입하면 별도 비교 ID로 측정한다.
