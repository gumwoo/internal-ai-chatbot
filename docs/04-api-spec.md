# HTTP API 계약

기본 경로 `/api/v1`. JSON UTF-8, 시각 ISO8601+offset, 업무 날짜 ISO date. UUID 자원 식별자와 PDF-번호 source_file_id를 구분한다. 아래는 구현 목표다. 현재 실행되는 것은 health, 교육 조회(`/trainings`), 대화·메시지·run(`/conversations`, `/runs`)과 메시지 POST의 진행 상황 스트리밍(SSE), 로컬 세션(`/session`, AUTH_MODE=local_session)이다. 근거/PDF·티켓은 아직 없다.

## 공통

최종 MVP는 MOD-09 로컬 서버 세션을 사용한다. 모든 업무 API는 인증 필요. 상태 변경에는 CSRF/Origin 검증을 적용한다. 브라우저의 user_id/role/strategy로 권한·검색 설정을 바꿀 수 없다. 입력의 알 수 없는 필드를 거절한다.

오류 JSON(code/stage/details는 [닫힌 사전](contracts/03-errors.md)의 매핑을 따른다):

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "요청한 항목을 찾을 수 없습니다.",
    "stage": "auth",
    "retryable": false,
    "details": null
  },
  "request_id": "22222222-2222-4222-8222-222222222201"
}
```

메시지 POST가 run을 수락한 뒤의 실패·만료(최초 응답과 재전송 모두)는 최상위에 `run_id`를 함께 둔다. 그 밖의 오류에는 없다. message에는 CT-12.safe_message만 매핑한다. stage는 CT-12와 같은 이름을 사용하고 내부 원인은 숨긴다. 같은 자원 종류의 미존재/접근 불가는 code·message·stage·HTTP를 동일하게 만든다. 대화/메시지/run/세션/티켓/action/근거/PDF 응답은 `Cache-Control: private, no-store`다. UI의 메모리 캐시도 로그아웃·권한 변경에서 지운다.

## 세션 — MOD-09

| Method·경로 | 입력 | 반환 |
|---|---|---|
| POST `/session` | local 계정 username/password | 200 표시용 사용자, 세션 cookie; 인증 실패401 |
| GET `/session` | cookie | 200 user_id/display_name/허용 UI capabilities/CSRF 정보 |
| DELETE `/session` | cookie+CSRF | 204 세션 회수 |

구현 세부(M3): 세션 cookie `agent_session`(HttpOnly·SameSite=Strict·Path=/api/v1·Max-Age=세션 수명, production에서 Secure), 서버에는 토큰의 SHA-256만 저장한다. 세션 수명은 설정 `SESSION_TTL_S`(초기 8시간). CSRF 토큰은 세션 토큰의 HMAC이며 로그인 응답과 GET `/session`의 `csrf_token`으로만 받는다. 상태 변경 요청은 `X-CSRF-Token` 헤더가 맞아야 하며(403 CSRF_FAILED) Origin 검사와 별개다. 로그인은 `Content-Type: application/json`만 받는다. 로그인 실패 사유(계정 없음·비밀번호 틀림·웹 로그인 없음·비활성)는 모두 같은 401이다. 웹 세션 actor에는 운영(ops.*)·평가(eval.*) capability를 주지 않는다. 로그인은 별도 Origin 검사/로그인 CSRF 방어를 적용한다. 클라이언트에 세션 저장소 값·해시·모델 키를 반환하지 않는다. 첫 조회 구간의 test_stub은 서버 설정/테스트 DI로 고정하고 클라이언트에서 사용자를 선택하지 않는다. [첫 구간의 제한](12-first-milestone-spec.md)을 따르며 최종 ACL/사용자 분리 검증에는 세션이 필요하다.

## 대화·실행 — MOD-01

| Method·경로 | 입력 | 반환 |
|---|---|---|
| POST `/conversations` | title?(1~100자) | 201 id/title/created_at, 검색 전략은 서버 설정 |
| GET `/conversations` | limit1~50=20, offset>=0 | 200 items/total/limit/offset/has_more, 본인만 |
| GET `/conversations/{id}` | 소유 ID | 200 표시 정보·active_run_id |
| GET `/conversations/{id}/messages` | limit1~50=20, offset>=0 | 200 items/total/limit/offset/has_more, 현재 권한 재검증 후 가림 |
| POST `/conversations/{id}/messages` | content(1~4000자), UUID Idempotency-Key header | 최초 동기 완료200, 동일 요청 실행 중 replay202, 유효한 다른 실행 중409 |
| GET `/runs/{id}` | 본인 run ID | 만료 회수·현재 가시성 재검증 후200 상태·outcome·시간·usage·도구 안전 요약 |

메시지 POST의 기본(`Accept: application/json`)은 단계 이벤트 없는 동기 처리다. M2 이후에는 아래 "진행 상황 스트리밍"을 선택적으로 쓴다. 어느 쪽이든 답변 본문은 권한 재확인·인용 검증·commit을 마친 뒤 한 번에 보낸다. HTTP 응답 유실·클라이언트 timeout을 서버 취소로 간주하지 않는다. 같은 사용자 입력의 재시도는 같은 키를 유지한다. MOD-01은 actor/conversation/key/content hash와 run을 원자 수락하고, 재전송은 기존 실행만 조회/재표시한다. 같은 키·다른 내용은409 MESSAGE_IDEMPOTENCY_CONFLICT다. 활성 run은 running, 종료는 completed/failed/expired다. 시작·조회·다음 수락에서 deadline 지난 running을 회수한다. 전이·늦은 완료·복구는 [실행 계약](contracts/01-run-lifecycle.md)이 기준이다. run의 내부 원인·제한 도구 인자/결과·Wiki 진단 전문을 반환하지 않는다.

202 replay는 conversation_id/user_message_id/run_id/status=running을 반환한다. UI는202 뒤 GET run으로 종료를 확인한 다음 동일 키/본문 POST replay로 최종 answer를 받는다. 종료 replay는 현재 권한으로 안전 응답을 다시 구성하며 최초 성공은200, 실패/만료는 저장된 오류 HTTP로 반환한다. 원래 입력과 run을 새로 만들지 않는다.

### 진행 상황 스트리밍(M2 이후, 선택)

같은 메시지 POST를 `Accept: text/event-stream`으로 보내면 Server-Sent Events로 응답한다. 새 경로는 만들지 않으며 멱등키·수락·409·replay 규칙은 JSON 요청과 같다.

- `progress` 이벤트: `{run_id, seq, stage}`. stage 닫힌 값은 accepted/model_waiting/training_lookup/document_search/ticket_lookup/ticket_prepare/verifying이다. 서버가 CT-11 observer로 실제 기록한 단계만 보낸다. 도구 인자·문서 제목·검색 결과 수·답변 일부는 넣지 않는다(결과 수는 제한 문서의 존재를 짐작하게 할 수 있다).
- 종료 이벤트는 정확히 하나다. `result`는 JSON 200 응답과 같은 본문이며 권한 재확인·인용 검증·commit 뒤에만 보낸다. `error`는 오류 envelope와 같은 내용이다.
- 15초마다 heartbeat 주석 줄을 보내 연결을 유지한다. 연결이 끊겨도 실행을 취소하지 않으며 UI는 기존처럼 GET run 후 동일 키 POST replay로 최종 결과를 받는다. 실행 중 replay는 SSE를 다시 열지 않고 JSON 202를 반환한다. 종료된 run의 replay도 SSE가 아니라 JSON 요청과 같은 응답(200 또는 저장된 오류)이다. 수락 전 오류(404·409·422)는 스트림을 열지 않고 JSON 오류로 반환한다.
- 만료·종료된 run의 늦은 단계는 보내지 않는다. 다른 사용자의 run은 동일404다.

메시지 성공 응답은 `conversation_id,run_id,message_id,status,outcome,answer,training_refs,ticket_refs,citations,action_preview,error`다. status=completed와 error=null, outcome은 [Agent 정책](05-agent-execution.md)과 같다. refs는 실제 결과의 ID/title 요약이다. 날짜/장소·ticket 상태는 해당 상세 API나 검증된 서버 DTO로 표시한다.

action_pending 응답의 표시 부분 예시(가상 요청 내용이며 실제 규정 아님):

```json
{
  "outcome": "action_pending",
  "answer": "아래 내용으로 IT 지원 요청을 등록할 수 있습니다. 내용을 확인해 주세요.",
  "action_preview": {
    "action_id": "33333333-3333-4333-8333-333333333301",
    "version": 1,
    "subject": "VPN 접속 오류 문의",
    "description": "VPN 접속이 안 돼요.",
    "category": "network",
    "request_type": "incident",
    "target_service": "사내 VPN",
    "occurred_at": null,
    "impact_scope": null,
    "urgent_work": null,
    "urgency_reason": null,
    "asset_identifier": null,
    "reply_channel": "서버 프로필의 사내 회신 수단",
    "status": "draft",
    "missing_fields": ["occurred_at", "impact_scope", "urgent_work"],
    "expires_at": "2026-10-16T10:05:00+09:00",
    "conversation_id": "44444444-4444-4444-8444-444444444401"
  }
}
```

이력의 assistant 메시지는 `visibility=visible|redacted`를 가진다. redacted는 일반 안내만 반환하며 원래 answer/citations/refs/preview 본문은 포함하지 않는다. 최종 반환 직전 권한을 잃은 새 답변도 같은 규칙으로 가리며 outcome=insufficient_evidence의 안전한 안내를 반환한다. 내부에는 original outcome과 redaction 사유를 별도로 보존한다.

## 교육 — MOD-04

GET `/trainings`: date_preset(default next_30_days), custom일 때 start_date/end_date_exclusive, query<=100자, limit1~20=10, offset>=0. enum·90일·KST 날짜 정책은 [도구](05-agent-execution.md)와 동일. 200 CT-05 Page. 기본 scheduled만 포함한다.

GET `/trainings/{id}`: 200 CT-05 Detail, UUID 형식 오류422, 미존재404. 취소/완료도 상세에서 실제 상태를 반환한다. fixture의 예정 여부를 규정상 의무교육 여부로 확장하지 않는다.

## 근거·PDF — MOD-05

| 경로 | 반환·권한 |
|---|---|
| GET `/evidence/{passage_id}` | 200 문서/판본/시행 구간·원문·page_spans. 현재 ACL 재검증 |
| GET `/source-files/{source_file_id}/pdf` | application/pdf 원본 bytes. 현재 ACL/withdrawn 확인 후만 제공 |

인용 DTO는 `citation_id,passage_id,document_key,source_file_id,version,title,document_role,available_from,knowledge_as_of,prospective,effective_from,effective_to,edition_state,as_of_date,date_basis,event_key,page_spans,quote,evidence_url,pdf_url`다. edition_state는 현행/종전/철회 상태의 서버 표시 값이며 적용 판단은 사건 날짜·시행 구간을 따른다. URL과 날짜 표시도 서버가 생성한다. PDF URL의 `#page=물리페이지`는 보기 힌트이며 권한 수단이 아니다. 근거/PDF는 `Cache-Control: private, no-store`로 제공하고 공개 blob URL/정적 파일 접근을 허용하지 않는다. 존재 불가/접근 불가는 동일404다. PDF를 이미 내려받은 사용자의 로컬 파일을 서버가 회수할 수 있다는 주장은 하지 않는다.

