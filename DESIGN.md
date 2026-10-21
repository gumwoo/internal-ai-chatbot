> 적용 범위: 기존 정적 시안의 시각 기준이다. 통합 업무지원의 기능 요구사항은 [UI 명세](docs/ui/01-screen-proposal.md)에 정의한다. 2026-10-17 사용자 승인 보정으로 입력 경계 토큰을 추가했으며 그 외 시각 방향은 유지한다.
>
> 2026-10-21 서비스 화면 개편(D-79, 사용자 요청 "딱딱하다"): 실제 서비스 화면(`frontend/src/styles.css`)의 값은 아래 frontmatter가 아니라 맨 끝 "서비스 화면 값" 절이 기준이다. frontmatter와 본문은 정적 시안 기록으로 남긴다.

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

## 서비스 화면 값(2026-10-21, D-79)

정적 시안의 구조(대화 목록 · 가운데 대화 · 선택적 상세)와 단일 청색 강조는 유지하고, 딱딱한 인상을 줄이려고 아래를 바꿨다. 값의 원본은 `frontend/src/styles.css`다.

- **색:** `ink #1f2933`, `muted #5b6672`, `navigation #f5f7fa`, `line #e2e7ed`, `accent #2b5c99`(hover `#224b80`), `selected #e4edf8`, `highlight #eef3fa`. 종전 판본 표시는 `past #8a5a00` / `past-bg #fff4e2`. 12~13px 보조 글자는 `faint` 대신 `muted`를 써서 밝은 배경에서 대비 4.5:1 이상을 지킨다.
- **글자:** 본문 14px, 답 본문 15px·행간 1.75, 버튼 13px. 화면 문구는 짧은 해요체로 쓰고, "AI가 생성 중" 같은 표현과 이모지는 쓰지 않는다.
- **모양:** 버튼 8px, 카드·입력 영역 12~14px, 칩(근거 쪽·피드백·교육) 999px 둥근 모서리. 그림자는 근거 미리보기 말풍선에만 쓴다.
- **배치:** 대화와 입력은 가운데 최대 760px. 목록 264px, 상세 400px. 900px 이하에서는 목록을 메뉴로, 상세를 전체 너비로, 근거 미리보기는 입력창 위에 고정한다.
- **근거(D-75·D-76):** 답 문장 끝의 번호(본문에 먼저 나온 순서), 답 아래 "참고한 문서"에 문서마다 한 줄·쪽마다 번호 칩. 번호나 칩에 마우스를 올리거나 포커스하면 문서명·쪽·원문 앞부분을 미리 보이고, 누르면 상세에서 그 쪽의 원문 조각을 모두 보인다. 번호는 앞 낱말과 함께 줄을 바꾼다.
- **첫 화면:** 인사와 한 줄 안내, 주제별 예시 질문 3개(누르면 바로 보냄).
- **대화 목록(D-78):** 서비스 이름, 새 대화, 검색, 날짜 묶음(오늘·어제·지난 7일·지난 30일·그 이전). 이름은 정한 제목, 없으면 첫 질문(D-74).
- **답변 피드백(D-77):** 답 아래 "도움이 됐어요"·"아쉬워요" 칩. 아쉬워요는 사유(근거 문서가 맞지 않아요·근거가 부족해요·답이 틀렸어요·기타)와 선택 의견을 받는다.
- **IT 접수 카드:** 채운 항목과 꼭 필요한 빈 항목만 줄로 보이고, 빈 선택 항목은 한 줄로 모은다. 만료 시각은 문장으로 알린다.
