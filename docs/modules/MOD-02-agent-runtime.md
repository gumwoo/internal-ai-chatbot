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
- 오늘로 가정(D-61, 2026-10-19): date_basis=current 검색이면 이번·이력 본인 메시지에 날짜 표현이 없고 이번 메시지에 과거 단서가 없는지 보고 field_origins `assume_today={allowed, reason}`로 넘긴다(`dates.assume_today_check`). 검색 결과 `assumed_today=true`면 모델은 오늘 기준으로 답했다는 것을 밝힌다.
- 사건 날짜 검증 보강(2026-10-18 독립 검증 두 차례 뒤, TS-26): 숫자 경계 대조, 인용 안 날짜 하나, 역할·시제는 날짜 뒤 그 사건의 동사·명사에서(O-13 임시 목록 v4), 연도 표지·범위는 문장 전체에서, 예정은 90일 안. 인용은 모델에 보낸 이력 창 안에서만 찾는다. 같은 support_group이라도 사건 문맥(event_key·date_basis·as_of_date)이 다르면 새 인용 ID를 준다. 대표 그룹이 예산으로 빠진 검색은 그 검색을 인용하지 않으면 다른 인용이 있어도 insufficient_evidence다. 이력의 사용자 메시지도 표시 문자열을 무력화한다(`neutralize`). 프롬프트 `m3-docs-7`(date_quote는 날짜 하나 + 바로 뒤 사건 동사).
- 규범 공백(T-17): 공백은 사건 문맥(event_key·date_basis·as_of_date) 단위로 기억한다(같은 사건의 다른 질의·재사용 citation ID 포함). 공백 사건을 그날 유효한 규범 없이 인용했거나 공백 사건 말고는 인용이 없으면 answered·insufficient_evidence를 서버 문구로 바꾸고 인용은 남긴다. 교육 ID가 있어도 예외가 아니다. needs_clarification 문장은 바꾸지 않는다. 모델에는 passage의 document_type(FAQ·공지·규정)을 보여 주고, 프롬프트 `m3-docs-8`에서 "안내는 규정을 바꾸지 못함, 우선관계 없는 규정·공지 충돌은 양쪽 인용" 규칙을 둔다(서버가 충돌 여부를 판정하지는 않는다).
- D-37: 도구 없는 첫 응답의 빈 answer(되묻기 제외)는 `[서버 안내]` 문구로 한 번만 다시 부르고 usage.empty_answer_retries에 남긴다. 사용자가 쓴 `[서버 안내]`는 무력화한다.
- D-72(2026-10-20): `_search_view` 예산 packing에 검색당 몫 `_SEARCH_BUDGET_SHARE`(0.75)를 더했다. 한 검색은 실행 예산의 0.75까지만 새로 쓰고(첫 그룹은 예외로 전체 예산 안이면 넣음), 몫 때문에 멈춘 것은 evidence_budget_exceeded가 아니다. 전체 예산 초과·대표 그룹 누락 판정은 그대로다.
- D-71(2026-10-20): `_search_view`가 예산 안 passage(`kept_groups`)로 `deadlines.deadline_hints`를 만들어 모델 보기에 `deadline_hints`로 붙인다. 기준일 후보는 `dates.deadline_bases`(이번 메시지 + 이력 창 본인 메시지를 최근 것부터, 최대 4개). 프롬프트 `m7-answer-6`(규칙 21).
- D-75(2026-10-21): 프롬프트 `m7-answer-7`은 answer 형식만 정한다(첫 한두 문장에 결론, 덧붙일 조건·금액·기한·예외·절차가 둘 이상이면 빈 줄 뒤 "- " 항목, 다른 마크다운 금지). 내용·인용·결론 규칙은 m7-answer-6과 같다.
- D-76(2026-10-21): 프롬프트 `m7-answer-8`은 근거 문장 끝에 citation_id 인용 표시(`[c1-2]`, 여러 개면 `[c1-2, c1-3]`)를 달고, 사용자에게 서버·도구·필드 이름 같은 내부 처리 말을 쓰지 않게 한다. `_finish`는 표시 중 원장에 있는 ID를 citation_ids에 더하고(목록에서 빠졌어도 인용으로 인정), 결론 매핑 뒤 최종 인용 목록에 없는 표시는 지운다(원장 밖 표시는 실행 실패가 아니라 삭제, 되묻기·0건 답은 표시가 모두 빠진다). 모델에 보내는 이력의 지난 답에서는 표시를 지운다(`shared/citation_markers.py`). 평가 채점(eval_score)과 judge 입력도 표시를 지우고 본다(표시 없는 옛 결과에는 영향 없음, scoring rule-v2·judge-v1 그대로).
- D-80(2026-10-21): 도구 없는 첫 응답이 action_pending인데 action_id가 없고 prepare_it_ticket이 허용되면 `TICKET_PROMISE_RETRY`(프롬프트 `m7-answer-9`)를 붙여 tool_choice=any로 한 번 다시 부른다(`_ticket_promise` → `_retry_promise`, D-68과 같은 fallback·시간 여유 규칙). 재호출도 도구 없이 끝나면 첫 응답으로 `_finish`해 MODEL_OUTPUT_INVALID. usage.ticket_promise_retries.
- D-82(2026-10-21): `_neutralized`가 모델에 보낼 도구 결과(검색 원문·교육·티켓 문자열)의 지시문 문장을 가림 문구로 바꾸고 가린 문장을 run에 모은다(원장·기록은 원문 그대로). `_finish`는 인용 표시 정리 뒤 `injection.leak_reason`(운영 표식·지침 40자 구간·가린 지시문 14자 구간·미끼 값)이 걸리면 답을 `injection.WITHHOLD`로 바꾸고 인용·교육 참조를 비운다. 프롬프트 `m7-answer-11`(운영 표식 `injection.CANARY`, 지시 무력화 요청 거절).
- D-83(2026-10-21): `deadlines.rule_event`가 기한 숫자 바로 앞 12자에서 기준 사건(끝나는 날·시작·요청·통지·사용)을 읽고, `base_events`가 사용자 날짜 문구 뒤의 사건 말("…일부터"는 시작)을 읽어 맞는 기준일에 `matches_rule`을 붙이고 앞에 둔다. "부터 사흘 동안"이면 끝나는 날을 후보로 더한다(`_expand_bases`, 규칙이 있을 때만). 프롬프트 `m7-answer-12`: 규칙 21(matches_rule: true인 deadline을 쓴다), edition_split이 있으면 첫 문장부터 두 갈래 결론(규칙 20·답 형식), 한 질문의 다른 기한은 일마다 따로 검색(규칙 11).
- D-85(2026-10-21): 지시문 판정을 넓혔다. 부르는 말 뒤 "시스템·도구·모델"("AI 시스템은"), 영어로 부르는 말("Note to AI assistants", 줄 앞 "assistant:"), "state that", 부르는 말 없이 요약하는 쪽에 시키는 문장("이 규정을 요약하는 경우 … 적는다"), 도구 결과 속 서버 표시 문자열("[서버 안내]" 등)로 시작하는 문장. 표 행은 셀마다 판정해 지시문 셀만 가리고, 문장 가운데 남은 서버 표시 문자열은 괄호를 바꿔 무력화한다. 원문 248쪽 오탐 0.
- D-86(2026-10-21): (1) 판본별 원문(edition_split, 날짜로 해결된 같은 사건 없음)을 받고 원문을 하나도 인용하지 않은 채 needs_clarification·answered로 끝난 응답은 `EDITION_SPLIT_RETRY`(프롬프트 `m7-answer-13`)를 붙여 한 번만 다시 부른다(`_edition_split_ask` → `_retry_edition_split`, 도구는 강제하지 않음, 실패·시간 초과면 첫 응답으로 `_finish`). 계산표 마감일을 쓴 answered는 (2)로 인용이 붙으므로 다시 부르지 않는다. usage.edition_split_retries. (2) `_search_view`가 계산표 rule의 (citation_id, 계산한 마감일)을 run에 모으고, `_finish`는 answered 답에 그 마감일(2027-01-06·2027년 1월 6일·1월 6일, 앞이 숫자인 "11월 6일"은 제외)이 나오면 그 rule의 citation_id(원장에 있는 것만)를 인용에 더한다. usage.deadline_citations_added. (3) `_field_origins`의 오늘 가정 판정이 past_cue면 MOD-03이 `SearchRequest.past_event`로 넘긴다.
- D-88(2026-10-21, P-30 C): 이어지는 턴(모델에 보내는 이력 창에 지난 답이 있음)에서 이번 메시지가 질문이고(`promises.rule_question`, 요약·인사·감사 제외), 도구를 부르지 않은 첫 응답이 answered·insufficient_evidence이며 교육·티켓·초안 참조가 없고 답이 규정 내용을 말하면(`promises.discusses_rules`) `FOLLOWUP_SEARCH_RETRY`(프롬프트 `m7-answer-14`)를 붙여 검색을 강제해 한 번 다시 부른다(`_followup_unsearched` → `_retry_promise`, D-68 경로·여유 시간, 실패하거나 또 도구 없이 끝나면 첫 응답). 되묻기는 잡지 않는다. D-68 약속 문형에 "검색이 필요합니다"·"찾아본 뒤 답드리겠습니다"·"원문을 검색해 … 안내드리겠습니다"를 더했다. usage.followup_search_retries.
- D-93(2026-10-24): `_edition_split_notes`는 일부 판본만 인용한 답이라도 사용자 날짜(`_deadline_bases`의 이번·이력 본인 메시지 날짜)가 인용 판본 구간 안이고 빠진 판본 구간에는 없거나, 답에 판본 경계 날짜(빠진 판본의 시행일·종료일, 가장 오래된 판본 시작일 제외)가 나오면 다른 판본 안내를 붙이지 않는다(`_edition_already_settled`). 대화 모델 출력 상한은 앱 조립의 `CHAT_MAX_OUTPUT_TOKENS`(2048)다.
- D-91(2026-10-23, P-31 D): 응답 뒤 서버 재호출은 `_reprompt_plan`(판정)과 `_reprompt`(실행) 하나로 처리한다. 사유(`Reprompt`)와 실행 방식(`_RepromptRule`: 서버 안내, tool_choice, 재호출 경로 실패 때 첫 응답 유지 여부, 다시 받은 응답이 도구 없이 끝날 때 첫 응답으로 끝낼지)은 `_REPROMPT_RULES`에 판정 순서대로 있다. 사유별 발동 조건은 D-37·D-68·D-80·D-86·D-88 판정 함수 그대로이고, 시도·시간 여유 검사는 `_can_reprompt` 하나다(빈 첫 답은 검사하지 않음). 재호출 횟수는 `_Run.reprompts`에 사유별로 세어 usage의 기존 6필드로 낸다. `AgentRuntime(first_response_sink=…)`(평가 실행기만 넘김, `create_app`도 같은 인자)은 run의 첫 응답이 도구 없이 끝났을 때 (run_id, {outcome, answer, reprompt})를 받는다. 기록 실패는 경고 로그만 남긴다.
- D-69(2026-10-20): calculate_business_deadline의 field_origins `base_date={verified, source}`를 계산한다(이번 실행 도구 결과의 ISO 날짜 `tool_dates`, 본인 메시지의 월·일 표현, 오늘+"오늘"). 계산 호출은 `deadline_calls`로 따로 세고 상한 `_MAX_DEADLINE_CALLS`=4, 나머지 도구는 기존 max_tool_proposals. 프롬프트 `m7-answer-5`(규칙 21, 규칙 10의 계산 날짜 예외).
- D-68(2026-10-20): 도구 없는 유효한 첫 응답에 검색·확인 약속(`promises.promises_lookup`)이 있고 search_documents가 허용되면 `SEARCH_PROMISE_RETRY`(프롬프트 `m7-answer-4`)를 붙여 tool_choice=any로 한 번 다시 부른다(`_retry_search_promise`). 재호출 경로는 `_drive(fallback=첫 응답)`로 이어 가고 실행 기한보다 `_PROMISE_RESERVE_S`(2초) 먼저 끊는다. 그 안의 AppError·시간 초과, 다시 도구 없이 끝난 응답은 첫 응답으로 `_finish`한다. usage.search_promise_retries.
- D-39: 확인된 사건의 인용(또는 교육)이 있는 answered에 날짜를 확인하지 못한 사건(같은 event_key가 끝내 resolved되지 않은 되묻기)이 있으면, 그 서버 되묻기 문구를 답 끝에 붙인다(모델 답에 이미 있으면 붙이지 않음).
- D-67(2026-10-19): edition_split 결과는 모델에 clarification 없이 판본별 그룹(`as_of_date`)과 `edition_split`로 보인다(프롬프트 `m7-answer-3` 규칙 20: 시행일 경계로 나눠 답함). 인용 문맥은 그룹의 as_of_date로 나눈다. 판본별 결과의 첫 그룹이 예산 밖이어도 필수 근거 누락으로 보지 않는다. 결론: 판본별 결과만 있고 인용·교육이 없으면 needs_clarification(서버 문구), 그 사건의 대상 문서 규범 인용이 없으면 D-39 되묻기 문구, 일부 판본만 인용했으면 인용하지 않은 판본마다 "사건이 …부터 … 전까지이면 … 판본이 적용됩니다" 안내를 답 끝에 붙인다(중복 없이). 모델 보기의 edition_split에서는 document_key를 뺀다. 같은 support_group을 다른 사건 문맥으로 다시 받으면 새 인용 ID를 주되 예산은 한 번만 센다(`charged_groups`). 인용 DTO `edition_split`이 참이면 as_of_date는 판본 기준일이다. 같은 사건이 같은 실행에서 날짜로 확인됐으면(판본별이 아닌 resolved) 붙이지 않는다. 서버 문구로 답을 바꿀 때도 판본별 사건의 되묻기를 함께 붙인다.
- D-40: search_documents의 other_events를 사건마다 date_quote로 검증해 field_origins `other_events[i]`로 넘긴다(상신은 request_date 역할). 프롬프트 `m3-docs-9`.
- M5: prepare_it_ticket의 origin_candidates로 field_origins를 계산한다(04-field-origins 구현 메모). 최종 출력에 ticket_ids·action_id를 받고 action_pending을 연다(D-42). 빈 첫 답 재호출은 tool_choice=any로 도구 호출을 강제한다(D-41). 프롬프트 `m5-tickets-1`.
