# MOD-09 사용자·인증·인가


## 책임과 소유권

users/departments/role memberships/local sessions/auth_revision을 소유한다. 세션으로 actor를 만들고 자원 소유자가 제공한 정책에 대해 현재 접근 가능 여부를 판정한다. 문서/티켓 저장소를 직접 읽지 않는다.

표시 프로필의 reply_channel은 MOD-09 사용자 데이터로 관리하고 MOD-12에 서버 조회로 제공한다. 지원 담당 범위는 MOD-12의 자원 정책, 역할 membership은 MOD-09 소유다. 역할 변경 감사는 MOD-09, 문서 ACL 변경 감사는 MOD-05가 소유한다. 최초 fixture의 값은 M3/M5 전에 검수하며 모델이 채우지 않는다.

## 공개 작업

Login/Logout/GetSession → 서버 세션과 표시용 사용자. ResolveActor(session) → CT-01. Authorize(actor,capability,resource_policy) → AccessDecision. ReloadActor(user_id) → 현재 부서/역할/revision. ChangeMembership(운영자,변경) → revision 증가. ResolveOperatorActor(서버 설정의 운영 계정) → CT-01 source=operator_cli, ResolveEvalActor(평가 설정의 profile) → CT-01 source=eval_fixture. 두 작업은 각각 APP-03/APP-04 조립 지점에서만 호출하며 HTTP·모델 입력으로 호출할 수 없다. capability 이름은 CT-01의 닫힌 목록만 쓴다. 운영 관리 화면은 MVP 필수 범위가 아니다.

## 최소 인증 범위

로컬 데모 계정과 서버 세션을 사용한다. 비밀번호를 저장할 경우 검증된 해시 방식 사용, 세션은 HttpOnly·SameSite cookie, 운영 HTTPS에서 Secure. 상태 변경 HTTP는 CSRF/Origin 검증을 한다. 세션/계정 실데이터는 구현 시 가상 fixture로 분리하고 실제 SSO·회원가입·비밀번호 복구는 제외한다.

## 접근 정책

- 인증·행위 capability·자원 허용 범위가 모두 충족돼야 한다. classification 이름 하나만으로 권한을 부여하지 않는다.
- 기본 거부, 비어 있거나 알 수 없는 정책은 거부. 전사 공개도 명시적인 authenticated 정책이다.
- 현재 부서/역할이 기준. Authorize는 세션 회수·현재 auth_revision을 확인하고 오래된 ActorContext의 capability를 갱신/거절한다. 과거 규정 조회가 이전 직원 권한을 부활시키지 않는다.
- 브라우저·LLM의 user_id,admin,approved 등은 무시/거절한다. 서버 계정 ID로만 판정한다.
- 문서 ACL은 MOD-05, 티켓 범위는 MOD-12 소유다. MOD-09가 업무 데이터 저장소의 결합 지점이 되지 않는다.
- 역할/문서 ACL 변경을 revision으로 검출하고 이력/캐시/최종 반환에서 재검사한다.

## 검토·테스트

T-22 로그인/세션/CSRF, T-23 default deny·역할 변경·서버 actor, T-04 재열람. FR-10, NFR-02/11 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

## 2026-10-17 M3 구현 메모

- 데모 조직·계정은 D-30 fixture(`backend/src/agent/modules/identity_access/demo_org.json`, `seed-identity`)로만 적재한다. 비밀번호는 scrypt 해시만 저장하고, 비밀번호·웹 로그인 여부가 바뀌면 그 계정의 세션을 회수한다. 재적재는 비활성 계정을 되살리지 않는다. 부서·역할 변경은 auth_revision을 올리고 감사 행을 남긴다.
- Authorize는 local_session actor의 세션 회수·만료와 현재 부서·역할·revision을 다시 읽어 판정한다. 비밀번호 검증은 이벤트 루프 밖(스레드, 동시 4개)에서 한다.

## 2026-10-17 계약 보정

CLI actor source는 operator_cli이며 서버 운영 계정/capability로만 만든다. 직원 요청이나 모델 입력은 이 source를 만들 수 없다. 데모 지원 역할도 명시된 department 범위만 허용한다.
