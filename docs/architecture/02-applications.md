# 애플리케이션 실행 단위

| ID | 실행 단위 | 포함·호출 모듈 | 진입 |
|---|---|---|---|
| APP-01 | 직원 웹 | MOD-08, 서버 HTTP 사용 | 브라우저 |
| APP-02 | 플랫폼 API | MOD-01~05/07/09~12 조립 | FastAPI HTTP |
| APP-03 | 지식 운영 CLI | MOD-06 수집, MOD-05 게시/ACL 변경, MOD-10 Wiki, MOD-09 역할 변경 | 운영자 명령 |
| APP-04 | 테스트·평가 실행기 | 공개 모듈/API, MOD-11 A/B | pytest·평가 명령 |

APP-02와 APP-03은 동일 소스 패키지를 사용하되 실행 수명과 권한을 구분한다. 온라인 API가 PDF 전량 처리나 Wiki 재생성을 요청 응답 안에서 수행하지 않는다. APP-03 운영 자격을 LLM 도구에 전달하지 않는다.

## 조립 책임

앱 시작 지점에서 DB 어댑터, 모델 어댑터, clock, MOD-09 인증·인가, MOD-01의 실행 기록 observer, 자원 가시성 검사 포트를 연결한다. 모듈이 다른 모듈의 저장소를 직접 생성하지 않는다. 설정에는 검색 모드·모델·프롬프트·시간 상한·활성 스냅샷이 있다.

## 운영 절차

1. 사용자 PDF·메타데이터 입력 검수.
2. 수집 CLI가 준비하고 MOD-05가 corpus snapshot을 게시.
3. Wiki CLI가 같은 snapshot을 읽어 빌드·검수한 뒤 MOD-10이 게시.
4. API는 대화 생성 시 전략, 각 요청 수락 시 사용할 snapshot/config를 고정. 시작·조회·수락에서 MOD-01의 만료 회수를 실행.
5. 평가는 신뢰된 MOD-01.CreateConversation(server_options)로 A/B 각각 별도 대화를 만들고 비교 보고서를 저장. 직원 HTTP로 전략을 바꾸지 않는다.

운영 CLI의 역할 변경/ACL 변경은 MOD-09.ChangeMembership과 MOD-05.UpdateResourceAccess 공개 작업을 사용하고 운영자·revision·변경 대상을 감사에 남긴다. 운영자는 시작 설정의 허용된 로컬 운영 계정을 MOD-09로 확인하며 명령 인자의 임의 role/admin을 actor로 신뢰하지 않는다. 온라인 모델에 운영 actor나 이 진입점을 제공하지 않는다.

명령의 실제 이름·옵션은 구현 단계에 README로 확정한다. 아직 실행되지 않는 명령을 사용 가능한 기능처럼 적지 않는다. 건강 확인은 `/health/live`, `/health/ready`이며 유료 모델 호출을 수행하지 않는다.

M1/M2는 APP-02의 DisabledRetrievalContextProvider 어댑터가 knowledge_enabled=false/검색 snapshot null 문맥을 제공한다. MOD-11 실제 구현은 M3부터 주입하고 새 모듈은 추가하지 않는다.
