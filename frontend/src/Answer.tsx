// 답 본문과 근거(D-75·D-76). 본문의 [c1-2] 표시는 근거 번호로 바꾸고, 아래에는 문서별로 쪽을 모아 보인다.
// 번호·쪽·판본은 서버 인용 DTO에서만 만든다(모델 문장에서 뽑지 않는다).
import type { Citation } from "./types";

const MARKER = /\s?\[(c\d+-\d+(?:\s*[,，]\s*c\d+-\d+)*)\]/g;

/** 같은 문서·판본·쪽·적용 기준의 원문 조각 묶음. */
export interface PageGroup {
  key: string;
  number: number;
  citations: Citation[];
}

export interface DocumentGroup {
  key: string;
  title: string;
  version: string;
  past: boolean;
  pages: PageGroup[];
}

const pageOf = (c: Citation) => c.page_spans?.[0]?.page ?? 1;
const isPast = (c: Citation) => Boolean(c.edition_state && c.edition_state !== "current");

function markerIds(text: string): string[] {
  const ids: string[] = [];
  for (const match of text.matchAll(MARKER)) {
    for (const id of match[1].split(/\s*[,，]\s*/)) if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

/** 쪽 묶음을 만들고, 본문에 먼저 나온 근거부터 1, 2, 3… 번호를 붙인다. */
export function groupCitations(citations: Citation[], answer: string): { pages: PageGroup[]; documents: DocumentGroup[]; byId: Map<string, PageGroup> } {
  const groups = new Map<string, PageGroup>();
  const byId = new Map<string, PageGroup>();
  for (const c of citations) {
    const key = [c.title, c.version, pageOf(c), c.edition_state, c.as_of_date, c.date_basis, c.edition_split ?? false, c.source_role ?? ""].join("|");
    let group = groups.get(key);
    if (!group) groups.set(key, (group = { key, number: 0, citations: [] }));
    if (!group.citations.some((g) => g.passage_id === c.passage_id)) group.citations.push(c);
    byId.set(c.citation_id, group);
  }
  const ordered: PageGroup[] = [];
  for (const id of markerIds(answer)) {
    const group = byId.get(id);
    if (group && !ordered.includes(group)) ordered.push(group);
  }
  for (const group of groups.values()) if (!ordered.includes(group)) ordered.push(group);
  ordered.forEach((g, i) => (g.number = i + 1));

  const documents = new Map<string, DocumentGroup>();
  for (const group of ordered) {
    const c = group.citations[0];
    const key = [c.title, c.version, c.edition_state].join("|");
    let doc = documents.get(key);
    if (!doc) documents.set(key, (doc = { key, title: c.title, version: c.version, past: isPast(c), pages: [] }));
    doc.pages.push(group);
  }
  return { pages: ordered, documents: [...documents.values()], byId };
}

function Preview({ group }: { group: PageGroup }) {
  const c = group.citations[0];
  const quote = c.quote.length > 160 ? `${c.quote.slice(0, 160)}…` : c.quote;
  return (
    <span className="preview" role="tooltip">
      <span className="preview-title">{c.title} · {pageOf(c)}쪽{isPast(c) ? " · 종전 판본" : ""}</span>
      <span className="preview-quote">{quote}</span>
    </span>
  );
}

function citationLabel(group: PageGroup): string {
  const c = group.citations[0];
  return `근거 ${group.number}: ${c.title} ${c.version} ${pageOf(c)}쪽${isPast(c) ? " 종전 판본" : ""}`;
}

type Open = (group: PageGroup, opener: HTMLElement) => void;

/** 본문 한 줄: 인용 표시를 근거 번호 버튼으로 바꾼다. 원장에 없는 표시는 서버가 이미 지웠다. */
function Inline({ text, byId, onOpen }: { text: string; byId: Map<string, PageGroup>; onOpen: Open }) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    // 번호가 혼자 다음 줄로 넘어가지 않게 앞 낱말·문장 부호·번호를 한 덩어리로 묶는다.
    // 문장 부호는 각주처럼 번호 앞으로 옮긴다.
    const before = text.slice(last, match.index);
    const word = /\S+$/.exec(before)?.[0] ?? "";
    const end = (match.index ?? 0) + match[0].length;
    const punctuation = /^[.,!?)」』…]+/.exec(text.slice(end))?.[0] ?? "";
    parts.push(before.slice(0, before.length - word.length));
    const groups: PageGroup[] = [];
    for (const id of match[1].split(/\s*[,，]\s*/)) {
      const group = byId.get(id);
      if (group && !groups.includes(group)) groups.push(group);
    }
    parts.push(
      <span className="cite-glue" key={match.index}>
        {word}
        {punctuation}
        {groups.map((group) => (
          <span className="cite-wrap" key={group.key}>
            <button type="button" className="cite-mark" aria-label={citationLabel(group)}
              onClick={(e) => onOpen(group, e.currentTarget)}>
              {group.number}
            </button>
            <Preview group={group} />
          </span>
        ))}
      </span>,
    );
    last = end + punctuation.length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

/** 답 본문: 빈 줄로 문단을 나누고 "- "로 시작하는 줄은 목록으로 보인다. */
export function AnswerText({ text, byId, onOpen }: { text: string; byId: Map<string, PageGroup>; onOpen: Open }) {
  const blocks: ({ kind: "p"; lines: string[] } | { kind: "ul"; items: string[] })[] = [];
  for (const line of text.split("\n")) {
    const item = /^\s*[-•]\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];
    if (item) {
      if (last?.kind === "ul") last.items.push(item[1]);
      else blocks.push({ kind: "ul", items: [item[1]] });
    } else if (!line.trim()) {
      if (last && !(last.kind === "p" && last.lines.length === 0)) blocks.push({ kind: "p", lines: [] });
    } else if (last?.kind === "p") last.lines.push(line);
    else blocks.push({ kind: "p", lines: [line] });
  }
  return (
    <div className="answer">
      {blocks.map((b, i) =>
        b.kind === "ul" ? (
          <ul key={i}>{b.items.map((item, j) => <li key={j}><Inline text={item} byId={byId} onOpen={onOpen} /></li>)}</ul>
        ) : b.lines.length > 0 ? (
          <p key={i}><Inline text={b.lines.join("\n")} byId={byId} onOpen={onOpen} /></p>
        ) : null,
      )}
    </div>
  );
}

/** 답 아래 근거: 문서마다 한 줄, 쪽은 번호가 붙은 작은 버튼. 마우스를 올리면 원문 일부를 미리 보인다. */
export function Sources({ documents, onOpen }: { documents: DocumentGroup[]; onOpen: Open }) {
  return (
    <section className="sources" aria-label="근거 원문">
      <h3>참고한 문서</h3>
      <ul>
        {documents.map((doc) => (
          <li key={doc.key} className="source">
            <span className="source-name">
              {doc.title}
              <span className="source-version">{doc.version}</span>
              {doc.past && !doc.title.includes("종전") && <span className="tag">종전</span>}
            </span>
            <span className="source-pages">
              {doc.pages.map((group) => (
                <span className="cite-wrap" key={group.key}>
                  <button type="button" className="citation" aria-label={citationLabel(group)}
                    onClick={(e) => onOpen(group, e.currentTarget)}>
                    <span className="cite-no">{group.number}</span>
                    {pageOf(group.citations[0])}쪽
                  </button>
                  <Preview group={group} />
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
