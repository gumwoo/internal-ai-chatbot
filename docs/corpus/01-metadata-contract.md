# PDF 메타데이터·제작 인계 계약

## 역할과 입력

사용자는 PDF 100개와 가상 회사의 규칙·조직·권한·판본 정보를 제공한다. 개발자는 누락/모순을 보고하고 색인·검색을 구현한다. 이 설계가 휴가 일수·지원 금액·결재자·실제 법규를 정하지 않는다.

PDF 입력 위치는 [data/raw/pdfs](../../data/raw/pdfs/README.md). manifest는 향후 `data/raw/document-manifest.json`으로 제공/정리한다. 이번 변경은 실제 manifest를 생성하지 않는다.

## 파일별 필수 manifest 필드

| 필드 | 의미·검증 |
|---|---|
| source_file_id | PDF-001~PDF-100, 물리 파일 고유 ID |
| document_key | DOC-번호, [개정 쌍](00-document-inventory.md)의 이전/현행은 동일 키 |
| version | 작성자가 정하는 불변 업무 판본 식별값; 키+version 유일 |
| filename | 입력 루트 기준 PDF 상대 경로; 상위 경로·URL·중복 매핑 거절 |
| title/domain/document_type | 제목·6개 업무 영역·정책/규정/매뉴얼/FAQ/공지/체크리스트 등 |
| source_document_number | 원래 PDF 번호(GW-ED-030 등), 시스템/논리 ID와 별도 보존 |
| application_basis / basis_evidence | general_reference/training_start/trip_start/approval_date/request_date/work_date/processing_date/per_claim; 근거 조항 필수, 대응표는 검색 조립 계약 |
| document_role | normative 또는 guidance, 규정 효력과 안내의 공개 시점을 구분 |
| guidance_valid_from / guidance_valid_to | 안내 판본 자체의 지식 시점 유효 구간(종료 제외), 개정 쌍 중복/공백 검수 |
| transition_relations | 반대편 판본 경과조항, 검수 후만 회수. 기본 판본 항목에 `{from_source_file_id(이 파일), to_source_file_id(같은 문서 키의 반대편 판본), clause_anchor(조항 제목), application_basis, event_conditions:[{event(사건 기준 닫힌 값), compare(before/on_or_after), date}], authority_relation(current_rules_apply/past_reference_current_recheck), basis_evidence(원문 조항)}` (D-40) |
| available_from | 검수된 공개 가능 시각; 미확인값 자동 추정 금지 |
| effective_from | normative 규칙의 사건 적용 시작 날짜(포함); guidance의 표지 날짜는 별도 원문 메타데이터 |
| effective_to | 종료 날짜, 제외; 현행 종료 미정이면 null |
| supersedes_source_file_id | 이 판본이 대체한 이전 파일 ID, 없으면 null |
| owning_department | 가상 조직에 정의된 소유 부서 |
| classification | 취급 등급 레이블; 이것만으로 권한 부여하지 않음 |
| access_policy | 명시적 읽기 허용 범위, 현재 정책 적용; 누락/알 수 없음은 거부 |
| related_document_keys | 관련 논리 문서 키 목록, 링크 실재 여부 검증 |
| authority_relations | 위임·예외·상위 규정 등 의미가 명시된 관계; 없으면 빈 목록. `{kind(defers_to/precedes/limited_by), target_document_key, target_code, page, quote(근거 문장)}`. 본문에 다른 문서 번호와 관계 표현(따른다·우선 확인·범위 안에서만)이 함께 적힌 문장만(D-40) |
| review_status | 본문·메타데이터 검수 상태; 미검수 게시 금지 |

수령 PDF에는 담당 부서·등급이 모두 표시되어 있지 않다. PDF의 /Author도100개 모두 ‘가온웍스 인사팀’이므로 실제 문서 소유자나 ACL의 근원으로 쓰지 않는다. 운영 manifest는 작성자 확인·검수로 채우고 미확인 ACL은 거부한다. PDF 본문에서 확인한 ID·판본·시행일·관계는 manifest와 대조하며 차이는 자동 추정으로 통과시키지 않는다. 개정일·시행일은 분리한다. 수령한 `ED-030_문서명.pdf`를 보존하고 PDF-030/DOC-030/GW-ED-030을 매핑한다. [수령 목록](02-received-register.md)과 [실제 수령 보정](03-received-pdf-adjustments.md)을 따른다.

## 접근 정책 의미

문서의 현재 ACL은 논리 키 수준으로 적용하며 판본의 추가 제한은 이를 더 좁힐 수 있다. 예시 정책 형태는 `audience=authenticated` 또는 `audience=restricted`와 허용 user/department/role ID 집합이다. restricted는 허용 집합의 합집합을 기본으로 평가하고, required_capabilities는 별도로 모두 요구한다. 정책 내부 의미를 선언하지 않은 임의 AND/OR 해석은 금지한다. 명시적 허용 대상이 없는 restricted는 거부한다.

