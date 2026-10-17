# 사건 날짜·지식 시점 계약

## 서로 다른 두 날짜

`knowledge_as_of`는 어떤 시점까지 공개된 정보를 읽는가이고, `as_of_date`는 규칙을 적용할 **사건 날짜**다. 기존 as_of_date 필드는 사건 날짜라는 의미로 유지한다. 전자는 기본 run 수락 시각이며 명시적인 과거 지식 조회만 더 과거로 줄인다. 미래 지식 조회는 미지원이다. 사건 날짜를 지식 시점으로 대신하지 않는다.

MOD-02가 후보를 만들고 MOD-11이 검수된 application_basis와 일치하는지 판정한다. 교육·출장·결재·신청·근무·처리 사건을 구분한다.

## BusinessDateEvidence와 검증 경로

CT-03 business_dates 항목은 `event_key,event_type,date,source_kind,source_message_id,source_span,resource_ref`다. event_type/date_basis는 training_start/trip_start/approval_date/request_date/work_date/**processing_date**/explicit_date이며 사건 없는 일반 조회만 current를 허용한다.

source_kind=user_message는 MOD-01이 본인 user 메시지 구간과 run 고정 시각의 상대 날짜 정규화를 검증한다. verified_training은 MOD-03이 MOD-04의 실제 CT-05 결과를 받아 CT-11로 기록한 **training result receipt**(run/ordinal/training ID/starts_at/결과 hash)를 참조한다. 어느 회차를 선택했는지도 사용자 메시지로 남긴다. CP-07 어댑터(MOD-01)가 receipt와 날짜를 대조한다. 모델/assistant 문장만으로 확정하지 않는다. MOD-02는 검증된 evidence만 상태 후보에 넣고 MOD-01이 최종 저장한다.

## SearchRequest와 날짜 미확정의 첫 단계

모델 입력은 `query,top_k,as_of_date?,date_quote?,date_basis,event_key?,knowledge_date?`다. date_quote는 사건 날짜를 말한 사용자 문장 부분 그대로이며 출처 후보(user_quote)다. MOD-02가 본인 사용자 메시지(현재 질문, 그다음 이력)에 정확히 한 번 있는지 확인해 code point 구간을 계산하고, 인용 안의 날짜를 run 고정 시각으로 정규화한다(연도 생략은 아래 시제 규칙). 정규화한 값만 쓰고 모델의 as_of_date는 쓰지 않는다. 인용이 없거나 확인되지 않으면 날짜 미확정(missing_date), 시제로 연도를 정할 수 없으면 ambiguous_date로 되묻는다. 서버가 `knowledge_as_of,business_dates,question_context,execution_context`를 추가한다. actor/snapshot/business_dates/knowledge_as_of는 모델 인자가 아니다.

명시적인 과거 지식 조회는 knowledge_date 경로로만 한다. 모델은 사용자가 "그때 안내", "당시 알 수 있었던 기준"처럼 과거 지식 시점을 직접 말한 경우에만 knowledge_date와 해당 user_quote origin 후보를 제안한다. MOD-02가 CP-07로 그 구간을 검증하면 서버가 knowledge_as_of를 그 날짜의 KST 다음날00시(종료 제외)로 줄인다. 검증되지 않으면 무시하고 수락 시각을 쓴다. 미래 knowledge_date는 unsupported(future_knowledge)다. 사건 날짜(as_of_date)와 섞지 않는다.

날짜를 모르면 MOD-11→MOD-05 `LookupApplicableBasis`로 현재 ACL·게시·knowledge_as_of에 맞는 **검수 메타데이터만** 조회한다. 사건 날짜 필터는 아직 적용하지 않는다. 반환은 application_basis/required_event_type/원규정 관계이며 답변용 passage가 아니다. 사건 날짜가 필요하면 되묻고 오늘 날짜를 넣어 금액부터 검색하지 않는다. 제한 문서의 이름·존재를 질문에 드러내지 않는다. 복수 사건은 event_key별 별도 검색이다.

## 규정과 안내 자료의 필터

