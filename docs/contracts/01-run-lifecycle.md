# 대화 실행 수락·재전송·복구 계약

MOD-01이 소유하는 모듈 계약이다. HTTP 표기는 [API](../04-api-spec.md), Agent 결과는 CT-10이다. 큐·스케줄러·마이크로서비스를 추가하지 않는다.

## 실행 상태와 시간

| 상태 | 진입 조건 | 활성 소유권 |
|---|---|---|
| running | 질문·run·메시지 멱등 접수를 함께 저장 | 해당 conversation의 active_run_id |
| completed | 유효한 CT-10 정상 결과, 현재 권한 확인, deadline 이전 완료 commit | 같은 commit에서 해제 |
| failed | deadline 이전 모델/도구/기록/출력 실패 | 같은 commit에서 해제 |
| expired | running의 deadline_at 경과 | 만료 처리와 함께 해제 |

accepted_at은 서버 시각, deadline_at은 accepted_at+60초인 영속 시각이다. 같은 프로세스 안의 경과 측정은 단조 clock을 쓴다. 프로세스 재시작 후에는 영속 deadline_at을 서버 시각과 비교한다. 완료와 만료는 run ID·현재 상태·deadline을 조건으로 경쟁하며 한 종료만 유효하다. 이전 run의 해제가 새 run의 active_run_id를 지우면 안 된다.

CT-10의 completed/failed는 MOD-02가 내놓는 실행 결과 후보다. MOD-01의 영속 run 상태와 별개이며, 후보가 성공이어도 deadline 경과 시 expired로 끝낸다. CT-10 failed의 원인이 전체 RUN_TIMEOUT이면 expired, deadline 이전의 개별 호출 실패면 failed다. 실패·만료에서는 대화 업무 상태 후보를 적용하지 않는다.

## 죽은 실행의 회수

MOD-01.RecoverExpiredRuns(now)는 다음 진입에서 실행한다.

1. APP-02 시작 시, deadline이 지난 running을 회수한다.
2. AcceptMessage의 활성 소유권 검사 전 해당 대화를 회수한다.
3. GetConversation/GetRun에서 해당 run의 상태를 반환하기 전 회수한다.

프로세스가 죽었어도 미래 deadline을 즉시 만료시키지 않는다. 다른 작업자가 실행 중일 수 있기 때문이다. 마지막 수락으로부터 최대60초가 지난 다음 진입에서는 회수 후 새 메시지를 수락할 수 있다. 아무 요청도 없을 때 즉시 상태를 갱신하는 백그라운드 작업은 MVP 필수가 아니다. 늦은 도구 기록·결과는 진단 대상으로만 남고 메시지·업무 상태·활성 소유권을 변경하지 않는다.

## 메시지 멱등 접수

POST messages는 클라이언트가 한 번 생성한 UUID Idempotency-Key를 요구한다. MOD-01은 `(actor_id,conversation_id,key)`와 content hash, user_message_id, run_id를 message_receipts에 저장한다. 질문·receipt·run 수락은 원자적이다. 같은 질문 문자열이라도 새 키는 새 사용자 의도다.

| 재요청 | 결과 |
|---|---|
| 같은 키·같은 content, running | 202, 기존 run_id/user_message_id/status; 새 실행 없음 |
| 같은 키·같은 content, 종료됨 | 기존 성공200 또는 저장된 실패/만료 HTTP·안전 오류를 재구성; 새 실행 없음 |
| 같은 키·다른 content | 409 MESSAGE_IDEMPOTENCY_CONFLICT |
| 새 키, 유효한 다른 active run 존재 | 409 CONVERSATION_BUSY, 새 receipt/메시지/run 없음 |
| 새 키, 이전 active run 만료 | 회수 후 원자 수락 |

replay에서도 현재 소유권·참조 가시성을 검사한다. 저장된 응답 bytes를 권한 검사 없이 재전송하지 않는다. receipt는 대화 보존 기간 동안 유지하고 최초 MVP에서는 임의 TTL로 제거하지 않는다. UI는 전송·응답 유실·조회·재시도 동안 같은 키를 보관하며 자동으로 새 키를 만들지 않는다. 단순 재조회/재전송이 pending 티켓 준비를 취소하지 않는다.

## Agent 준비와 사용자 확인의 실행 자격

CP-06 RunEligibility는 MOD-01이 구현하고 앱이 MOD-12에 주입하는 읽기 포트다. MOD-12가 MOD-01 저장소에 직접 접근하지 않는다.

- CheckPrepare(actor,conversation,run): 소유권이 맞고 active running이며 deadline 이전이어야 한다. 준비 진입과 저장 직전에 확인한다. 이미 실패/만료/완료된 run의 새 prepare는 RUN_NOT_ELIGIBLE이다.
- CheckActionOrigin(actor,conversation,run,action): initiating run이 completed이고 그 결과에 해당 root draft action이 채택되어야 한다. 수정 후 action은 이 채택된 action의 서버 관리 계보를 따른다.
- Agent prepare는 draft만 저장하고 이전 pending/head를 바꾸지 않는다. 준비만 저장된 뒤 run이 실패/만료되면 그 draft는 미공개 준비로 남을 수 있으나 확인·수정할 수 없다. 확인 가능한 action 목록으로 표시하지 않고 필요 시 정리한다. 준비 저장과 대화 완료를 분산 트랜잭션으로 묶지 않는다.
- 성공한 run의 사용자 확인은 Agent의60초 제한과 별개이며 action의5분 만료와 현재 권한을 적용한다. 새 run이 있다는 이유만으로 이미 완료된 run의 유효 action을 자동 취소하지 않는다.

검증: T-02 복구/늦은 완료, T-03 수락·완료 commit 실패, T-05 재전송 단일 실행, T-31/33 부적격 run 준비/확인 차단.

## 202 이후 최종 답변 수령

MOD-08은 POST 메시지의 동일 키/본문을 보관한다.202이면 GET run으로 상태를 확인하고, 종료되면 **동일 키·동일 본문으로 POST를 replay**하여 answer/citations/action_preview 또는 저장된 안전 오류를 받는다. GET run은 상태 확인용이며 answer 경로를 대신하지 않는다. poll 간격은1초부터 최대5초로 늘리고 페이지 이탈 후 같은 receipt로 복구한다. 재전송은 새 모델 실행이나 새 draft를 만들지 않는다.
