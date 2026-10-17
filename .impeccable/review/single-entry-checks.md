# 첫 화면 단일 진입 시안 검증

2026-10-17. 사용자 피드백: 검토용 상단 항목·상태 선택이 필요하지 않으므로 첫 화면에서 시작하도록 정리한다. 정적 HTML/CSS/JS와 사용 문서만 변경한다.

## 변경과 실행 확인

- 상단 바로가기·상태 선택 DOM/CSS/이벤트를 제거했다. 첫 화면 추천 질문·직접 입력·최근 대화·새 대화는 유지한다.
- 화면 높이를100dvh, 모바일 메뉴/배경의 시작점을0으로 맞췄다. 색·서체·주요 배치와 원문 상세·요청 확인 흐름은 유지한다.
- Node 구문 검사 통과. 제거한 선택자·이벤트 이름이 시안 소스에 남지 않음을 검색했다(rg의 일치 없음은 exit1).
- 별도 Playwright CLI에서 추천 질문→규정/원문, 과거 기준/현행 비교, IT 입력/수정/취소, 교육 일정, 직접 입력→0건 응답을 확인했다.
- 모바일 메뉴/배경 상단0, 메뉴/원문 닫기의 포커스 복원, 첫 화면→요청 준비→명시 확인→DEMO 번호를 확인했다.
- 1440×900,390×844,1280×720에서 가로 넘침과 삭제한 막대 자리의 공백이 없음을 assert했다. 앱 JavaScript pageerror 없음. favicon404는 기존 정적 서버의 별도 요청이다.
- 자동화 초기에 모바일의 숨겨진 새 대화 버튼과 같은 이름의 대화 이력 때문에 locator를 수정했다. UI를 추가 수정한 것은 아니며 아래 캡처는 수정된 검증의 성공 실행으로 모두 덮어썼다.

## 최종 캡처

모두 저장 후 각각 열어 대상과 정상 렌더를 확인했다.

- [desktop home](single-entry-home-desktop.jpg) ·1440×900
- [desktop source](single-entry-policy-desktop.jpg) ·1440×900
- [mobile home](single-entry-home-mobile.jpg) ·390×844
- [mobile source](single-entry-policy-mobile.jpg) ·390×844
- [mobile request](single-entry-ticket-mobile.jpg) ·390px 전체 문서
- [1280 home](single-entry-home-user-1280.jpg) ·1280×720

## 탐지와 범위

[이번 수정의 단회 탐지](single-entry-detector.json)는 기존11px 보조 문구 경고만 반환했다. 기존 시각 시스템의 보조 정보에 한정하고 본문 크기는 유지한다. 실제 AI·RAG·인증·DB·티켓 API 및 예외 처리의 운영 검증은 이번 범위가 아니다. 이전 integrated-* 검증 기록과 캡처는 상단 검토 도구가 있던 이전 버전의 기록이다.
