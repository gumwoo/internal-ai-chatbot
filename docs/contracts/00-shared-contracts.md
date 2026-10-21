# 모듈 사이 공통 계약

공급자 중립 의미 계약이다. 클래스·ORM 객체를 강제하지 않는다. HTTP는 [API](../04-api-spec.md), 문서 정책은 [메타데이터](../corpus/01-metadata-contract.md)가 기준이다. nullable 값은 미확인을 뜻하며 0이나 허가로 해석하지 않는다.

## CT-01 ActorContext / AccessDecision

MOD-09가 서버 세션에서 만든 `user_id, department_ids, role_ids, capabilities, auth_revision, source`다. source=local_session이면 서버 내부 값 `session_ref`(세션 토큰 hash)를 함께 두어 Authorize가 세션 회수·만료를 다시 확인한다. session_ref는 응답·로그·모델 입력에 넣지 않는다. local_session actor에는 ops.*·eval.* capability를 주지 않는다. 최종 MVP의 source는 local_session, 첫 구간 테스트 대체 객체는 test_stub으로 구분한다. 운영 CLI는 source=operator_cli이며 서버 설정의 전용 운영 계정·허용 capability로만 구성한다. 직원 세션/모델 입력에서 운영자로 승격하지 않는다. test_stub은 서버 시작 설정/테스트 DI로만 선택하고 HTTP의 사용자 헤더/본문으로 바꾸지 않는다. 상세 제한은 [첫 구간](../12-first-milestone-spec.md)이다. 브라우저·모델이 actor를 만들지 않는다. 문서 ACL에 대한 판정은 허용/거부와 정책 revision을 반환한다. 거부 사유에 제한 문서 제목·내용을 넣지 않는다. 판정 시 MOD-09는 현재 세션·역할 revision을 확인하며 요청 시작 때 받은 capability 사본만으로 계속 허용하지 않는다.

APP-04 평가 실행은 source=eval_fixture이며 평가 설정의 고정 actor profile로만 만들고 직원 세션으로 승격하지 않는다. capability는 아래 닫힌 이름만 쓴다. 어느 역할에 어떤 capability를 줄지는 O-01/O-10의 fixture에서 정하며 이 목록이 권한 부여를 뜻하지 않는다. 새 이름은 계약 개정 없이 추가하지 않는다.

| capability | 허용 행위 | 주로 확인하는 모듈 |
|---|---|---|
| training.read | 교육 목록·상세, list/get_training 도구 | MOD-04/03 |
| knowledge.search | search_documents, calculate_business_deadline(D-69), 근거·PDF 조회(문서 ACL은 별도로 판정) | MOD-05/11/03 |
| ticket.read_own | 본인 티켓 목록·상세 | MOD-12 |
| ticket.read_support_scope | support_department_ids에 속한 요청자 티켓 조회 | MOD-12 |
| ticket.read_all | 전사 티켓 조회(별도 명시 부여만) | MOD-12 |
| ticket.prepare | Agent prepare_it_ticket으로 draft 생성 | MOD-03/12 |
| ticket.submit | UI revise·confirm·cancel | MOD-12 |
| ops.corpus_ingest / ops.corpus_publish | PDF 수집 준비 / corpus 게시 | MOD-06/05 |
| ops.wiki_build | Wiki 빌드·검수·게시 | MOD-10 |
| ops.access_admin / ops.membership_admin | 문서 ACL 변경 / 부서·역할 변경 | MOD-05/09 |
| eval.run | APP-04 평가 실행·전략 지정 | MOD-01/11 |

## CT-02 ExecutionContext

MOD-01이 수락 시 `request_id, conversation_id, run_id, actor, current_time, timezone, deadline_at, policy, retrieval_context`를 고정한다. 시각은 KST, 같은 프로세스의 경과는 단조 clock, 재시작 후 회수는 영속 deadline_at을 사용한다. [수락·복구 계약](01-run-lifecycle.md)의 메시지 receipt와 함께 저장한다. retrieval_context는 CT-13이며, 요청 중 활성 snapshot이 바뀌어도 혼합하지 않는다. 권한을 고정해 영구 허용한다는 뜻은 아니다. 최종 반환 직전 현재 권한을 다시 확인한다.

## CT-03 ConversationSnapshot

