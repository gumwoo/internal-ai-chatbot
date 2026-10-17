# 계약·시안 보정 검증

2026-10-17. 범위는 설계 명세와 정적 시안이다. 백엔드/실제 ACL·DB 경쟁·모델 품질의 통과 보고서가 아니다.

## 지적별 반영

| 지적 | 반영 |
|---|---|
| 새 prepare가 기존 준비를 조기 취소 | Agent draft는 head 불변. 채택된 run의 UI revise 성공만 pending 교체 |
| 입력 출처 검증 경로 부재 | CP-07 MOD-01 읽기 어댑터→MOD-12 구간 검증. 교육 결과는 CT-11 receipt→CP-07 |
| 과거 사건에서 현행 FAQ 누락 | knowledge_as_of와 사건 as_of_date, normative/guidance 분리 |
| 미래 날짜 전면 거절 | 공개된 규정으로90일 이내 예정 사건 허용, prospective와 unsupported 결과 명시 |
| root/revision 유일키 충돌 | root prepare receipt만(run,ordinal) 유일, revision UI 키 분리 |
| 소유권/version·대체 action 혼동 | 소유권 먼저, superseded409, 단조 head_revision으로 상태 변경 감지 |
| 202 최종 답변 경로 | GET run 종료 확인 후 동일 키/본문 POST replay |
| gold 파서 의존 | PDF hash/page/quote 정본과 parser별 alignment 분리 |
| 파싱·평가 누락 | M3 경계/띄어쓰기/표/양식 게이트, A/B 상한 해석·ACL coverage 층화 |
| UI 반복·값 생성·잘못된 폼 수정 | 날짜 슬롯, 미입력 값 빈칸, message ID 바인딩, 입력 보존 |
| UI 편집/만료·예외·포커스 | 편집 취소 보존·성공 시 교체, 만료 재사용 차단, QA 전용 fixture, 모바일 dialog trap |

## 실행한 검증

- 저장된 browser-flows.cjs: 실제 Chrome headless,54개 검사 통과. 데스크톱1440×900/1280×720 및 모바일390×844. 이 결과는 고정 응답 시안에서만 유효하다.
- scripts/check_specs.py: Markdown48개/로컬 링크189개, JSON fence,16 CT/12모듈/35 T ID·필수 계약 필드 검사, PDF100개 해시 목록 비교. 의미적 무결성을 자동으로 증명하는 검사라는 뜻은 아니다.
- 시안 인용문7개를 해당 PDF 물리 페이지의 추출 텍스트와 공백 정규화 후 대조했다. 모두 일치. quote-results.json 참조.
- detector 1회: 기존11px 보조 주석 경고1건. 기능 보정 범위에서 CSS/기존 시각 토큰을 바꾸지 않았으며 경고를 기록했다.
- 화면12개는 각 기기별 home/form 상단/form 하단/preview다. 폼이 내부 스크롤 영역이라는 점을 명시한다.

브라우저 스크립트/실행 방법을 저장했으며 임시 스크립트 실행 결과만으로 재현 가능하다고 주장하지 않는다. 실제 manifest/150문항/서버 구현은 아직 만들지 않았다. PDF 원본에는 쓰기를 수행하지 않았다.

독립 검토의 F1(지역 답변에 출장 포함 시 날짜 소실), F2(VPN 교육 접수 의도 오인)를 수정하고 동일 문장 회귀2개를 추가했다. 같은12개 화면을 다시 캡처했다. 최초 검토와 후속 verdict는 별도 파일에 보존한다.