초기 MVP는 별도 문서 업로드·Wiki 편집/빌드·임의 검색 전략 전환 HTTP를 만들지 않는다. 문서 운영은 CLI, 채팅 검색은 도구 계약으로 수행한다.

## IT 지원 — MOD-12

| Method·경로 | 입력 | 반환 |
|---|---|---|
| GET `/it-tickets` | status?(open), limit1~20=10, offset>=0 | 200 TicketPage(items/total/limit/offset/has_more) |
| GET `/it-tickets/{id}` | 현재 허용 ID | 200 TicketDetail |
| GET `/ticket-actions/{id}` | 본인 action | 200 preview/status/ticket_id, root/prepared_from/displaced_head/superseded_by/current_action_id 및 허용 완료 결과 |
| POST `/ticket-actions/{id}/revise` | version, fields(허용 접수 필드), Idempotency-Key header, CSRF | 최초201 새 action preview/반복200 같은 수정 결과·현재 상태 |
| POST `/ticket-actions/{id}/confirm` | version, Idempotency-Key header, CSRF | 최초201/반복200, action_id/ticket_id/ticket/status |
| POST `/ticket-actions/{id}/cancel` | version, CSRF | draft/pending/cancelled200, superseded/confirmed409, expired410 |

티켓 접수 DTO는 CT-16과 [수령 보정](corpus/03-received-pdf-adjustments.md)의 요청 유형·서비스·발생 시각·영향·긴급 여부·자산 식별·서버 회신 수단을 포함한다. 최초 준비는 Agent의 prepare_it_ticket만 시작한다. Agent prepare는 불완전한 draft이며 기존 pending/head에 영향이 없다. 편집 폼은 채택된 completed run의 미만료 draft 또는 현재 pending을 revise하여 새 pending을 만들며, 확인 본문에는 payload를 다시 받지 않는다. 수정·확인 모두 현재 권한과 CP-06 원본 run 자격을 확인한다. 최초 prepare의 자유문장은 서버가 사용자 메시지 근원을 검증하고, revise는 인증된 사용자의 직접 입력으로 바인딩한다. requester/reply_channel/status/run/승인 값은 fields로 바꿀 수 없다.

