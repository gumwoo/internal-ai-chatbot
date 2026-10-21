// IT 지원 접수 확인 카드(docs/14-ticket-workflow.md, MOD-08). 확인 버튼을 누르기 전에는 접수 완료로 표시하지 않는다.
import { useEffect, useRef, useState } from "react";
import { ApiError, NetworkError, api, newKey } from "./api";
import { ACTION_STATUS, CATEGORIES, FIELD_LABELS, REQUEST_TYPES, fieldValue, formatTime } from "./labels";
import type { ActionPreview } from "./types";

const FIELDS = Object.keys(FIELD_LABELS);
type Fields = Record<string, unknown>;

function toLocalInput(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "";
  const date = new Date(iso);
  const kst = new Date(date.getTime() + 9 * 3600 * 1000);
  return kst.toISOString().slice(0, 16);
}

function fromLocalInput(value: string): string | null {
  return value ? `${value}:00+09:00` : null;
}

export function ActionCard({
  initial,
  onOpenTicket,
  onExpired,
}: {
  initial: ActionPreview;
  onOpenTicket: (id: string, title: string) => void;
  onExpired: () => void;
}) {
  const [action, setAction] = useState<ActionPreview>(initial);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Fields>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [ticket, setTicket] = useState<Record<string, unknown> | null>(null);
  // head 충돌: 이 초안은 더 이상 저장할 수 없다(새 초안으로 다시 검토, 14-ticket-workflow).
  const [stale, setStale] = useState(false);
  // 같은 대상의 재시도는 같은 멱등키를 쓴다(응답 유실 시 중복 생성 없음). 키는 action·version에 묶는다.
  const confirmKey = useRef<{ scope: string; key: string } | null>(null);
  // 렌더 전 두 번째 클릭도 막는다(busy 상태는 다음 렌더에야 반영된다).
  const inFlight = useRef(false);
  // 수정 재시도 키는 대상 action·version·입력에 묶는다(유실 뒤 같은 대상으로 다시 보내면 같은 결과).
  const reviseKey = useRef<{ scope: string; key: string } | null>(null);
  const savedFields = useRef<string | null>(null);
  const firstField = useRef<HTMLInputElement | null>(null);

  async function refresh(id = action.action_id): Promise<ActionPreview | null> {
    try {
      const { data } = await api.action(id);
      let current = data as ActionPreview;
      // 이전 메시지의 action은 current_action_id를 따라 지금 내용을 다시 보여 준다(자동 승인 없음).
      if (current.current_action_id && current.current_action_id !== current.action_id) {
        current = (await api.action(String(current.current_action_id))).data as ActionPreview;
      }
      setAction(current);
      if (current.status === "confirmed" && current.ticket_id) {
        setTicket((await api.ticket(String(current.ticket_id))).data);
      }
      return current;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onExpired();
      else if (error instanceof ApiError && error.status === 404) setNotice("이 접수 초안은 더 이상 볼 수 없습니다.");
      return null;
    }
  }

  useEffect(() => {
    void refresh(initial.action_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial.action_id]);

  useEffect(() => {
    if (editing) firstField.current?.focus();
  }, [editing]);

  function startEdit() {
    const values: Fields = {};
    for (const name of FIELDS) values[name] = action[name] ?? null;
    setForm(values);
    setNotice(null);
    setStale(false);
    savedFields.current = JSON.stringify(values);
    setEditing(true);
  }

  function explain(error: unknown): string {
    if (error instanceof NetworkError) return "응답을 받지 못했습니다. 현재 상태를 다시 확인했습니다.";
    if (!(error instanceof ApiError)) return "처리하지 못했습니다.";
    switch (error.code) {
      case "ACTION_EXPIRED":
        return "만료되어 접수되지 않았습니다. 필요하면 대화에서 다시 요청해 주세요.";
      case "ACTION_SUPERSEDED":
        return "더 새로운 내용이 있습니다. 최신 내용을 다시 확인해 주세요.";
      case "ACTION_HEAD_CONFLICT":
        return "이 초안을 만든 뒤 다른 접수 내용이 저장돼 이 초안은 더 이상 저장할 수 없습니다. 입력한 내용은 그대로 두었습니다. 최신 접수 내용을 확인하거나 대화에서 새로 요청해 주세요.";
      case "ACTION_CANCELLED":
        return "취소된 접수입니다.";
      case "ACTION_ALREADY_CONFIRMED":
        return "이미 접수가 완료됐습니다.";
      case "INVALID_REQUEST": {
        const names = (error.details?.field_names as string[] | undefined) ?? [];
        return `필수 항목을 확인해 주세요: ${names.map((n) => FIELD_LABELS[n] ?? n).join(", ")}`;
      }
      default:
        return error.message;
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    const fields: Fields = {};
    for (const name of FIELDS) {
      const value = form[name];
      fields[name] = value === "" || value === undefined ? null : value;
    }
    if (fields.urgent_work !== true) fields.urgency_reason = null; // 긴급이 아니면 사유를 보내지 않는다
    const body = JSON.stringify(fields);
    if (action.status === "pending" && body === savedFields.current) {
      // 바꾼 것이 없는 pending은 새 action을 만들지 않고 현재 상태만 다시 읽는다(MOD-08).
      setEditing(false);
      await refresh();
      return;
    }
    const scope = `${action.action_id}:${action.version}:${body}`;
    if (!reviseKey.current || reviseKey.current.scope !== scope) reviseKey.current = { scope, key: newKey() };
    inFlight.current = true;
    setBusy(true);
    try {
      const { data } = await api.revise(action.action_id, action.version, fields, reviseKey.current.key);
      setAction(data as ActionPreview);
      reviseKey.current = null;
      setEditing(false);
      setNotice("수정한 내용을 저장했습니다. 아래 내용을 확인한 뒤 '확인하고 접수'를 눌러 주세요.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return onExpired();
      setNotice(explain(error));
      if (error instanceof ApiError && error.code === "ACTION_SUPERSEDED") {
        // 입력은 그대로 두고 최신 action을 불러온다. 다시 저장하면 최신 내용 위에 이 입력으로 새 pending을 만든다.
        const current = error.details?.current_action_id;
        if (typeof current === "string") await refresh(current);
      } else if (error instanceof ApiError && error.code === "ACTION_HEAD_CONFLICT") {
        setStale(true);
        await refresh();
      } else if (error instanceof NetworkError) {
        // 저장됐을 수 있다. 같은 대상·같은 키로 다시 누르면 같은 결과를 받는다(대상은 바꾸지 않는다).
        try {
          const { data } = await api.action(action.action_id);
          if (data.status === "superseded" && data.current_action_id) {
            const latest = (await api.action(String(data.current_action_id))).data as ActionPreview;
            const same = Object.keys(fields).every((k) => JSON.stringify(latest[k] ?? null) === JSON.stringify(fields[k] ?? null));
            if (same) {
              setAction(latest);
              reviseKey.current = null;
              setEditing(false);
              setNotice("수정한 내용을 저장했습니다. 아래 내용을 확인한 뒤 '확인하고 접수'를 눌러 주세요.");
            }
          }
        } catch {
          // 다시 연결되면 같은 키로 재시도한다
        }
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function confirm() {
    if (inFlight.current) return;
    const scope = `${action.action_id}:${action.version}`;
    if (!confirmKey.current || confirmKey.current.scope !== scope) confirmKey.current = { scope, key: newKey() };
    inFlight.current = true;
    setBusy(true);
    setNotice(null);
    try {
      const { data } = await api.confirm(action.action_id, action.version, confirmKey.current.key);
      const result = data as { ticket: Record<string, unknown> | null };
      setTicket(result.ticket);
      await refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return onExpired();
      setNotice(explain(error));
      await refresh(); // 등록 실패로 단정하지 않고 실제 상태를 읽는다
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function cancel() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const { data } = await api.cancel(action.action_id, action.version);
      setAction(data as ActionPreview);
      setNotice("접수를 취소했습니다.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return onExpired();
      setNotice(explain(error));
      await refresh();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const live = action.status === "draft" || action.status === "pending";
  const missing = action.missing_fields ?? [];
  // 채운 항목과 꼭 필요한 빈 항목만 줄로 보이고, 선택 항목 중 빈 것은 한 줄로 모은다.
  const empty = (name: string) => action[name] === null || action[name] === undefined || action[name] === "";
  const rows = FIELDS.filter((name) => !empty(name) || missing.includes(name));
  const blank = FIELDS.filter((name) => empty(name) && !missing.includes(name));
  return (
    <section className="action-card" aria-label="IT 지원 접수 확인" data-status={action.status}>
      <header>
        <strong>IT 지원 접수</strong>
        <span className={`status status-${action.status}`}>{ACTION_STATUS[action.status] ?? action.status}</span>
      </header>
      {!editing && (
        <dl className="fields">
          {rows.map((name) => (
            <div key={name} className={missing.includes(name) ? "missing" : undefined}>
              <dt>{FIELD_LABELS[name]}</dt>
              <dd>{missing.includes(name) && empty(name) ? <span className="need">입력 필요</span> : fieldValue(name, action[name])}</dd>
            </div>
          ))}
          <div>
            <dt>회신</dt>
            <dd>{String(action.reply_channel ?? "")}</dd>
          </div>
        </dl>
      )}
      {!editing && blank.length > 0 && (
        <p className="hint">비어 있는 선택 항목: {blank.map((n) => FIELD_LABELS[n] ?? n).join(", ")}</p>
      )}
      {!editing && missing.length > 0 && live && (
        <p className="hint">접수하려면 "내용 수정"에서 채워 주세요: {missing.map((n) => FIELD_LABELS[n] ?? n).join(", ")}</p>
      )}
      {live && !editing && <p className="hint">{formatTime(action.expires_at)}까지 확인하지 않으면 이 초안은 만료돼요.</p>}
      {editing && (
        <form className="ticket-form" onSubmit={save} aria-label="접수 내용 수정">
          <label>
            제목
            <input ref={firstField} name="subject" value={String(form.subject ?? "")} maxLength={120}
              onChange={(e) => setForm({ ...form, subject: e.target.value })} />
          </label>
          <label>
            현상
            <textarea name="description" value={String(form.description ?? "")} maxLength={4000}
              onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <label>
            요청 유형
            <select name="request_type" value={String(form.request_type ?? "")} onChange={(e) => setForm({ ...form, request_type: e.target.value })}>
              <option value="">선택</option>
              {Object.entries(REQUEST_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            분류
            <select name="category" value={String(form.category ?? "")} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              <option value="">선택</option>
              {Object.entries(CATEGORIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            대상 서비스
            <input name="target_service" value={String(form.target_service ?? "")} maxLength={120}
              onChange={(e) => setForm({ ...form, target_service: e.target.value })} />
          </label>
          <label>
            발생 시각(장애일 때)
            <input type="datetime-local" name="occurred_at" value={toLocalInput(form.occurred_at)}
              onChange={(e) => setForm({ ...form, occurred_at: fromLocalInput(e.target.value) })} />
          </label>
          <label>
            영향 범위(확인된 것만)
            <input name="impact_scope" value={String(form.impact_scope ?? "")} maxLength={500}
              onChange={(e) => setForm({ ...form, impact_scope: e.target.value })} />
          </label>
          <label>
            긴급 업무
            <select name="urgent_work" value={form.urgent_work === null || form.urgent_work === undefined ? "" : String(form.urgent_work)}
              onChange={(e) => setForm({ ...form, urgent_work: e.target.value === "" ? null : e.target.value === "true" })}>
              <option value="">선택</option>
              <option value="true">예</option>
              <option value="false">아니요</option>
            </select>
          </label>
          {form.urgent_work === true && (
            <label>
              긴급 사유
              <input name="urgency_reason" value={String(form.urgency_reason ?? "")} maxLength={500}
                onChange={(e) => setForm({ ...form, urgency_reason: e.target.value })} />
            </label>
          )}
          <label>
            자산번호(아는 경우)
            <input name="asset_identifier" value={String(form.asset_identifier ?? "")} maxLength={120}
              onChange={(e) => setForm({ ...form, asset_identifier: e.target.value })} />
          </label>
          <p className="hint">비밀번호·인증 코드는 입력하지 마세요.</p>
          <div className="buttons">
            <button type="submit" disabled={busy || stale}>저장</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => { setEditing(false); setNotice(null); }}>
              편집 취소
            </button>
          </div>
        </form>
      )}
      {!editing && live && (
        <div className="buttons">
          <button type="button" className="secondary" disabled={busy} onClick={startEdit}>내용 수정</button>
          {action.status === "pending" && (
            <button type="button" disabled={busy} aria-busy={busy} onClick={confirm}>확인하고 접수</button>
          )}
          <button type="button" className="secondary" disabled={busy} onClick={cancel}>접수 취소</button>
        </div>
      )}
      {action.status === "confirmed" && ticket && (
        <p className="done">
          접수가 완료됐습니다. 티켓{" "}
          <button type="button" className="link" onClick={() => onOpenTicket(String(ticket.id), String(ticket.subject))}>
            {String(ticket.id).slice(0, 8)}
          </button>{" "}
          · {String(ticket.status)}
        </p>
      )}
      {notice && <p className="notice" role="status">{notice}</p>}
    </section>
  );
}
