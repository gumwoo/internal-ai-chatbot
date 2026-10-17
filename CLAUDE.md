# Enterprise Knowledge & Work Agent

가상 회사의 사내 통합 업무지원 AI Agent다. 무엇을 만들지는 `docs/`의 명세가 기준이며, 이 파일은 명세의 위치와 작업 규칙만 담는다.

## 현재 상태

- 설계 문서와 정적 시안만 있다. 백엔드·DB·RAG·Wiki 코드는 없다. 다음 단계는 M0(`docs/08-development-plan.md`).
- Python 패키지 관리·ORM·마이그레이션·모델 SDK는 미정이다(O-03, O-04). 정해지면 "명령" 절을 채운다.

## 명세 위치

필요한 파일만 읽는다. 기억이나 추측으로 답하지 않는다.

| 알고 싶은 것 | 파일 |
|---|---|
| 범위·요구사항 | `docs/00-project-overview.md`, `docs/01-requirements.md` |
| 모듈 경계·허용 의존 | `docs/architecture/04-module-map.md`, `docs/modules/MOD-01~12` |
| 공통 계약(CT·CP) | `docs/contracts/00-shared-contracts.md`, `docs/contracts/01~05` |
| HTTP·오류 코드 | `docs/04-api-spec.md`, `docs/contracts/03-errors.md` |
| 확정 결정(D)·미정(O) | `docs/10-decisions-and-open-questions.md` |
| 정책 선택 이력(P) | `docs/15-policy-options.md` |
| 테스트 ID(T)·첫 구간 | `docs/07-test-and-evaluation.md`, `docs/12-first-milestone-spec.md` |

P-xx(정책)와 CP-xx(공통 포트)는 다른 체계다.

## 작업 규칙

- PDF 원본(`data/raw/pdfs/`)과 `.env`는 훅이 막는다. 막히면 우회하지 말고 사용자에게 알린다.
- O-xx로 남은 값은 임의로 정하지 않는다. 선택지와 trade-off를 `docs/15-policy-options.md`에 적고 묻는다.
- 계약을 바꾸면 그 계약을 참조하는 문서(`00-shared-contracts`, `04-api-spec`, 해당 MOD, `04-module-map`, `07-test-and-evaluation`)를 함께 고치고, 확정은 D 표·미정은 O 표에 남긴다.
- 문서 수정 뒤에는 명세 검사를 돌린다. 코드에는 해당 T ID의 테스트를 함께 쓴다.

## 반복 처리

- 같은 지적을 두 번 받으면 CLAUDE.md 수정안을 보여주고, 승인받은 뒤 반영한다.
- 같은 절차를 세 번 요청받으면 `.claude/skills/` skill 초안을 보여주고, 승인받은 뒤 만든다.
- 매번 반드시 지켜야 하는 규칙이 보이면 hook 초안과 시험 결과를 보여주고, 승인받은 뒤 등록한다.
- `[반복 감지 훅]` 알림은 제안의 근거일 뿐 자동 반영의 근거가 아니다. 감지는 글자 조각 비교라 다른 표현의 반복은 놓칠 수 있다.

## 명령

명세 검사(결과는 저장소 밖에 쓴다):

```bash
SPEC_RESULTS_DIR="$TEMP/spec-results" python -B scripts/check_specs.py
```

정적 시안 테스트: `prototypes/education-agent/tests/README.md` 참조(`PROTOTYPE_RESULTS_DIR`는 저장소 밖).

백엔드·프런트 실행/테스트: O-03 결정 후 추가.
