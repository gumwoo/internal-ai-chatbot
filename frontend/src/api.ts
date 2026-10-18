// HTTP 클라이언트(docs/04-api-spec.md). 서버가 판정한 값만 쓴다(권한·날짜·ID를 화면에서 만들지 않는다).
import type { Conversation, MessageResult, Page, SessionInfo, StoredMessage } from "./types";

const BASE = "/api/v1";
let csrfToken: string | null = null;

export function setCsrf(token: string | null): void {
  csrfToken = token;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> | null = null,
    readonly retryable = false,
    readonly runId: string | null = null,
  ) {
    super(message);
  }
}

/** 네트워크가 끊겨 결과를 모르는 경우(서버에서는 성공했을 수 있다). 새 작업으로 재시도하지 않는다. */
export class NetworkError extends Error {}

type Body = Record<string, unknown> | undefined;

function errorFrom(status: number, data: unknown): ApiError {
  const envelope = (data as { error?: Record<string, unknown>; run_id?: string } | null) ?? null;
  const error = envelope?.error ?? {};
  return new ApiError(
    status,
    String(error.code ?? "SERVICE_UNAVAILABLE"),
    String(error.message ?? "지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요."),
    (error.details as Record<string, unknown> | null) ?? null,
    Boolean(error.retryable),
    envelope?.run_id ?? null,
  );
}

export async function call<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: Body,
  headers: Record<string, string> = {},
): Promise<{ status: number; data: T }> {
  const write = method !== "GET";
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method,
      credentials: "same-origin",
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(write && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new NetworkError("서버와 연결이 끊겼습니다.");
  }
  if (response.status === 204) return { status: 204, data: null as T };
  const data = await response.json().catch(() => null);
  if (!response.ok) throw errorFrom(response.status, data);
  return { status: response.status, data: data as T };
}

export const api = {
  session: () => call<SessionInfo>("GET", "/session"),
  login: (username: string, password: string) => call<SessionInfo>("POST", "/session", { username, password }),
  logout: () => call<null>("DELETE", "/session"),
  conversations: () => call<Page<Conversation>>("GET", "/conversations?limit=50"),
  createConversation: () => call<Conversation>("POST", "/conversations", {}),
  messages: (id: string) => call<Page<StoredMessage>>("GET", `/conversations/${id}/messages?limit=50`),
  run: (runId: string) => call<{ status: string }>("GET", `/runs/${runId}`),
  training: (id: string) => call<Record<string, unknown>>("GET", `/trainings/${id}`),
  evidence: (url: string) => call<Record<string, unknown>>("GET", url.replace(/^\/api\/v1/, "")),
  action: (id: string) => call<Record<string, unknown>>("GET", `/ticket-actions/${id}`),
  revise: (id: string, version: number, fields: Record<string, unknown>, key: string) =>
    call<Record<string, unknown>>("POST", `/ticket-actions/${id}/revise`, { version, fields }, { "Idempotency-Key": key }),
  confirm: (id: string, version: number, key: string) =>
    call<Record<string, unknown>>("POST", `/ticket-actions/${id}/confirm`, { version }, { "Idempotency-Key": key }),
  cancel: (id: string, version: number) => call<Record<string, unknown>>("POST", `/ticket-actions/${id}/cancel`, { version }),
  ticket: (id: string) => call<Record<string, unknown>>("GET", `/it-tickets/${id}`),
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 메시지 전송(D-29 진행 상황 스트리밍). 서버가 보낸 progress 단계만 알리고 답은 result로 한 번에 받는다.
 * 같은 키 재전송이 실행 중(202)이면 run 종료를 기다린 뒤 같은 키·본문으로 다시 보내 최종 결과를 받는다.
 */
export async function sendMessage(
  conversationId: string,
  content: string,
  key: string,
  onStage: (stage: string) => void,
): Promise<MessageResult> {
  const path = `${BASE}/conversations/${conversationId}/messages`;
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "Idempotency-Key": key,
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      body: JSON.stringify({ content }),
    });
  } catch {
    throw new NetworkError("서버와 연결이 끊겼습니다.");
  }
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("text/event-stream")) {
    const data = await response.json().catch(() => null);
    if (!response.ok) throw errorFrom(response.status, data);
    if (response.status === 202) return await waitAndReplay(conversationId, content, key, (data as { run_id: string }).run_id);
    return data as MessageResult;
  }
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        const event = /^event: (.*)$/m.exec(block)?.[1];
        const raw = /^data: (.*)$/m.exec(block)?.[1];
        if (!event || raw === undefined) continue;
        const payload = JSON.parse(raw);
        if (event === "progress") onStage(String(payload.stage));
        if (event === "result") return payload as MessageResult;
        if (event === "error") throw errorFrom(Number(payload.status ?? 500), payload);
      }
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new NetworkError("응답을 받는 중 연결이 끊겼습니다.");
  }
  throw new NetworkError("응답을 받는 중 연결이 끊겼습니다.");
}

async function waitAndReplay(conversationId: string, content: string, key: string, runId: string): Promise<MessageResult> {
  for (let i = 0; i < 120; i += 1) {
    const { data } = await api.run(runId);
    if (data.status !== "running") break;
    await sleep(1000);
  }
  const { status, data } = await call<MessageResult>("POST", `/conversations/${conversationId}/messages`, { content }, { "Idempotency-Key": key });
  if (status === 202) throw new NetworkError("아직 처리 중입니다. 잠시 뒤 다시 보내면 같은 요청의 결과를 받습니다.");
  return data;
}

export function newKey(): string {
  return crypto.randomUUID();
}