Idempotency-Key는 UUID 형식, actor 범위에서 작업·대상·입력에 바인딩한다. 같은 키와 다른 작업/action/version/payload는409다. 같은 action의 반복 확인은 다른 키로 와도 기존 ticket으로 수렴한다. GET action은 lazy 만료를 계산하되200 상태를 반환한다. 만료 action confirm/revise/cancel은410, 취소 action confirm/revise는409, 반복 cancel은200, confirmed cancel/revise/새 prepare는409다. 미존재/불허는 상태 정보 없이 동일404다. 버전 불일치는409다. 단일 대화의 요청 계보·수정 경쟁·입력 출처는 [티켓 흐름](14-ticket-workflow.md)을 따른다.

## 상태 코드

| HTTP | 대표 코드 |
|---|---|
| 401 | AUTHENTICATION_REQUIRED / SESSION_EXPIRED |
| 403 | CSRF_FAILED / ACTION_NOT_ALLOWED (자원 존재를 새로 노출하지 않는 행위 거부) |
| 404 | CONVERSATION_NOT_FOUND / RUN_NOT_FOUND / TRAINING_NOT_FOUND / RESOURCE_NOT_FOUND |
| 409 | CONVERSATION_BUSY / MESSAGE_IDEMPOTENCY_CONFLICT / ACTION_VERSION_CONFLICT / ACTION_ALREADY_CONFIRMED / ACTION_CANCELLED / ACTION_NOT_PREPARED / ACTION_SUPERSEDED / ACTION_HEAD_CONFLICT / PREPARE_PAYLOAD_CONFLICT / ACTION_ORIGIN_INVALID / RUN_NOT_ELIGIBLE / IDEMPOTENCY_CONFLICT |
| 410 | ACTION_EXPIRED (이미 소유권 확인한 본인 action) |
| 422 | INVALID_REQUEST / TOOL_ARGUMENT_INVALID / TOOL_NOT_REGISTERED / TICKET_FIELD_ORIGIN_INVALID |
| 429 | UPSTREAM_RATE_LIMITED |
| 502 | MODEL_UPSTREAM_ERROR / MODEL_OUTPUT_INVALID / TOOL_EXECUTION_FAILED |
| 503 | PERSISTENCE_FAILED / MODEL_NOT_CONFIGURED / SERVICE_UNAVAILABLE / RETRIEVAL_NOT_READY / WIKI_NOT_READY |
| 504 | RUN_TIMEOUT / TOOL_TIMEOUT / AGENT_LIMIT_EXCEEDED |