같은 소유자의 최근 메시지 최대 12개와 검증된 업무 상태를 담는다. schema_version=2. `last_training_ids, selected_training_id, last_date_filter, training_cache`(각 후보/사본 최대20), `selected_ticket_id, pending_action_id, pending_clarification, last_document_query, business_dates`를 선택 필드로 둔다. business_dates는 [사건 날짜 계약](02-business-dates.md)의 event_key/type/date/source_message_id·근원으로 구성한다. 교육·출장·결재·신청·근무·처리 사건을 구분하며 추정 날짜는 확정 저장하지 않는다. 각 참조에는 원본 run·조회 시각·자원 의존성이 있다. 기존 이름 pending_action_id는 채택된 root draft 참조도 보존할 수 있는 표시용 참조이며 승인 자격이 아니다. UI는 GetAction의 상태/계보를 다시 읽고 pending만 확인한다. CP-07은 현재 run의 검증된 snapshot에서 참조된 과거 사용자 메시지/교육 receipt도 소유권·의존성 검사를 거쳐 읽을 수 있다.

MOD-01은 이력을 모델이나 UI에 보내기 전 현재 권한을 재검증한다. 근거가 회수/철회된 assistant 메시지는 전체 본문·인용·제한 참조를 가리고 일반 안내만 반환한다. 저장 원본은 감사 목적 접근과 구분한다. dependency는 최종 인용만이 아니라 모델 문맥에 제공된 모든 원문·참조와 재사용한 assistant 메시지의 dependency 합집합이다. 모델이 인용을 생략해도 접근 검사를 피하지 못한다. 문서 본문 캐시는 새 요청에서 근거로 무조건 재사용하지 않고 검색으로 다시 확인한다. 교육 사본의 기존 필드 재사용은 허용하되 최신 상태 질문은 재조회한다.

## CT-04 TrainingSearchInput

date_preset 또는 custom의 start_date/end_date_exclusive, 선택 query, limit/offset. MOD-04가 서버 clock으로 날짜를 해석한다. KST 시작 포함·종료 제외, 최대90일. today는 오늘00시~내일00시, this_week는 이번 월요일00시~다음 월요일00시, next_week는 다음 월요일00시부터7일, next_30_days는 오늘00시부터30일이다. 현재 시각 이후라는 추가 필터는 없다. 상세 범위는 [첫 구간](../12-first-milestone-spec.md)이다.

## CT-05 TrainingPage / Detail

Summary=`id, code, title, starts_at, ends_at, location, status`. Detail=Summary+description. Page=`items,total,limit,offset,has_more,resolved_range`. 빈 목록은 정상 결과. 장소는 Summary에 있으므로 불필요한 상세 호출을 강제하지 않는다.

## CT-06 ToolCallProposal / ToolResult

제안은 `name, arguments, provider_call_id, origin_candidates?`이고 서버가 run 내 `call_ordinal`을 부여한다. 결과는 `ok,data,error`, 성공에는 error=null, 실패에는 data=null. data는 교육 Page/Detail, CT-14 검색 결과, CT-16 TicketPage/Detail/ActionPreview 중 등록 타입이다. 오류는 CT-12. 인자 검증 실패도 도구 제안 수에 포함한다. MOD-03은 단일 시도이며 온라인 읽기 재시도는 MOD-02가 맡는다.

MOD-02→03의 서버 실행 입력은 `ToolExecutionInput={proposal, call_ordinal, field_origins?, observer}`다. field_origins는 MOD-02가 CP-07로 계산한 정규 값이며 모델 제안에 있던 값을 그대로 쓰지 않는다. observer는 CT-11이다. 모델이 보는 도구 인자 스키마에는 field_origins/observer가 없다.

## CT-07 ModelRequest / Response / EmbeddingBatch

Chat/structured 요청=`purpose,messages,tools,output_contract,timeout,model_config`. 응답=도구 제안 또는 최종 구조화 후보 + 실제 model ID + usage. `purpose`는 agent_answer 또는 wiki_build 등을 명시한다. SDK 메시지/예외는 외부에 노출하지 않는다. 도구와 텍스트가 함께 오면 도구 처리 전에 완료 답변으로 저장하지 않는다.

