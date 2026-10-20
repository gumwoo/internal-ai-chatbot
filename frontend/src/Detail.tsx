// 선택적 상세 패널: 교육 상세·원문 근거·티켓(서버 DTO만). 좁은 화면에서는 전체 너비로 열린다.
import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { CATEGORIES, DATE_BASES, REQUEST_TYPES, formatTime } from "./labels";
import type { Detail } from "./types";

export function DetailPanel({ detail, onClose, onExpired }: { detail: Detail; onClose: () => void; onExpired: () => void }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [texts, setTexts] = useState<(string | null)[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setTexts(null);
    setError(null);
    const fail = (e: unknown) => {
      if (!alive) return;
      if (e instanceof ApiError && e.status === 401) onExpired();
      else setError(e instanceof ApiError && e.status === 404 ? "볼 수 없는 자료입니다." : "불러오지 못했습니다.");
    };
    if (detail.kind === "citation") {
      // 묶인 조각마다 원문을 읽는다(권한은 요청마다 서버가 다시 확인한다).
      Promise.all(detail.group.map((c) => api.evidence(c.evidence_url)))
        .then((loaded) => alive && setTexts(loaded.map(({ data }) => (data.text as string | undefined) ?? null)))
        .catch(fail);
    } else {
      (detail.kind === "training" ? api.training(detail.id) : api.ticket(detail.id))
        .then(({ data }) => alive && setData(data))
        .catch(fail);
    }
    heading.current?.focus();
    return () => {
      alive = false;
    };
  }, [detail, onExpired]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const title = detail.kind === "citation" ? detail.citation.title : detail.title;
  return (
    <aside className="detail" aria-label="상세">
      <div className="detail-head">
        <button type="button" className="secondary back" onClick={onClose}>뒤로</button>
        <h2 tabIndex={-1} ref={heading}>{title}</h2>
      </div>
      {error && <p className="notice" role="alert">{error}</p>}
      {detail.kind === "citation" && <CitationBody detail={detail} texts={texts} />}
      {detail.kind === "training" && data && (
        <dl className="fields">
          <div><dt>교육</dt><dd>{String(data.title)}</dd></div>
          <div><dt>일시</dt><dd>{formatTime(String(data.starts_at))} ~ {formatTime(String(data.ends_at))}</dd></div>
          <div><dt>장소</dt><dd>{String(data.location ?? "")}</dd></div>
          <div><dt>상태</dt><dd>{String(data.status)}</dd></div>
          {data.description ? <div><dt>설명</dt><dd>{String(data.description)}</dd></div> : null}
        </dl>
      )}
      {detail.kind === "ticket" && data && (
        <dl className="fields">
          <div><dt>티켓</dt><dd>{String(data.id)}</dd></div>
          <div><dt>상태</dt><dd>{String(data.status)}</dd></div>
          <div><dt>요청 유형</dt><dd>{REQUEST_TYPES[String(data.request_type)] ?? String(data.request_type)}</dd></div>
          <div><dt>분류</dt><dd>{CATEGORIES[String(data.category)] ?? String(data.category)}</dd></div>
          <div><dt>현상</dt><dd>{String(data.description)}</dd></div>
          <div><dt>접수 시각</dt><dd>{formatTime(String(data.created_at))}</dd></div>
        </dl>
      )}
    </aside>
  );
}

function CitationBody({ detail, texts }: { detail: Extract<Detail, { kind: "citation" }>; texts: (string | null)[] | null }) {
  const c = detail.citation;
  const page = c.page_spans?.[0]?.page ?? 1;
  const past = c.edition_state && c.edition_state !== "current";
  return (
    <div className="citation-detail">
      <dl className="fields">
        <div><dt>판본</dt><dd>{c.version}{past ? " (종전 판본)" : ""}</dd></div>
        <div><dt>시행</dt><dd>{c.effective_from ?? "?"} ~ {c.effective_to ?? "현재"}</dd></div>
        {c.edition_split ? (
          // D-67: 사건 날짜를 확인하지 못해 판본별로 함께 준 원문이다. 날짜는 사건 날짜가 아니라 판본 기준일이다.
          <div><dt>적용 기준</dt><dd>{DATE_BASES[c.date_basis ?? "current"] ?? c.date_basis} 미확인 (판본 기준일 {c.as_of_date ?? ""})</dd></div>
        ) : (
          <div><dt>적용 기준</dt><dd>{DATE_BASES[c.date_basis ?? "current"] ?? c.date_basis} {c.as_of_date ?? ""}{c.year_inferred ? " (연도는 서버가 추론)" : ""}</dd></div>
        )}
        {c.source_role === "transition" && <div><dt>구분</dt><dd>반대편 판본의 경과조항</dd></div>}
        <div><dt>쪽</dt><dd>{page}쪽</dd></div>
      </dl>
      {detail.group.map((g, i) => (
        <blockquote key={g.citation_id}>{texts?.[i] ?? g.quote}</blockquote>
      ))}
      {/* 서버가 만든 같은 출처 경로만 링크로 쓴다 */}
      {c.pdf_url.startsWith("/api/v1/") && (
        <a className="pdf-link" href={c.pdf_url} target="_blank" rel="noreferrer">PDF {page}쪽 열기</a>
      )}
    </div>
  );
}
