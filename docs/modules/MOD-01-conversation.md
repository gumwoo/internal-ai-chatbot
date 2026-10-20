# MOD-01 대화·실행 관리


## 책임과 소유권

conversations/messages/message_receipts/agent_runs/tool_calls/tool_result_receipts의 단일 쓰기 소유자. 대화 소유권·동시 실행·수락/완료/만료·검증된 상태·이력의 재노출을 담당한다. 모델 호출·검색·티켓 생성은 소유하지 않는다.

## 공개 작업

| 작업 | 입력 | 출력·조건 |
|---|---|---|
| Create/List/GetConversation | 현재 actor·표시 정보, 신뢰된 server_options | 소유 대화만, 전략은 생성 시 고정; 직원 HTTP는 전략 입력 불가 |
| AcceptMessage | actor·conversation·본문1~4000자·Idempotency-Key | 만료 회수 후 메시지+receipt+run+활성 소유권 원자 저장 또는 기존 run replay |
| RunConversation | 수락한 run | 재검증된 CT-10과 저장된 사용자 응답 |
| ListMessages/GetRun | actor·소유 ID | 현재 가시성을 확인한 이력·진단 요약 |
| Finalize/Fail/Expire | 활성 run·결과 | 답변·상태·run 종료·활성 해제 원자 저장 |
| ReadUserEvidence / ReadTrainingEvidence | CP-07 actor·conversation·run·근원 ref | 본인 user 원문 구간/실제 교육 receipt 대조, 앱 주입 읽기 포트 |
| RecordTrainingResult | CT-11의 실제 MOD-04 결과·run/ordinal | 교육 결과 receipt 저장, 실패 시 실행 중단 |
| RecordToolCall | CT-11 이벤트 | run/ordinal 기준 필수 기록 |
| RecoverExpiredRuns | 서버 현재 시각·선택 대화/run | deadline 지난 running 종료·해제; 시작/조회/수락에 사용 |
| CheckPrepare/CheckActionOrigin | CP-06의 actor·conversation·run/action | 현재 run 자격·채택된 원본 action 읽기 판정 |
| StreamRunProgress | actor·소유 run | M2 이후. 새로 수락한 실행에만 채널을 연다(같은 키 재전송은 JSON). accepted는 MOD-01이, 나머지는 CT-11 RecordStage로 기록된 단계만 progress로 보내고, deadline 뒤·종료 저장 뒤의 단계는 버린다. Finalize 뒤 같은 최종 응답을 result로 한 번 보냄. 내용·인자·결과 수 미포함 |

## 협력

MOD-09로 세션·현재 actor를 확인한다. MOD-11에서 검색 모드·snapshot을 고정하고 MOD-02에 CT-02/03과 observer를 전달한다. 문서 참조는 MOD-11, 티켓/준비 참조는 MOD-12의 가시성 계약으로 검사한다. 이 검사는 모델 문맥 작성 전, 이력 HTTP 반환 전, 최종 응답 전달 전 수행한다.

전략은 대화 생성 시, snapshot/config는 각 run 수락 시 고정한다. APP-04는 신뢰된 모듈 포트의 server_options로 A/B를 선택한다. CP-06은 읽기 포트로 앱이 MOD-12에 주입하며 그 모듈에 저장소 쓰기 권한을 주지 않는다. [실행 생명주기](../contracts/01-run-lifecycle.md)가 복구·멱등 재전송·CT-10 변환의 기준이다.

## 불변식·실패

- 한 대화에 활성 run은 하나. 동시 수락은 409, 다른 대화는 독립 실행.
- 네트워크/모델 대기 중 DB 잠금 유지 금지. 만료 run이 늦게 돌아와도 완료를 덮어쓰지 못한다.
- 최종 commit 실패 시 성공 응답 금지. 티켓 확정은 독립 작업이므로 대화 실패로 티켓을 취소했다고 주장하지 않는다.
- 제한 자원에 의존한 이전 답변은 본문·인용·참조 전체를 가리고 그 본문을 모델 문맥에서 제외한다. 일반 안내만 남긴다.
- 문서 ACL revision/역할이 달라지면 현재 권한을 다시 평가한다. snapshot 고정은 권한 고정이 아니다.
- 실패한 실행의 상태 후보를 저장하지 않는다. pending action 참조만으로 생성 완료 표시 금지.

## 검토·테스트

T-01 대화 격리, T-02 동시/재시작·lazy 만료, T-03 기록 실패·로그 정보 최소화, T-04 권한 철회 후 이력·완료·캐시 차단, T-05 멱등 재전송. FR-04/06, NFR-02~06 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 계약 보정

CP-07 ConversationEvidenceReader 구현을 소유한다. ReadUserEvidence는 본인/run 문맥 user 원문만 반환하고 ReadTrainingEvidence는 CT-11로 저장된 실제 교육 receipt를 대조한다.202 이후 동일 키 POST replay로 최종 응답을 제공한다.

## 2026-10-18 M3 구현 메모

- 수락 시 대화 전략(raw)·게시 snapshot·actor의 knowledge.search로 지식 기능을 켜고 run에 고정한다.
- 답변의 dependency_ids에는 이번 문맥의 교육 ID·문서 키(`doc:키`)와, 이력으로 다시 넣은 assistant 메시지의 의존 합집합을 함께 저장한다(CT-03). 권한을 잃으면 그 답과 그 답을 이어받은 답이 함께 가려진다.
- 최종 응답(JSON·SSE·재전송) 직전에 MOD-09 ReloadActor로 actor를 다시 읽는다. 세션 회수·비활성이면 가린다.
- 사용자 입력의 서버 표시 문자열("[대화 자료]", "[사용자 질문]")은 모델 문맥에 넣을 때 괄호를 바꿔 서버 블록과 섞이지 않게 한다(MOD-02).
- M5(2026-10-18): 메시지에 action_preview(채택한 root draft)와 ticket_refs를 저장한다. 의존 자원에 `ticket:{id}`(모델 문맥에 들어간 티켓)를 넣고, 이력·응답 직전에 MOD-12 CheckTicketVisibility(CP-05)로 다시 판정해 볼 수 없으면 가린다. CP-06 `DbRunEligibility`(check_prepare: 본인 running·deadline 전, adopted: completed이고 그 답의 action_preview가 root draft)와 CP-07 `read_user_messages`(본인 대화·그 run의 질문과 이력 창의 user 메시지만)를 MOD-12에 주입한다. HistoryMessage·ExecutionContext에 message ID를 싣는다.

## 구현 메모(M4 검색 전략, 2026-10-18)

- 목록·상세의 title은 저장된 제목이 없으면 첫 사용자 질문 앞 40자로 만든다(저장하지 않는 표시 값, 사용자 질문은 가리지 않으므로 권한 재검증 대상이 아니다).
- `create_conversation(actor, title, server_options=ServerOptions(strategy, strict))`. 직원 HTTP는 server_options를 넘기지 않는다(본문의 strategy 같은 값은 무시). 평가 포트(APP-04)만 raw/wiki_assisted·엄격 모드를 고른다. `conversations.retrieval_strict` 칸.
- run 수락 때 corpus snapshot과(B 대화면) Wiki snapshot을 고정해 `agent_runs.retrieval_context`(strategy·wiki_snapshot_id·strict)에 남긴다. 실행 도중 새 Wiki가 게시돼도 그 run은 바뀌지 않는다(T-27).
