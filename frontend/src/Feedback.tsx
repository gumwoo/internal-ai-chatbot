// 답변 피드백(D-77). "도움이 됐어요"는 바로 저장하고, "아쉬워요"는 사유를 고른 뒤 저장한다.
import { useState } from "react";
import { ApiError, api } from "./api";
import { FEEDBACK_REASONS } from "./labels";
import type { Feedback as Saved } from "./types";

export function Feedback({
  conversationId,
  messageId,
  initial,
  onExpired,
}: {
  conversationId: string;
  messageId: string;
  initial: Saved | null;
  onExpired: () => void;
}) {
  const [saved, setSaved] = useState<Saved | null>(initial);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string>(initial?.reason ?? "wrong_source");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function send(body: Saved & { comment?: string | null }) {
    setBusy(true);
    setNotice(null);
    try {
      const { data } = await api.feedback(conversationId, messageId, body);
      setSaved({ rating: data.rating, reason: data.reason });
      setOpen(false);
      setNotice(body.rating === "helpful" ? "의견을 남겼어요." : "의견을 남겼어요. 확인해서 고칠게요.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return onExpired();
      setNotice("의견을 저장하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="feedback">
      <div className="feedback-buttons" role="group" aria-label="답변 평가">
        <button type="button" className={`chip${saved?.rating === "helpful" ? " on" : ""}`} aria-pressed={saved?.rating === "helpful"}
          disabled={busy} onClick={() => void send({ rating: "helpful", reason: null })}>
          도움이 됐어요
        </button>
        <button type="button" className={`chip${saved?.rating === "not_helpful" ? " on" : ""}`} aria-pressed={saved?.rating === "not_helpful"}
          aria-expanded={open} disabled={busy} onClick={() => setOpen(!open)}>
          아쉬워요
        </button>
      </div>
      {open && (
        <form className="feedback-form" aria-label="아쉬운 점"
          onSubmit={(e) => { e.preventDefault(); void send({ rating: "not_helpful", reason, comment: comment.trim() || null }); }}>
          <fieldset>
            <legend>어떤 점이 아쉬웠나요?</legend>
            {Object.entries(FEEDBACK_REASONS).map(([value, label]) => (
              <label key={value} className="option">
                <input type="radio" name={`reason-${messageId}`} value={value} checked={reason === value}
                  onChange={() => setReason(value)} />
                {label}
              </label>
            ))}
          </fieldset>
          <label>
            <span className="visually-hidden">자세한 내용</span>
            <textarea value={comment} maxLength={500} placeholder="자세히 적어 주시면 고치는 데 도움이 돼요(선택)"
              onChange={(e) => setComment(e.target.value)} />
          </label>
          <div className="buttons">
            <button type="submit" disabled={busy}>의견 보내기</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setOpen(false)}>닫기</button>
          </div>
        </form>
      )}
      {notice && <p className="feedback-notice" role="status">{notice}</p>}
    </div>
  );
}