현재 계정·역할·자원 ACL로 판정하며 과거 시행일은 권한의 시간 여행을 허용하지 않는다. 문서 ID·제목·검색 건수·Wiki 요약·PDF 링크·과거 대화 모두 같은 경계를 지킨다. 외부 응답은 미존재/접근 불가를 구분하지 않는다.

## 판본·시점·우선순위

- 업무 판본과 색인 artifact revision을 분리한다. parser/chunk/embedding 변경은 업무 version 변경이 아니다.
- 같은 논리 규범의 normative published 판본 적용 구간은 겹치지 않는다. 구버전도 published로 남기고 종료일을 둔다.
- normative는 knowledge_as_of까지 공개됐고 사건 날짜 t에서 `effective_from <= t < effective_to`인 판본을 사용한다. guidance는 available_from/현재 ACL로 먼저 고르고 문장별 사건 조건·연결 원규정으로 검증한다. 안내의 발행일이 과거 사건 뒤라는 이유만으로 제외하지 않는다. 종료 null은 열린 구간. 공백은 근거 없음이며 가장 가까운 미래/과거 판본으로 채우지 않는다.
- 사건 없는 현재 질문만 run 수락일을 기본으로 쓴다. 교육/출장 등은 원문이 정한 사건 날짜를 우선하고 누락 시 되묻는다. 종료일 포함 표기는 종료 제외 날짜로 변환하고 원문 값을 보존한다. 미래 지식 조회는 제외하며 현재 공개된 규정으로90일 이내 예정 사건은 허용한다. 개정 전후 비교는 두 날짜를 명시하고 각각 검색한다.
- 91현행+9이전은 검수 기준일에 유효기간을 검사한 파일 수다. 업로드 시각·수정 시각을 시행일로 쓰지 않는다.
- FAQ·매뉴얼은 규정을 임의 변경할 수 없고 공지가 예외를 만든다면 위임·적용 구간을 명시한다. 우선순위 정보가 없는 충돌은 양쪽 근거와 불확실성을 보고한다.
- 구버전/현행 차이처럼 의도된 변경과 우연한 모순을 검수표에서 구분한다.

## 원문 provenance

수집기는 immutable PDF SHA-256·저장 ID, parser/revision, OCR 사용 여부, 물리 페이지(1부터), 인쇄 페이지 표기(선택), page 내 block ID·Unicode offset·bbox(가능하면)를 보존한다. 청크는 한 개 이상의 원문 block/span을 참조한다. 머리말 제거·공백 정리·표 변환 이후에도 원문 대응을 복원할 수 있어야 한다.

표에는 제목·열 헤더·행·주석을 함께 보존한다. 스캔/복잡한 표는 추출 샘플을 검수하고 실패 시 needs_review로 남긴다. 페이지 수는 제작 참고이며 지원 한계·파일/페이지/시간 상한은 파서 설정에 별도 기록한다. PDF에서 추출한 지시문은 도구 권한이나 시스템 프롬프트로 승격하지 않는다.

## 게시 단위

draft 준비 → 검수 완료 → 불변 corpus snapshot 게시. snapshot에는 포함 source/edition/artifact ID와 manifest/parser/chunk/embedding hash를 담는다. 파일럿 subset은 ID·개수를 명시하고 최종100개 release와 구분한다. 유효하지 않은 파일을 제외했으면 제외 내역을 보고한다. 준비 실패 시 현재 게시본은 유지한다. 정책 회수/문서 철회는 과거 snapshot 접근에도 즉시 재검사한다.

## PDF 수령 후 체크리스트

1. 100개 고유 파일, 91개 논리 키, 9개 개정 쌍 확인.
2. 제목/버전/시행일/부서/ACL과 PDF 본문 대조.
3. 가상 조직·용어·조건·예외·문서 우선순위 충돌 검수.
4. 원문 페이지·표·조항 추출 샘플 및 실패 목록 검수.
5. 파일럿 원문 검색과 권한/시점 테스트 후 전체 게시.
6. 평가 정답 근거를 원문으로 확정한 뒤 Wiki 및 비교 실험 진행.

IT-045/046 등 guidance 개정 쌍은 available_from만으로 둘 다 회수하지 않는다. 안내 판본 선택·규범 공백 시 결론 보류·경과조항 확장은 [검색 조립](../contracts/05-retrieval-assembly.md)을 따른다. available_from/document_role/application_basis 및 IT-038/055의 개정일과 시행일 해석은 O-02에서 사용자 원문/작성 의도 확인 후 manifest에 기록한다.
