> 적용 범위: 기존 정적 시안의 시각 기준이다. 통합 업무지원의 기능 요구사항은 [UI 명세](docs/ui/01-screen-proposal.md)에 정의한다. 2026-10-17 사용자 승인 보정으로 입력 경계 토큰을 추가했으며 그 외 시각 방향은 유지한다.

---
name: "사내 업무 도우미 · 검토용 시안"
description: "구현된 정적 시안의 시각 기준; 최종 디자인 승인 및 서비스 구현과 구분한다."
colors:
  ink: "#202a34"
  muted: "#5c6875"
  faint: "#6b7681"
  canvas: "#ffffff"
  navigation: "#f1f4f7"
  subtle: "#f7f9fb"
  line: "#dce2e8"
  input-border: "#75899b"
  accent: "#244e73"
  accent-hover: "#183d5e"
  selected: "#e0e9f1"
  highlight: "#e7eef5"
  error: "#a33232"
  error-bg: "#fcf3f2"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.5
    letterSpacing: "-0.035em"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.6
    letterSpacing: "-0.025em"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
  body-answer:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.95
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "13px"
    fontWeight: 600
  control:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "맑은 고딕", sans-serif'
    fontSize: "12px"
    fontWeight: 600
rounded:
  control: "6px"
  composer: "12px"
  citation: "4px"
spacing:
  space-8: "8px"
  space-12: "12px"
  space-16: "16px"
  space-20: "20px"
  space-24: "24px"
  space-30: "30px"
  space-44: "44px"
components:
  button-send:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.canvas}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  button-send-hover:
    backgroundColor: "{colors.accent-hover}"
  button-new-conversation:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.accent}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  input-composer:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.composer}"
    padding: "14px 16px 12px"
  navigation-conversation:
    backgroundColor: "{colors.navigation}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px"
  navigation-conversation-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.accent}"
  chip-citation:
    backgroundColor: "{colors.highlight}"
    textColor: "{colors.accent}"
    rounded: "{rounded.citation}"
    padding: "0 5px"
  chip-citation-expanded:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.canvas}"
  card-notice:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "15px 16px"
  card-notice-error:
    backgroundColor: "{colors.error-bg}"
  training-table:
    textColor: "{colors.ink}"
    width: "100%"
---

# Design System: 사내 업무 도우미 · 검토용 시안

## Overview

**Creative North Star: "밝고 차분한 업무 도구"**

이 문서는 `prototypes/work-assistant/`의 검토용 정적 시안에서 추출한 시각 기준이다. 서비스 구현 완료나 사용자의 최종 색상 승인을 뜻하지 않는다. PC 우선·모바일 기본 지원과 대화 목록·중앙 대화·선택적 근거 영역은 수락한 방향이며, 아래 색·간격·세부 모양은 사용자 디자인 검토를 기다리는 현재 구현값이다.

Operate 모드의 밝고 차분한 업무 도구다. 흰 읽기 영역과 옅은 회청색 탐색 영역을 얇은 선으로 구분하고, 절제한 청색으로 선택과 동작을 표시한다. 한국어 시스템 산세리프는 긴 답변과 일정 비교를 위한 의도적인 선택이다. 별도의 브랜드 은유나 확정 기업 아이덴티티를 부여하지 않는다.

**Key Characteristics:**

- 읽기와 일정 비교가 중심인 PC 화면
- 필요할 때 열고 닫는 출처·교육 상세
- 평면 배경, 얇은 구분선, 단일 청색 강조
- 가상 데이터와 화면 시안 범위의 지속적인 표시

추출 근거: [현재 스타일](prototypes/work-assistant/styles.css), [화면 구조](prototypes/work-assistant/index.html), [로컬 상태](prototypes/work-assistant/app.js). 범위는 [제품 맥락](PRODUCT.md)과 [수락한 화면 방향](docs/ui/01-screen-proposal.md)을 따른다. [검토 결과](.impeccable/review/reviewer-result.md)의 ship은 정적 시안 범위의 판정이다.

## Colors

흰색·옅은 회청색 바탕에 청색 하나로 동작과 선택의 위계를 만든다. 값은 위 frontmatter와 원본 CSS가 기준이다.

### Primary

- **절제한 청색** (`accent`): 전송, 교육명, 인용, 선택된 대화에 사용한다.
- **짙은 청색** (`accent-hover`): 전송·텍스트 동작의 hover에 사용한다.
- **옅은 선택 청색** (`selected`): 현재 대화의 배경이다.
- **옅은 인용 청색** (`highlight`): 닫힌 인용 번호의 배경이다.

### Neutral

- **본문 먹색** (`ink`), **설명 회색** (`muted`), **약한 회색** (`faint`): 본문·설명·입력 안내를 구분한다.
- **작업 흰색** (`canvas`), **탐색 회청색** (`navigation`), **보조 바탕** (`subtle`): 작업·탐색·근거 영역을 나눈다.
- **구분선 회색** (`line`): 표, 영역, 출처 행의 경계를 표시한다.
- **입력 경계 회청색** (`input-border`): 질문 입력 영역과 IT 요청의 입력·선택·여러 줄 필드 경계를 표시한다. 영역 구분선은 기존 `line`을 사용한다.

오류는 `error`와 `error-bg`의 상태 의미로만 사용한다. 별도 보조 브랜드 색으로 확대하지 않는다. sidecar의 8단계 색상 띠는 패널 미리보기용 보간이며 채택된 UI 토큰이 아니다.

## Typography

**Body Font:** 운영체제 UI 글꼴과 한국어 고딕 대체 글꼴을 잇는 `--font-ui`.

