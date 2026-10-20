// 업무 대화 화면: 왼쪽 대화 목록, 가운데 대화, 선택적 오른쪽 상세(docs/ui/01-screen-proposal.md).
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ActionCard } from "./ActionCard";
import { ApiError, NetworkError, api, newKey, sendMessage } from "./api";
import { DetailPanel } from "./Detail";
import { OUTCOMES, STAGES, formatTime } from "./labels";
import type { Citation, Conversation, Detail, MessageResult, SessionInfo, StoredMessage } from "./types";

type Pending = { content: string; key: string; conversationId: string };

function fromResult(result: MessageResult, content: string): StoredMessage[] {
  return [
    {
      id: `${result.message_id}-q`, role: "user", visibility: "visible", content, outcome: null,
      training_refs: [], citations: [], ticket_refs: [], action_preview: null, run_id: result.run_id, created_at: "",
    },
    {
      id: result.message_id, role: "assistant", visibility: "visible", content: result.answer, outcome: result.outcome,
      training_refs: result.training_refs, citations: result.citations, ticket_refs: result.ticket_refs,
      action_preview: result.action_preview, run_id: result.run_id, created_at: "",
    },
  ];
}

export function Workspace({ session, onLogout, onExpired }: { session: SessionInfo; onLogout: () => void; onExpired: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [current, setCurrent] = useState<string | null>(null);
  const [messages, setMessages] = useState<StoredMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [stage, setStage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ message: string; retry: boolean } | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const pending = useRef<Pending | null>(null);
  // 응답이 도착했을 때 화면에 열린 대화가 보낸 대화와 같은지 확인한다(다른 대화에 답이 붙지 않게).
  const shown = useRef<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const detailOpener = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLTextAreaElement | null>(null);

  const handle = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && (error.code === "AUTHENTICATION_REQUIRED" || error.code === "SESSION_EXPIRED")) {
        onExpired();
        return true;
      }
      return false;
    },
    [onExpired],
  );

  const loadConversations = useCallback(async () => {
    try {
      setConversations((await api.conversations()).data.items);
    } catch (error) {
      handle(error);
    }
  }, [handle]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  async function open(id: string) {
    if (busy) return;
    shown.current = id;
    setCurrent(id);
    setMenuOpen(false);
    setDetail(null);
    setFailure(null);
    try {
      const items = (await api.messages(id)).data.items;
      if (shown.current === id) setMessages(items); // 늦게 온 이전 대화 응답은 버린다
    } catch (error) {
      if (!handle(error)) setFailure({ message: "대화를 불러오지 못했습니다.", retry: false });
    }
    input.current?.focus();
  }

  function startNew() {
    if (busy) return;
    shown.current = null;
    setCurrent(null);
    setMessages([]);
    setDetail(null);
    setFailure(null);
    setMenuOpen(false);
    input.current?.focus();
  }

  async function send() {
    const content = draft.trim() ? draft : "";
    if (!content || busy) return;
    setBusy(true);
    setFailure(null);
    setStage(null);
    try {
      let conversationId = current;
      const created = !conversationId;
      if (!conversationId) {
        conversationId = (await api.createConversation()).data.id;
        shown.current = conversationId;
        setCurrent(conversationId);
        void loadConversations();
      }
      // 같은 입력의 재시도는 같은 멱등키(응답 유실 시 같은 run을 다시 받는다).
      if (!pending.current || pending.current.content !== content || pending.current.conversationId !== conversationId) {
        pending.current = { content, key: newKey(), conversationId };
      }
      // 진행 단계와 결과가 한 덩어리로 도착하면(빠른 응답) React가 갱신을 묶어 단계가 화면에 한 번도
      // 그려지지 않는다. 단계마다 바로 반영해 서버가 보낸 단계를 화면에 남긴다(D-29).
      const result = await sendMessage(conversationId, content, pending.current.key, (next) =>
        flushSync(() => setStage(next)),
      );
      pending.current = null;
      setDraft("");
      if (created) void loadConversations(); // 첫 질문이 대화 이름이 되므로 목록을 다시 읽는다
      if (shown.current === conversationId) {
        setMessages((previous) => [...previous, ...fromResult(result, content)]);
        setAnnounce("새 답변이 도착했습니다.");
      } else {
        setAnnounce("다른 대화의 답변이 도착했습니다. 그 대화를 열면 볼 수 있습니다.");
      }
    } catch (error) {
      if (handle(error)) return;
      if (error instanceof NetworkError) {
        // 결과를 모른다: 같은 키로 다시 보내 같은 실행의 결과를 받는다.
        setFailure({ message: "응답을 받지 못했습니다. 다시 보내면 같은 요청으로 이어집니다.", retry: true });
      } else if (error instanceof ApiError) {
        // 서버가 실패로 끝낸 실행: 같은 키는 같은 실패를 돌려주므로 다시 보낼 때는 새 요청으로 보낸다.
        pending.current = null;
        setFailure({ message: error.message, retry: error.retryable });
      } else setFailure({ message: "처리하지 못했습니다.", retry: false });
    } finally {
      setBusy(false);
      setStage(null);
    }
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중 Enter는 전송하지 않는다(IME). Shift+Enter는 줄바꿈.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      void send();
    }
  }

  function openDetail(next: Detail, opener: HTMLElement) {
    detailOpener.current = opener;
    setDetail(next);
  }

  function closeDetail() {
    setDetail(null);
    detailOpener.current?.focus(); // 닫으면 원래 위치로 포커스를 돌려준다
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      // 이미 만료된 세션이어도 화면 캐시는 지운다
    }
    onLogout();
  }

  return (
    <div className={`workspace${detail ? " with-detail" : ""}`}>
      <button type="button" className="menu-toggle secondary" aria-expanded={menuOpen} aria-controls="conversation-list"
        onClick={() => setMenuOpen(!menuOpen)}>
        대화 목록 {menuOpen ? "닫기" : "열기"}
      </button>
      <nav id="conversation-list" className={`sidebar${menuOpen ? " open" : ""}`} aria-label="대화 목록"
        onKeyDown={(e) => e.key === "Escape" && setMenuOpen(false)}>
        {/* 답을 기다리는 동안에는 대화를 바꾸지 않는다(답과 진행 상태가 다른 대화에 섞이지 않게) */}
        <button type="button" id="new-conversation" disabled={busy} onClick={startNew}>새 대화</button>
        <ul>
          {conversations.map((c) => (
            <li key={c.id}>
              <button type="button" className={c.id === current ? "selected" : "plain"} aria-current={c.id === current}
                data-id={c.id} disabled={busy} onClick={() => open(c.id)} title={c.title ?? undefined}>
                {c.title ?? `대화 · ${formatTime(c.created_at)}`}
              </button>
            </li>
          ))}
        </ul>
        <div className="me">
          <span>{session.display_name}</span>
          <button type="button" className="secondary" onClick={logout}>로그아웃</button>
        </div>
      </nav>
      <main className="conversation" aria-label="업무 대화">
        <p className="visually-hidden" role="status">{announce}</p>
        <div className="messages">
          {messages.length === 0 && <p className="empty">교육 일정, 회사 규정, IT 지원을 물어보세요.</p>}
          {messages.map((m) => (
            <MessageView key={m.id} message={m} onDetail={openDetail} onExpired={onExpired} />
          ))}
        </div>
        {busy && <p className="progress" role="status">{stage ? STAGES[stage] ?? "처리 중" : "처리 중"}</p>}
        {failure && (
          <p className="notice" role="alert">
            {failure.message}{" "}
            {failure.retry && <button type="button" className="link" onClick={() => void send()}>다시 보내기</button>}
          </p>
        )}
        <form className="composer" aria-busy={busy} onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <label htmlFor="composer-input" className="visually-hidden">질문</label>
          <textarea id="composer-input" ref={input} value={draft} maxLength={4000} placeholder="질문을 입력하세요"
            onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} />
          <button type="submit" id="send-button" disabled={busy || !draft.trim()}>보내기</button>
        </form>
      </main>
      {detail && <DetailPanel detail={detail} onClose={closeDetail} onExpired={onExpired} />}
    </div>
  );
}

