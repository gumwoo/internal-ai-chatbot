# MOD-07 모델 연동


## 책임과 소유권

채팅/구조화 생성(Anthropic)·임베딩과 평가 judge(Google Gemini) SDK, 인증 키, 호출 설정, 공급자 응답·오류·사용량 정규화를 담당한다(D-25·D-27). 공급자마다 어댑터를 두고 같은 CT-07 계약으로 정규화하며, 다른 모듈은 공급자를 알지 못한다. 업무 DB·도구 실행·위키 게시·Agent 의사결정은 소유하지 않는다.

## 공개 작업

CompleteOnce(CT-07 ModelRequest) → ModelResponse. EmbedOnce(texts,config,timeout) → EmbeddingBatch. 호출 목적·실제 모델명·설정 버전을 결과에 기록한다. 테스트용 결정적 어댑터를 같은 계약으로 교체할 수 있다.

## 불변식·오류

- 호출 한 번 단위. SDK 자동 재시도는 끄거나 외부 예산에 포함해 하나의 소유자만 관리한다.
- 입력 순서/벡터 수/차원/유한 수를 검사하고 모델이 바뀐 벡터를 같은 인덱스에 섞지 않는다.
- 도구 제안과 최종 후보를 공급자 중립 구조로 변환한다. JSON/스키마 오류를 정상 답변으로 숨기지 않는다.
- rate limit, timeout, 미설정 키, 일시 장애, 입력 거절을 구분한다. 원문 키/공급자 예외 본문을 사용자에 노출하지 않는다.
- usage 미제공·네트워크 실패는 null/incomplete. 실패 요청도 실제 과금 가능성을 0으로 단정하지 않는다.
- 공급자 선택·버전·가격표는 구현/실험 시점에 확정한다. 가정 비용을 실제 측정처럼 적지 않는다.

## 협력·검토

MOD-02(Agent), MOD-05(온라인 검색 임베딩), MOD-06(색인), MOD-10(Wiki 빌드)이 소비한다. T-19 SDK 변환·usage·임베딩 검증·hidden retry. FR-06, NFR-01/07 담당.


## 경계 기준

이 문서는 모듈 수준의 책임·공개 계약·협력까지 정의한다. 클래스·SQL·파일 배치·세부 알고리즘은 별도 구현 결정이다. 공통 타입은 [계약](../contracts/00-shared-contracts.md), 의존 방향은 [모듈 지도](../architecture/04-module-map.md), 검증 ID는 [테스트](../07-test-and-evaluation.md)를 따른다.

prepare의 공급자 도구 arguments 안 origin_candidates는 CT-06.origin_candidates로 분리하고 업무 arguments와 구분한다. 값은 검증된 출처가 아닌 비신뢰 제안이며 MOD-02/12가 출처 계약대로 검증한다.

- M5(2026-10-18, D-41): ModelRequest.tool_choice(auto/any). any면 Anthropic `tool_choice={type: any}`로 보내고 최종 JSON 형식(output_config)은 붙이지 않는다(응답이 tool_use뿐). 빈 첫 답 재호출에서만 쓴다.

## 구현 메모(평가 judge, 2026-10-18)

- `gemini_chat.py` `GeminiJudgeModel`: purpose=eval_judge 전용 구조화 생성(JSON 스키마 응답, 온도 0, 도구 없음, SDK 재시도 끔). 답변 생성·Wiki 빌드는 Anthropic이다(D-25). 사용량은 응답 metadata가 있을 때만 채우고 없으면 미확인으로 둔다. 모델 ID는 설정 `JUDGE_MODEL`(D-27, 실행 날짜와 함께 기록). D-90: JUDGE_MODEL이 `claude-`로 시작하면 `eval-judge`는 `AnthropicChatModel`로 같은 judge 요청(purpose=eval_judge, JSON 스키마)을 보낸다. D-93: judge 지침 judge-v2(근거·금지 주장 기준), gold 사실이 있는 문항은 verdict를 항목 판정에서 계산(`eval_judge.derived_verdict`, model_verdict 보존).

