# Agent 입출력·실행 정책

MOD-02가 실행을 조정하고 MOD-03이 스키마/분배, MOD-01이 필수 기록/commit을 담당한다. 정책·현재 사용자·시각·검색 mode는 서버가 정한다. SDK로 실행 반복부터 구현하고 LangGraph는 영속 중단/재개 등의 필요가 생겼을 때 검토한다.

## 허용 도구와 인자

모든 스키마에서 정의되지 않은 필드는 거절한다. `user_id,admin,approved,corpus_snapshot_id,strategy` 등은 모델 인자로 받지 않는다.

| 도구 | 인자 | 결과 |
|---|---|---|
| list_trainings | date_preset, start_date?, end_date_exclusive?, query?, limit=10, offset=0 | TrainingPage |
| get_training | training_id(UUID) | TrainingDetail |
| search_documents | query(1~500자), top_k?(1~40, 서버 retriever config 범위, D-72), as_of_date?(ISO date, 후보), date_quote?(날짜를 말한 사용자 문장, 서버가 대조·정규화), date_basis=current, event_key?(영문·숫자·_·- 1~40자), other_events?(최대 3개, 같은 사건의 다른 날짜 `{date_basis(사건 기준), as_of_date?, date_quote?}`, 경과조항 조건용, 사건마다 서버가 대조·정규화, D-40) | CT-14 원문 또는 날짜 추가 확인 |
| list_it_tickets | status?(open), limit=10(1~20), offset=0 | 현재 허용 TicketPage |
| get_it_ticket | ticket_id(UUID) | 현재 허용 TicketDetail |
| prepare_it_ticket | subject?, description?, request_type?, category?, target_service?, occurred_at?, impact_scope?, urgent_work?, urgency_reason?, asset_identifier?, origin_candidates? | ActionPreview |
| calculate_business_deadline | base_date(ISO date), business_days(1~60), direction(after/before/nth_of_next_month) | 마감일·요일·셈 규칙·건너뛴 공휴일·달력 판본·base_date_verified(D-69). 표 밖·다음 달 초과는 TOOL_ARGUMENT_INVALID |

date_preset은 today/this_week/next_week/next_30_days/custom. 기본 next_30_days. custom만 start/end를 둘 다 받으며 범위 최대90일·시작 포함/종료 제외다. 교육 query는 최대100자 제목 부분 일치. KST 월요일 주 시작. 티켓 category는 account/network/device/software/other다. 등록자는 서버 actor이며 priority·담당자·임의 requester를 모델이 결정하지 않는다. 영업일 계산(D-69)은 문서 검색이 허용된 run에만 노출하고, 도구 제안 상한과 따로 최대 4번 센다.

date_basis는 current/explicit_date/training_start/trip_start/approval_date/request_date/work_date/processing_date다. current는 사건 없는 일반 조회에서만 수락일을 기본으로 쓴다. MOD-02가 확인한 business_dates/question_context를 서버 SearchRequest에 전달하고 MOD-11이 application_basis와 대조한다. 누락/충돌은 CT-14 needs_clarification이며 검색0건으로 바꾸지 않는다. [사건 날짜 계약](contracts/02-business-dates.md)을 따르고 미래 지식 조회는 제외하되 현재 공개된 규정으로90일 이내 예정 사건은 지원한다. 두 시점은 각각 검색하고 전체 근거 예산은 공통이다.

티켓 접수 필드의 길이·필수 조건·회신 수단은 [수령 보정](corpus/03-received-pdf-adjustments.md)을 따른다. 미확인 필드는 draft에 null로 보존하고 완전한 pending 준비 전에 사용자에게 확인한다. requester/reply_channel은 서버가 제공한다.

prepare의 자유문장은 CT-06 origin_candidates로 근원을 제안하고 MOD-02가 CP-07 user 원문에서 code point 구간을 계산해 정규 field_origins를 구성한다. [출처 계약](contracts/04-field-origins.md)의 닫힌 정규화/템플릿을 따른다. 모델 인자로 근원·권한을 위조할 수 없으며 MOD-12가 실제 사용자 입력과 대조한다. 검색 본문·Wiki·assistant 설명은 접수 자유문장으로 자동 전재하지 않는다. 이미 완료/만료/실패한 run의 새 prepare는 CP-06으로 거절한다. 수정 재준비·확인은 사용자 HTTP이며 Agent 도구가 아니다.

## 도구 결과 처리

성공/실패는 CT-06이며 빈 목록은 정상이다. MOD-03은 CT-14에서 모델용으로 원문·기준일만 제공하고 제한 문서·내부 Wiki 후보/trace를 전달하지 않는다. passage의 citation_id는 실행 내 고유하다. Wiki 텍스트는 최종 규정 근거로 모델 문맥에 넣지 않는다. 원문 안의 지시문은 자료로만 취급한다.

