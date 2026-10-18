# 결정 기록과 미정 항목

설계 개정2 · 2026-10-16. 아래 확정은 이번 대화에서 채택한 범위다. 미정 값은 구현/문서 인계 전에 구체화하되 임의로 사실처럼 채우지 않는다.

## 확정

| ID | 결정 | 이유·적용 |
|---|---|---|
| D-01 | 교육을 포함한 사내 통합 업무지원 Agent | 문서 연결과 업무 API를 함께 검증 |
| D-02 | 사용자 제공 PDF100=현행91+이전9 | 논리 문서91종, 개정 쌍 고정 |
| D-03 | A 원문 / B Wiki 보조 원문 비교 | 양쪽 최종 근거는 PDF 원문 |
| D-04 | 문서별 권한·과거 시점 지원 | 현재 ACL, PDF·Wiki·이력·캐시까지 적용 |
| D-05 | 업무는 교육 조회·IT 조회/확인 등록 | 문서 범위와 변경 기능 범위를 구분 |
| D-06 | 모듈형 모놀리스·12모듈 | 기존8개 유지+권한/Wiki/검색전략/IT |
| D-07 | FastAPI·PostgreSQL/pgvector·React/TS·Compose | 기존 방향 유지. 공급자는 D-27에 따라 대화 Anthropic, 임베딩·judge Google 두 곳 |
| D-08 | SDK 반복 먼저, LangGraph/MCP는 후속 | 도구/상태 원리부터 검증 |
| D-09 | 평가150, dev50/holdout100 | 유형별 원문 gold 검수·누수 방지 |
| D-10 | PC 우선·기본 모바일 | 기존 화면 구성/시각 원칙 유지 |
| D-11 | 로컬 데모 세션 | 권한 테스트 가능, 실제 SSO는 별도 |
| D-12 | 구현 내부와 모듈 계약 분리 | 검토 단위는 인프라→앱→레이어→모듈/협력 |
| D-13 | 영속 run 만료/복구·메시지 멱등·동일 키 결과 replay | 실패/응답 유실에서 단일 실행 |
| D-14 | Agent draft와 UI pending 분리 | 실패 run이 이전 준비를 취소하지 않음 |
| D-15 | CP-07 원문/교육 receipt 읽기 포트 | 실제 검증 경로와 저장소 소유권 |
| D-16 | 지식 공개 시점과 사건 적용일 분리 | 현행 FAQ의 과거 사례 해설·예정 교육 지원 |
| D-17 | PDF hash/page/quote gold 정본 | 파서 revision 변경과 정답 분리 |
| D-18 | 독립 root draft 여러 개+대화별 head 하나 | 사용자 확인, 입력 출처와 밀려난 head 관계 분리 |
| D-19 | 원규정 공백의 금액/권리/의무 결론 보류 | 사용자 확인, guidance 절차 안내와 구분 |
| D-20 | 최종 근거5개 고정 상한 폐지 | 사용자 요구: 필수 근거 보존, 공통 token 예산·누락 평가 |
| D-21 | 근거 예산은 dev 예산 스윕으로 정하고 회수는 예산 기준 지표로 측정 | 사용자 확인: 공개 연구·실무 조사 반영. Recall@pool/Recall@budget·evidence-in-context·hard negative 오답, packing_order 고정 |
| D-22 | 전체 문맥 기준선만 먼저 계획, 공통 재정렬은 hard negative 오답 확인 시 추가 | 사용자 확인(P-04 B). 기준선은 actor별 token 실측 뒤 한도 안에서만 실행, 재정렬은 별도 비교 ID |
| D-23 | 4차 재검증 기술 보정 | 사용자 요청. 기준선은 평가 전용 strategy·MOD-05.ReadAllowedCorpus·passage 단위 인용, lazy 만료는 head_revision 미증가, 여러 검색의 최종 예산 조립은 MOD-02, CT-06 ToolExecutionInput으로 field_origins/observer 전달, capability 닫힌 목록과 eval_fixture source, support_scopes는 MOD-12 소유 |
| D-24 | 연도 생략 날짜는 시제로 추론해 표시(P-05 B), 티켓 수정 사슬 상한 없음(P-06 A), 표/문장 단위 적용 조건은 모델 판단+측정 후 조건부 열·행 분리(P-07 A) | 사용자 확인. 근거는 [정책 선택](15-policy-options.md) |
| D-25 | 대화(답변) 모델은 A/B·평가 실행을 포함해 Claude Haiku 5.5(`claude-haiku-5-5`), SDK는 Anthropic 공식 Python SDK | 사용자 확인(예산). judge는 D-27로 변경([정책 선택](15-policy-options.md) P-08) |
| D-26 | 백엔드 도구: uv(패키지·잠금), SQLAlchemy 2 + Alembic, psycopg 3, pytest, ruff. 프런트엔드: Vite + React + TypeScript | 사용자 확인. O-03 해소 |
| D-27 | 임베딩은 Google `gemini-embedding-2`(무료 티어부터), judge는 Gemini Flash 계열 무료 티어 | 사용자 확인(예산). 조건: 청크마다 별도 입력으로 임베딩, 차원은 768/1536 중 선택(O-04), 평가 때 호출 한도에 걸리면 유료 전환, 무료 티어 입력은 Google 제품 개선에 쓰이므로 가상 문서에만 사용, judge 모델 ID·날짜는 holdout 전 고정 |
| D-28 | 비동기 서버: FastAPI async 엔드포인트 + SQLAlchemy 2 async + psycopg 3 async, Python 3.13 | 사용자 확인. 모델 응답을 최대60초 기다리는 동안 다른 요청을 처리하고 NFR-03 동시성 테스트를 자연스럽게 하기 위함. 3.14는 라이브러리 지원을 확인하지 않아 보류 |
| D-29 | M2 이후 진행 상황 스트리밍: 같은 메시지 POST에 `Accept: text/event-stream`, 서버가 기록한 단계만 progress로 보내고 답변 본문은 검사·commit 뒤 result로 한 번 | 사용자 확인([정책 선택](15-policy-options.md) P-09 A). 토큰 단위 스트리밍은 권한 재확인·인용 검증 원칙과 충돌해 쓰지 않음 |
| D-30 | 데모 조직·역할·계정: 부서는 등록부 소관(인사팀·IT지원팀(IT운영 포함)·정보보안팀·경영지원팀·재무팀·총무팀)과 열람 부서(영업팀·개발팀). 역할은 employee·dept_head·hr_staff·approver·auditor·it_support·operator(CLI 전용). 시험 계정 emp-sales·emp-dev·head-sales·hr-staff·it-support·ops-admin(웹 로그인 없음). capability는 employee=training.read·knowledge.search·ticket.read_own(준비·제출은 M5), it_support는 +ticket.read_support_scope, operator=ops.* | 사용자 확인(2026-10-17, M3 진행 결정). O-01·O-10의 데모 값. 시험 비밀번호는 seed 파일에 둔다(가상 데모 계정). HR-014의 "평가권자"는 부서장으로 본다(가정) |
| D-31 | 문서 ACL: 기본은 전 문서 audience=authenticated이며 manifest에 "사용자 명시 결정"으로 남긴다. 원문에 열람 제한이 적힌 HR-013·HR-014는 hr_staff·dept_head, CM-093은 dept_head·approver·auditor로 제한. 부서 단위 제한은 시험 전용 가짜 문서로만 시험 | 사용자 확인(2026-10-17). O-02의 ACL 부분 해소. 원문에 근거가 없는 제한을 지어내지 않기 위함 |
| D-32 | 임베딩 차원 1536(`gemini-embedding-2`)으로 시작. 768과 작은 표본에서 비교해 선택 근거로만 기록(평가 결과로 쓰지 않음) | 사용자 확인(2026-10-17). O-04의 차원 부분 해소 |
| D-33 | PDF 파서 pdfplumber(MIT). PyMuPDF(AGPL)는 쓰지 않음. 100개 전에 15~20개 파일럿으로 한국어 추출 확인 | 사용자 확인(2026-10-17). O-05의 파서 선택 해소. OCR·표 복원 한계는 파일럿 보고에 남김 |
| D-34 | P-12는 B(명세대로 CP-07 포트를 MOD-02에 주입, MOD-01의 권한 선필터는 첫 겹으로 유지). P-13은 B(문서 passage는 tool_result로, 검증된 대화 자료는 system에서 빼 현재 사용자 턴 앞의 표시된 자료 블록으로, system에는 규칙만) | 사용자 확인(2026-10-17). O-16·O-17 해소. 근거는 [정책 선택](15-policy-options.md) P-12·P-13 |
| D-35 | M3 진행 규칙: Anthropic 비용 상한은 이번 진행 전체 $1이며 그 안에서는 호출마다 묻지 않음. Gemini는 무료 티어만(유료 필요 시 중단). 단계마다 테스트·lint·검증 에이전트 지적 수정·포트폴리오 갱신 뒤 커밋, push는 마일스톤 끝(SSE 뒤, M3 뒤). 비용 초과·새 정책 결정 필요·보호 파일 접근 필요·명세 충돌 시 중단 | 사용자 확인(2026-10-17) |
| D-36 | P-15 B: available_from = 각 판본 시행일(effective_from) 00:00 KST. 원문 추정이 아니라 가상 회사 설정 값이다. 안내 개정 쌍의 guidance 판본 구간도 같은 규칙(현행 시행일부터, 종전은 현행 시행일까지). manifest 초안의 나머지 제안값(document_role·application_basis·소관 등)은 일괄 승인하고 검사에서 걸리는 것만 고친다 | 사용자 확인(2026-10-18, "그거 다 진행해라": 남은 결정의 추천안 채택). O-02의 공개 시각·검수 방법 해소 |
| D-37 | P-16 B: 첫 모델 응답이 "도구 호출 없음 + 빈 answer"이면 서버가 한 번만 다시 부른다(서버 문구를 붙임, 모델 시도 상한 안). 그 사실을 run 기록에 남긴다. 그 밖의 무효 출력은 명세대로 실패 | 사용자 확인(2026-10-18, "그거 다 진행해라": 남은 결정의 추천안 채택). O-19 해소 |
| D-38 | O-13의 시제·역할 표지 목록은 P-05 보충의 A: 임시 목록(v4)을 확정하고, 평가에서 놓친 표현이 나오면 목록에 더한다. 목록 밖 표현은 되묻는다 | 사용자 확인(2026-10-18, "그거 다 진행해라": 남은 결정의 추천안 채택). O-13의 표지 목록 부분 해소(P-07 hard negative 기준은 남음) |
| D-39 | P-18 B: 여러 사건 중 일부만 날짜를 확인하지 못하면 확인된 사건은 답하고, 확인 못 한 사건의 되묻기 문구(서버 문구)를 답 끝에 붙인다. outcome은 answered 유지 | 사용자 확인(2026-10-18, "그거 다 진행해라": 남은 결정의 추천안 채택). O-21 해소 |
| D-40 | P-19 B: authority_relations·transition_relations의 형식·검사·회수(ExpandTransitionEvidence)와 사건 날짜 여러 개 입력을 구현한다. 값은 개발자가 원문 조항을 근거로 초안을 쓰고(근거 조항 기록) D-36처럼 일괄 승인, 닫힌 값으로 표현할 수 없으면 그 관계를 넣지 않고 보고한다 | 사용자 확인(2026-10-18, "그거 다 진행해라": 남은 결정의 추천안 채택). O-22 해소 |
| D-41 | M3 마무리~M6 진행 규칙(2026-10-18 GOAL): 미정 항목·새 결정은 추천안으로 정하고 D 표·docs/15에 기록(O-11 정식 이름·공개 배포·보존기간만 사용자). 비용 상한 없음(실제 호출 비용은 단계마다 측정·기록). 빈 첫 답 재호출 때 tool_choice=any로 도구 호출 강제(D-37 보완, P-16 C의 일부). 임베딩은 Gemini 무료 티어로 날을 나눠 채우고 그동안 파서·청크·문서 제목을 바꾸지 않음. 150문항은 서브에이전트가 원문만 보고 생성, 다른 에이전트가 원문 대조, 보고서에 "모델 생성 문항" 명시. 단계마다 독립 검증·변이 시험·커밋, push는 마일스톤 끝. D-35의 $1 상한·무료 티어 외 중단 규칙을 대체(무료 티어 규칙은 유지) | 사용자 확인(2026-10-18 /goal) |
| D-42 | M5 티켓 세부값([P-20](15-policy-options.md#p-20) A): pending 필수 필드는 subject·description·request_type·category·target_service·urgent_work(장애면 occurred_at, 긴급이면 urgency_reason 추가), impact_scope·asset_identifier는 선택. 데모 지원 범위는 it-support 계정 → 8개 부서 명시(전사 조회 아님). 회신 수단은 계정별 "사내 메신저 {표시 이름}"(fixture). 직원 역할에 ticket.prepare·ticket.submit. 입력 출처 정규화 목록은 P-20 표. draft 채택은 최종 출력 action_id가 이번 run에서 준비한 draft일 때만 | 추천안 채택(D-41 진행 규칙, 2026-10-18). O-10의 support_department_ids 해소 |
| D-43 | 티켓 준비에서 출처를 확인하지 못한 필드(출처 없음·중복·구간/정규화/값 불일치·미래 발생 시각)는 저장하지 않고 비운 뒤 `rejected_fields`로 알린다(초안 전체를 거절하지 않음). 자유문장 값이 인용 구간 안에 정확히 한 번 있으면 서버가 구간을 그 값으로 좁힌다. 오류 우선순위는 03-errors(소유권 → version·입력 → 성공 replay → 상태 → root 자격) | 추천안 채택(D-41 진행 규칙, 2026-10-18). 실제 모델 smoke에서 출처 하나가 틀리면 재시도가 반복 실패한 것이 근거([P-20](15-policy-options.md#p-20)) |
| D-44 | UI 연결(M6) 전 남은 값: P-10은 A(seed 때 교육 상태 계산 유지, 데모·평가는 fixed_status라 영향 없음), P-11은 A(모델 시간 초과는 MODEL_UPSTREAM_ERROR 유지, 화면 문구 동일), P-14는 C(원문은 바꾸지 않고 공백만 있는 제목·메시지는 422) | 추천안 채택(D-41 진행 규칙, 2026-10-18). O-14·O-15·O-18 해소 |
| D-45 | Wiki 주제·분할·검수([P-21](15-policy-options.md#p-21) A, O-08 해소): 주제 계획은 문서 제목·종류만 보고 모델이 도메인별 초안(needs_review)을 쓰고, 모든 문서가 한 주제 이상에 있는지 검사한 뒤 검수자가 reviewed로 표시한다. page = 주제 × 권한 등급(같은 접근 정책끼리) × (규범 시행 구간 \| 안내 유효 기간). 규범 판본의 시행 시작·끝 날짜마다 page를 나누고, 안내 문서는 규범 구간 page와 따로 둔다(현행 FAQ가 종전 구간 요약에 섞이지 않게). 자동 검사: 주장마다 원문 링크 1개 이상, 링크 라벨이 이 page 입력 passage, 인용이 그 passage의 연속 구간(공백 정규화)과 일치, 4~300자. 하나라도 어긋나면 문제를 알려 주고 1회 재생성, 다시 어긋나면 page를 미게시 항목(problems 기록)으로 둔다. 기여 원문 = page 입력 판본 전체. 공개 날짜가 다른 안내는 page를 나눈다(늦게 공개된 안내 때문에 먼저 공개된 안내까지 과거 지식 시점에서 빠지지 않게). 주제 제목은 page 생성 입력에 넣지 않는다(다른 권한 등급 문서 이름이 섞이지 않게). 원문은 이스케이프해 넣고, 인용은 숫자 중간에서 시작·끝나면 거절한다. 잘린 출력은 형식 문제로 알려 재생성하고, 일시 오류 재시도 1회는 재생성 기회와 따로 센다. 평가 질문·정답은 주제 계획·빌드 입력에 넣지 않는다 | 사용자 확인(2026-10-18 GOAL D-41: 추천안 채택) |
| D-46 | Wiki 탐색 설정(O-06의 Wiki 부분 해소): `wiki-exact-cosine-v1` = 질의 벡터를 A와 공유, 권한·적용 시점(사건 날짜가 page 구간 안, 지식 시점이 기여 원문 공개 이후·안내 유효 기간 안)을 통과한 page 5개를 같은 거리로 고르고, 그 page들의 주장·관계 링크를 모두 펼쳐 중복을 없앤 뒤 raw와 같은 SQL 필터(권한·게시·지식 시점·규범 적용 구간)와 같은 원문 거리로 정렬해 20개. 이후 support_group·경과조항·우선관계는 A와 같다. O-06의 chunk/overlap·거리·후처리는 M3 값(D-32 이후 바꾸지 않음, D-41)으로 고정 | 사용자 확인(D-41 추천안). 후보 수 5·확장 20은 docs/13 초기값 그대로이며 dev에서만 조정한다 |
| D-47 | 검색 전략 선택·기록: 대화 생성 때 서버가 strategy(raw/wiki_assisted)와 strict를 정한다(MOD-01 `ServerOptions`, 평가 포트만 지정, 직원 HTTP 입력 없음, 운영 기본 raw). Wiki snapshot은 run 수락 때 고정한다. 운영 B는 Wiki 미준비·stale·후보 0개면 raw로 fallback하고 effective_strategy=raw·fallback_reason을 남긴다. 엄격 B는 fallback 없이 strict_failure(wiki_not_ready/wiki_stale/no_wiki_candidates)를 남기고 빈 결과를 낸다. 검색 경로(resolution·날짜·요청/실제 전략·이유·실제 실행한 retriever_config_id·Wiki 후보 ID·패킹 전 후보 passage)는 `tool_calls.retrieval_trace`에, 근거 예산 안에 실제로 들어간 passage는 `agent_runs.evidence_trace`에만 저장하고 모델이 보는 도구 결과 형식은 A/B가 같다 | 사용자 확인(D-41 추천안) |
| D-48 | Wiki 의미 충실성 검수는 독립 검수 에이전트(모델)가 page마다 주장과 인용 원문을 대조해 approved/rejected를 기록하고(reviewer_kind=model), 보고서에 "모델 검수"라고 밝힌다. 사람 표본 검수는 하지 않았다고 한계로 적는다. 게시는 검수가 끝난(pending 없음) build의 승인 page만 묶는다 | 사용자 확인(D-41 추천안: 사람 검수자가 없는 포트폴리오 환경). 링크 자동 검사는 의미 검수를 대체하지 않는다(MOD-10) |
| D-49 | 비교 실행 설정([P-22](15-policy-options.md#p-22) A, O-07 해소): 예산 스윕 후보 4000·8000·12000 token(초기값 + 더 큰 값 2개), packing_order는 현재 구현 `group-relevance-v1`(그룹은 MOD-11 대표 거리 순, 그룹 안 원문 순서, 한 그룹은 끊지 않음, A/B 동일). dev50을 A/B × 3예산으로 1회씩 실행하고(모델 온도는 공급자 기본, 반복 1회), 답변 규칙 정답률이 더 오르지 않거나 hard negative 인용 오답이 늘기 시작하는 가장 작은 예산을 holdout 전에 동결한다. 동률이면 작은 값. judge 순서 seed 20261018. 모델 입력 한도(Haiku 5.5)는 12000 예산에서도 여유가 있다(문맥+시스템+도구 정의 합계를 실행 기록의 입력 token으로 확인) | 사용자 확인(D-41 추천안). 반복 1회는 비용·무료 티어 한도 때문이며 분산을 측정하지 못한다는 한계로 보고한다 |
| D-50 | 전체 문맥 기준선 실행(O-12의 기준선 부분 해소): `full_context_reference`(평가 포트·eval_fixture actor만)로 구현한다. 날짜 해석·LookupApplicableBasis·경과조항·우선관계는 A와 같고, 후보 단계만 그 사건 날짜에 허용된 passage 전체(A와 같은 SQL 필터·원문 거리 순, 그룹 안 원문 순서)로 바꾼다. 예산은 150,000 token(계정별 허용 원문 추정 11.9만 token 이하가 모두 들어가는 값, 모델 입력 한도는 첫 실제 호출의 입력 token으로 확인). 실행 가능성은 dev 첫 문항의 실제 호출로 판정하고, 모델 호출 20초·run 60초 상한을 넘으면 infeasible로 기록하고 상한을 바꾸지 않는다. 가능하면 dev50·holdout100에 A/B와 같은 조건으로 1회 실행한다. 재정렬(reranker) 추가 판단은 O-12에 남긴다 | 사용자 확인(D-41 추천안) |
| D-51 | 규칙 정답 정의([P-23](15-policy-options.md#p-23) A): answered는 outcome=answered, gold 근거 하나 이상 인용, gold 사실의 두 자리 이상 숫자·날짜·금액을 모두 말함(날짜는 표기와 무관하게 월-일, 'N만 원'은 원 단위로 맞춤, 조항 번호 제외), 금지 숫자(두 자리 이상) 없음, 별도 그룹 hard negative 인용 없음, 권한 누출 없음. 근거 집합을 모두 인용하면 rule_complete로 따로 센다. needs_clarification은 outcome 일치, insufficient_evidence는 기권+금지 숫자 없음. 실행 오류·전략 불일치·strict 실패는 오답으로 분모에 남긴다. 같은 그룹 hard negative는 그것을 인용하고 틀린 경우만 센다. 누출은 인용·문맥·패킹 전 후보의 파일과 답 속 제한 문서 제목을 보고, 판정할 수 없는 문서는 unscorable로 따로 센다. judge 익명 ID는 (seed, 문항, 설정, 판정 입력)의 hash다. 집계·쌍 비교는 설정(전략×엄격×예산)별이며 중복·누락을 보고한다. holdout은 `eval-freeze`로 기록한 예산으로만 실행한다 | 사용자 확인(D-41 추천안). 평가 도구 독립 검증 P1 2건(인용 하나로 정답 처리, judge ID가 위치 기반)을 재현해 고치며 정함. 한 자리 수 사실은 judge 판정에 맡긴다는 한계를 보고서에 적는다 |

## 초기 기본 정책 — 설정으로 명시

전체60초·모델6시도·도구4제안·추가읽기retry1, 로컬 세션 수명 8시간(SESSION_TTL_S), 최종 원문 개수 고정 상한 없음/초기4000token, draft/action 만료5분. 주 실험 A/B는 동일 임베딩/거리의 exact vector이며 A 원문20/B Wiki5→원문20에서 공통 최종 선택한다. 온라인 추가 LLM·B만의hybrid·reranker는 주 실험에서 제외한다. 4000token은 dev 예산 스윕의 시작점이다. 이 값의 변경은 테스트·실험 config 버전에 남긴다.

## 아직 정할 것

| ID | 항목 | 정하는 시점·주체 |
|---|---|---|
| O-01 | 조직·역할·부서는 D-30으로 데모 값 확정. 남은 것: 정책/예외·우선관계 | 사용자가 PDF 제작/인계할 때 |
| O-02 | (ACL은 D-31로 확정) 실제 판본 번호·시행/종료일·문서 종류·available_from/document_role/application_basis·guidance 판본 구간·IT-038/055 개정/시행일 확인, transition_relations의 사건 조건 매핑(예: CM-092 "상신"을 어느 닫힌 값으로 볼지)과 검수 주체 | 공개 시각·검수 방법은 D-36으로 해소(2026-10-18). 경과조항 사건 매핑은 D-40 |
| O-03 | D-26으로 해소. 남은 것: 각 도구의 버전 고정(uv 잠금 파일에 기록) | M0 |
| O-04 | 모델·공급자는 D-25/D-27로 확정. 남은 것: 차원은 D-32로 1536 시작(768 비교 기록), 한국어 품질 확인(dev 질문으로 비교 후보 하나와 대조, 예: 로컬 `voyage-4-nano`), judge의 정확한 Gemini 모델 ID, 공급자별 사용 한도 설정 | 차원·한국어 확인은 M3 색인 전. 차원이 pgvector 컬럼에 고정되므로 바꾸면 재색인. judge ID는 holdout 전 |
| O-05 | 파서는 D-33(pdfplumber)으로 확정. 남은 것: OCR 지원·한계·표 복원·파일 상한 | M3 파일럿 검증 |
| O-06 | D-46으로 해소(Wiki 탐색 `wiki-exact-cosine-v1`, chunk/거리는 M3 값 고정) | 2026-10-18 |
| O-07 | D-49로 해소(예산 4000·8000·12000, group-relevance-v1, dev 1회 실행 후 동결, [P-22](15-policy-options.md#p-22)) | 2026-10-18 |
| O-08 | D-45·D-48로 해소(주제 계획 초안+검수, 권한 등급·시행 구간 분할, 자동 대조+모델 의미 검수, [P-21](15-policy-options.md#p-21)) | 2026-10-18 |
| O-09 | 정답 근거·150문항 실물·검수자 | PDF 검수 후 |
| O-10 | D-30·D-42로 해소(it-support → 8개 부서 명시 범위) | 2026-10-18 |
| O-11 | 정식 이름·공개 배포·데이터 보존기간 | 최종 데모/공개 전 |
| O-12 | 방향은 D-22로 확정. actor별 허용 원문 token은 [최종 보고서 6절](report/final-evaluation.md)에 기록(약 10.8만~11.9만, 추정식 기준, 2026-10-18). 기준선 실행 방식은 D-50. 남은 것: 실제 호출로 본 실행 가능 여부(D-50 절차), 재정렬 추가를 판단할 hard negative 오답 기준, 추가 시 후보 수·한국어 reranker 모델·지연 허용치 | 기준선은 M4 비교 설계 전, 재정렬은 dev 예산 스윕 결과 확인 후 사용자와 확인([정책 선택 P-04](15-policy-options.md)) |
| O-13 | 방향은 D-24로 확정. 시제 판별 표현 목록은 D-38로 확정(v4, [P-05 보충](15-policy-options.md#p-05-o13)). 남은 것: P-07에서 C로 넘어갈 hard negative 오답 기준(O-12와 같은 판단) | M3 날짜 검색 구현 전, dev 예산 스윕 결과 확인 후 사용자와 확인([정책 선택](15-policy-options.md)) |
| O-14 | D-44로 해소(seed 때 계산 유지, [P-10](15-policy-options.md)) | 2026-10-18 |
| O-15 | D-44로 해소(MODEL_UPSTREAM_ERROR 유지, [P-11](15-policy-options.md)) | 2026-10-18 |
| O-16 | D-34로 해소(P-12 B) | M3 사건 날짜 대조 설계 전 사용자와 확인([정책 선택 P-12](15-policy-options.md)) |
| O-17 | D-34로 해소(P-13 B) | M3 원문 주입·T-34 설계 전 사용자와 확인([정책 선택 P-13](15-policy-options.md)) |
| O-20 | 명세대로 해소(사건 날짜는 사용자 문장 인용을 서버가 대조·정규화, [P-17](15-policy-options.md#p-17)) | 2026-10-18 구현 |
| O-21 | D-39로 해소(확인 못 한 사건의 되묻기 문구를 서버가 붙임, [P-18](15-policy-options.md#p-18)) | 2026-10-18 |
| O-22 | D-40으로 해소(형식·검사·회수·복수 사건 구현, 값은 원문 근거 초안 일괄 승인, [P-19](15-policy-options.md#p-19)) | 2026-10-18 |
| O-19 | D-37로 해소(첫 응답이 도구 없음 + 빈 답이면 1회 재호출, [P-16](15-policy-options.md#p-16)) | 2026-10-18 |
| O-18 | D-44로 해소(공백만 있는 값 422, 원문 보존, [P-14](15-policy-options.md)) | 2026-10-18 |

## 이번 변경에서 하지 않은 일

PDF/규정 본문·실제 manifest·평가 문항·백엔드·위키·DB 및 서버 테스트를 생성하지 않았다. 정적 시안 회귀 테스트는 별도로 저장했다. 2026-10-17 추가: 사용자 PDF100개/248쪽을 수령했고 실제 식별·사건 날짜·접수 필드를 보정했다. 기존 정적 시안에는 통합 업무 흐름을 추가했으며 실제 앱/백엔드 구현은 보류했다. 성능·정답률·비용·실제 공고 마감일은 새로 주장하지 않는다.

## 데모 지원 담당 범위

일반 직원은 본인 티켓만, support 역할은 manifest/fixture의 support_department_ids에 속한 요청자 티켓만 읽는다. 전사 지원 범위는 별도 명시 capability가 있을 때만 부여하며 빈 목록은 거부다. 공개 시안은 가상 단일 사용자이고 실제 권한 구현이 아니다. 실제 계정/부서 ID·비밀 값은 O-10에서 구현 전 확정한다.

선택지·trade-off와 사용자 답변의 반영은 [3차 정책 결정](15-policy-options.md)에 보존한다. 원문에서 알 수 없는 metadata/회사 정책 값은 이 결정으로 임의 생성하지 않는다.
