> **이전 설계 참고 자료:** 개정2 이전 예제다. 현재 ACL·시점·PDF/Wiki snapshot·티켓 계약은 [설계 검토 안내](../architecture/00-review-guide.md)를 따른다. 이 예제를 현재 명세로 사용하지 않는다.

# 구현 참고 03. 벡터 조회 SQL 예시

실제 질의 작성 시 참고할 예시입니다. 현재 검색 계약·필터 책임은 [MOD-05 지식 검색·카탈로그](../modules/MOD-05-knowledge.md)에 있습니다. SQL 매개변수 바인딩과 벡터 타입 변환은 MOD-05의 저장소 어댑터에서 구현합니다.

```sql
SELECT c.id, c.document_id, d.document_key, d.title, d.version,
       c.section, c.content, c.source_start, c.source_end,
       c.embedding <=> :query_vector AS distance
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.status = 'published'
  AND d.visibility = 'company'
  AND d.effective_from <= :current_kst_date
  AND c.embedding_model = :embedding_model
  AND c.embedding_dimensions = :embedding_dimensions
ORDER BY c.embedding <=> :query_vector, c.id
LIMIT :top_k;
```

