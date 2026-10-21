// 서버 DTO(docs/04-api-spec.md). 화면은 이 값만 표시하고 모델 문장에서 날짜·ID·등록 결과를 뽑지 않는다.

export interface SessionInfo {
  user_id: string;
  display_name: string;
  capabilities: string[];
  expires_at: string;
  csrf_token: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface Conversation {
  id: string;
  title: string | null;
  created_at: string;
}

export interface TrainingRef {
  id: string;
  code: string;
  title: string;
}

export interface Citation {
  citation_id: string;
  passage_id: string;
  title: string;
  version: string;
  document_role: string;
  edition_state: string | null;
  effective_from: string | null;
  effective_to: string | null;
  as_of_date: string | null;
  date_basis: string | null;
  year_inferred: boolean;
  edition_split?: boolean;
  source_role?: string;
  prospective: boolean;
  page_spans: { page: number }[];
  quote: string;
  evidence_url: string;
  pdf_url: string;
}

export interface TicketRef {
  id: string;
  subject: string;
  status: string;
}

export type ActionPreview = Record<string, unknown> & {
  action_id: string;
  version: number;
  status: string;
  expires_at: string;
  missing_fields: string[];
};

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  visibility: "visible" | "redacted";
  content: string;
  outcome: string | null;
  training_refs: TrainingRef[];
  citations: Citation[];
  ticket_refs: TicketRef[];
  action_preview: ActionPreview | null;
  run_id: string | null;
  created_at: string;
  feedback?: Feedback | null;
}

/** D-77 답변 피드백(지금 사용자가 이 답에 남긴 것). */
export interface Feedback {
  rating: "helpful" | "not_helpful";
  reason: string | null;
}

export interface MessageResult {
  conversation_id: string;
  run_id: string;
  message_id: string;
  status: string;
  outcome: string;
  answer: string;
  training_refs: TrainingRef[];
  ticket_refs: TicketRef[];
  citations: Citation[];
  action_preview: ActionPreview | null;
}

export type Detail =
  | { kind: "training"; id: string; title: string }
  // 같은 문서·판본·쪽의 원문 조각은 버튼 하나로 묶는다(group[0] = citation).
  | { kind: "citation"; citation: Citation; group: Citation[] }
  | { kind: "ticket"; id: string; title: string };
