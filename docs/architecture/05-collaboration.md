# 모듈 협력 시나리오

구체 import 의존은 [지도](04-module-map.md), DTO는 [계약](../contracts/00-shared-contracts.md)를 따른다. 아래 흐름은 업무 호출 순서이며 각 화살표가 별도 네트워크 서비스라는 뜻이 아니다.

## SC-01 질문 수락·교육 조회·완료

1. 08→01: 세션·질문. 01→09로 actor/소유권 확인.
2. M1은 APP-02의 DisabledRetrievalContextProvider→02, M2는 같은 provider→01→02로 knowledge_enabled=false context를 제공한다. M3부터01→11 실제 검색 provider로 snapshot/config를 고정한다.
3. 01이 사용자 메시지/run/활성 소유권을 짧게 commit.
4. 01→02: 가시성 검사를 통과한 이력·clock·예산·observer.
5. 02→07 도구 제안, 02→03→04 실제 교육 조회, 결과 원장 등록.
6. 02→CT-11(observer 구현01): 도구 기록. 이후07 최종 후보·검증.
7. 02→01: 결과 후보. 01은 활성/만료·현재 자원 권한을 재검사하고 메시지/상태/run을 commit한 뒤08에 반환.

모델·도구 대기 중 질문 수락 트랜잭션을 열어두지 않는다.

## SC-02 후속 질문·모호성

01이 같은 대화의 검증된 상태만02에 제공한다. 02가 후보/교육 사본을 식별하고 필요한 필드가 없으면03→04로 확인한다. 여러 대상이면 되묻고 임의 선택을 저장하지 않는다. 다른 대화의 상태를 조회하지 않는다.

## SC-03 PDF 수집·원문 게시

운영자 APP-03→06: 사용자 파일/manifest. 06이 파일·판본·원문 페이지를 검수하고07 임베딩을 준비한다. 06→05 CT-09로 staging 등록. 전체 membership/유효기간/ACL/원본 참조 검증 뒤05가 snapshot과 활성 포인터를 원자적으로 게시한다. 부분 실패 시 현재 게시본을 보존하고 실패 목록을 보고한다.

## SC-04 A/B 검색·시점

02→03 search_documents→11. A는11→05 raw. B는11→10 허용된 Wiki 후보→05 원문 확장. 05→09가 검색/출처의 현재 접근을 판정한다. 11은 같은 기준일로 호출 단위 후보·evidence_group·support_group을 구성해 CT-14를 반환한다. 여러 호출에 걸친 최종 token 예산 조립은 02가 [검색 조립 계약](../contracts/05-retrieval-assembly.md)의 같은 규칙으로 한다. 03은 고유 citation ID를 부여한다. 두 날짜 비교는 같은 snapshot에 별도 검색한다. Wiki 후보 본문은 최종 근거에 포함하지 않는다.

## SC-05 실패·만료·동시성

모델/도구 일시 오류 재시도는02 소유다. 03/07은 단일 시도다. CT-11 기록 실패는 추가 호출을 중단한다. 01은 실패/만료와 활성 해제를 commit하고 시작·조회·수락에서 만료를 회수한다. 같은 키/본문의 메시지 재전송은 기존 run으로 수렴하고 유효한 다른 run만409다. 늦은 완료는 만료를 덮어쓰지 않는다. [실행 계약](../contracts/01-run-lifecycle.md)을 따른다.

## SC-06 권한 변경·이력 재열람

역할은09, 문서 ACL/철회는05가 관리한다. 08→01 이력 조회 시01→11→05→09와01→12가 참조를 재검증한다. 어떤 의존 자원이든 불허면 해당 assistant 본문·인용·참조를 모두 가리고02에 재주입하지 않는다. 직접 근거/PDF URL도05에서 재검사한다. 새 답변도 최종 반환 전 같은 검사를 거친다.

## SC-07 Wiki 빌드·갱신

APP-03→10→05 운영자 권한의 고정 원문을 읽고10→07로 구조화 생성한다. 10이 주장 링크·의미·판본을 검수하고 Wiki snapshot을 게시한다. corpus가 바뀌면 대응 Wiki를 만들기 전 B는 stale/미준비다. 운영은11에서 raw fallback/reason 기록, strict 실험은 실패로 집계한다. ACL 변경은 현재 모든 기여 원문 가시성을 다시 확인한다.

## SC-08 티켓 준비·확인

02→03→12 prepare. 12→09 권한 확인, draft만 저장하며 기존 pending/head는 유지. 02는 action_pending을 반환,01은 참조를 저장한다. 01의 completed/채택→08 폼→12 revise로 pending 생성→구체 preview 확인→12 confirm HTTP. 12가 현재 소유권/권한/version/만료/키를 검증하고 ticket+action+응답+감사를 commit한다. 이 쓰기는02를 거치지 않는다. 상세는 [티켓 흐름](../14-ticket-workflow.md).

08의 폼 수정은12의 revise HTTP로 재검증·이전 pending superseded 전환·새 action 생성을 원자 처리한다. 12는 주입된 CP-06으로 prepare의 활성 run과 confirm/revise의 채택된 원본 run 자격을 확인한다. 사용자 입력 근원 검증과 계보 head의 직렬화로 검색 본문 자동 전재·잘못된 이전 action 확인을 막는다. 각 모듈 DB를 가로지르는 분산 트랜잭션은 두지 않는다.

## SC-09 비교 실험

APP-04가 고정 corpus/wiki/clock/actor/질문/최종 예산으로 A/B 별도 대화를 실행한다. 같은 검색 query 실험과 Agent 전체 실험을 구분한다. 도구/run 진단은01, 원문 순위/전략 진단은11, 오프라인 빌드 비용은06/10에서 모은다. 150문항 split·strict/fallback 구분은 [비교 프로토콜](../13-retrieval-comparison.md)을 따른다.

## 보정된 협력 경로

MOD-03→MOD-04 실제 교육 결과→CT-11(MOD-01 receipt 저장)→CP-07(MOD-02 evidence 확인)→MOD-11 날짜 판정이다. MOD-12도 앱 주입 CP-07로 user 원문을 읽으며 MOD-01 저장소 직접 접근은 금지다. Agent prepare draft는 head를 바꾸지 않고, run completed/채택 후 UI revise가 pending/head를 원자 교체한다. 실패 run은 이전 pending을 잃게 하지 않는다.
