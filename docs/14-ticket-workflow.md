# IT 티켓 초안·재준비·확인 계약

## 범위와 단일 기준

MOD-12가 action·head·ticket·감사를 소유한다. 실제 계정 복구/VPN 설정 없이 IT 접수까지만 다룬다. 한 대화는 지원 건 하나의 계보이며 confirmed 뒤 새 지원 건은 새 대화에서 시작한다. 본 문서는 CT-16·HTTP·모듈의 상태 전이 기준이다.

## 초안과 확인 가능한 준비의 분리

Agent의 `prepare_it_ticket`은 **draft만** 만든다. 부족한 필드는 null과 missing_fields로 보존하며 필드가 모두 있어도 draft다. 아직 확인 가능한 pending이나 head를 변경하지 않는다. CP-06.CheckPrepare로 준비 진입/저장 직전 활성 run 자격을 확인한다.

MOD-01이 run을 completed로 종료하고 root draft를 결과에 채택한 뒤에만 UI에 공개한다. 실패/만료 run의 draft는 확인·수정 불가이며 **이전 pending에 영향이 없다**. 두 모듈을 분산 commit으로 묶지 않는다.

UI의 POST `/ticket-actions/{id}/revise`가 완전한 필드를 받아 새 pending을 만든다. draft→pending과 pending→새 pending에 같은 작업을 사용한다. 변경 없는 draft도 이 작업이 필요하고, 변경 없는 pending 재열람만 GET이다. 폼 열기/입력/편집 취소는 서버 상태를 바꾸지 않는다.

## 입력 출처와 실제 검증 경로

subject 1~120자, description 1~4000자, category=account/network/device/software/other. 나머지는 [수령 보정](corpus/03-received-pdf-adjustments.md)의 접수 필드가 기준이다. draft에는 누락을 허용하지만 pending에는 필수 입력이 모두 필요하다. requester/reply_channel/created_at/status는 서버 값이다.

Agent 자유문장은 본인 user 메시지의 원문 구간 또는 허용된 서버 고정 템플릿만 사용한다. field_origins는 message_id·Unicode 구간·정규화 종류를 포함한다. MOD-12는 **CP-07 ConversationEvidenceReader**로 본인 소유이면서 해당 run 문맥에 속하는 실제 user 메시지를 읽고 구간을 대조한다. 모델이 보낸 원문 사본이나 ID만 믿지 않는다. 날짜·분류 정규화는 허용 목록으로 제한한다. CP-07의 MOD-01 읽기 어댑터는 앱이 주입하고, MOD-12는 대화 DB/01 구현을 직접 읽지 않는다.

PDF·Wiki·assistant·도구 로그·다른 티켓은 접수 자유문장의 자동 입력 원천이 아니다. UI 직접 입력은 인증된 user_input으로 actor·시각·직전 action을 감사에 남긴다. 사용자 확인은 출처 검증을 대체하지 않는다. 발생 시각·영향·긴급 여부는 사용자가 말하지 않았다면 비워 두고 확인한다. 비밀번호·토큰을 입력하지 않도록 안내한다.

## 재준비·계보·멱등성

1. **인증/소유권부터** 확인한다. 미존재/불허는 동일404다. 이후 version·입력·멱등키 바인딩을 검사한다.
2. `(actor,key)`에 같은 작업/대상/version/payload hash의 성공 결과가 있으면 현재 권한으로 replay한다. 다른 입력이면409 IDEMPOTENCY_CONFLICT다.
3. 신규 revise는 CP-06으로 root run의 completed/채택을 확인한다. 원본은 미만료 draft 또는 현재 head인 pending이어야 한다.
4. 공통 head 직렬화 안에서 기대 head/version·필드를 검증한 뒤 새 pending 생성·head 교체·이전 pending 및 원본 draft의 superseded 전환·역할별 계보·감사·멱등 결과를 함께 commit한다. prepared_from_action_id는 소비한 원본, displaced_head_id는 그와 별개로 밀려난 이전 pending이다. 둘이 같은 action이면 displaced_head_id=null로 중복을 제거한다. 실패하면 이전 pending을 유지한다.
5. root_action_id/prepared_from_action_id/displaced_head_id/superseded_by_action_id/current_action_id를 반환한다. 이전 버튼을 새 action 승인에 자동 연결하지 않고 새 내용을 다시 확인한다.

