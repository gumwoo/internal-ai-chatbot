---
version: 1
slug: "prototypes-education-agent-index-html"
primary_target: "prototypes/education-agent/index.html"
related_targets: ["prototypes/education-agent/styles.css","prototypes/education-agent/app.js"]
---

# 통합 업무지원 시안 확장

Operate · 기존 시각 시스템과 구성을 유지하는 기능/상태 확장이다. 사용자는 서비스 코드는 보류하고 HTML/CSS/JS 시안 수정만 명시 허용했다. 별도 재디자인·새 콘셉트·이미지 생성은 하지 않는다.

## Direction contract

**THESIS:** 질문의 답변·적용 사건 날짜·원문 근거·업무 접수 상태를 대화 흐름에서 구분한다.

**OWN-WORLD:** 기존 밝은 업무 도구. 흰 작업 영역, 옅은 회청색 탐색/상세, 절제한 청색, 기존 한국어 산세리프·여백·얇은 선을 유지한다. 카드 격자·그라데이션·장식 KPI를 추가하지 않는다.

**STORY:** 규정 질문→원문/PDF 확인. 9월 출장→종전/현재 판본 비교. VPN 요청→정보 입력→확인→가상 접수. 기존 교육 조회도 유지한다.

**FIRST VIEWPORT:** 왼쪽 대화 목록·중앙 대화/입력·선택적 오른쪽 근거/요청 상세. 첫 화면은 세 핵심 예시와 교육 조회 연결을 제시한다. 사용자의 후속 요청에 따라 시안용 상단 탭·상태 선택창을 제거했다. 첫 화면의 추천 질문이나 직접 입력, 최근 대화로 흐름을 이어간다.

**SIGNATURE INTERACTION:** 인용은 문서번호·판본·PDF 페이지로 연결한다. 과거 출장에는 복귀일이 아닌 출발일을 보여준다. IT 요청은 preview에서 미접수임을 표시하고 명시 확인 뒤 DEMO-IT 번호를 보여준다. 수정·취소·만료·응답 재확인을 구분한다.

2026-10-17 사용자 승인 보정: 교육비9월 후속 질문을 날짜 확인으로 연결하고, 출발일/지역을 질문에 명시하며 답변에 없는 복귀일을 추가하지 않는다. 입력 경계 토큰 input-border를 #75899b로 추가해 식별 대비를 높인다. 첫 화면·색/서체/배치와 수동 상태 메뉴 제거는 유지한다. DESIGN.md와 sidecar의 관련 토큰/컴포넌트만 이 승인 변경에 맞춘다.

**MOTION:** 기존 상세 등장 전환만 유지한다. 요청 대기는 로컬 예시이고 실제 도구 단계/스트리밍으로 표현하지 않는다.

**FORM:** 수락한 기존 구성에 대한 code-led extension. 승인된 이미지 comp나 새로운 QUALITY BAR 보드는 없다. 기존 DESIGN.md·이전 교육 캡처를 시각 참고로 사용한다. 모바일은 대화 목록 메뉴·전체 너비 상세·포커스 복원을 유지한다.

**FINISH:** 현재 소스의 동작/캡처 검증과 별도 finish review, 문서화 확인으로 종료한다. 정적 시안 범위의 판정만 보고한다.

## 콘텐츠와 경계

사용자가 제공한100개/248쪽 PDF 중 ED-030, GA-081/082, IT-037/045, ED-021의 확인된 구간을 고정 예시에 사용한다. PDF 원본은 변경하지 않는다. 시안 날짜는2026-10-16 등을 재현용으로 고정한다. 실제 AI·자동 검색·인증/ACL 집행·DB·티켓 생성은 없다. 위키/A/B 선택기를 일반 직원 화면에 넣지 않는다.

[화면 요구사항](../../docs/ui/01-screen-proposal.md), [사용 순서](../../docs/ui/02-prototype-walkthrough.md), [PDF 설계 보정](../../docs/corpus/03-received-pdf-adjustments.md)을 따른다.
