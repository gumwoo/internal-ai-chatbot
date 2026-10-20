# 판본 후보·경과조항·여러 검색 결과의 조립

## guidance 판본

knowledge_as_of에서 `available_from`을 통과한 안내 중 `guidance_valid_from <= knowledge_as_of < guidance_valid_to`인 안내 판본을 고른다. 이 구간은 **안내 판본 자체의 유효 구간**이며 규범의 사건 적용 effective 구간과 별개다. 같은 안내 개정 계열의 게시 구간은 겹치지 않는다. IT-045/046처럼 대체 관계가 있는 가이드는 현재 조회에서 현행 안내만 기본 후보가 된다. 종료/대체 관계가 불명확하면 검수 전 게시하지 않고 임의 최신 파일명 선택도 하지 않는다.

과거 가이드 자체의 조회("그때 안내", "당시 알 수 있었던 기준"처럼 사용자가 과거 지식 시점을 명시한 경우)는 [사건 날짜 계약](02-business-dates.md)의 knowledge_date 경로로만 knowledge_as_of를 줄여 종전 가이드를 찾는다. 모델이 edition ID나 knowledge_as_of를 직접 지정하지 않는다. 현재 안내가 과거 사건을 설명하는 경우에는 현재 안내 판본 안의 해당 조건과 당시 원규정을 연결한다. 과거 사건이라고 안내의 발행일을 사건일로 필터링하지 않는다.

적용 원규정 판본에 공백이 있으면 안내 문서는 절차/담당 확인을 보조할 수 있지만 금액·권리·의무 결론을 대신 확정하지 않는다. CT-10 insufficient_evidence와 규범 공백 원인을 기록한다. FAQ를 근거로 빈 규정 기간을 자동 메우지 않는다. 구현(2026-10-18, T-17): MOD-11이 LookupApplicableBasis 후보 전체에서 이 날짜 기준에 대응하는 가장 가까운 규범(per_claim 제외, 안내가 더 가까워도)을 골라 MOD-05 NormativeCovers로 그 날짜를 포함하는 공개 판본이 있는지 보고, 없으면 CT-14 `normative_gap`을 표시한다. 사건 기준 질문인데 그 기준의 규범은 없고 다른 사건 기준의 규범만 있으면 basis_mismatch로 되묻는다(안내로 답하지 않음). 결론 보류는 MOD-02가 사건 문맥(event_key·date_basis·as_of_date) 단위로 한다: 공백 사건의 원문을 인용했는데 그날 유효한 규범이 하나도 없거나, 공백 사건 말고는 인용이 없으면 answered·insufficient_evidence 모두 서버 문구로 바꾼다(인용한 안내는 절차 확인용으로 남김).

## 사건 날짜를 모를 때의 판본별 결과(D-67)

사건 날짜를 확인하지 못한 검색은 대상 규범 문서(이 사건 기준의 가장 가까운 규범)의 normative 판본(knowledge_as_of에 공개되고 90일 안에 시행되는 것 중 최근 3개)마다 그 판본 안의 날짜(옛 판본은 effective_to 전날, 현행은 오늘, 장래 판본은 시행일)로 같은 검색을 다시 한다. 오늘을 포함하는 판본이 없으면 판본별로 주지 않는다. 각 판본에서 그 문서의 그룹 2개와 다른 문서 그룹 1개를 남기고(전체 문맥 기준선은 전부), 그룹 순위가 같으면 최근 판본을 앞에 두어 섞는다. 판본 대표일은 경과조항 조건의 사건 날짜로 쓰지 않는다. 그룹은 `as_of_date`로 판본을 구분하며 MOD-02는 (event_key, date_basis, as_of_date)로 인용 문맥을 나눈다. authority_relations는 합치고, normative_gap은 모든 판본에 공백이 있을 때만 둔다.

## 영업일 기한 계산표(D-71)