draft에 `expected_head_id/expected_head_revision`를 기록한다. 기다리는 동안 다른 revise/confirm/cancel이 head ID/단조 증가 head_revision을 바꾸면409 ACTION_HEAD_CONFLICT이며 현재 허용 참조만 반환한다. 새 draft로 재검토한다. head가 confirmed이면 새 prepare/revise는409 ACTION_ALREADY_CONFIRMED다. Agent가 draft 여러 개를 만들더라도 head를 바꿀 수 없다.

payload는 불변이며 각 action의 version은 항상1이다. revise 사슬마다 새 pending의 만료가 다시5분으로 시작한다. MVP는 사슬 횟수·총 수명 상한을 두지 않고(D-24, [정책 선택](15-policy-options.md) P-06 A) 감사 기록으로 사슬 길이를 관찰한다. root prepare만 `ticket_prepare_receipts(run,ordinal,payload_hash,draft_id)`에 바인딩한다. 같은 `(run,ordinal)`·같은 hash는 같은 draft, 다른 hash는409 PREPARE_PAYLOAD_CONFLICT다. revision은 별도 action ID/UI 멱등키를 사용하며 원본 run/ordinal은 출처 참조이지 유일키가 아니다.

## 상태와 응답

| 현재 | 작업 | 결과 |
|---|---|---|
| 없음 | Agent prepare | draft; head 불변, ticket 0건 |
| draft | 유효 UI revise | 새 pending, 원본 superseded,201 |
| draft | confirm | 409 ACTION_NOT_PREPARED |
| draft/pending | 명시 cancel | cancelled,200; head면 같은 직렬화 경계에서 취소 |
| pending | 유효 revise | 이전 superseded+새 pending+head 교체,201 |
| pending | 유효 confirm | confirmed+ticket 1건,201 |
| draft/pending | expires_at 경과 | expired; 변경 작업410 ACTION_EXPIRED |
| superseded | confirm/revise/cancel | 409 ACTION_SUPERSEDED, 허용 current_action_id |
| cancelled | confirm/revise | 409 ACTION_CANCELLED |
| cancelled | cancel 재시도 | 200 cancelled |
| confirmed | 재확인 | 현재 열람 권한 확인 후 같은 ticket,200 |
| confirmed | revise/cancel/새 prepare | 409 ACTION_ALREADY_CONFIRMED |

GET은 lazy 만료 후200으로 현재 상태를 반환한다. 만료는 draft/pending에만 적용하고 confirmed 결과는 없애지 않는다. draft TTL은 생성부터5분, 새 pending은 revise commit부터5분이다. UI는 서버 expires_at을 표시한다. superseded/cancelled/expired를 편집으로 되살리지 않는다. 새 준비는 명시적인 새 Agent 요청으로 시작한다. 편집 취소는 원래 pending preview로 돌아가며 서버 cancel과 구분한다.

## 경쟁·응답 유실·원자성

revise/confirm/cancel은 같은 actor/conversation head 경계로 직렬화한다. confirm은 action 소비·ticket·감사·멱등 응답을 함께 commit한다. action당 ticket 최대1건, `(actor,key)`는 작업 종류까지 바인딩한다. 다른 키의 반복 confirm도 같은 ticket으로 수렴한다. 외부 모델 호출은 트랜잭션 밖이다.

