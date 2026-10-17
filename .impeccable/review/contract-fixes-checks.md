# 검토 의견 반영 확인

2026-10-17. 사용자 승인 범위: 실행 복구/멱등 접수, 티켓 수정과 입력 출처, 사건 날짜 전달, 개발 단계·수령 상태, A/B 검색 조건, 시안2개 버그와 입력 대비. 실제 backend나 PDF 본문을 구현/변경하지 않았다.

## 설계 검사

- 새 기준: docs/contracts/01-run-lifecycle.md, 02-business-dates.md. 기존 CT-01~16·모듈12개·테스트35개 체계는 유지한다.
- 공통 계약/API/소유 모듈/협력/데이터/단계/테스트/수령 안내를 함께 수정했다. 메시지 receipt와 티켓 멱등키는 소유권을 구분한다.
- 티켓의 최초 Agent 준비→편집 revise→새 preview→명시 confirm을 연결하고, 응답 유실·계보 조회·같은 키 replay·상태별 응답·run 자격을 명시했다.
- A/B는 동일 벡터 채널, 후보20/Wiki5→확장20/최종5passage·4000token 시작 설정이다. dev 조정과 holdout 동결, 일반화 한계를 적었다.
- Python 정적 검사: Markdown52개, 로컬 링크203개 모두 유효. JSON fence·코드 fence 정상. 모듈12/공통 계약16/테스트35 확인. PDF파일100개 유지.
- DESIGN.md의14개 색 토큰과 CSS가 일치하고 sidecar schema2/컴포넌트7개를 확인했다. 실제 DB·트랜잭션·ACL·복구·검색 성능 테스트가 아니다.

## 실행 시안 검사

Node --check 통과. 별도 Playwright CLI의27개 assertion 통과, 앱 pageerror 없음. 최초 favicon404는 기존 정적 서버의 별도 요청이다.

- 같은 교육비 대화의 ‘9월에 시작한 교육도 같은 기준이야?’는 날짜 확인이며 교육 일정 표가 아니다. 새 대화의 같은 지시어는 대상 확인이다.
- 9월29일 출발·수도권을 질문에 포함하고 복귀일을 답변에 추가하지 않는다. 날짜/지역이 모호한 출장 질문은 추가 확인이다.
- 종전8만원/현행12만원 비교와 원본 PDF200·%PDF 반환을 확인했다.
- 문의의 발생 시각 선택 여부가 수정 후에도 유지되며, preview 미접수·취소·모바일 명시 확인·중복 클릭 방지를 확인했다.
- compositor 및 form input/select/textarea의 실제 computed border는rgb(117,137,155). 흰 바탕 대비3.6157:1, 보조 바탕 대비3.4260:1이다. 비활성 필드는 별도 상태다.
- 1440×900/1280×720/390×844에서 가로 넘침과 상단 막대 자리 공백이 없다. 첫 화면·대화·상세 구성을 유지한다.

## 캡처

8개 모두 개별로 열어 정상 화면·대상·내용을 확인했다. 대화 스크롤의 마지막 답변/폼 입력부는 해당 검증 단계에서 보이는 위치이며 페이지는 상단이다.

- [desktop home](contract-fixes-home-desktop.jpg)
- [desktop follow-up](contract-fixes-followup-desktop.jpg)
- [desktop historical source](contract-fixes-history-desktop.jpg)
- [desktop request fields](contract-fixes-ticket-form-desktop.jpg)
- [mobile home](contract-fixes-home-mobile.jpg)
- [mobile follow-up](contract-fixes-followup-mobile.jpg)
- [mobile confirmation](contract-fixes-ticket-mobile.jpg)
- [user1280 home](contract-fixes-home-user-1280.jpg)

## 탐지·경계

[단회 탐지](contract-fixes-detector.json)는 기존11px 보조 문구 경고만 반환했다. 신규 본문을 작은 보조 글자로 만들지 않았으며 좁은 승인 범위에서 시각 재설계를 하지 않았다. 날짜 분기는 고정 시안이며 실제 NLU 검증이 아니다. 로컬 ticket 편집은 새 서버 API의 구현/보안 검증이 아니다.
