# 참고 자료와 포트폴리오 기록

## 원리·설계 참고

- [Karpathy의 LLM Wiki 구상](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): 원문에서 파생 지식 구조를 유지하는 아이디어. 이 프로젝트의 성능 근거로 대체하지 않는다.
- [Cochran, RAG/Wiki 비교 v3](https://arxiv.org/html/2605.18490v3): 실험 조건·토큰 비용·질문 유형과 근거 평가의 한계를 함께 읽는다. 다른 corpus 결과를 여기의 우위로 일반화하지 않는다.
- [LlamaIndex Document Summary Index](https://www.llamaindex.ai/blog/a-new-document-summary-index-for-llm-powered-qa-systems-9a32ece2f9ec): 요약으로 문서를 고른 뒤 원문을 회수하는 설계 참고. 오래된 코드/API는 구현 시 재확인한다.
- [Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval): chunk별 문맥 보강 개념. 문서 전체 Wiki와 동일한 방식은 아니다. 같은 글은 후보 150개를 재정렬해 20개를 넘긴 설정과, 지식베이스가 약200k token 미만이면 전체를 프롬프트에 넣는 방안을 소개한다. 영어 데이터·해당 설정의 결과라 이 코퍼스의 적정값으로 옮기지 않는다.

## 근거 양·예산 참고

- [Lost in the Middle (Liu et al.)](https://arxiv.org/abs/2307.03172): 긴 문맥 중간에 놓인 근거를 덜 쓰고, 넣는 문서를 20개에서 50개로 늘려도 개선이 작았다는 보고. packing_order 고정의 근거.
- [Long-Context LLMs Meet RAG (ICLR 2025)](https://arxiv.org/abs/2410.05983): 넣는 passage 수를 늘리면 품질이 오르다 떨어지고 그럴듯한 오답 근거(hard negative)가 원인이라는 보고. 예산 스윕·hard_negative 지표의 근거.
- [Long Context vs. RAG for LLMs: An Evaluation and Revisits](https://arxiv.org/abs/2501.01880): 모델·과제에 따라 긴 문맥과 RAG의 우열이 갈린다는 정리. 전체 문맥 기준선을 대조군으로만 두는 이유.
- 예산 기준 회수 지표와 고정 개수 대신 token으로 맞춘 비교 방식은 2026년 preprint와 실무 글에서 참고했다. 예비 결과이므로 지표 정의만 차용하고 수치는 인용하지 않는다.
- [Microsoft GraphRAG Local Search](https://microsoft.github.io/graphrag/query/local_search/): 구조화 지식과 원문을 연결하는 검색 참고. 우리 B와 동일 알고리즘으로 부르지 않는다.
- [pgvector 공식 저장소](https://github.com/pgvector/pgvector), [FastAPI 공식 튜토리얼](https://fastapi.tiangolo.com/tutorial/), [PostgreSQL 문서](https://www.postgresql.org/docs/): DB·API 구현 기준.

## 탐색한 실무·개인 사례

[Syshin의 Wiki 활용](https://syshin0116.vercel.app/blog/wiki-instead-of-rag), [Wiki와 ADR](https://syshin0116.vercel.app/blog/llm-wiki-and-adr), [Vibed Lab의 비교](https://vibed-lab.com/blog/rag-vs-llm-wiki), [Kevin의 소규모 평가](https://osisdie.github.io/blog/2026/hybrid-vs-llm-wiki-eval/)는 사례로 읽는다. 특히 Hybrid가 키워드+벡터를 뜻하는 글을 Wiki+원문 혼합의 측정 결과로 오해하지 않는다. 개인 사례의 표본·비용·검색/도구 설정은 이 프로젝트와 다르다.

[Glean의 크롤링/동기화 안내](https://docs.glean.com/connectors/crawling-faq)는 원본 변경·권한 동기화 검토 참고다. [교원그룹 공고](https://kyowon.ninehire.site/job_posting/jSiNzfb9)는 직무 맥락이다. 이 파일의 링크가 특정 기능의 구현 완료나 최신 공고 상태를 보장하지 않는다.

## 남길 증거

지금까지의 결정·사례는 [포트폴리오 기록](portfolio/README.md)(ADR·트러블슈팅)에 정리한다.

1. 모듈 경계/계약 결정과 책임 변경 이유.
2. PDF100/91문서/9개정 쌍 검수 보고서, 파싱 실패와 해결 사례.
3. 같은 corpus의 A/B 설정·원문 gold·유형별 결과·fallback/실패.
4. 권한 철회 후 이력/PDF/Wiki 차단과 과거 시점 판본 선택 사례.
5. IT 확인 전 무생성·동시 확인·응답 유실 테스트 결과.
6. Wiki 구축/갱신·요청 비용, 누락/미확인 사용량을 포함한 측정.
7. AI 코딩 도구가 만든 제안과 직접 검토/수정한 코드·테스트 사례.

측정 전에는 “정확도 향상”, “유출0”, “비용 절감”을 성과로 쓰지 않는다. 실제 보고서의 표본·조건·실패를 설명한다. 회사 자료가 아니라 가상 회사 샘플이라는 점을 데모에 표시한다.
