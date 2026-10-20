# 평가셋 150문항(dev50 / holdout100)

> **모델 생성 문항이다.** 문항·정답 근거는 서브에이전트가 원문(프로젝트 파서로 추출한 쪽별 텍스트)만 보고 만들었고, 다른 에이전트가 정답 근거를 원문과 대조했다. 사람 검수자는 없다. 결과 보고서에도 이 사실을 밝힌다.

구성·지표·동결 규칙은 [비교 프로토콜](../docs/13-retrieval-comparison.md)이 기준이다(D-09). 이 폴더는 그 형식의 구현이다.

| 유형(category) | 전체 | dev | holdout |
|---|---:|---:|---:|
| single_doc 단일 문서 | 30 | 10 | 20 |
| multi_doc 복수 문서 종합 | 40 | 13 | 27 |
| exception 예외·조건 | 25 | 8 | 17 |
| revision 과거·현행 비교 | 20 | 7 | 13 |
| no_evidence 근거 없는 질문 | 15 | 5 | 10 |
| access 접근 권한 | 20 | 7 | 13 |

## eval-v2 새 검증셋(holdout2, 2026-10-19)

eval-v1 holdout 결과와 오답을 본 뒤 시스템을 고쳤기 때문에(D-60~D-63), 개선 효과는 **새 문항 `cases/holdout2.jsonl`(95문항)**로 잰다(D-62). 만든 방법은 위와 같다(모델 생성·모델 대조 검증, 사람 검수 없음). 생성 에이전트는 원문과 명세만 봤고 시스템 답변·평가 결과는 보지 않았다. 구성: 단일 20, 복수 23, 예외 17, 개정 12, 근거 없음 10, 권한 13(계획 100문항 중 검증에서 5문항 제외: 복수 문서가 필요 없는 4, 기존 문항과 중복 1). 정답 근거에 같은 사실의 대체 근거(규정과 같은 금액을 적은 FAQ 등)를 함께 넣었다. holdout2도 동결 예산으로만 실행한다.

## eval-v3 새 검증셋(holdout3, 2026-10-20)

holdout2 실행 기록을 보고 D-67(판본별 안내)·D-68(검색 약속 재호출)·D-69(영업일 계산)를 고쳤고, D-68 판정 규칙은 holdout2 답을 참고해 보정했다. 그래서 이 변경들의 효과는 **새 문항 `cases/holdout3.jsonl`(97문항)**로 잰다(D-70). 생성 지침은 저장소 밖 `data/staging/eval-drafts/holdout3/BRIEF.md`(모델 생성·모델 대조 검증, 사람 검수 없음)이고, 생성·검증 에이전트는 원문·명세·지침만 봤다(시스템 답변·평가 결과·코드는 보지 않음). 구성: 단일 20, 복수 30, 예외 16, 개정 11, 근거 없음 10, 권한 10(초안 113문항 중 검증에서 16문항 제외: 한 문서로 충분 8, 기존·같은 셋과 중복 8). 기대 결과는 현재 정책을 따른다: 날짜 없는 과거 사건은 두 판본을 나눠 안내하는 것이 정답(tag `edition_split` 5문항, 사건 기준 + as_of_date null), 영업일 마감 날짜를 묻는 문항은 원문 기한과 계산한 날짜를 함께 말해야 정답(tag `deadline_calc` 10문항, D-69 계산 규칙과 공휴일표). holdout3도 동결 예산으로만 실행한다.

## 파일

- `cases/dev.jsonl`, `cases/holdout.jsonl`: 한 줄에 한 문항.
- `manifest.json`: 평가 버전, 파일 hash, 생성·검증 방법, 원문 corpus(manifest hash·parser revision).
- holdout은 설정·프롬프트·Wiki 주제를 동결한 뒤에만 실행한다. holdout을 본 뒤 고치면 새 평가 버전이다.
- 평가 질문·정답은 Wiki 주제 계획·빌드 입력에 넣지 않는다.

## 문항 형식

```json
{
  "case_id": "EV-S-001",
  "split": "dev",
  "category": "single_doc",
  "tags": ["faq_sufficient"],
  "asked_at": "2026-10-16T10:00:00+09:00",
  "actor": "emp-sales",
  "turns": ["질문 문장"],
  "expected_outcome": "answered",
  "date_basis": "training_start",
  "as_of_date": "2026-09-29",
  "required_facts": ["원문으로 확인되는 사실 한 줄씩"],
  "required_exceptions": ["빠뜨리면 틀리는 조건·예외"],
  "forbidden_claims": ["말하면 틀리는 주장(다른 판본 금액, 제한 문서 내용 등)"],
  "evidence_sets": [[{"source_file_id": "PDF-031", "page": 1, "quote": "원문 그대로", "occurrence": 1}]],
  "hard_negative_anchors": [{"source_file_id": "PDF-030", "page": 1, "quote": "원문 그대로", "occurrence": 1, "same_group": false}],
  "rationale": "정답이 원문에서 어떻게 나오는지 한두 문장",
  "generated_by": "model:subagent",
  "verified_by": "model:subagent"
}
```

- `actor`: 데모 계정(D-30) `emp-sales`·`emp-dev`(일반 직원), `head-sales`(부서장), `hr-staff`(인사 담당), `it-support`.
- `expected_outcome`: `answered` / `needs_clarification`(사건 날짜가 없어 되물어야 함) / `insufficient_evidence`(근거 없음·권한 없음).
- `date_basis`·`as_of_date`: 질문의 사건 기준과 날짜(질문에 있는 날짜만). 사건 없는 일반 질문은 `current`와 null.
- `evidence_sets`: 대체 가능한 최소 충분 근거 집합의 목록. 각 인용은 그 쪽 텍스트의 연속 구간을 글자 그대로(공백 차이만 허용) 옮기고 `occurrence`는 그 쪽에서 몇 번째로 나오는 같은 문구인지다. 근거가 없거나 권한이 없는 문항은 빈 목록이다.
- `hard_negative_anchors`: 그럴듯하지만 이 문항에는 틀린 근거(다른 판본의 같은 표, 현행 FAQ의 다른 금액 등). `same_group`은 정답과 같은 조항·표 안이면 true.
- 정본은 PDF SHA-256·물리 쪽·정확 인용문·발생 순번이다(`manifest.json`의 hash로 묶는다). chunk ID·Wiki로 정답을 정하지 않는다.