function MessageView({
  message,
  onDetail,
  onExpired,
}: {
  message: StoredMessage;
  onDetail: (detail: Detail, opener: HTMLElement) => void;
  onExpired: () => void;
}) {
  if (message.role === "user") return <div className="message user"><p>{message.content}</p></div>;
  return (
    <article className={`message assistant${message.visibility === "redacted" ? " redacted" : ""}`} data-outcome={message.outcome ?? ""}>
      {message.outcome && message.outcome !== "answered" && <span className="badge">{OUTCOMES[message.outcome] ?? message.outcome}</span>}
      <AnswerText text={message.content} />
      {message.training_refs.length > 0 && (
        <ul className="refs" aria-label="교육">
          {message.training_refs.map((t) => (
            <li key={t.id}>
              <button type="button" className="ref" onClick={(e) => onDetail({ kind: "training", id: t.id, title: t.title }, e.currentTarget)}>
                {t.title}
              </button>
            </li>
          ))}
        </ul>
      )}
      {message.citations.length > 0 && (
        <ul className="refs" aria-label="근거 원문">
          {groupCitations(message.citations).map((group) => {
            const c = group[0];
            return (
              <li key={c.citation_id}>
                <button type="button" className="citation"
                  onClick={(e) => onDetail({ kind: "citation", citation: c, group }, e.currentTarget)}>
                  {c.title} · {c.version} · {c.page_spans?.[0]?.page ?? 1}쪽
                  {c.edition_state && c.edition_state !== "current" ? " · 종전" : ""}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {message.ticket_refs.length > 0 && (
        <ul className="refs" aria-label="티켓">
          {message.ticket_refs.map((t) => (
            <li key={t.id}>
              <button type="button" className="ref" onClick={(e) => onDetail({ kind: "ticket", id: t.id, title: t.subject }, e.currentTarget)}>
                {t.subject} · {t.status}
              </button>
            </li>
          ))}
        </ul>
      )}
      {message.action_preview && (
        <ActionCard
          initial={message.action_preview}
          onExpired={onExpired}
          onOpenTicket={(id, title) => onDetail({ kind: "ticket", id, title }, document.activeElement as HTMLElement)}
        />
      )}
    </article>
  );
}

// 같은 문서·판본·쪽·적용 기준의 원문 조각은 버튼 하나로 묶는다. 처음 나온 순서를 지킨다.
function groupCitations(citations: Citation[]): Citation[][] {
  const groups = new Map<string, Citation[]>();
  for (const c of citations) {
    const key = [c.title, c.version, c.page_spans?.[0]?.page ?? 1, c.edition_state, c.as_of_date, c.date_basis,
      c.edition_split ?? false, c.source_role ?? ""].join("|");
    const group = groups.get(key);
    if (!group) groups.set(key, [c]);
    else if (!group.some((g) => g.passage_id === c.passage_id)) group.push(c);
  }
  return [...groups.values()];
}

// 답 본문: 빈 줄로 문단을 나누고, "- "로 시작하는 줄은 목록으로 보인다. 그 밖의 글자는 그대로 둔다.
function AnswerText({ text }: { text: string }) {
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
          <ul key={i}>{b.items.map((item, j) => <li key={j}>{item}</li>)}</ul>
        ) : b.lines.length > 0 ? (
          <p key={i}>{b.lines.join("\n")}</p>
        ) : null,
      )}
    </div>
  );
}
