// 업무 대화 화면: 왼쪽 대화 목록, 가운데 대화, 선택적 오른쪽 상세(docs/ui/01-screen-proposal.md).
import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ActionCard } from "./ActionCard";
import { AnswerText, Sources, groupCitations, type PageGroup } from "./Answer";
import { ApiError, NetworkError, api, newKey, sendMessage } from "./api";
import { DetailPanel } from "./Detail";
import { Feedback } from "./Feedback";
import { OUTCOMES, STAGES } from "./labels";
import type { Conversation, Detail, MessageResult, SessionInfo, StoredMessage } from "./types";

type Pending = { content: string; key: string; conversationId: string };

// 첫 화면 예시 질문. 누르면 바로 보낸다.
const EXAMPLES = [
  { topic: "교육 일정", text: "다음 주에 들을 수 있는 교육 알려줘" },
  { topic: "회사 규정", text: "출장비 정산은 언제까지 해야 해요?" },
  { topic: "IT 지원", text: "VPN이 안 돼요. 접수해 주세요" },
];

function fromResult(result: MessageResult, content: string): StoredMessage[] {
  return [
    {
      id: `${result.message_id}-q`, role: "user", visibility: "visible", content, outcome: null,
      training_refs: [], citations: [], ticket_refs: [], action_preview: null, run_id: result.run_id, created_at: "",
    },
    {
      id: result.message_id, role: "assistant", visibility: "visible", content: result.answer, outcome: result.outcome,
      training_refs: result.training_refs, citations: result.citations, ticket_refs: result.ticket_refs,
      action_preview: result.action_preview, run_id: result.run_id, created_at: "", feedback: null,
    },
  ];
}

const DAY = 24 * 3600 * 1000;
const kstDay = (time: number) => Math.floor((time + 9 * 3600 * 1000) / DAY);

/** 대화 목록을 만든 날짜로 묶는다(한국 시간 기준). 목록은 서버가 최근순으로 준다. */
function byDay(items: Conversation[], now = Date.now()): { label: string; items: Conversation[] }[] {
  const today = kstDay(now);
  const label = (iso: string) => {
    const days = today - kstDay(new Date(iso).getTime());
    if (days <= 0) return "오늘";
    if (days === 1) return "어제";
    if (days < 7) return "지난 7일";
    if (days < 30) return "지난 30일";
    return "그 이전";
  };
  const groups: { label: string; items: Conversation[] }[] = [];
  for (const item of items) {
    const name = label(item.created_at);
    const last = groups[groups.length - 1];
    if (last?.label === name) last.items.push(item);
    else groups.push({ label: name, items: [item] });
  }
  return groups;
}

