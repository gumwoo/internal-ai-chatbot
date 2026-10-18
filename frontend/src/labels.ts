// 서버 닫힌 값 → 화면 문구. 서버가 보내지 않은 단계는 만들지 않는다(D-29).

export const STAGES: Record<string, string> = {
  accepted: "요청을 받았습니다",
  model_waiting: "답변을 준비하는 중",
  training_lookup: "교육 일정 조회 중",
  document_search: "규정 문서 검색 중",
  ticket_lookup: "티켓 조회 중",
  ticket_prepare: "접수 초안 준비 중",
  verifying: "결과 확인 중",
};

export const OUTCOMES: Record<string, string> = {
  answered: "답변",
  needs_clarification: "추가 확인 필요",
  no_results: "결과 없음",
  insufficient_evidence: "근거 부족",
  action_pending: "확인 대기",
};

export const ACTION_STATUS: Record<string, string> = {
  draft: "초안(아직 접수 전)",
  pending: "확인 대기(아직 접수 전)",
  superseded: "새 내용으로 바뀜",
  confirmed: "접수 완료",
  cancelled: "취소됨",
  expired: "만료됨(접수되지 않음)",
};

export const FIELD_LABELS: Record<string, string> = {
  subject: "제목",
  description: "현상",
  request_type: "요청 유형",
  category: "분류",
  target_service: "대상 서비스",
  occurred_at: "발생 시각",
  impact_scope: "영향 범위",
  urgent_work: "긴급 업무",
  urgency_reason: "긴급 사유",
  asset_identifier: "자산번호",
};

export const REQUEST_TYPES: Record<string, string> = {
  incident: "장애",
  service_request: "요청",
  inquiry: "문의",
};

export const CATEGORIES: Record<string, string> = {
  account: "계정",
  network: "네트워크",
  device: "기기",
  software: "소프트웨어",
  other: "기타",
};

export const DATE_BASES: Record<string, string> = {
  current: "현재 기준",
  explicit_date: "지정 날짜 기준",
  training_start: "교육 시작일 기준",
  trip_start: "출장 시작일 기준",
  approval_date: "최종 결재일 기준",
  request_date: "신청일 기준",
  work_date: "근무일 기준",
  processing_date: "처리일 기준",
};

export function fieldValue(name: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "미입력";
  if (name === "request_type") return REQUEST_TYPES[String(value)] ?? String(value);
  if (name === "category") return CATEGORIES[String(value)] ?? String(value);
  if (name === "urgent_work") return value ? "예" : "아니요";
  if (name === "occurred_at") return formatTime(String(value));
  return String(value);
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" });
}