임베딩은 텍스트 순서와 벡터 순서를 일치시키고 모델·차원·유한 수·0 벡터를 검증한다. usage는 알려진 입력/출력 토큰과 complete 여부를 보존하고 미확인은 null이다. 한 호출은 한 시도다. 재시도 소유자는 온라인 MOD-02, 수집 MOD-06, Wiki 빌드 MOD-10이며 SDK의 숨은 재시도와 중첩하지 않는다. 온라인 검색 임베딩 재시도도 MOD-02의 논리 도구 재시도 안에서만 한다.

## CT-08 EvidencePassage / RegisteredEvidence

MOD-05 원문 passage 필드:

- `passage_id, document_key, edition_id, source_file_id, artifact_revision, corpus_snapshot_id`.
- 제목·업무 영역·문서 종류·판본·시행 구간·정책 우선순위 메타데이터.
- `page_spans`: 실제 PDF 물리 페이지(1부터), block_id, Unicode 시작/끝 offset, 선택 bbox/printed_page_label.
- 원문 text, 관련 절·검색 점수·검색 순위. 숫자 점수는 다른 설정 간 확률처럼 비교하지 않는다.
- 접근/게시 판정에 필요한 revision과 의존 자원 ID. 불허 자원은 결과에 포함하지 않는다.

MOD-03이 실행 내 고유 citation_id를 추가해 RegisteredEvidence로 만든다. call ordinal을 포함해 두 시점 검색의 인용 ID도 충돌하지 않는다. 사용자 제목·인용문·PDF/근거 URL은 서버가 passage로 생성한다. 모델이 임의 제목·페이지·URL을 만들지 않는다. 인용 ID 존재 검증만으로 주장의 참임이 보장되지는 않으며 별도 평가가 필요하다.

## CT-09 PreparedEdition / PreparedCorpus

MOD-06→05. 사용자 manifest, PDF SHA-256, 원본 안전 경로, parser/config revision, 추출/OCR·검수 상태, 페이지별 blocks, chunks의 block 범위, embedding 설정/차원/벡터를 포함한다. 동일 업무 판본의 파서 변경은 artifact_revision 변경이다. PreparedCorpus는 포함 판본 목록과 manifest/config hash를 가진다. 원자적 corpus 게시 전에는 검색에 보이지 않는다. 초안 일부 성공을 전량 성공으로 보고하지 않는다.

## CT-10 ExecutionResult

`status=completed|failed`, 정상 outcome=`answered|needs_clarification|no_results|insufficient_evidence|action_pending`, answer, training_refs, ticket_refs, citations, action_preview, context_candidate, usage, tool_summary, retrieval_trace, error. 참조와 preview는 실제 도구 결과 원장에서만 구성한다. failed에는 context_candidate를 적용하지 않는다. MOD-01의 활성 run·권한 재검증 및 commit을 통과해야 사용자용 완료가 된다. action_pending은 티켓 생성 완료가 아니다.

이 status는 MOD-02 결과 후보다. 영속 run의 running/completed/failed/expired와 혼동하지 않으며 [실행 계약](01-run-lifecycle.md)에 따라 MOD-01이 deadline·활성 소유권을 검증해 종료한다.

## CT-11 ExecutionObserver

MOD-02가 요구하고 MOD-01 어댑터가 구현한다. MOD-02는 CT-06의 ToolExecutionInput으로 같은 observer를 MOD-03에 넘긴다. 작업은 RecordToolCall(모든 도구 시도, MOD-02)과 RecordTrainingResult(MOD-04 결과 receipt, MOD-03), RecordStage(진행 단계, MOD-02)다. RecordStage는 run_id와 닫힌 stage 값(accepted/model_waiting/training_lookup/document_search/ticket_lookup/ticket_prepare/verifying)만 받으며 필수 기록이 아니다. 실패해도 실행을 멈추지 않고, 저장하지 않으며 같은 프로세스의 진행 스트림(MOD-01 StreamRunProgress)에만 넘긴다. run/ordinal/이름/허용된 인자 요약/시도 수/시간/오류 단계/반환 자원 ID를 기록한다. `(run_id,ordinal)` 멱등 기록. 필수 기록 실패는 추가 모델·도구 호출을 중단한다. 일반 진단 로그 실패와 구분한다. 이미 만료된 run의 늦은 이벤트가 활성 상태를 변경하지 않는다.

## CT-12 AppError