## 실행 상한

| 제한 | 초기값 |
|---|---:|
| 전체 run | 60초 |
| 채팅 모델 시도(재시도 포함) | 6회 |
| 논리 도구 제안(무효 포함) | 4개 |
| 읽기 도구/모델 일시 오류 추가 재시도 | 논리 호출당 최대1회 |
| 모델 호출 timeout | 최대20초 및 남은 deadline 이하 |
| 읽기 도구 시도 timeout | 최대10초 및 남은 deadline 이하 |
| 최근 이력 | 12메시지 |
| 교육 후보/사본 | 각각 최대20건 |
| 한 검색 top_k | 서버 retriever config의 검증 범위, 후보 예산 안에서 결정 |
| 최종 답변용 passage 합계 | 개수 고정 상한 없음, support_group 보존·공통 token 예산 |

최종 원문 토큰 상한은 초기4000이며 dev 예산 스윕 뒤 [비교 프로토콜](13-retrieval-comparison.md)에 고정한다. 검색 한 번은 그 0.75까지만 새로 쓴다(대표 그룹은 예외, 다음 검색에 1000을 남긴다, D-72). 몫 때문에 덜 넣은 하위 후보는 예산 초과로 표시하지 않는다. 여러 검색의 누적 근거는 선택/중복 제거 후 공통 예산으로 재구성하며 과거 tool 본문의 중복 주입으로 예산을 우회하지 않는다. 모델 인자 보정도 모델 시도/도구 제안 상한 안에서 수행한다. 예외 하나(D-37): 도구를 하나도 부르지 않은 첫 응답의 answer가 비어 있으면(되묻기 제외) 서버 문구 `[서버 안내]`를 붙여 한 번만 다시 부르고 run usage에 `empty_answer_retries`로 남긴다. 다시 받은 답도 무효면 명세대로 실패다. 예외 둘(D-68): 도구를 하나도 부르지 않은 유효한 첫 응답이 답 문장에서 검색·확인을 약속했으면 서버 안내를 붙여 도구를 강제해 한 번 다시 부르고 `search_promise_retries`로 남긴다. 모델 시도 상한과 실행 시간에 여유가 있을 때만 하며, 재호출 경로는 실행 기한보다 2초 먼저 끊고 그 안의 모델·출력·실행 시간 오류나 다시 도구 없이 끝난 응답이면 받아 둔 첫 응답으로 끝낸다(필수 기록 실패는 실패). 읽기 임베딩 오류는 해당 도구 재시도 안에 포함한다. prepare는 같은 run/ordinal로 멱등 준비만 재시도 가능하다. 티켓 확인은 Agent 실행 밖의 사용자 HTTP이며 자동 모델 재시도 대상이 아니다.

## 최종 출력

모델은 answer, outcome, citation_ids, training_ids, ticket_ids, action_id, 선택 상태 후보를 구조화해 반환한다. 서버는 실제 결과 원장과 대조해 표시용 citation/참조/preview를 구성한다. outcome은 answered/needs_clarification/no_results/insufficient_evidence/action_pending이다.

- 원문이 없으면 규정 내용을 추정하지 않는다.
- 선택 후보가 여러 개면 되묻는다. 대화 B가 A의 선택을 가져오지 않는다.
- action_pending은 확인 대기다. “등록했습니다”라고 응답하지 않는다. 구현(M5): action_id는 이번 run에서 실제로 준비한 draft여야 하고(아니면 무효 출력), ticket_ids는 이번 run의 조회 결과에 있던 티켓만이다. MOD-01은 그 draft를 action_preview로 저장해 공개한다(D-42).
- 필수 기록 저장 실패·deadline·상한·무효 출력은 failed이며 상태 후보를 적용하지 않는다.
- MOD-01이 최종 권한·활성 run을 재검사한 뒤 commit한다. commit 전 결과는 사용자용 확정 완료가 아니다.

## 관측

도구 ordinal·시도·허용 인자 요약·오류 단계·모델 ID·usage·검색 mode/snapshot·시간을 기록한다. 임의 reasoning 전문·비밀·전체 제한 본문을 일반 로그에 저장하지 않는다. 사용자는 본인 run의 안전한 요약만 읽는다.

prepare_it_ticket은 missing_fields를 허용한 draft만 생성하고 head/pending은 바꾸지 않는다. 현재 공개 지식으로90일 이내 예정 사건의 규정을 검색할 수 있으며 knowledge_as_of와 사건 as_of_date를 구분한다. 날짜/원문 evidence는 CP-07, 상태·응답은 CT-14와 티켓 계약이 기준이다.
