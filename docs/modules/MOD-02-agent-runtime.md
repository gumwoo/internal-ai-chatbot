# MOD-02 Agent 실행


## 책임과 소유권

실행 중 모델/도구 반복·예산·업무 문맥·근거 원장·결과 후보를 소유한다. 영속 DB를 소유하지 않는다. 입력은 CT-02 ExecutionContext와 가시성 검사를 통과한 CT-03 Snapshot, 출력은 CT-10이다.

## 공개 작업

Execute(context,snapshot,message,observer) → ExecutionResult. 도구 선택→인자 검증→결과 확인→다음 행동/되묻기/완료를 제어한다. 조회가 불필요하면 검증된 같은 대화의 교육 사본으로 답할 수 있다. 자료가 없는 규정 사실은 추정하지 않는다.

M1에서 교육 도구 반복·호출 상한과 메모리 observer를 먼저 구현하고, M2에서 MOD-01의 영속 observer/상태를 연결한다. 모듈 전체가 M2까지 존재하지 않는다는 뜻이 아니다. 사건 날짜는 [확인된 근원](../contracts/02-business-dates.md)과 함께 SearchRequest에 전달한다. CT-14 needs_clarification은 검색0건이 아닌 후속 질문으로 변환한다. 티켓 자유문장 제안은 본인 사용자 입력의 field_origins를 포함하며 검색 본문을 접수 내용으로 합성하지 않는다.

## 협력

MOD-07로 한 번의 모델 호출, MOD-03으로 한 번의 도구 시도를 요청한다. 논리 호출의 제한된 재시도는 여기서 조정한다. CT-11 추상 observer로 필수 도구 기록을 요청한다. MOD-01 구현·DB·티켓 확인 API를 직접 호출하지 않는다.

## 불변식

- 서버 actor·시각·전략·도구 목록·상한을 모델 출력으로 변경하지 않는다.
- 도구 결과/허용 사본만 근거 원장에 등록한다. 최종 citation·교육·티켓·action ID는 원장에 있어야 한다.
- 문서 검색은 MOD-11이 원문 passage로 반환한다. Wiki의 문장을 규정 근거로 추가하지 않는다.
- 승인 여부는 결정하지 않는다. prepare_it_ticket 성공은 action_pending이며 확인 완료를 말하지 않는다.
- 조회 0건, 근거 부족, 추가 질문은 정상 결과다. 도구 장애를 0건으로 포장하지 않는다.
- 모델이 제안한 외부 지시나 PDF 내부 프롬프트를 실행 정책으로 사용하지 않는다.
- 상태 후보는 schema_version=2 계약으로 검증한다. 존재하지 않는 대상 ID를 선택 상태로 저장하지 않는다.

## 실패·관측

시간/호출 상한, 무효 최종 출력, 필수 관측 저장 실패에서 종료한다. usage 미확인은 null과 incomplete를 유지한다. 적용 여부는 MOD-01이 최종 결정한다. [실행 정책](../05-agent-execution.md)에 고정된 상한을 따른다.

## 검토·테스트

T-05 도구 선택/후속/모호성, T-06 상한·재시도, T-07 결과 원장·무효 출력, T-08 도구 장애. FR-03/04/06 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

앱이 주입한 CP-07로 날짜 evidence를 대조한다. SearchRequest는 knowledge_as_of와 사건 as_of_date를 구분한다. 날짜 미확정/unsupported는 CT-14 계약대로 추가 질문/근거 부족이다. Agent prepare 결과는 draft이며 pending 승인/생성을 실행하지 않는다.

origin_candidates의 quote/message ID를 CP-07 user 원문과 대조해 code point 구간을 계산한다. 다중 검색의 support_group은 token 예산 내 완결된 형태로만 답변에 사용한다. 필요한 그룹이 넘치면 해당 결론을 기권하며 근거를5개로 잘라 조건을 잃지 않는다.

## 2026-10-17 M3 구현 메모

- 근거 원장: search_documents 결과 중 모델 문맥에 실제로 넣은 passage만 원장에 올린다. 최종 citation_ids가 원장 밖이면 MODEL_OUTPUT_INVALID다. 되묻기·0건에서는 인용을 저장하지 않는다.
- 예산 해석(2026-10-18): 그룹은 MOD-11 순서대로 넣다가 처음으로 들어가지 않는 그룹에서 멈춘다(예산 밖 후보를 순서를 바꿔 넣지 않음, 05-retrieval-assembly 7항). 대표 그룹(첫 그룹)이 빠지면 필수 근거 누락으로 표시하고, 근거 없이 answered로 끝내면 서버가 insufficient_evidence로 바꾼다. 같은 실행에서 이미 넣은 그룹은 비용을 다시 세지 않고 처음 citation_id를 재사용한다.
- 결론 매핑: 이번 실행의 검색이 모두 needs_clarification/unsupported인데 근거 없이 answered로 끝내면 서버가 되묻기(서버 문구) 또는 insufficient_evidence(미지원 안내)로 바꾼다(answer_source=server_mapping).
- 예산: 실행 전체에서 원문 합계 `final_context_token_limit`(초기 4000, token은 `utf8-bytes-div3-v1` 추정값)을 넘기지 않는다. support_group 단위로 MOD-11 순서대로 통째로만 넣고, 못 넣은 그룹은 `evidence_budget_exceeded`로 도구 결과와 내부 로그에 남긴다.
- P-12 B: 실행 시작 때 CP-07(ConversationEvidenceReader)로 대화 사본을 실제 receipt와 다시 대조한다. 대조 실패는 필수 기록 실패와 같게 실행 실패다.
- P-13 B: system에는 규칙만 둔다. 검증된 대화 자료는 현재 사용자 턴 앞의 `[대화 자료]` 블록으로, 문서 passage는 tool_result로만 넣는다(프롬프트 `m3-docs-1`, 이후 실제 모델 smoke에 따라 `m3-docs-4`까지 조정, TS-24).
- 사건 날짜(2026-10-18): search_documents의 date_quote를 현재 질문·이력의 사용자 메시지와 대조하고(정확히 한 번, code point 구간), 인용 안의 날짜를 정규화해 field_origins로 MOD-03에 넘긴다. 연도 생략은 D-24 시제 규칙(완료 → 지난 날, 예정 → 다가올 날, 모호 → ambiguous_date). 없는 달력 날짜는 보정하지 않는다. 모델 as_of_date는 쓰지 않고 다르면 date_evidence에 남긴다. 인용에는 year_inferred를 둔다.
