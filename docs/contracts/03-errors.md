# CT-12 오류 사전과 매핑

모듈 AppError와 직원 HTTP envelope를 구분한다. 내부 원인/본문/토큰은 외부에 노출하지 않는다. 이 표가 code/stage의 닫힌 사전이며 신규 값은 계약 개정·테스트 없이 추가하지 않는다.

## 구조

AppError=`code,safe_message,stage,retryable,details,internal_cause_id`.
HTTP error=`code,message,stage,retryable,details`이며 message=safe_message, internal_cause_id는 제외한다. 메시지 POST의 수락 후 실패·만료 응답은 envelope 최상위에 `run_id`를 더한다([API](../04-api-spec.md)). details는 null 또는 코드별 허용 객체다. ACTION_SUPERSEDED/ACTION_HEAD_CONFLICT는 본인 자격 확인 뒤 `{current_action_id,head_revision}`, 필드 오류는 `{field_names}`만 허용한다. 미존재/불허는 details=null이며 제한 ID/제목/원문을 넣지 않는다. 버전 충돌도 타인 여부가 확인되기 전에는 노출하지 않는다. details에 임의 키를 넣지 않는다.

stage enum=`validation|auth|execution|search|wiki|model|tool|persistence|confirmation`.

| code (각 셀의 나열값만 허용) | stage | 직접 HTTP 매핑 |
|---|---|---|
| AUTHENTICATION_REQUIRED, SESSION_EXPIRED | auth | 401 |
| CSRF_FAILED, ACTION_NOT_ALLOWED | auth | 403 |
| CONVERSATION_NOT_FOUND, RUN_NOT_FOUND, TRAINING_NOT_FOUND, RESOURCE_NOT_FOUND | auth | 404 |
| INVALID_REQUEST, TOOL_ARGUMENT_INVALID, TOOL_NOT_REGISTERED | validation | 422 |
| TICKET_FIELD_ORIGIN_INVALID | validation | 422 |
| CONVERSATION_BUSY, MESSAGE_IDEMPOTENCY_CONFLICT, RUN_NOT_ELIGIBLE | execution | 409 |
| RUN_TIMEOUT, AGENT_LIMIT_EXCEEDED | execution | 504 |
| ACTION_VERSION_CONFLICT, ACTION_ALREADY_CONFIRMED, ACTION_CANCELLED, ACTION_NOT_PREPARED, ACTION_SUPERSEDED, ACTION_HEAD_CONFLICT, PREPARE_PAYLOAD_CONFLICT, ACTION_ORIGIN_INVALID, IDEMPOTENCY_CONFLICT | confirmation | 409 |
| ACTION_EXPIRED | confirmation | 410 |
| MODEL_NOT_CONFIGURED | model | 503 |
| MODEL_OUTPUT_INVALID, MODEL_UPSTREAM_ERROR | model | 502 |
| UPSTREAM_RATE_LIMITED | model | 429 |
| TOOL_EXECUTION_FAILED | tool | 502 |
| TOOL_TIMEOUT | tool | 504 |
| RETRIEVAL_NOT_READY | search | 503 |
| WIKI_NOT_READY | wiki | 503 |
| PERSISTENCE_FAILED | persistence | 503 |
| SERVICE_UNAVAILABLE | execution | 503 |

## 검사 순서와 경쟁

자원을 지정하는 일반 변경 요청은 인증/CSRF→소유권/현재 권한→키 입력 일치·version 등 유효성→성공 replay→신규 상태/만료/root 자격→commit 순서다. 인증 전에 반환할 수 있는 것은 JSON 문법처럼 자원 존재와 무관한 형식 오류뿐이다. 소유권 거절은 version 불일치보다 우선하며 동일404다. 성공 replay도 현재 권한을 통과하고 신규 상태 검사보다 먼저 반환한다.

상태 오류 우선순위는 confirmed의 같은 confirm 결과→superseded→cancelled→만료→draft confirm 불가→head/root 자격이다. confirmed의 cancel/revise는 ACTION_ALREADY_CONFIRMED다. 여러 오류가 함께 있어도 공통 순서를 적용하며 만료 상태를 통해 타인 action 존재를 드러내지 않는다.

## 도구 오류와 HTTP 오류

CT-06 `ok=false,data=null,error=AppError`는 도구 실행 결과이며 HTTP status가 아니다. 예를 들어 도구의 RESOURCE_NOT_FOUND를 Agent가 처리해 안전한 안내로 완료하면 메시지 HTTP는200일 수 있다. 직접 자원 GET은 같은 code를404로 매핑한다. 복구 불가능한 도구 실패로 run이 종료되면 외곽은 TOOL_EXECUTION_FAILED/TOOL_TIMEOUT 등의 run 오류로 매핑하고 원래 원인은 내부 진단에 보존한다. 원래 도구 경로 stage를 일반 tool로 덮어써 기록하지 않는다. 실제 변경 성공 여부 불명은 새 작업 자동 생성으로 바꾸지 않는다.

날짜 추가 질문/검색0건/근거 부족은 AppError가 아니며 CT-14/CT-10의 정상 결과다. 비밀·권한 관련 details는 도구 모델 문맥으로도 보내지 않는다.