`code, safe_message, stage, retryable, details, internal_cause_id`. code·stage는 [닫힌 오류 사전](03-errors.md)만 허용하고 검사 우선순위·details 허용 키·도구/HTTP 매핑을 따른다. HTTP의 message는 safe_message만 매핑하며 internal_cause_id는 반환하지 않는다. 미존재와 접근 불가 자원은 외부에서 동일404·코드·문구·stage=auth로 정규화한다. 정상0건·근거 부족·날짜 추가 확인은 오류가 아니다. HTTP 매핑은 API 명세를 따른다.

## CT-13 RetrievalContext / SearchRequest

MOD-11이 `knowledge_enabled, corpus_snapshot_id, wiki_snapshot_id|null, requested_strategy, strict_mode, retriever_config_id, final_passage_limit, final_context_token_limit`를 구성해 MOD-01에 반환한다. strategy는 raw 또는 wiki_assisted이며 대화 생성 시 신뢰된 서버/평가 설정으로 고정한다. 평가 전용 full_context_reference는 source=eval_fixture·eval.run인 APP-04만 지정할 수 있고 운영 설정에서는 비활성이다([비교 프로토콜](../13-retrieval-comparison.md)의 전체 문맥 기준선). snapshot/config는 각 run 수락 시 고정한다. 모델과 직원 HTTP 입력이 전략을 바꾸지 못한다. final_passage_limit=null(개수 고정 상한 없음), 토큰 상한 초기4000이며 dev 예산 스윕 뒤 비교 전 고정 설정에 기록한다. retriever_config_id는 후보 수·packing_order·재정렬 사용 여부(주 실험은 없음)를 포함한다. 후보·확장·검색 채널은 [비교 프로토콜](../13-retrieval-comparison.md)을 따른다. M0~M2는 knowledge_enabled=false이며 snapshot/config는 null을 허용하고 search_documents를 등록하지 않는다. 지식 기능 활성화 시 corpus와 필수 검색 설정이 없으면 준비 오류다.

SearchRequest=`query,top_k,knowledge_as_of,as_of_date,date_basis,event_key,business_dates,question_context,execution_context`. 날짜 미확정 시 LookupApplicableBasis 메타데이터 조회 후 되묻고 오늘 날짜로 답변용 검색을 하지 않는다. business_dates/question_context는 MOD-02의 검증된 상태와 사용자 메시지를 서버가 전달한다. date_basis는 current/explicit_date/training_start/trip_start/approval_date/request_date/work_date/processing_date다. current는 사건 없는 일반 조회에서만 수락일을 기본으로 쓴다. [사건 날짜 계약](02-business-dates.md)이 필수 입력·검증·추가 확인의 기준이다. knowledge_as_of는 run 수락 시각(명시적 과거 지식 조회만 축소)이며 as_of_date는 사건 날짜다. 현재까지 공개된 규정으로90일 이내 예정 사건은 prospective=true로 지원한다. 과거 비교는 같은 snapshot에 서로 다른 날짜로 별도 호출한다. 특정 사용자·ACL·snapshot을 모델 인자로 받지 않는다.

## CT-14 RetrievalResult

원문 passages(CT-08) + `knowledge_as_of,prospective,unsupported,resolution,clarification,requested_strategy,effective_strategy,fallback_reason,corpus_snapshot_id,wiki_snapshot_id,as_of_date,date_basis,event_key,date_evidence,timings,usage,trace_id`. resolution=resolved이면 clarification=null이며 빈 passages는 정상0건이다. needs_clarification이면 passages=[]이고 [날짜 계약](02-business-dates.md)의 안전한 reason/required_event_type/event_key/prompt를 반환한다. 사건 날짜를 확인하지 못한 검색은 되묻기 대신 판본별 원문을 함께 주는 resolved일 수 있다(D-67): `edition_split={event_type,reason,editions}`와 그룹별 `as_of_date`를 두고, 이때 clarification은 서버 안전장치용으로만 남아 모델에 보이지 않는다. 사건 기준 없는 규정(general_reference)도 과거 단서가 있으면 판본별로 나눈다(D-86, event_type=explicit_date). 날짜를 정한 경로와 판본을 나누지 않은 이유는 도구 기록 trace의 `date_path`에만 남고 모델·화면에는 보내지 않는다. unsupported이면 passages=[]/clarification=null/unsupported={reason,safe_message}이며 reason=future_knowledge/event_out_of_horizon/unsupported_event_type다. HTTP200 outcome=insufficient_evidence로 매핑한다. 날짜 확인과0건을 구분한다. resolution=resolved에 `normative_gap={reason=normative_gap,safe_message}`가 있으면 적용 원규정 판본이 그 날짜에 없는 것이다([검색 조립](05-retrieval-assembly.md)). passages에는 그 날짜에 유효한 규범과 안내만 남고, MOD-02는 사건 문맥 단위로, 공백 사건을 그날 유효한 규범 없이(안내로) 결론 냈거나 공백 사건 말고는 인용이 없는 answered·insufficient_evidence를 서버 문구로 바꾼다. 문서 키·제목은 넣지 않는다. `authority_relations`는 결과 문서의 명시 우선관계 중 대상 문서가 현재 ACL로 보이는 것만 담는다(D-40). 경과조항 확장 원문은 passage의 source_role=transition이다. Wiki 후보는 최종 근거가 아니다. 운영 B가 fallback한 경우 effective_strategy=raw와 원인을 기록한다. 엄격 B 평가에서는 fallback 대신 실패로 집계한다. 빈 결과에서 제한 문서의 존재·제목·총량을 노출하지 않는다.