확인이 먼저면 교체409, 교체가 먼저면 이전 확인409다. 소유권 검사 전 version 오류를 노출하지 않는다. 유실 시 GET action 후 **동일 키**로 재시도한다. 원본이 superseded여도 성공 replay는 신규 상태 검사보다 먼저다. 결과 action의 현재 상태를 반환하고 pending으로 되돌리지 않는다.

## 반례 검증

- A pending → B run draft 준비 → B 실패/만료 → A 여전히 확인 가능.
- A 편집 열기 → 편집 취소/탐색 → A pending 유지. 수정 저장 성공만 A superseded.
- 같은 prepare key·다른 payload →409, 기존 draft 유지. revision은 root 유일키와 충돌하지 않음.
- 타인 action의 틀린 version도404. superseded cancel은409이며 후속 action 불변.
- 사용자 구간 위조/PDF 내용을 증상으로 자동 복사 → 실패. 빈 발생 시각/영향을 추정하지 않음.

T-30~33에 포함한다. 이 명세의 DB 경쟁 검증은 구현 단계의 필수 작업이며 정적 시안 테스트로 서버 원자성을 입증하지 않는다.

head_revision은 MOD-12가 revise/confirm/현재 pending cancel의 성공 commit마다 증가시킨다. payload version과 별개이며 head ID가 그대로인 상태 변화도 감지한다. head 부재는 (null,0)이고 첫 UI revise가 직렬화 경계 안에서 최초 head를 만든다. head의 lazy 만료는 revision을 증가시키지 않는다. 만료는 expires_at과 직렬화 경계 안의 같은 clock으로 결정되므로 기대값 비교에 별도 세대가 필요 없고, GET 시점에 따라 draft의 revise 결과가 달라지면 안 되기 때문이다. Agent draft는 이 값을 읽어 고정할 뿐 수정하지 않는다.

revise 시 현재 head가 cancelled이거나 같은 clock 기준 만료된 pending이면 교체 가능한 head로 본다. 새 pending이 head가 되고 displaced_head_id에 그 action ID를 기록하되 그 action의 상태(cancelled/expired)는 superseded로 바꾸지 않는다. confirmed head는 교체하지 않는다(409 ACTION_ALREADY_CONFIRMED).

## head row·초기 경쟁·취소 후 상태

`ticket_action_heads`는 conversation_id UNIQUE, actor_id, head_action_id(nullable), head_revision을 가진다. conversation의 단일 owner와 actor_id 일치를 검증하며 actor를 바꿔 같은 대화에 head를 추가할 수 없다. head_revision은 row 세대 번호이고 payload version과 다르다. 독립 root draft 여러 개는 허용하지만 현재 pending/confirmed head는 하나다.

최초 revise 둘이 동시에 (null,0)을 보았어도 UNIQUE row 삽입/잠금 경계 안에서 하나만 head를 만들 수 있다. 경쟁 삽입자는 현재 row를 다시 읽고 기대값이 달라졌으면 ACTION_HEAD_CONFLICT다. 유일키 예외를500으로 흘리거나 head를 마지막 쓰기로 덮지 않는다. 실패한 새 pending/action/audit는 함께 rollback한다.

현재 pending 취소 뒤 head_action_id는 취소된 action ID로 유지하고 revision을 증가시킨다. root draft 취소는 head를 바꾸지 않는다. 다음 명시 준비는 이 ID/revision을 기대값으로 캡처하고 UI revise 성공 시만 교체한다. confirmed 결과는 취소로 초기화하지 않는다.

새 pending에는 prepared_from_action_id와 displaced_head_id를 보존한다. 이전 draft/pending 각각의 superseded_by_action_id는 새 pending을 가리킨다. root_action_id는 준비 출처 root로 유지한다. head의 계보 조회와 root의 출처 조회는 다른 축이며 singular supersedes 필드 하나로 두 관계를 대신하지 않는다. 결정 이력은 [정책 선택](15-policy-options.md)을 따른다.