정상0건/근거 부족은200. 실제 오류는 오류 envelope와 가능한 run_id를 포함하고 failed/expired 상태를 보존한다. DB commit 불확실성은 무조건 재생성하지 않고 자원 상태를 조회한다.

## 건강 확인

GET `/health/live`: 프로세스 응답. GET `/health/ready`: DB 등 필수 의존 상태, corpus/wiki 준비 여부는 capability 상태로 표시한다. 교육만 구현한 단계에서 문서 미게시를 전체 앱 장애로 판정하지 않는다. 모델 유료 호출은 하지 않는다.

## 목록 공통 형태와 티켓 초안 표시

모든 offset 목록은 `items,total,limit,offset,has_more`를 반환하고 빈 목록은 items=[]/total=0/has_more=false다. TicketPage.items는 CT-16 Ticket, TicketDetail은 Ticket과 같다. 미확인 draft 필드는 null과 missing_fields로 표시하고 예시 발생 시각이나 영향 범위를 서버에서 만들어 채우지 않는다. 위 draft 예시의 description은 사용자가 같은 원문을 입력했고 field_origins 검증을 통과했다는 전제다. draft는 confirm409 ACTION_NOT_PREPARED이며 UI revise로 완전한 pending을 만든 뒤에만 확인 가능하다. superseded의 변경 요청은409 ACTION_SUPERSEDED와 본인 current_action_id다. 소유권 검사는 version보다 먼저다. 정확한 전이는 [티켓 계약](14-ticket-workflow.md)을 따른다.

ACTION_HEAD_CONFLICT/ACTION_SUPERSEDED의 error.details는 소유권 확인 후 `{current_action_id,head_revision}`를 반환한다. 미존재/불허는 details=null이다. 도구의 AppError는 HTTP status 그 자체가 아니며 복구 가능한 도구 실패가 메시지 정상 완료로 끝날 수 있다. 현재 head와 새 입력을 다시 검토하게 하되 충돌 응답으로 폼 입력을 지우지 않는다.
