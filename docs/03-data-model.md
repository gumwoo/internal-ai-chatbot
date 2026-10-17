# 데이터 모델·소유권

논리 엔터티와 불변식 명세다. SQL 타입·ORM·파일 배치는 구현 단계에 결정한다. 다른 모듈의 테이블을 직접 수정하지 않는다.

## 엔터티

| 소유 모듈 | 엔터티 | 관계·핵심 필드 |
|---|---|---|
| MOD-09 | users/departments/memberships/sessions | 현재 역할·부서·capability, session 만료/회수, auth_revision |
| MOD-01 | conversations | owner, 생성 시 서버 검색 전략, active_run, schema v2 업무 상태 |
| MOD-01 | messages | conversation, role, 본문·outcome, 자원 dependency IDs, citations/action refs |
| MOD-01 | message_receipts | actor+conversation+key 유일, content hash, user_message/run ID; 대화 보존 기간 유지 |
| MOD-01 | tool_result_receipts | run/ordinal/resource ID/starts_at/hash, 교육 API 실제 결과 및 선택 user 메시지; CP-07 읽기 |
| MOD-01 | agent_runs/tool_calls | request/run, accepted_at/deadline_at, 고정 snapshot/config, running/completed/failed/expired·usage·오류·ordinal/attempt |
| MOD-04 | trainings | UUID/code, title/description, starts/ends, location/status |
| MOD-05 | logical_documents/resource_acl | document_key, 담당 부서·현재 access_policy/revision |
| MOD-05 | document_editions/source_files | key+업무 version, document_role(normative/guidance), available_from, application_basis/basis_evidence, guidance_valid_from/to, transition_relations, 규범 적용 유효기간·대체 관계·상태, PDF hash·안전 저장 ID |
| MOD-05 | parsed_artifacts/pages/blocks | edition+parser revision, 물리 페이지·구간·추출/OCR 검수 |
| MOD-05 | chunks/embeddings | 원문 block/span refs, chunk config, 모델·차원·벡터 |
| MOD-05 | corpus_snapshots/memberships | 불변 edition/artifact 집합·manifest/config hash·게시 포인터 |
| MOD-10 | wiki_builds/snapshots/pages | source corpus, 모델/프롬프트/config, 상태·비용·게시 포인터 |
| MOD-10 | wiki_claims/source_links | page의 주장·판본·원문 block/span, 시행 구간·기여 원문 집합 |
| MOD-10 | wiki_embeddings | wiki page/snapshot, 모델·차원·벡터·탐색 config |
| MOD-12 | tickets | requester, subject/description/category와 CT-16 접수 필드, status=open, created_at |
| MOD-12 | ticket_actions | actor/conversation/source_run/source_ordinal/expected_head_id/expected_head_revision, root_action_id/prepared_from_action_id/displaced_head_id/superseded_by_action_id, payload/hash/version/field_origins, 만료·상태·ticket_id |
| MOD-12 | ticket_action_heads | conversation_id UNIQUE, actor_id, head_action_id(nullable), head_revision; 최초 삽입 경쟁·취소 후 ID 유지는14번 계약 |
| MOD-12 | ticket_prepare_receipts | (run,ordinal) 유일, payload_hash/draft_id; root prepare만 적용, revision 제외 |
| MOD-12 | idempotency_records/ticket_audit | actor+key, 작업·action/payload hash, 수정/확정 결과; 사건·시각·주체 |
| MOD-12 | support_scopes | support 역할 사용자·support_department_ids·revision; 빈 목록은 거부. 값은 fixture/운영 CLI로만 적재하며 실제 ID는 O-10 |

평가 설정·정답·보고서는 APP-04 파일 산출물로 시작한다. 온라인 업무 DB에 별도 평가 관리 시스템을 먼저 만들지 않는다. MOD-06의 체크포인트·파싱 보고서는 staging 산출물이며 게시 데이터와 구분한다.

## 핵심 불변식

1. logical document 91개와 PDF100개를 같은 개념으로 세지 않는다. key+업무version 유일, physical source ID 유일.
2. 같은 판본의 PDF hash는 불변이다. PDF를 바꾸면 새 판본을 검수한다. 파서 재실행은 새 artifact revision이다.
3. normative 게시 판본의 규범 시행 구간은 같은 key 안에서 겹치지 않는다. guidance의 공개 가능 시각은 사건 적용 구간이 아니다. 종료 제외·KST 기준이다.
4. corpus/Wiki snapshot membership은 불변이다. 새 활성 포인터는 준비 완료 후 전환한다. 실시간 ACL/철회는 snapshot보다 우선한다.
5. chunks와 Wiki claims는 원문 span을 참조한다. gold의 정본은 PDF SHA-256/물리 page/정확 인용문/동일 문구 발생 순번·선택 bbox다. block/span은 parser revision별 파생 alignment이며 정답 식별자가 아니다.
6. 한 conversation에 활성 run 하나. messages/run 종료/업무 상태 변경은 MOD-01의 최종 원자 작업이다.
7. action 하나당 ticket 최대 하나. `(actor,key)` 멱등키 유일, root prepare receipt의 `(run,ordinal)`만 유일이며 다른 payload 재사용은409다. revision은 별도 ID/UI 멱등키를 쓴다. action 소비·ticket·응답·감사는 함께 commit한다.
8. usage 미확인은 null, 기록 없는 토큰을0으로 채우지 않는다. citations의 표시 필드는 원문 DTO로 생성한다.
9. MOD-01의 메시지 receipt는 MOD-12의 수정/확인 멱등키와 별도 저장소·범위다. 재전송은 새 실행이나 새 action을 만들지 않는다.
10. 티켓 자유문장은 검증된 사용자 입력/서버 템플릿만 허용한다. PDF·Wiki·assistant 답변을 지원 담당자용 본문으로 자동 전재하지 않는다. 세부 [티켓 계약](14-ticket-workflow.md)을 따른다.

## 이력과 가시성

저장된 과거 assistant 본문이 현재 열람 권한을 보장하지 않는다. dependency 목록은 최종 인용뿐 아니라 모델에 제공된 모든 원문·사용한 티켓·준비 action·재사용한 메시지의 의존성까지 포함한다. MOD-01이 모델 문맥/이력/완료 직전 재검사하고 제한 메시지를 가린다. 감사 원본 접근은 운영 권한과 분리한다. 사용자 입력에 있던 자유 텍스트는 자원 참조와 별도 취급하며 검색 결과에서 회수된 제한 본문을 재주입하지 않는다.

## 삭제·보존

개발 초기에는 게시/withdrawn/retired 상태로 참조를 보존한다. 물리 삭제·보존기간은 운영 정책을 정한 뒤 수행한다. 과거 평가 snapshot 재현은 현재 접근권한을 우회하는 공개 경로가 아니다. 이전 SQL 예제는 [구현 참고](implementation-notes/README.md)의 역사 자료다.