## CT-15 WikiBuild / WikiSnapshot / WikiCandidate

build는 source corpus ID·설정/프롬프트/모델 hash·빌드 범위·입력 비용을 기록한다. page는 제목·주제·요약·주장·관련 문서 관계를 담고, 각 주장에 원문 edition/block/span 링크를 가진다. 기여 원문 집합에는 본문 작성에 사용한 입력과 관계/제목을 인용한 원문도 포함한다. snapshot은 검수된 page 목록과 빌드 provenance를 고정한다. candidate는 권한과 적용 시점 검사를 통과한 page의 ID·탐색용 텍스트·원문 링크다. 서로 다른 시행 구간의 내용은 구간별 탐색 page로 분리하고 같은 시점 요약처럼 반환하지 않는다.

원문 전체를 읽는 빌드 운영자는 명시된 운영 권한이 필요하다. 읽기용 candidate를 반환할 때는 모든 기여 원문을 현재 사용자가 읽을 수 있어야 한다. 원문 링크 하나라도 해석되지 않으면 게시 실패 또는 명시된 미게시 항목이다.

구현(D-45~D-48): page는 주제 × 권한 등급 × (규범 시행 구간 | 안내 유효 기간)이고 기여 원문은 page 입력 판본 전체다. 원문 대조에 실패한 page는 problems를 기록한 미게시 항목이다. candidate는 page_id·제목·거리·링크 passage ID이며 Wiki 본문은 근거로 넘기지 않는다. 검색 경로는 모델이 보지 않는 `tool_calls.retrieval_trace`에 남긴다(D-47).

## CT-16 Ticket / PendingAction / Confirmation

Ticket=`id,subject,description,request_type,category,target_service,occurred_at,impact_scope,urgent_work,urgency_reason,asset_identifier,reply_channel,status,requester_id,created_at`. MVP 생성 상태 open. TicketDetail=Ticket, TicketPage={items:Ticket[],total,limit,offset,has_more}. ActionPreview는 missing_fields 및 action_id/version/status/expires_at/conversation_id와 Ticket의 모든 접수 필드 및 서버 생성 회신 표시를 포함한다. 필드·누락 시 추가 질문 기준은 [수령 보정](../corpus/03-received-pdf-adjustments.md)의 IT 접수 표를 따른다. 사용자 ID는 서버가 바인딩한다.

구현(M5, 2026-10-18, D-42): ActionPreview는 `action_id,version,status,expires_at,conversation_id,`접수 필드 10개`,missing_fields,reply_channel,root_action_id,prepared_from_action_id,displaced_head_id,superseded_by_action_id,current_action_id,ticket_id,head_revision`이다. pending 필수 필드는 D-42. Draft/PendingAction은 actor·conversation·initiating_run·expected_head_id/expected_head_revision·불변 payload/hash·version·만료 시각·상태를 MOD-12가 저장한 것이다. Confirmation은 인증된 UI의 action ID/version/Idempotency-Key와 CSRF 검증 결과다. 모델의 approved=true나 자연어 동의만으로 생성하지 않는다. 상태/원자성은 [티켓 흐름](../14-ticket-workflow.md) 기준이다.

