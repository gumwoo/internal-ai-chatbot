# MOD-12 IT 지원 티켓


## 책임과 소유권

tickets/ticket_actions/ticket_action_heads/ticket_prepare_receipts/idempotency_records/ticket_audit/support_scopes를 소유한다. support_scopes 조회 판정은 MOD-09의 현재 역할·capability(ticket.read_support_scope/ticket.read_all) 확인 뒤에 적용한다. 본인/담당 범위 조회와 등록 준비·수정 재준비·확인·취소를 담당한다. 실제 계정 복구·VPN 변경·담당자 자동 배정·종결 워크플로는 제외한다.

## 공개 작업

ListTickets/GetTicket → 현재 권한의 CT-16 목록/상세. PrepareTicket(actor,conversation,run,ordinal,fields,field_origins) → draft preview(missing_fields 허용, head 불변). ReviseAction(actor,id,version,fields,key) → 새 pending preview. GetAction → lazy 만료 후 현재 상태/기존 결과. ConfirmAction(actor,id,version,key) → 실제 ticket. CancelAction → 취소 상태. CheckTicketVisibility → 참조의 현재 판정.

## 도구/HTTP 구분

모델 도구는 list/get/최초prepare만이다. 수정 재준비·확인·취소는 인증된 화면 HTTP다. MOD-09로 capability·현재 역할을 재검사하고 주입된 CP-06 읽기 포트로 원본 run 자격을 확인한다. requester는 현재 actor로 서버가 정한다. 직원은 본인 티켓, 지정 지원 역할은 허용된 담당 범위만 조회한다. 존재하지 않거나 접근 불가하면 동일404. 수정 endpoint는 채택된 completed run의 미만료 draft 또는 현재 head pending에서만 새 action을 만든다.

## 접수 필드

IT-037의 요청 유형·대상 서비스·발생 시각·영향·긴급 여부·자산 식별을 CT-16에 포함한다. 서버 프로필의 요청자/회신 수단을 사용하고, 빠진 필수 정보는 draft에 null로 보존하고 UI/추가 질문으로 확보한 뒤 pending을 만든다. [수령 보정](../corpus/03-received-pdf-adjustments.md)의 필드 표가 기준이다.

## 상태·원자성

- 준비는 CT-16 불변 payload/version과 actor·conversation·run을 저장하며 티켓은 생성하지 않는다. root prepare receipt의 같은 run/ordinal·같은 payload만 같은 draft를 돌려준다. 다른 payload는409이며 revision은 이 유일키 대상이 아니다.
- draft/pending/superseded/confirmed/cancelled/expired. 초기 유효시간5분(서버 설정). Agent draft는 이전 pending에 영향이 없고 UI revise commit만 이전 pending을 superseded로 바꾼다.
- 확인에서 action 소유권·capability를 먼저 확인한 뒤 version·만료·멱등키를 검증한다. action소비+티켓생성+멱등응답+감사를 한 짧은 트랜잭션으로 처리한다.
- 동일 action 확인은 키가 달라도 기존 티켓으로 수렴한다. 동일 키·다른 action/payload는409. 확인 후 응답 유실에도 GET action으로 확인한다.
- 취소/만료 action은 티켓을 생성할 수 없다. 불확실한 네트워크 결과를 새 키의 신규 등록으로 자동 재시도하지 않는다.
- MOD-01 대화 저장에 직접 쓰지 않는다. 생성 결과와 감사의 기준은 이 모듈이다.

첫 MVP의 한 대화는 티켓 한 건의 action 계보를 다룬다. head 직렬화·이전 pending 교체 범위·상태별 HTTP·user field_origins·수정/확인 경쟁은 [티켓 흐름](../14-ticket-workflow.md)을 단일 기준으로 따른다. confirmed 뒤 별도 신규 건은 새 대화다.

## 실패·검토

필드 오류·권한 철회·만료·버전 불일치·동시 확인·DB 실패를 각각 검증한다. T-30 조회 범위, T-31 준비/미확인 무생성, T-32 멱등/동시 확인, T-33 유실/만료/원자 실패. [티켓 상세](../14-ticket-workflow.md). FR-14/15 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## CP-07 협력

APP-02가 MOD-01의 ConversationEvidenceReader 어댑터를 주입한다. PrepareTicket은 ReadUserEvidence로 본인/run 문맥 user 원문 구간과 field_origins를 대조한다. CP-06만으로 원문 검증을 대신하지 않는다. draft의 expected_head_id와 head 직렬화, superseded 응답은 [티켓 계약](../14-ticket-workflow.md)이 기준이다.

독립 root draft 여러 개·대화별 head 하나다. prepared_from_action_id와 displaced_head_id를 분리하고 conversation_id UNIQUE/head_revision으로 최초 생성 경쟁까지 처리한다. cancel 후 head ID를 유지한다. 자세한 검사 순서와 오류 details는 티켓/오류 계약을 따른다.

## 구현 메모(M5, 2026-10-18)

- 패키지 `agent/modules/it_support`(tables·contracts·service), 마이그레이션 0008. HTTP는 `agent/app/tickets.py`.
- revise·confirm·cancel은 `ticket_action_heads`(conversation_id PK) 행을 INSERT … ON CONFLICT DO NOTHING 뒤 SELECT … FOR UPDATE로 잠근 트랜잭션에서 상태 검사·새 action·head 교체·감사·멱등 기록을 함께 commit한다. 같은 키 동시 요청의 유일키 충돌은 먼저 commit된 결과로 replay한다.
- 조회 범위: 본인(ticket.read_own) ∪ 지원 범위 부서 요청자(ticket.read_support_scope + support_scopes) ∪ 전사(ticket.read_all). 티켓에는 확인 시점의 요청자 부서를 저장한다. 미존재·불허는 같은 404.
- 만료는 lazy(TTL 5분, 같은 clock). head_revision은 성공한 revise·confirm·현재 pending cancel마다만 증가.
- 필수 필드·지원 범위·회신 수단·출처 정규화는 D-42([P-20](../15-policy-options.md#p-20)).