export function Workspace({ session, onLogout, onExpired }: { session: SessionInfo; onLogout: () => void; onExpired: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
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
  const bottom = useRef<HTMLDivElement | null>(null);
  const queryRef = useRef("");

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
    const q = queryRef.current;
    try {
      const items = (await api.conversations(q)).data.items;
      if (queryRef.current === q) setConversations(items); // 늦게 온 이전 검색 결과는 버린다
    } catch (error) {
      handle(error);
    }
  }, [handle]);

  useEffect(() => {
    queryRef.current = query;
    const timer = setTimeout(() => void loadConversations(), query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [query, loadConversations]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [messages, busy]);

  // 입력창은 내용에 맞춰 늘어난다(최대 높이는 CSS).
  useEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

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
      if (!handle(error)) setFailure({ message: "대화를 불러오지 못했어요.", retry: false });
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

  async function send(text?: string) {
    const content = text ?? (draft.trim() ? draft : "");
    if (!content || busy) return;
    if (text !== undefined) setDraft(text);
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
        setAnnounce("새 답변이 도착했어요.");
      } else {
        setAnnounce("다른 대화의 답변이 도착했어요. 그 대화를 열면 볼 수 있어요.");
      }
    } catch (error) {
      if (handle(error)) return;
      if (error instanceof NetworkError) {
        // 결과를 모른다: 같은 키로 다시 보내 같은 실행의 결과를 받는다.
        setFailure({ message: "응답을 받지 못했어요. 다시 보내면 같은 요청으로 이어져요.", retry: true });
      } else if (error instanceof ApiError) {
        // 서버가 실패로 끝낸 실행: 같은 키는 같은 실패를 돌려주므로 다시 보낼 때는 새 요청으로 보낸다.
        pending.current = null;
        setFailure({ message: error.message, retry: error.retryable });
      } else setFailure({ message: "처리하지 못했어요.", retry: false });
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

  const groups = byDay(conversations);
  return (
    <div className={`workspace${detail ? " with-detail" : ""}`}>
      <button type="button" className="menu-toggle secondary" aria-expanded={menuOpen} aria-controls="conversation-list"
        onClick={() => setMenuOpen(!menuOpen)}>
        대화 목록 {menuOpen ? "닫기" : "열기"}
      </button>
      <nav id="conversation-list" className={`sidebar${menuOpen ? " open" : ""}`} aria-label="대화 목록"
        onKeyDown={(e) => e.key === "Escape" && setMenuOpen(false)}>
        <p className="brand">사내 업무 도우미</p>
        {/* 답을 기다리는 동안에는 대화를 바꾸지 않는다(답과 진행 상태가 다른 대화에 섞이지 않게) */}
        <button type="button" id="new-conversation" className="new" disabled={busy} onClick={startNew}>새 대화</button>
        <label className="search">
          <span className="visually-hidden">대화 검색</span>
          <input type="search" value={query} maxLength={100} placeholder="대화 검색" onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="history">
          {groups.length === 0 && <p className="history-empty">{query.trim() ? "찾는 대화가 없어요." : "아직 대화가 없어요."}</p>}
          {groups.map((group) => (
            <section key={group.label} aria-label={group.label}>
              <h3>{group.label}</h3>
              <ul>
                {group.items.map((c) => (
                  <li key={c.id}>
                    <button type="button" className={c.id === current ? "selected" : "plain"} aria-current={c.id === current}
                      data-id={c.id} disabled={busy} onClick={() => open(c.id)} title={c.title ?? undefined}>
                      {c.title ?? "이름 없는 대화"}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="me">
          <span>{session.display_name}</span>
          <button type="button" className="secondary" onClick={logout}>로그아웃</button>
        </div>
      </nav>
      <main className="conversation" aria-label="업무 대화">
        <p className="visually-hidden" role="status">{announce}</p>
        <div className="messages">
          {messages.length === 0 && !busy && (
            <div className="welcome">
              <h2>{session.display_name}님, 안녕하세요</h2>
              <p>교육 일정, 회사 규정, IT 지원 접수를 여기서 물어볼 수 있어요. 규정 답변에는 근거 문서와 쪽이 함께 붙어요.</p>
              <ul className="examples" aria-label="이렇게 물어볼 수 있어요">
                {EXAMPLES.map((example) => (
                  <li key={example.text}>
                    <button type="button" className="example" onClick={() => void send(example.text)}>
                      <span className="example-topic">{example.topic}</span>
                      {example.text}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {messages.map((m) => (
            <MessageView key={m.id} message={m} conversationId={current} onDetail={openDetail} onExpired={onExpired} />
          ))}
          {busy && <p className="progress" role="status">{stage ? STAGES[stage] ?? "처리하고 있어요" : "처리하고 있어요"}</p>}
          <div ref={bottom} />
        </div>
        {failure && (
          <p className="notice" role="alert">
            {failure.message}{" "}
            {failure.retry && <button type="button" className="link" onClick={() => void send()}>다시 보내기</button>}
          </p>
        )}
        <form className="composer" aria-busy={busy} onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <div className="composer-box">
            <label htmlFor="composer-input" className="visually-hidden">질문</label>
            <textarea id="composer-input" ref={input} value={draft} maxLength={4000} rows={1} placeholder="궁금한 내용을 입력하세요"
              onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} />
            <button type="submit" id="send-button" disabled={busy || !draft.trim()}>보내기</button>
          </div>
          <p className="composer-hint">Enter로 보내고, Shift+Enter로 줄을 바꿔요.</p>
        </form>
      </main>
      {detail && <DetailPanel detail={detail} onClose={closeDetail} onExpired={onExpired} />}
    </div>
  );
}

function MessageView({
  message,
  conversationId,
  onDetail,
  onExpired,
}: {
  message: StoredMessage;
  conversationId: string | null;
  onDetail: (detail: Detail, opener: HTMLElement) => void;
  onExpired: () => void;
}) {
  if (message.role === "user") return <div className="message user"><p>{message.content}</p></div>;
  const { documents, byId } = groupCitations(message.citations, message.content);
  const openGroup = (group: PageGroup, opener: HTMLElement) =>
    onDetail({ kind: "citation", citation: group.citations[0], group: group.citations }, opener);
  const badge = message.outcome ? OUTCOMES[message.outcome] : undefined;
  const redacted = message.visibility === "redacted";
  return (
    <article className={`message assistant${redacted ? " redacted" : ""}`} data-outcome={message.outcome ?? ""}>
      {badge && <span className="badge">{badge}</span>}
      <AnswerText text={message.content} byId={byId} onOpen={openGroup} />
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
      {documents.length > 0 && <Sources documents={documents} onOpen={openGroup} />}
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
      {!redacted && conversationId && (
        <Feedback conversationId={conversationId} messageId={message.id} initial={message.feedback ?? null} onExpired={onExpired} />
      )}
    </article>
  );
}
