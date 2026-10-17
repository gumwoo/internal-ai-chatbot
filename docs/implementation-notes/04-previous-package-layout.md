> **이전 설계 참고 자료:** 개정2 이전 예제다. 현재 ACL·시점·PDF/Wiki snapshot·티켓 계약은 [설계 검토 안내](../architecture/00-review-guide.md)를 따른다. 이 예제를 현재 명세로 사용하지 않는다.

# 구현 참고 04. 이전 패키지 배치 초안

이전의 기술 역할별 폴더 예시를 보존한 자료이며 현재 모듈 경계의 기준은 아닙니다. `api`, `services`, `repositories`는 레이어·기술 역할 분류입니다. 논리 모듈을 폴더와 일대일로 고정하지 않으며 실제 배치는 [레이어 설계](../architecture/03-layers.md)를 참고해 구현 시 결정합니다.

```text
backend/
  app/
    main.py
    api/
    core/          # 설정, clock, 현재 사용자, 오류
    services/
    agent/
    tools/
    providers/
    repositories/
    retrieval/
    ingestion/
  migrations/
  tests/
frontend/
data/
  trainings/
  policies/
evals/
  cases/
  results/
docs/
compose.yaml
.env.example
```

