# 통합 업무지원 정적 시안 검증 기록

2026-10-17. 설계+정적 시안 검토이며 실제 서비스/보안/업무 트랜잭션 통합 테스트가 아니다.

## 실행 확인

- Node 구문 검사 통과.
- 별도 Playwright CLI 세션에서 아래 assert 기반 흐름 검증 완료(exit0). 사용자 탭 상태와 분리했다.
- 최초 앱 내 브라우저 캡처의 대상/프레임 불일치를 확인해 캡처를 폐기하고 검증용 브라우저로 교체했다. 아래 캡처가 최신 증거다.
- 원문 링크가200·%PDF 파일을 반환함을 확인.
- 종전 출장에 출발일 기준8만원, 현행과 비교12만원 구분.
- 필수 서비스 누락 시 preview 차단, 긴급 사유 필수 전환.
- 최종 검토에서 수정 화면의 발생 시각 필수 조건을 보정했다. 서비스 요청·사용 문의는 발생 시각을 비운 채 preview → 내용 수정 → preview가 가능하고, 장애는 빈 발생 시각으로 진행할 수 없음을 각각 assert로 확인했다.
- 확인 전 미접수, 확인 후DEMO 번호, 반복 확인의 동일 번호, 취소·만료·응답 유실 결과 재확인.
- 제한 상태에 출처 제목/링크 없음.
- 모바일 상세/메뉴 닫기 시 포커스 복원.
- 1440/1280/390px에서 문서 가로 넘침 없음.
- 검사 중 앱 JavaScript pageerror 없음. 최초 정적 서버 favicon404는 기능 실패와 구분한다.
- 보정 후 동일한 11개 화면을 같은 크기로 다시 캡처하고 각각 열어 내용·대상을 확인했다. 최종 실행의 38개 assertion이 통과했다.

## 캡처

| 파일 | 실제 크기 |
|---|---|
| [integrated-history-desktop.jpg](integrated-history-desktop.jpg) | 1440 × 900 |
| [integrated-home-desktop.jpg](integrated-home-desktop.jpg) | 1440 × 900 |
| [integrated-policy-desktop.jpg](integrated-policy-desktop.jpg) | 1440 × 900 |
| [integrated-policy-mobile.jpg](integrated-policy-mobile.jpg) | 390 × 844 |
| [integrated-policy-user-1280.jpg](integrated-policy-user-1280.jpg) | 1280 × 720 |
| [integrated-ticket-confirm-action-desktop.jpg](integrated-ticket-confirm-action-desktop.jpg) | 1440 × 900 |
| [integrated-ticket-confirm-action-mobile.jpg](integrated-ticket-confirm-action-mobile.jpg) | 390 × 844 |
| [integrated-ticket-confirm-desktop.jpg](integrated-ticket-confirm-desktop.jpg) | 1440 × 900 |
| [integrated-ticket-confirm-mobile.jpg](integrated-ticket-confirm-mobile.jpg) | 390 × 844 |
| [integrated-ticket-done-desktop.jpg](integrated-ticket-done-desktop.jpg) | 1440 × 900 |
| [integrated-ticket-form-desktop.jpg](integrated-ticket-form-desktop.jpg) | 1440 × 939 |

## 탐지기

[단회 결과](integrated-detector.json): 상단 시안 탭의 밑줄 정렬/배경 경계,11px 메타·보조 글자 경고. 기존 DESIGN.md도11px를 본문 기준으로 일반화하지 않는다. 판단이 필요한 경고를 finish reviewer에게 전달한다. 탐지기를 반복 실행하지 않았다.

## 범위

고정 응답과 탭 메모리 상태만 검증했다. 실제 날짜 해석·RAG 정확도·사용자 세션·ACL·DB 멱등성/동시성·모델 오류는 서비스 구현 단계 검증이다.