PendingAction은 root_action_id/prepared_from_action_id/displaced_head_id와 자유문장 field_origins를 보존한다. 후보 전달·code point 구간 계산·템플릿 목록은 [출처 계약](04-field-origins.md)을 따른다. 조회 DTO는 superseded_by_action_id/current_action_id도 제공해 이전 메시지에서 최신 계보를 찾을 수 있게 한다. 새 action을 자동 승인하지 않고 내용을 다시 표시한다. Agent prepare는 draft이며 기존 head를 바꾸지 않는다. 채택된 completed run의 draft/pending에서만 인증된 UI의 version/fields/Idempotency-Key로 새 pending을 준비하며 확인은 변경된 payload를 받지 않는다. version은 불변 payload 판별용이며 각 action에서 항상1이다(값이 바뀌지 않는다). 경쟁 감지는 head_revision이 맡는다. 실제 접수 자유문장은 검증된 사용자 입력/서버 템플릿만 허용하며 검색 원문을 자동 전재하지 않는다. 상태는 draft/pending/superseded/confirmed/cancelled/expired다. MOD-12가 CP-06으로 원본 run 자격, CP-07로 본인 user 메시지 원문 구간을 확인한다.

## 공통 포트

| ID | 포트 | 책임 |
|---|---|---|
| CP-01 | Clock | KST 기준 시각·고정 fixture clock·경과 시간 |
| CP-02 | CurrentActor | MOD-09 세션 해석 어댑터; 테스트 대체 객체 구분 |
| CP-03 | TransactionBoundary | 소유 모듈의 짧은 commit; 타 모듈 DB 접근 권한 아님 |
| CP-04 | Telemetry | 비밀·본문 제외 진단, 시간·usage·fallback 기록 |
| CP-05 | ResourceVisibility | MOD-01이 이력/완료 시 MOD-11(문서)·MOD-12(티켓)로 참조 재검증 |
| CP-06 | RunEligibility | MOD-01 구현 읽기 포트; MOD-12의 prepare 및 action 원본 run 자격 확인, 앱이 주입 |
| CP-07 | ConversationEvidenceReader | MOD-01 구현 읽기 포트; 본인/run 문맥 user 원문 및 검증된 교육 결과 receipt를 제공, 앱이 MOD-02/12에 주입 |

CP-05는 MOD-02가 DB를 읽게 하는 포트가 아니다. 의존성이 변경되면 메시지를 보수적으로 가리고 일반 안내를 반환한다. 권한이 변경되는 모든 순간의 무지연 철회를 보장한다는 주장은 하지 않으며 반환 직전 서버 확인을 수행한다.

## CP-07의 공개 작업과 교육 receipt

ReadUserEvidence(actor,conversation,run,refs)는 소유권·run 문맥을 검증한 user 메시지 ID/Unicode 구간/원문만 반환한다. assistant/PDF/Wiki/다른 대화는 허용하지 않는다. MOD-12가 field_origins를 대조한다. ReadTrainingEvidence(actor,conversation,run,ref)는 실제 교육 응답 receipt와 선택한 사용자 메시지를 대조한다. MOD-03이 CT-11의 RecordTrainingResult로 MOD-04 결과의 run/ordinal/training ID/starts_at/hash를 기록한 후에만 모델에 전달하며, MOD-02가 CP-07로 날짜 근원을 검증한다. 필수 receipt 저장 실패는 실행 실패다. 원문 구간과 hash는 모델 제안에서 가져오지 않는다. MOD-01이 receipt 저장과 읽기 어댑터를 소유한다.

CT-13 application_basis는 [검색 조립 계약](05-retrieval-assembly.md)의 닫힌 값/대응표를 사용한다. 여러 검색의 사건별 evidence_group·support_group과 token 예산 병합은 같은 계약을 따른다. CT-08은 evidence_group/support_group 및 source_role(base/transition/referenced_rule), knowledge_as_of/as_of_date/date_basis/event_key를 보존한다. CT-09는 guidance 자체의 판본 유효 구간과 검수된 transition_relations를 포함한다.

M1의 knowledge_enabled=false RetrievalContext는 APP-02의 DisabledRetrievalContextProvider(조립용 어댑터, 새 모듈 아님)가 제공하며 in-memory observer를 쓴다. M2도 같은 disabled provider를 MOD-01에 주입한다. M3부터 실제 MOD-11 provider로 교체한다. 검색 기능 없는 단계에서 MOD-11 구현을 앞당겨 요구하지 않는다.
