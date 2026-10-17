# 실제 PDF 수령 후 설계 보정

2026-10-16 · 서비스 구현은 보류하고 설계와 클릭 가능한 로컬 시안만 수정한다. 원본 PDF는 변경하지 않는다.

## 수령과 식별

100파일·248쪽, 현행91파일·종전9파일의 열기/텍스트 추출을 확인했다. 대표 페이지와 주요 규정은 별도 검토했으며 전체 의미·모순 검수가 끝난 것은 아니다. [수령 목록](02-received-register.md)은 관찰한 메타데이터를 담고 운영 manifest/승인된 ACL과 구분한다.

원래 파일 `ED-030_외부교육비_지원_규정.pdf`와 PDF 번호 `GW-ED-030`을 그대로 보존한다. 시스템 물리 ID는 PDF-030, 논리 문서 키는 DOC-030이다. 종전 GW-ED-031도 DOC-030에 연결한다. 파일을 이름 변경하거나 다시 만들지 않는다. 문서 영역만 보고 소관 부서·허용 역할을 자동 추정하지 않는다.

## 규정 적용일

수락 시각·게시/시행일·업무 사건 날짜를 구분한다.

| 문서군 | 적용 판본의 기준 | 원문 |
|---|---|---|
| 교육 수료·출석 | 교육회차 시작일 | ED-021 제12/20조, ED-034 제12조 |
| 외부교육비 | 교육 시작일 | ED-030 제5조/유의사항, ED-031 제3조 |
| 출장비 | 출장 시작일 | GA-081 제4조, GA-082 제2조 |
| 전자결재 | 최종 결재일·원문의 경과조건 | CM-092 제2/9조, CM-091과 대조 |
| 종전 휴가·근무 | 신청·처리일 또는 근무일, 질문 사건에 따라 확인 | HR-005 유의사항, HR-003 유의사항 |
| 사건 없는 일반 규정 | 질문의 기준일, 없으면 수락일 | CM-095 제6조 |

9월29일 출발·10월2일 복귀한 출장에는 종전 GA-082를 적용한다. 교육9월30일 시작·출장10월2일 시작이면 교육비/출장비 판본이 다를 수 있다(GA-090 1~2쪽).

CT-13의 as_of_date는 실제 적용 날짜다. date_basis는 current/explicit_date/training_start/trip_start/approval_date/request_date/work_date/processing_date다. current는 사건 없는 일반 조회에서만 수락일을 기본으로 쓴다. 날짜 근원과 추가 확인은 [사건 날짜 계약](../contracts/02-business-dates.md)이 기준이다. 날짜가 빠진 사건을 오늘로 대체하지 않고 서로 다른 사건은 별도로 검색한다.

MOD-02가 사용자 진술의 사건을 구분하고 CT-03 business_dates에 event_key/type/date·원본 메시지·구간을 보관한다. 서버 SearchRequest로 business_dates/question_context를 MOD-11에 전달하고, MOD-11이 application_basis와 날짜 근원을 검증해 CT-14 resolved/needs_clarification/unsupported을 반환한다. 결과와 인용에는 실제 date_basis와 적용 날짜를 기록한다. PDF의 사건 적용 규칙은 서버 메타데이터로 검수하며 모델이 임의 변경하지 못한다.

manifest에는 application_basis와 근거 조항을 추가한다. 복합 FAQ는 각 사건의 원규정으로 검증한다. “2026.09.30.까지”인 종전본은 시스템 종료 제외 규칙의 effective_to=2026-10-01로 변환하고 원래 표기도 보존한다. 과거 조회에도 현재 ACL을 적용한다.

## IT 접수 필드

IT-037 1쪽을 반영한다. category(서비스 영역)와 request_type(요청 유형)을 분리한다.

| 필드 | 의미·검증 |
|---|---|
| subject/description | 제목1~120자, 사용자 설명/현상1~4000자 |
| request_type | incident/service_request/inquiry |
| category | account/network/device/software/other |
| target_service | 서비스명1~120자 |
| occurred_at | 장애 발생 시각 ISO8601 KST. 장애는 필수, 모호하면 되묻기 |
| impact_scope | 확인된 영향 범위1~500자. 미확인 범위는 추정하지 않음 |
| urgent_work/urgency_reason | 긴급 업무 여부, true면 사유1~500자. 자동 우선순위 지정 아님 |
| asset_identifier | 자산번호, 미보유/미확인은 null과 설명. 가상 번호 생성 금지 |
| requester/reply_channel | 서버 actor와 사내 회신 수단. 모델의 임의 사용자/연락처 금지 |

장애 이외 요청은 occurred_at=null을 허용한다. 필요한 정보가 없으면 draft의 missing_fields에 남기고 UI/추가 질문으로 확인한 뒤 pending을 만든다. 서버 프로필의 회신 수단이 없으면 준비 오류다. preview와 실제 ticket은 동일 필드와 불변 payload/hash를 쓴다. UI 수정은 인증된 revise API로 새 action을 만들고 이전 pending을 superseded로 바꾼다. 자유문장은 사용자 입력 근원을 검증하며 검색 본문을 자동 전재하지 않는다. 확인·경쟁·멱등성·lazy 만료는 [티켓 계약](../14-ticket-workflow.md)을 따른다. 전체 배정/종결 업무는 추가하지 않는다.

## 시안의 세 흐름

| 흐름 | 예시 | 원문 |
|---|---|---|
| 규정·출처 | 외부교육비 한도·예외 | ED-030 1쪽 제5~6조 |
| 과거 규정 | 9월29일 시작한 출장 숙박비, 현재 기준과 비교 | GA-082 1쪽 제2/5조, GA-081 2쪽 제9조 |
| IT 지원 | VPN 증상·서비스·발생 시각·영향·긴급 여부→내용 확인→등록 예시 | IT-037 1쪽, IT-045 |

시안은 원문을 사람이 확인해 만든 고정 응답이다. 실제 검색/AI/인증/DB/접수는 없고 시안의 접수번호도 가상이다. 일반 직원 화면에 A/B 전환·Wiki 운영 기능을 추가하지 않는다.

## 평가·파싱 보정

GA-090처럼 FAQ 한 개에 이미 종합 정답이 있으면 해당 태그로 구분한다. 실제 다문서 회수 문항과 섞어 성능을 부풀리지 않으며 A/B의 corpus는 동일하게 유지한다. FAQ 질문/답변·표 헤더/행이 페이지를 넘는 경우(GA-090 1~2쪽, IT-037 2~3쪽), 의미 단위를 연결하고 모든 원문 페이지/span을 보존한다.

문서 판본의 시행일만으로 비교표의 모든 숫자를 해당 사건의 정답으로 취급하지 않는다. GA-082의 현행 비교열·ED-032의 종전 과정·ED-030의 종전 지급액 누계를 [조건 보존 기준](../contracts/02-business-dates.md)에 따라 검증한다. IT-038/055의 개정일7/1과 시행일10/1은 서로 다른 종류의 날짜로 보존하며 차이만으로 모순 판정을 하지 않는다.

날짜 해석 보정: 문서 공개 시점 knowledge_as_of와 규범 적용 사건 as_of_date는 별개다. GA-090 등 guidance는 사건 뒤 발행돼도 현재 지식으로 과거 사례를 해설할 수 있다. IT-041/SEC-062의 처리일은 processing_date다. 세부 필터는 [사건 날짜 계약](../contracts/02-business-dates.md)을 따른다.