MOD-02는 모델에 보이는 검색 결과에 `deadline_hints={rules:[{citation_id,version,as_of_date,rule,business_days,direction,computed:[{base_date,base_quote,deadline,deadline_weekday,skipped_holidays}]}],counting,calendar_version,calendar_note}`를 붙일 수 있다. rules는 예산 안에 들어간 원문에서만 찾고(제한·예산 밖 원문은 대상이 아니다), 기준일은 사용자 메시지의 날짜다. 계산표는 근거가 아니라 계산 보조이며 원문 근거 예산에 세지 않는다. 답에 쓴 기한의 근거는 그 rule의 citation_id 원문이다.

## 반대편 판본의 경과조항

MOD-05가 검수한 `transition_relations={from_edition_id,to_edition_id,clause_anchor,application_basis,event_conditions,authority_relation}`를 보존한다(manifest에서는 판본을 source_file_id로 적는다, [메타데이터 계약](../corpus/01-metadata-contract.md)). 구현(2026-10-18, D-40): verified_events는 이번 검색의 사건 날짜와 search_documents의 other_events 중 MOD-02가 사용자 문장으로 확인한 날짜다. 이미 알려진 조건이 어긋나면 확장하지 않고(묻지도 않음), 알려진 조건이 모두 맞는데 남은 사건 날짜가 없으면 그 사건 종류를 되묻는다. 확장 원문은 기본 그룹 뒤에 `source_role=transition`으로 붙는다. 문서 우선관계(authority_relations)는 결과 문서의 관계 중 대상 문서를 지금 볼 수 있는 것만 `{from_title,kind,to_title,quote}`로 결과에 싣는다. MOD-11이 기본 판본을 고른 뒤 MOD-05.ExpandTransitionEvidence로 CM-092 제9조/IT-041 제13조 등의 명시 경과조항을 회수한다. 다른 판본 전체를 재검색해 무관한 금액을 섞지 않는다. 링크 대상도 현재 ACL/게시/knowledge_as_of를 통과해야 한다.

event_conditions는 조건마다 application_basis 닫힌 값의 사건 종류와 비교(이전/이후/구간)를 가진 목록이다. CM-092 제9조처럼 "상신일과 승인일" 두 사건이 필요하면 조건 두 개를 모두 확인한 verified_events가 있어야 확장한다. 원문의 사건 표현(예: 상신)을 어느 닫힌 값으로 볼지는 검수자가 transition_relations에 기록하며(O-02), 닫힌 값으로 표현할 수 없으면 needs_review로 게시하지 않는다. 사건 하나라도 미확인이면 되묻는다.

기본 조항·경과조항·경과조항이 참조한 반대편 판본의 필수 조항을 하나의 support_group으로 묶고 출처 edition과 역할(base/transition/referenced_rule)을 각각 보존한다. 검수된 사건 조건을 확인할 수 없으면 되묻거나 근거 부족이다. 자동 우선순위 추정은 하지 않는다. A/B 모두 동일 확장을 사용하고 Wiki에만 특별 회수 경로를 주지 않는다.

## application_basis의 닫힌 값과 대응

| application_basis | 허용 date_basis | 사건 |
|---|---|---|
| general_reference | current, explicit_date | 사건 없는 기준 조회 |
| training_start | training_start | 교육 시작 |
| trip_start | trip_start | 출장 출발/시작 |
| approval_date | approval_date | 최종 결재 |
| request_date | request_date | 신청 |
| work_date | work_date | 근무 |
| processing_date | processing_date | 처리 |
| per_claim | 해당 claim의 위7개 값에 따른 date_basis | 복합 FAQ/해설; 부모만으로 날짜 확정 금지 |

미확인 값은 published application_basis에 넣지 않고 review_status=needs_review다. 한 조항이 신청일과 처리일을 함께 필요로 하면 claim 조건에 두 evidence를 모두 요구한다. date_basis를 편의상 current로 바꾸지 않는다. 반대로 current 질문에 사건 기준 규범이 걸리면, MOD-02가 사용자 문장에 날짜·과거 단서가 없다고 확인한 경우에만 사건 날짜를 오늘로 보고 그 사건 기준으로 검색한다(D-61, `date_evidence.source=assumed_today`, 결과 `assumed_today=true`). 그 밖에는 사건 날짜를 되묻는다. CT-03은 processing_date 사건과 source refs를 보존한다.