하나의 산세리프 계열 안에서 크기·굵기·행간으로 위계를 만든다. 별도 장식 글꼴이나 디스플레이 서체는 없다.

- **Headline:** 첫 화면 질문 제목. 모바일에서는 (23px)로 줄어든다.
- **Title:** 교육·규정 상세 제목.
- **Body / Body answer:** 일반 문구와 긴 답변. 답변은 더 넓은 행간을 사용한다.
- **Label / Control:** 대화 선택·교육명과 전송·보조 동작.

현재 구현에는 (11px) 메타데이터·보조 문구도 있다. 이를 일반 본문·최소 가독성·향후 화면의 기본 크기로 규범화하지 않는다. 모바일 본문은 (13px), 입력란은 확대 방지를 위한 (16px)다.

## Layout

PC 우선이다. 기본 왼쪽 목록은 (224px), 가운데는 남은 너비, 선택한 상세는 오른쪽 (348px)이다. 상세를 여는 초광폭 (1550px 이상) 구성은 (240px / 가변 / 380px)이다. 대화와 입력 영역은 최대 (824px), 첫 화면 안내는 최대 (630px) 안에 놓는다.

(1199px 이하)에서는 왼쪽 목록이 (200px)가 되고 상세가 가운데 대화를 대신한다. (767px 이하)에서는 목록을 닫힌 메뉴로 제공하고 상세를 전체 너비로 표시한다. 일정 표는 레이블을 가진 세로 항목으로 바뀐다. 상세를 닫으면 읽던 대화와 포커스로 돌아온다.

간격은 추출한 spacing 단계와 실제 구성의 용도를 따른다. 본문 영역과 하단 입력 영역을 각각 스크롤·고정 배치하여 답변을 읽으면서 질문을 이어간다. 상단 시안 전환 도구는 제품 내비게이션의 영구 요소로 일반화하지 않는다.

## Elevation & Depth

그림자는 없다. 배경 톤·얇은 선·선택색으로 영역을 구분한다. 모바일 메뉴 뒤에는 기존 먹색의 반투명 가림막이 있다. 키보드 포커스는 청색 외곽선 (2px, 간격 3px), 입력 영역은 focus-within 테두리와 외곽선 (1px)을 사용한다.

상세 내용에만 (180ms, ease-out)의 짧은 등장 동작이 있으며, 움직임 감소 설정에서는 실행하지 않는다. 샘플 응답의 대기 시간은 디자인 모션 토큰이 아니다.

## Shapes

일반 동작·선택 행·안내는 작은 둥근 모서리, 입력 영역은 더 큰 둥근 모서리를 쓴다. 인용 번호는 별도의 작은 사각 형태다. 사용자 질문은 한쪽 꼬리처럼 작은 모서리를 가진 버블이며, 답변과 교육 목록은 별도 카드 격자 없이 읽기 흐름 안에 놓인다. 아이콘은 원본에서 작성한 단색 선 SVG다.

## Components

아래 7개는 실제 시안에서 추출했고, sidecar는 각각 독립 HTML/CSS/SVG 예시를 제공한다. 버튼의 focus는 전역 포커스 규칙을 포함하며 원본에 없는 active 장식은 추가하지 않는다.

1. **전송 버튼:** 청색 바탕·흰 글자. hover는 짙은 청색, 빈 입력·준비 중에는 비활성화된다.
2. **새 대화 버튼:** 흰 바탕과 가는 테두리, 청색 글자·더하기. hover에 옅은 청색 바탕과 경계 변화가 있다.
3. **질문 입력 영역:** `input-border` 경계·둥근 모서리·여러 줄 입력·전송을 묶는다. focus-within으로 전체 입력 영역을 표시한다.
4. **대화 탐색:** 가벼운 행 목록. hover와 `aria-current="page"` 선택 상태를 구별한다. 모바일에서는 메뉴 안에 놓인다.
5. **인용 번호:** 작은 번호형 chip. hover 또는 `aria-expanded="true"`에 청색으로 채우며 상세 원문과 연결한다. 일반 태그나 필터는 없다.
6. **결과 안내:** 평면 안내 컨테이너. 조회 0건·근거 부족은 중립 바탕, 실패는 오류 바탕과 제목색으로 구분한다. 별도 카드 격자는 없다.
7. **교육 일정 표:** 교육·일시·장소를 정렬한다. 교육명은 상세를 여는 동작이며 모바일은 레이블을 가진 행별 항목이다.

샘플 상태 전환은 로컬 JavaScript 데모다. 코드에 없는 신청·승인·첨부·모델 선택 조작은 이 문서에 추가하지 않는다.

## Do's and Don'ts

### Do:

- **Do** 수락한 대화 목록·중앙 대화·선택적 근거 구조와 모바일 기본 작업을 유지한다.
- **Do** 일정의 날짜·시간·장소를 정렬하고 인용 번호와 원문 구간의 연결을 유지한다.
- **Do** 현재 색·간격을 시안의 검토 기준으로 사용하고 변경 시 소스와 이 문서를 함께 갱신한다.
- **Do** 키보드 포커스와 시안·가상 자료 표시를 유지한다.

### Don't:

- **Don't** 시안의 색·간격을 최종 사용자 승인이나 기업 브랜드 확정으로 해석한다.
- **Don't** 장식용 그래픽·그라데이션·의미 없는 KPI를 추가한다.
- **Don't** 작은 보조 글자 크기나 임시 대기 시간을 전 화면의 기준으로 확대한다.
- **Don't** 예시 응답·처리 내역을 실제 모델·서버의 실행 결과로 표현한다.