- normative(규정/위임 규범): `available_from <= knowledge_as_of`와 `effective_from <= as_of_date < effective_to`를 모두 만족해야 한다. 종료 null은 열린 구간이다.
- guidance(FAQ/매뉴얼/해설): available_from과 knowledge_as_of에서 유효한 안내 판본·현재 ACL/게시 상태로 후보를 고른다. 안내 자체의 판본 구간과 과거 사건 조건은 별개다. 안내 자료의 발행·시행일이 사건 뒤라는 이유로 제외하지 않는다. 각 문장의 사건 조건과 연결 원규정 판본을 검증한다. FAQ가 규정을 바꾸지는 못한다.
- GA-090(2026.10.06 안내)은 현재 지식으로9/29 출장의 종전 규정을 설명할 때 사용할 수 있다.9/29 당시 알 수 있었던 정보만 묻는다면 available_from으로 제외한다. 금액은 종전 원규정에 연결한다.
- available_from은 검수한 공개 가능 시각이다. 업로드 시각/PDF 개정일에서 임의 추정하지 않는다. 미확인은 needs_review다.

## 미래의 예정 사건

수락일부터90일 이내의 확정된 예정 사건은 허용한다. 현재까지 공개된 규정만 사용하며 이미 공개된 장래 시행 규정도 적용 구간으로 판정한다. `prospective=true`와 “현재 공개된 규정 기준이며 이후 개정 시 달라질 수 있음”을 표시한다. 다음 주 교육 조회→규정 검색을 미래라는 이유로 거절하지 않는다.

## CT-14 결과

| resolution | 필수 결과 |
|---|---|
| resolved | 검증된 두 날짜/date_basis/event_key/date_evidence/prospective, passages; 빈 목록은 검색0건 |
| needs_clarification | passages=[], clarification={reason,required_event_type,event_key,prompt}; 미확정 사건일 null |
| unsupported | passages=[], clarification=null, unsupported={reason,safe_message}; 미확정 날짜 null |

추가 질문 reason=missing_date/conflicting_dates/ambiguous_event/basis_mismatch/ambiguous_date/range_spans_editions. unsupported reason=future_knowledge/event_out_of_horizon/unsupported_event_type. MOD-03은 정상 도구 결과로 전달하고 MOD-02는 unsupported를 outcome=insufficient_evidence로 매핑한다(메시지 성공 HTTP200). 잘못된 달력 날짜는 검증/추가 확인이며 임의 날짜 보정 금지다.

## 월·범위·연도 생략 표현

- 날짜 표현은 KST 구간 [start,end)로 정규화한다. 하루는 그날00시~다음날00시, "2025년 3월"은 2025-03-01~2025-04-01, "9월 30일까지"는 끝이 2026-10-01이고 시작이 열린 구간이다.
- 사건 구간 전체가 normative 한 판본의 effective 구간 안에 있으면 resolved이며 as_of_date는 구간 시작일(열린 시작이면 끝 직전 날짜)로 두고 원래 구간을 date_evidence에 남긴다.
- 구간이 둘 이상의 판본에 걸치면 needs_clarification(range_spans_editions)이다. 단, 그 경계에 검수된 transition_relations가 있고 질문이 경계 전후 처리 자체를 묻는다면 기본 판본+경과조항 support_group으로 resolved한다.
- 연도가 없는 날짜("9월 29일")는 사용자 문장의 시제로 연도를 정한다(D-24, [정책 선택](../15-policy-options.md) P-05 B). 완료 표현("출발한", "다녀온")은 knowledge_as_of 이전의 가장 가까운 날짜, 예정 표현("갈", "시작하는")은 이후90일 이내의 가장 가까운 날짜다. 시제가 불명확하거나 두 해석이 다른 판본으로 이어지면 ambiguous_date로 되묻는다. 추론한 연도는 date_evidence에 `year_inferred=true`로 남기고 답변에 "2026년으로 보고 답합니다"처럼 표시한다.

## 문장 조건과 검증

판본 필터만으로 비교표·종전 과정·연간 누계의 적용을 결정하지 않는다. 제목·표 헤더·조건·주석과 원규정 링크를 함께 보존한다. ED-030 연간 누계는 종전 지급액도 포함하므로 지급 원장이 없으면 잔여 한도를 계산하지 않는다. processing_date는 IT-041·SEC-062 등의 처리일 기준이며 요청일로 바꾸지 않는다. T-15/17/29에 GA-090 과거 사건 해설, 과거 지식 제외, 다음 주 교육,90일 초과, 근원 위조, 조건 보존을 포함한다.

application_basis 열거와 date_basis 대응, 안내 개정 쌍 선택·원규정 공백·다른 판본의 경과조항·다중 검색 병합은 [검색 조립 계약](05-retrieval-assembly.md)을 따른다. 날짜는 문장 첫 위치가 아니라 사건별 역할로 연결하고 작년/명시 연도는 run의 고정 시각과 사용자 구간으로 검증한다. 복귀/정산일을 출장 시작일로 쓰지 않는다.