## 여러 검색 결과 병합

책임: 한 search_documents 호출 안의 후보 정렬·evidence_group·support_group 구성은 MOD-11이 한다. 여러 호출에 걸친 최종 선택과 token 예산 조립은 [모듈 지도](../architecture/04-module-map.md)의 "예산·문맥" 소유자인 MOD-02가 답변 모델 호출 직전에 한다. 두 모듈은 아래 같은 규칙을 쓰며, 앞선 tool 결과를 그대로 다시 넣어 예산을 우회하지 않는다.

1. MOD-03이 run/call_ordinal별 citation ID를 발급한다. 서로 다른 사건/기준일의 결과를 별도 evidence_group에 유지한다.
2. MOD-11은 각 SearchRequest의 actor·snapshot/config·knowledge_as_of·event_key·as_of_date·date_basis를 검증한다. 맞지 않는 snapshot/config를 섞지 않는다.
3. 같은 원문 anchor여도 사건/날짜/조건이 다르면 근거 연결을 합쳐 없애지 않는다. 같은 evidence_group 내부에서만 중복 text/span을 제거한다. 표 헤더·예외·경과조항은 support_group 단위로 보존한다.
4. 다른 query의 거리 점수는 확률이나 공통 척도처럼 합산하지 않는다. 선택 단위는 support_group이다. evidence_group 안에서 support_group을 대표 passage(기본 조항)의 거리로 정렬하고, evidence_group 사이에는 처음 등장한 call_ordinal 순으로 결정적 round-robin을 적용하며 passage ID로 tie-break한다. ExpandTransitionEvidence로 붙은 구성원은 자체 거리가 없으므로 기본 조항의 순위를 따른다. 같은 설정을 A/B에 적용한다. D-72: A(raw, 운영 B의 raw fallback 포함)는 한 검색 결과 안에서 거리 순 그룹을 문서마다 앞 4그룹 먼저, 나머지는 뒤로 다시 놓는다(`raw-diverse-cosine-v2`). B 성공 경로는 거리 순 그대로다.
5. 필수 조건을5개 상한 때문에 버리지 않는다. 최종 passage 수 고정 상한은 폐지하고 모델 context에서 예약한 답변·시스템·도구 예산을 제외한 원문 token 예산으로 제한한다. 기존4000 token은 초기 dev 설정이며 최종 값은 [비교 프로토콜](../13-retrieval-comparison.md)의 dev 예산 스윕으로 정해 holdout 전에 양쪽 동일하게 동결한다.
6. support_group 전체가 예산에 들어갈 때만 그 그룹을 답변 근거로 채택한다. 온라인에서 "필수"는 gold가 아니라 구조로 안다. 검색된 기본 조항에 연결된 표 헤더·예외·경과조항(transition_relations)과 사건별 evidence_group의 대표 그룹이다. 이런 필수 그룹을 못 넣으면 evidence_budget_exceeded와 누락 그룹을 내부 trace에 기록하고 해당 결론은 기권/insufficient_evidence다. 불완전한 규정 조건으로 단정하지 않는다. 추가 분할 검색도 기존 전체 실행 예산 안에서만 하며 무제한 실행을 새로 허용하지 않는다.
7. 채택한 근거를 답변 문맥에 넣는 순서는 retriever config의 packing_order로 고정한다. 초기 규칙은 4번의 선택 순서대로 support_group을 앞부터 배치하고, 한 support_group은 끊지 않고 연속 배치하며 그 안에서는 base→transition→referenced_rule→표 헤더/예외 순이다. A/B와 재정렬 유무에 같은 규칙을 적용한다. 예산 밖 후보를 순서 조정으로 다시 넣지 않는다.

온라인은 모든 필수 근거의 발견을 보장하지 않는다. 평가에서 gold 전체와 실제 수집/사용 근거를 대조해 회수 누락과 문맥 예산 부족을 구분한다.
