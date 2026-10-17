# MOD-06 PDF 수집·색인 준비


## 책임과 소유권

입력 파일·manifest 검증, PDF 추출/OCR 상태, 정규화·구간 보존·분할·임베딩 준비·작업 보고서를 담당한다. 지식 테이블의 쓰기 소유자가 아니다. 원본 PDF와 사내 규정 본문을 생성하는 기능도 아니다.

## 공개 작업

ValidateInput(directory,manifest,limits) → 오류/누락/100파일 구성 보고서. PrepareEdition(file,metadata,parser/chunk/embedding_config) → CT-09. PrepareCorpus(manifest,selected_ids) → 준비 집합. RequestPublication(prepared) → MOD-05 게시 결과.

## 처리 계약

- 사용자 파일명과 source_file_id는 manifest로 대응한다. 경로는 입력 루트 내부의 PDF만 허용하며 외부 URL·상위 경로를 거절한다.
- PDF hash·물리 페이지·텍스트 block·선택 bbox·Unicode offset·추출 방식·파서 revision을 보존한다.
- 표의 제목/열/주석, 조항의 조건/예외가 잘리지 않게 준비·검수한다. 반복 머리말 제거도 원문 대응 정보를 잃지 않는다.
- 손상/암호화/스캔/빈 추출을 정상 텍스트로 게시하지 않는다. OCR은 지원할 경우 출처·품질 검수와 함께 기록한다.
- 같은 업무 판본의 추출 설정 변경은 새 artifact revision이다. 업무 버전·시행일은 운영자 메타데이터로만 바꾼다.
- 임베딩 준비·재시도는 MOD-06 소유, 저장 commit은 MOD-05. 네트워크 대기 중 게시 트랜잭션 금지.
- 15~20파일 파일럿은 명시된 부분 snapshot이다. 최종100파일 게시 검수와 구분한다.

## 실패·검토

부분 실패·재시도 횟수·비용·검수 필요 구간을 보고한다. 입력/설정 hash가 같으면 준비 산출물 재사용 가능하되 이미 게시된 원본을 덮어쓰지 않는다. T-13 추출, T-14 게시 실패, T-18 100/91/9 및 manifest 검증. FR-09, NFR-09/10 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.
