# 통합 업무지원 시안 문서화 확인

2026-10-17 · ordinary extension / compare-and-preserve.

**판정: 기존 시각 시스템을 보존했다.** 새 시각 세계나 시스템 재정의가 아닌, 기존 정적 업무 도구의 기능·상태 확장으로 확인했다. 이 인계에서는 이 결과 파일만 작성했다.

## 확인한 근거

- [방향 계약](../surfaces/prototypes-education-agent-index-html.md), [PRODUCT.md](../../PRODUCT.md), [DESIGN.md](../../DESIGN.md), [sidecar](../design.json)를 완성된 [HTML](../../prototypes/education-agent/index.html)·[CSS](../../prototypes/education-agent/styles.css)·[JavaScript](../../prototypes/education-agent/app.js)와 대조했다.
- [README](../../prototypes/education-agent/README.md), [사용 순서](../../docs/ui/02-prototype-walkthrough.md), [PDF 반영 보정](../../docs/corpus/03-received-pdf-adjustments.md), [검증 기록](integrated-checks.md), [최종 리뷰](integrated-reviewer-result.md)를 읽었다.
- 기존 [교육 첫 화면](desktop-home.jpg)과 최종 [통합 첫 화면](integrated-home-desktop.jpg), [IT 입력 화면](integrated-ticket-form-desktop.jpg), [모바일 원문 상세](integrated-policy-mobile.jpg)를 직접 열어 비교했다. 나머지 캡처의 검증은 위 검증 기록과 리뷰의 범위로 인용한다. 브라우저·탐지기를 실행하지 않았다.

## 보존 결과

13개 기본 색 토큰, 한국어 시스템 산세리프, 14px 본문과 답변 행간, 6px 동작·12px 입력 모서리, 그림자 없는 톤·얇은 선 구성을 유지한다. 대화 목록/중앙 대화/선택적 상세와 224px/348px 기본 폭, 1550·1199·767px 반응형 분기, 모바일 전체 너비 상세도 기존 기준과 일치한다. 청색 포커스와 움직임 감소 조건을 적용한 180ms 상세 전환도 유지한다.

새 IT 필드·확인 동작은 기존 입력 테두리·모서리·청색 동작을 이어받고, 규정 비교는 기존 표·원문 상세 안에 배치했다. 장식 KPI·그라데이션·카드 격자·새 서체는 추가되지 않았다. 상단 바로가기는 검토용으로 설명하며 제품 내비게이션의 영구 기준으로 확대하지 않았다.

## 기존 문서의 차이

- DESIGN.md와 sidecar는 교육 시안 제목 및 기존 7개 컴포넌트 중심이다. 새 IT 입력·확인 패턴의 목록은 담지 않으며 이번 확장 문서와 사용 순서가 해당 맥락을 보완한다. 새 패턴을 전역 규칙으로 편입하지 않았다.
- 기존 DESIGN.md의 YAML 구간 앞에 적용 범위 인용문이 있다. document.md의 frontmatter-first 형식과 다른 기존 문서 구조다. 이번 인계에서 수정하지 않았다.
- 11px 보조 문구는 기존 구현에도 있고 DESIGN.md가 일반 본문 기준으로 규범화하지 않는다. 이를 새로운 디자인 승인으로 해석하지 않았다. 확인한 비교 범위에서 별도의 기존 시각 드리프트는 발견하지 못했다.

## 범위와 인계

최종 리뷰의 `ship`은 장애 외 요청의 발생 시각 필수 조건 수정에 대한 verdict pass다. 이를 전체 표면이나 운영 서비스의 승인으로 확대하지 않는다. 소스에서도 발생 시각의 최초 렌더와 유형 변경 조건이 모두 `incident`에만 필수를 적용함을 확인했다. 실행 검증 38개 assertion 및 11개 재캡처 결과는 검증 기록에 근거하며, 이 문서화 인계에서 재실행하지 않았다.

고정 응답·PDF 원문 링크·탭 메모리의 가상 접수 범위다. 실제 AI·RAG·인증/ACL·DB·티켓 생성은 검증 대상이 아니다. 구현 소스·서비스·PDF 본문과 두 시각 기준 파일은 이 인계에서 변경하지 않았다.
