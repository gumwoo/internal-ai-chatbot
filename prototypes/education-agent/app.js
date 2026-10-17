"use strict";

// Local, deterministic screen prototype. No AI, API, storage or real ticket calls.
const $ = id => document.getElementById(id);
const escapeText = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = name => {
  const paths = {
    plus:'<path d="M12 5v14M5 12h14"/>', arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
    close:'<path d="m6 6 12 12M18 6 6 18"/>', menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
    chat:'<path d="M20 15a3 3 0 0 1-3 3H9l-5 3V6a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3z"/>',
    document:'<path d="M14 3H5v18h14V8zm0 0v5h5M8 12h8M8 16h6"/>',
    book:'<path d="M4 4.5h6.5L12 6l1.5-1.5H20v15h-6.5L12 21l-1.5-1.5H4zM12 6v15"/>'
  };
  return `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">${paths[name]}</svg>`;
};
const sources = {
  oldEducation:{title:"외부교육비 지원 규정 [종전]",number:"GW-ED-031",version:"제1차 개정",period:"2025.01.01.–2026.09.30. 시작 과정",state:"종전",page:1,section:"개인별 지원 한도",basis:"교육 시작일",file:"ED-031_외부교육비_지원_규정_종전.pdf",quote:"2025년 1월 1일부터 2026년 9월 30일까지 시작한 자율·선택 외부교육은 1회 과정당 최대 1,000,000원, 직원 1인 지원연도별 합산 최대 2,000,000원의 범위에서 지원할 수 있다."},
  educationCost:{title:"외부교육비 지원 규정",number:"GW-ED-030",version:"제2차 개정",period:"2026.10.01.부터",state:"현행",page:1,section:"제5조 개인별 지원 한도 · 제6조 지원 항목",basis:"교육 시작일 기준",file:"ED-030_외부교육비_지원_규정.pdf",quote:"2026년 10월 1일 이후 시작하는 자율·선택 외부교육의 교육비는 1회 과정당 최대 1,500,000원, 직원 1인 지원연도별 합산 최대 3,000,000원으로 한다. 두 기준은 함께 적용한다."},
  oldTrip:{title:"출장비 지급 기준 [종전]",number:"GW-GA-082",version:"제1차 개정",period:"2025.01.01.–2026.09.30. 시작 출장",state:"종전",page:1,section:"제2조 적용기간 · 제5조 숙박비",basis:"출장 시작일 기준",file:"GA-082_출장비_지급_기준_종전.pdf",quote:"2025년 1월 1일부터 2026년 9월 30일까지 시작한 출장에 적용한다. 이 기간에 시작한 출장은 복귀일 또는 정산일이 2026년 10월 이후이더라도 본 기준을 적용한다.",extra:"국내 숙박비는 실제 지출액 범위 내에서 수도권 1박 80,000원, 기타 지역 1박 70,000원을 상한으로 한다."},
  currentTrip:{title:"출장비 지급 기준",number:"GW-GA-081",version:"제2차 개정",period:"2026.10.01.부터 시작 출장",state:"현행",page:2,section:"제9조 숙박비",basis:"출장 시작일 기준",file:"GA-081_출장비_지급_기준.pdf",quote:"증빙이 있는 국내 숙박비의 1박 상한은 수도권 120,000원, 그 밖의 지역 90,000원이다."},
  ticketProcedure:{title:"IT 헬프데스크 티켓 접수 및 처리 절차",number:"GW-IT-037",version:"문서판 2.0",period:"2026.10.01.부터",state:"현행",page:1,section:"1.2 필수 입력 · 1.3 첨부 제한",basis:"현재 기준 · 2026.10.16.",file:"IT-037_IT_헬프데스크_티켓_접수_및_처리_절차.pdf",quote:"요청자, 회신 수단, 대상 서비스, 현상, 발생 시각, 영향 범위, 긴급 업무 여부, 관련 자산번호를 기록한다."},
  vpn:{title:"VPN 원격접속 이용 가이드",number:"GW-IT-045",version:"문서판 2.0",period:"2026.10.01.부터",state:"현행",page:1,section:"1. 이용 요건",basis:"현재 기준 · 2026.10.16.",file:"IT-045_VPN_원격접속_이용_가이드.pdf",quote:"VPN은 IT지원팀이 관리상태를 확인한 회사 업무기기에서만 이용한다."},
  educationPolicy:{title:"사내 교육 운영 규정",number:"GW-ED-021",version:"제2차 개정",period:"2026.10.01.부터",state:"현행",page:2,section:"제10조 신청 취소 · 제11조 불참과 대체교육",basis:"교육 시작일 · 2026.10.20.",file:"ED-021_사내_교육_운영_규정.pdf",quote:"직원은 참석이 어려워진 사실을 확인하는 즉시 담당자에게 알린다. 교육운영담당은 불참 사유와 필수 대상 여부를 확인하고, 개설된 대체회차를 안내하거나 추후 일정에 배정한다."}
};
const trainings = [
  {id:"security",code:"TR-SEC-001",title:"신입사원 정보보안 교육",date:"10월 20일 (화)",time:"14:00–16:00",location:"3층 교육장",description:"신입사원을 위한 계정 보안과 업무 정보 취급 교육입니다."},
  {id:"collaboration",code:"TR-COLLAB-001",title:"신입사원 협업 도구 교육",date:"10월 22일 (목)",time:"10:00–11:30",location:"온라인",description:"공동 문서 작성과 일정 공유의 기본 기능을 실습합니다."}
];
let messageCounter = 0;
const user = text => ({id:`message-${++messageCounter}`,role:"user",text});
const assistant = (kind,extra={}) => ({id:`message-${++messageCounter}`,role:"assistant",kind,...extra});
const conversations = new Map([
  ["schedule",{id:"schedule",title:"다음 주 교육 일정",messages:[user("다음 주에 어떤 교육이 있어?"),assistant("schedule")]}],
  ["policy",{id:"policy",title:"외부교육비 지원 한도",messages:[user("10월에 시작하는 외부교육비는 얼마까지 지원돼?"),assistant("policy")]}],
  ["historical",{id:"historical",title:"9월 출장의 숙박비 기준",messages:[user("9월 29일 출발해서 10월 2일 복귀했어. 수도권 숙박비 한도는?"),assistant("historical")]}],
  ["ticket",{id:"ticket",title:"VPN 접속 오류 지원 요청",messages:[user("VPN 인증 요청이 반복되고 접속이 안 돼. IT 지원 요청을 남기고 싶어."),assistant("ticketForm")] }]
]);
const ticketActions = new Map();
const actionHeads = new Map();
const headRevisions = new Map();
let homeDraft = "";
let activeId = null, detail = null, detailTrigger = null, detailReturnSelector = null;
let counter = 0, actionCounter = 0, ticketCounter = 0;
const announce = text => { $("announcement").textContent = text; };
const followup = text => `<button type="button" class="text-action" data-prompt="${escapeText(text)}">${escapeText(text)}${icon("arrow")}</button>`;
const sourceLink = (key,label) => { const s=sources[key]; return `<button type="button" class="source-link" data-evidence="${key}" aria-controls="detail-panel">${icon("document")}<span class="source-copy"><strong>${escapeText(s.title)}</strong><small>${escapeText(s.number)} · ${s.state} · PDF ${s.page}쪽${label ? " · "+escapeText(label) : ""}</small></span>${icon("arrow")}</button>`; };
const citation = (key,number) => `<button type="button" class="citation" data-evidence="${key}" aria-controls="detail-panel" aria-expanded="false" aria-label="출처 ${number}, ${escapeText(sources[key].title)} PDF ${sources[key].page}쪽">${number}</button>`;
const trace = steps => `<details class="trace"><summary>처리 흐름 · 고정 시안 예시</summary><ul>${steps.map(s=>`<li>${escapeText(s)}</li>`).join("")}</ul><p>실제 검색·모델·업무 API 호출 기록이 아닙니다.</p></details>`;
const fieldRow = (label,value) => `<div><dt>${escapeText(label)}</dt><dd>${escapeText(value)}</dd></div>`;
const requestTypes = {incident:"장애",service_request:"서비스 요청",inquiry:"사용 문의"};
const categories = {account:"계정",network:"네트워크",device:"기기",software:"소프트웨어",other:"기타"};
const blankFields = text => ({subject:"IT 지원 요청",description:text||"",request_type:"",category:"",target_service:/VPN/i.test(text||"")?"VPN":"",occurred_at:"",impact_scope:"",urgent_work:"",urgency_reason:"",asset_identifier:""});
const expiryLabel = action => new Intl.DateTimeFormat("ko-KR",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false,timeZone:"Asia/Seoul"}).format(action.expiresAt)+" (KST)";
function messageForForm(form){return conversations.get(form.dataset.conversationId)?.messages.find(m=>m.id===form.dataset.messageId);}
function readFields(form){const f=Object.fromEntries(new FormData(form));for(const key of Object.keys(f))f[key]=f[key].trim();return {...blankFields(),...f};}
function saveForm(form){const m=messageForForm(form);if(m)m.fields=readFields(form);}
function saveVisibleDrafts(){document.querySelectorAll("[data-ticket-form]").forEach(saveForm);const c=conversations.get(activeId);if(c)c.composerDraft=$("composer-input").value;else homeDraft=$("composer-input").value;}


function trainingTable(){ return `<p class="result-period">2026. 10. 19.–10. 25. · 한국 시간 · 예정 2건 · 가상 일정</p><table class="training-table"><caption class="sr-only">다음 주 예정 교육 2건</caption><thead><tr><th scope="col">교육</th><th scope="col">일시</th><th scope="col">장소</th></tr></thead><tbody>${trainings.map(t=>`<tr><td><button type="button" class="training-link" data-training="${escapeText(t.id)}">${escapeText(t.title)}</button><span class="training-code">${escapeText(t.code)}</span></td><td data-label="일시">${escapeText(t.date)}<span class="training-time">${escapeText(t.time)}</span></td><td data-label="장소">${escapeText(t.location)}</td></tr>`).join("")}</tbody></table>`; }
function optionList(values,selected){ return Object.entries(values).map(([value,label])=>`<option value="${escapeText(value)}" ${value===selected?"selected":""}>${escapeText(label)}</option>`).join(""); }
function ticketForm(message){
  if(!message.actionId){const a=createDraft(message.fields||blankFields(conversations.get(activeId)?.messages.filter(m=>m.role==="user").at(-1)?.text),activeId);message.actionId=a.id;}
  const a=refreshAction(ticketActions.get(message.actionId));
  if(!a || !["draft","pending"].includes(a.status))return ticketSummary(message);
  const f=message.fields || a.fields;
  const error=message.formError?`<p role="alert">${escapeText(message.formError)}</p><button type="button" class="text-action" data-rebase-draft="${escapeText(message.id)}">입력값으로 새 초안 준비</button>`:"";
  return `<p>접수 전에 아래 내용을 확인해 주세요.</p><p class="form-note">말씀하신 내용만 옮겼습니다. 비어 있는 필수 항목을 입력해 주세요. 비밀번호·MFA 코드는 적지 마세요.</p><form class="ticket-form" data-ticket-form data-message-id="${escapeText(message.id)}" data-conversation-id="${escapeText(activeId)}">${error}<div class="form-grid">
  <label>요청 유형<select name="request_type" required><option value="">선택해 주세요</option>${optionList(requestTypes,f.request_type)}</select></label>
  <label>서비스 영역<select name="category" required><option value="">선택해 주세요</option>${optionList(categories,f.category)}</select></label>
  <label class="full">대상 서비스<input name="target_service" value="${escapeText(f.target_service)}" required maxlength="120" autocomplete="off"></label>
  <label class="full">제목<input name="subject" value="${escapeText(f.subject)}" required maxlength="120" autocomplete="off"></label>
  <label class="full">현상·오류 내용<textarea name="description" required maxlength="4000" rows="3">${escapeText(f.description)}</textarea></label>
  <label>발생 시각 (한국 시간)<input name="occurred_at" type="datetime-local" value="${escapeText(f.occurred_at)}" max="2026-10-16T10:00" ${f.request_type==="incident"?"required":""}><span class="field-hint">장애는 필수 · 시안 기준 10월16일 10시</span></label>
  <label>관련 자산번호 (선택)<input name="asset_identifier" value="${escapeText(f.asset_identifier)}" placeholder="미확인 시 비워 두기" maxlength="120" autocomplete="off"></label>
  <label class="full">확인된 영향 범위<input name="impact_scope" value="${escapeText(f.impact_scope)}" required maxlength="500" autocomplete="off"></label>
  <label>긴급 업무가 있나요?<select name="urgent_work" required><option value="">선택해 주세요</option><option value="false" ${f.urgent_work==="false"?"selected":""}>없음</option><option value="true" ${f.urgent_work==="true"?"selected":""}>있음</option></select></label>
  <label>긴급 사유<span class="sr-only"> (긴급 업무가 있으면 필수)</span><input name="urgency_reason" value="${escapeText(f.urgency_reason)}" maxlength="500" ${f.urgent_work==="true"?"required":"disabled"}></label>
  </div><p class="form-note">요청자 김직원 · 회신 사내 메신저 (가상 프로필)</p><button type="submit" class="primary-button">요청 내용 확인${icon("arrow")}</button><p class="form-note">이 단계에서는 접수되지 않습니다.</p>${a.status==="pending"?`<button type="button" class="text-action" data-cancel-edit="${a.id}">수정 취소</button>`:""}</form>${sourceLink("ticketProcedure")}`;
}
function refreshAction(action){ if(["draft","pending"].includes(action?.status) && Date.now()>=action.expiresAt){action.status="expired";if(actionHeads.get(action.conversationId)===action.id)headRevisions.set(action.conversationId,(headRevisions.get(action.conversationId)||0)+1);}return action; }
function ticketSummary(message){
  const a=refreshAction(ticketActions.get(message.actionId)); if(!a)return "<p>준비된 요청을 찾을 수 없습니다. 다시 준비해 주세요.</p>";
  if(a.status==="draft")return `<p>다른 요청의 준비 상태가 바뀌어 이 초안을 저장하지 못했습니다. 기존 요청을 확인하고 필요하면 새로 준비해 주세요.</p>${followup("IT 지원 요청을 새로 준비하고 싶어")}`;
  if(a.uncertain) return `<div class="notice"><h3>등록 결과 확인이 필요합니다</h3><p>응답을 받지 못한 상황의 예시입니다. 새 요청을 만들기 전에 기존 요청 상태를 확인하세요.</p></div><button type="button" class="text-action" data-check-action="${a.id}">접수 상태 다시 확인${icon("arrow")}</button><p class="form-note">시안 내부에서만 재현합니다. 실제 접수는 없습니다.</p>`;
  if(a.status==="confirmed")return `<p><strong>지원 요청 접수 예시가 완료됐습니다.</strong></p><dl class="inline-metadata">${fieldRow("시안 번호",a.ticketId)}${fieldRow("상태","접수 · 담당 배정 전")}${fieldRow("대상 서비스",a.fields.target_service)}</dl><button type="button" class="text-action" data-action-detail="${a.id}">요청 내용 보기${icon("arrow")}</button><p class="form-note">실제 티켓은 생성되지 않았습니다. 같은 요청을 다시 확인해도 시안 번호는 유지됩니다.</p>`;
  if(a.status==="superseded")return `<p>새 내용으로 교체된 준비입니다.</p><button type="button" class="text-action" data-action-detail="${escapeText(a.successorId)}">현재 요청 확인${icon("arrow")}</button>`;
  if(a.status==="expired" || a.status==="cancelled")return `<div class="notice"><h3>${a.status==="expired"?"확인 시간이 지났습니다":"요청 준비를 취소했습니다"}</h3><p>접수되지 않았습니다. 내용을 다시 확인해 새로 준비할 수 있어요.</p></div>${followup("IT 지원 요청을 새로 준비하고 싶어")}`;
  return `<p>요청 내용을 준비했습니다. <strong>아직 접수되지 않았습니다.</strong></p><dl class="inline-metadata">${fieldRow("제목",a.fields.subject)}${fieldRow("서비스",a.fields.target_service)}${fieldRow("확인 기한",expiryLabel(a))}</dl><button type="button" class="text-action" data-action-detail="${a.id}">내용 확인 후 등록${icon("arrow")}</button>`;
}
function renderAnswer(message){
  switch(message.kind){
    case "policy": return `<p class="answer-basis">교육 시작일 기준 · 2026.10.01. 이후 과정</p>${message.prospective?"<p>현재 공개된 규정 기준입니다. 예정 교육일까지 개정되면 달라질 수 있습니다.</p>":""}<p>자율·선택 외부교육은 <strong>1회 최대 150만원, 연간 최대 300만원</strong>이며 두 한도를 함께 적용합니다.${citation("educationCost",1)}</p><ul class="policy-list"><li>직무 관련성과 사전 승인을 확인해야 합니다.</li><li>회사 지정 필수교육에는 개인 자율교육 한도를 이유로 지급을 제한하지 않습니다.</li><li>숙박·교통 등 출장비는 별도 기준으로 심사합니다.</li></ul><p>개인별 남은 한도와 지급 여부는 승인·기지급 내역 확인이 필요합니다.</p>${sourceLink("educationCost")}${followup("9월에 시작한 교육도 같은 기준이야?")}${trace(["교육 시작일 확인","해당 판본의 제5~6조 확인"])}`;
    case "historical": return `<p class="answer-basis">출장 시작일 ${escapeText(message.eventDate||"2026-09-29")} · ${message.region==="other"?"기타 지역":"수도권"} 기준</p><p>이 출장은 <strong>종전 기준</strong>을 적용합니다. 숙박비 상한은 실제 지출 범위에서 <strong>1박 ${message.region==="other"?"7":"8"}만원</strong>입니다.${citation("oldTrip",1)}</p><p>출장 시작일이 개정 전이므로 복귀일이나 정산일이 10월이어도 현재 상한으로 바뀌지 않습니다.</p>${sourceLink("oldTrip","출장 시작일로 판정")}<div class="followups">${followup("현재 기준과 비교해 줘")}</div>`;
    case "compare": return `<p>두 시점에 시작한 출장의 기본 숙박비 상한을 비교하면 다음과 같습니다.</p><table class="comparison-table"><caption class="sr-only">출장 시작일별 기본 숙박비 상한</caption><thead><tr><th scope="col">구분</th><th scope="col">${escapeText(message.eventDate||"2026-09-29")} 시작</th><th scope="col">10월16일 시작 가정</th></tr></thead><tbody><tr><th scope="row">적용 판본</th><td>종전 · GA-082</td><td>현행 · GA-081</td></tr><tr><th scope="row">수도권 / 1박</th><td>8만원 ${citation("oldTrip",1)}</td><td>12만원 ${citation("currentTrip",2)}</td></tr><tr><th scope="row">기타 지역 / 1박</th><td>7만원</td><td>9만원</td></tr></tbody></table><p>${escapeText(message.eventDate||"2026-09-29")} 시작한 기존 출장에는 종전 기준을 유지합니다. 제공된 숙소·실제 지출·예외 승인도 별도로 확인해야 합니다.</p>${sourceLink("oldTrip")}${sourceLink("currentTrip")}`;
    case "currentTrip":return `<p class="answer-basis">출장 시작일 ${escapeText(message.eventDate||"2026-10-16")} · 현행</p><p>국내 출장 숙박비의 기본 상한은 <strong>수도권 1박12만원, 기타 지역9만원</strong>입니다.${citation("currentTrip",1)}</p><p>실제 지출·증빙과 예외 승인을 확인해야 합니다. 10월 이전에 시작한 출장은 시작일을 알려주세요.</p>${sourceLink("currentTrip")}`;
    case "educationDate":return `<p>정확한 교육 시작일을 알려주세요. 2026년9월30일까지 시작한 교육과10월1일 이후 시작한 교육은 적용 판본이 다릅니다.</p><p>예: “9월30일에 시작했어”처럼 답하면 해당 기준으로 이어서 확인합니다.</p>`;
    case "trainingCost":return `<p class="answer-basis">보안교육 · 예정 2026.10.20.</p><p>현재 공개된 규정 기준으로 확인할 수 있습니다. 다만 일정에는 이 과정의 비용과 교육 구분이 없어 지원 금액을 확정할 수 없습니다.</p><p>자율·선택 외부교육의 한도를 이 사내 과정에 그대로 적용하지 않습니다. 교육 담당자에게 과정 구분과 비용 부담을 확인해 주세요. 예정일까지 규정이 개정되면 달라질 수 있습니다.</p>${sourceLink("educationCost","외부교육 한도의 적용 범위")}`;
    case "oldEducation":return `<p class="answer-basis">교육 시작일 ${escapeText(message.eventDate)} · 종전</p><p>자율·선택 외부교육은 <strong>1회 최대100만원, 지원연도 합산 최대200만원</strong>입니다.${citation("oldEducation",1)}</p><p>개인 잔여 한도는 지급 내역 없이 계산할 수 없습니다.</p>${sourceLink("oldEducation")}`;
    case "tripDate":return `<p>출장 시작일과 숙박 지역을 알려주세요. 시작일에 따라 적용하는 규정이 달라집니다.</p><p class="form-note">이 시안의 준비된 사례는 2026년9월29일 출발한 수도권 출장입니다.</p>`;
    case "enrollmentPeriod":return `<p>교육 신청 접수 기간은 교육별 일정과 운영 안내를 확인해야 합니다. 이 시안에는 확정된 접수 기간 데이터가 없어 날짜를 만들어 안내하지 않습니다.</p>${followup("다음 주 교육 알려줘")}`;
    case "educationPolicy":return `<p>참석이 어려워진 사실을 확인하는 즉시 담당자에게 알려주세요. 필수 대상 여부와 불참 사유를 확인한 뒤 대체회차를 안내받습니다.${citation("educationPolicy",1)}</p><p>일반 선택·직무교육 취소는2영업일 전까지가 원칙이고, 이후/당일 사유는 담당자에게 확인합니다. 대체교육의 실제 일정은 교육 조회가 필요합니다.</p>${sourceLink("educationPolicy")}`;
    case "sessionExpired":return `<div class="notice"><h3>세션이 만료됐습니다</h3><p>시안의 입력값을 보존했습니다. 데모 세션을 다시 시작한 뒤 계속할 수 있습니다.</p></div><button type="button" class="text-action" data-restore-session>데모 세션 다시 시작</button>`;
    case "clarificationCancelled":return `<p>추가 질문을 취소했습니다. 다른 업무를 물어보세요.</p>`;
    case "filteredSchedule":{const found=trainings.filter(t=>message.trainingIds.includes(t.id));return `<p class="answer-basis">교육 시작일 ${escapeText(message.eventDate)} · 고정 시안 일정</p>${found.length?found.map(t=>`<p><button type="button" class="training-link" data-training="${escapeText(t.id)}">${escapeText(t.title)}</button> · ${escapeText(t.time)}</p>`).join(""):`<p>이 날짜에 시작하는 교육은 시안 일정에 없습니다.</p>`}`;}
    case "ticketForm":return ticketForm(message);
    case "ticketPreview":return ticketSummary(message);
    case "schedule":return `<p>다음 주 예정 교육은 <strong>2건</strong>입니다. 교육명을 선택해 상세를 확인하세요.</p>${trainingTable()}<div class="followups">${followup("그중 보안교육은 어떤 내용이야?")}</div>`;
    case "training":{const t=trainings.find(t=>t.id===message.trainingId)||trainings[0];return `<p><strong>${escapeText(t.title)}</strong>은 ${escapeText(t.date)} ${escapeText(t.time)}, ${escapeText(t.location)}입니다.</p><p>${escapeText(t.description)}</p><button type="button" class="text-action" data-training="${escapeText(t.id)}">교육 상세 보기${icon("arrow")}</button><div class="followups">${followup("참석이 어려우면 어떻게 해야 해?")}</div>`;}
    case "clarify":return `<p>어떤 교육을 말씀하시는지 확인할게요. 교육명이나 날짜를 알려주세요.</p><div class="followups">${trainings.map(t=>followup(`${t.title}은 어떤 내용이야?`)).join("")}</div>`;
    case "empty":return `<div class="notice"><h3>해당하는 교육이 없습니다</h3><p>시안 일정에서 찾지 못했어요. 다른 교육명이나 기간으로 확인해 주세요.</p></div>${followup("다음 주 교육 알려줘")}`;
    case "insufficient":return `<div class="notice"><h3>확인할 수 있는 근거가 부족합니다</h3><p>제공된 자료만으로 답을 확정할 수 없습니다. 필요한 조건이나 담당자의 확인을 요청해 주세요.</p></div>`;
    case "restricted":return `<div class="notice"><h3>이 내용을 표시할 수 없습니다</h3><p>현재 열람 가능한 근거로 답변을 제공할 수 없습니다. 문서명·인용·기존 답변도 표시하지 않습니다.</p></div><p class="form-note">권한 변경 후 이력 표시를 검토하는 고정 예시입니다. 실제 권한 검사 기능은 없습니다.</p>`;
    case "error":return `<div class="notice notice-error"><h3>정보를 불러오지 못했습니다</h3><p>조회 실패 상황의 예시입니다. 잠시 후 다시 확인해 주세요.</p></div><button type="button" class="text-action" data-retry>다시 시도${icon("arrow")}</button>`;
    default:return `<p>이 질문은 현재 시안의 지원 범위 밖입니다. 확인되지 않은 규정이나 연락처는 안내하지 않습니다.</p><p>이 시안은 아래 질문에 준비된 응답만 보여줍니다. 질문은 외부로 전송되지 않습니다.</p><div class="followups">${followup("외부교육비 지원 한도를 알려줘")}${followup("9월 29일 출발한 수도권 출장의 숙박비 한도는?")}${followup("VPN 오류 지원 요청을 남기고 싶어")}</div>`;
  }
}
function renderHome(){return `<section class="home"><h2>어떤 업무를 도와드릴까요?</h2><p>사내 규정과 근거를 확인하고,<br>교육 일정을 찾거나 IT 지원 요청을 준비하세요.</p><div class="suggestions"><p>이렇게 물어보세요</p>${["10월에 시작하는 외부교육비는 얼마까지 지원돼?","9월 29일 출발한 수도권 출장의 숙박비 한도는?","VPN 접속 오류를 IT 지원팀에 접수하고 싶어"].map(q=>`<button type="button" class="suggestion" data-prompt="${escapeText(q)}">${escapeText(q)}${icon("arrow")}</button>`).join("")}</div><div class="followups">${followup("다음 주 교육 일정도 보여줘")}</div></section>`;}
function updateSendButton(){const pending=conversations.get(activeId)?.pending;$("send-button").disabled=!$("composer-input").value.trim()||!!pending;$("composer-input").readOnly=!!pending;$("composer").setAttribute("aria-busy",String(!!pending));}
function updateCitationState(){document.querySelectorAll(".citation").forEach(b=>b.setAttribute("aria-expanded",String(detail?.type==="evidence"&&detail.key===b.dataset.evidence)));}
function render({scroll=false}={}){
  document.querySelectorAll("[data-ticket-form]").forEach(saveForm);
  const c=conversations.get(activeId);$("conversation-title").textContent=c?.title||"새 대화";
  $("conversation-list").innerHTML=[...conversations.values()].reverse().map(c=>`<button type="button" class="conversation-item" data-conversation="${c.id}" ${activeId===c.id?'aria-current="page"':""}>${icon("chat")}<span>${escapeText(c.title)}${c.completionNotice?" · 접수 예시 완료":""}</span></button>`).join("");
  $("conversation-content").innerHTML=c?c.messages.map(m=>m.role==="user"?`<article class="message message-user" aria-label="내 질문"><p class="question-text">${escapeText(m.text)}</p></article>`:`<article class="message message-assistant" aria-label="도우미 답변"><div class="assistant-label">${icon("book")}업무 도우미</div><div class="answer">${renderAnswer(m)}</div></article>`).join("")+(c.pending?'<p class="pending" role="status">시안 응답을 준비하고 있습니다.</p>':""):renderHome();
  updateSendButton();updateCitationState();if(scroll)$("conversation-scroll").scrollTop=$("conversation-scroll").scrollHeight;
}
function closeDetail({focus=true}={}){detail=null;$("workspace").inert=false;$("sidebar").inert=false;$("detail-panel").removeAttribute("role");$("detail-panel").removeAttribute("aria-modal");$("detail-panel").hidden=true;$("app-shell").classList.remove("has-detail");updateCitationState();if(focus){const target=detailTrigger?.isConnected?detailTrigger:detailReturnSelector?document.querySelector(detailReturnSelector):null;target?.focus();}detailTrigger=null;detailReturnSelector=null;}
function actionMarkup(a){
  refreshAction(a);const f=a.fields;const confirmed=a.status==="confirmed"&&!a.uncertain;
  return `<h3>${confirmed?"IT 지원 요청 접수 예시":"지원 요청 내용을 확인해 주세요"}</h3><p class="detail-description">${a.status==="expired"?"확인 시간이 지났습니다.":a.status==="cancelled"?"취소한 요청입니다.":a.status==="superseded"?"새 내용으로 교체된 요청입니다.":confirmed?"실제 업무 시스템에는 접수되지 않았습니다.":"아래 내용을 확인한 뒤 등록 버튼을 눌러주세요."}</p><dl class="metadata ticket-metadata">${fieldRow("요청자","김직원 (가상)")}${fieldRow("회신","사내 메신저 (가상)")}${fieldRow("유형",requestTypes[f.request_type])}${fieldRow("영역",categories[f.category])}${fieldRow("서비스",f.target_service)}${fieldRow("제목",f.subject)}${fieldRow("현상",f.description)}${fieldRow("발생 시각",f.occurred_at?f.occurred_at.replace("T"," ")+" (KST)":"해당 없음")}${fieldRow("영향",f.impact_scope)}${fieldRow("긴급 업무",f.urgent_work==="true"?f.urgency_reason:"없음")}${fieldRow("자산번호",f.asset_identifier||"미확인")}${confirmed?fieldRow("시안 번호",a.ticketId):fieldRow("확인 기한",expiryLabel(a))}</dl>${a.status==="pending"?`<div class="ticket-actions"><button type="button" class="primary-button" data-confirm-action="${a.id}">이 내용으로 등록 (시안)</button><div class="action-secondary"><button type="button" class="text-action" data-edit-action="${a.id}">내용 수정</button><button type="button" class="text-action" data-cancel-action="${a.id}">취소</button></div></div>`:a.status==="confirming"?'<p class="pending" role="status">등록 예시 처리 중…</p>':confirmed?'<p class="ticket-status" role="status">접수 · 담당 배정 전</p>':`<p>이 준비는 등록하거나 수정할 수 없습니다. ${a.status==="superseded"?"현재 요청 내용을 별도로 확인하세요.":"대화에서 명시적으로 새 요청을 준비해 주세요."}</p>${a.successorId?`<button type="button" class="text-action" data-action-detail="${a.successorId}">현재 요청 확인</button>`:""}`}<p class="detail-footnote">모든 접수 상태와 번호는 이 탭 메모리의 시안 데이터입니다. 실제 접수·인증·DB 저장은 없습니다.</p>`;
}
function paintDetail(){
  if(!detail)return;
  if(detail.type==="evidence"){
    const s=sources[detail.key];const href=encodeURI(`../../data/raw/pdfs/${s.file}`)+`#page=${s.page}`;
    $("detail-heading").textContent="인용한 원문";
    $("detail-content").innerHTML=`<h3>${escapeText(s.title)}</h3><div class="document-version"><span>${escapeText(s.state)}</span><span>${escapeText(s.version)}</span></div><dl class="metadata">${fieldRow("문서번호",s.number)}${fieldRow("적용기간",s.period)}${fieldRow("판정 기준",s.basis)}${fieldRow("원문 위치",`PDF ${s.page}쪽`)}</dl><h4>${escapeText(s.section)}</h4><blockquote class="document-excerpt"><mark>${escapeText(s.quote)}</mark>${s.extra?`<p>${escapeText(s.extra)}</p>`:""}</blockquote><a class="text-action pdf-link" href="${href}" target="_blank" rel="noopener">PDF ${s.page}쪽 열기 · 새 탭${icon("arrow")}</a><p class="detail-footnote">사용자가 제공한 가온웍스 가상 회사 PDF입니다. 인용문과 응답은 사람이 원문을 확인해 넣은 고정 시안이며 실제 검색 결과가 아닙니다.</p>`;
  }else if(detail.type==="ticket"){
    const a=ticketActions.get(detail.key);if(!a)return;$("detail-heading").textContent="IT 지원 요청";$("detail-content").innerHTML=actionMarkup(a);
  }else{
    const t=trainings.find(t=>t.id===detail.key);if(!t)return;$("detail-heading").textContent="교육 상세";$("detail-content").innerHTML=`<h3>${escapeText(t.title)}</h3><p class="detail-description">${escapeText(t.code)} · 가상 교육</p><dl class="metadata">${fieldRow("날짜",`2026년 ${t.date}`)}${fieldRow("시간",t.time)}${fieldRow("장소",t.location)}${fieldRow("상태","예정")}</dl><h4>교육 내용</h4><p>${escapeText(t.description)}</p><div class="followups">${followup("참석이 어려우면 어떻게 해야 해?")}</div>`;
  }
}
function openDetail(type,key,trigger){saveVisibleDrafts();detail={type,key};detailTrigger=trigger||null;detailReturnSelector=type==="evidence"?`[data-evidence="${key}"]`:type==="ticket"?`[data-action-detail="${key}"]`:`[data-training="${key}"]`;paintDetail();$("detail-panel").hidden=false;$("app-shell").classList.add("has-detail");$("detail-panel").scrollTop=0;updateCitationState();syncDetailMode();$("close-detail").focus();}
function toggleMenu(open){$("sidebar").classList.toggle("is-open",open);$("menu-backdrop").hidden=!open;$("open-menu").setAttribute("aria-expanded",String(open));$("workspace").inert=open;if(open)$("close-menu").focus();}
function showConversation(id=null){saveVisibleDrafts();closeDetail({focus:false});toggleMenu(false);activeId=id;$("composer-input").value=conversations.get(id)?.composerDraft||(!id?homeDraft:"");render();$("conversation-scroll").scrollTop=0;const c=conversations.get(id);if(c?.completionNotice){announce(c.completionNotice);delete c.completionNotice;}}
// Deterministic demo interpretation, not a general natural-language date parser.
const DEMO_TODAY = "2026-10-16";
function datesFromText(text){
  const matches=[...text.matchAll(/(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일/g)];
  return matches.map((m,i)=>{
    const prefix=text.slice(0,m.index);
    const years=[...prefix.matchAll(/20\d{2}년|재작년|작년|올해|내년/g)];
    const yearWord=years.at(-1)?.[0];
    const year=Number(m[1]||(yearWord?.match(/20\d{2}/)?.[0])||(yearWord==="작년"?2025:yearWord==="재작년"?2024:yearWord==="내년"?2027:2026));
    const month=Number(m[2]),day=Number(m[3]),d=new Date(Date.UTC(year,month-1,day));
    const after=text.slice(m.index+m[0].length,matches[i+1]?.index??text.length).split(/[,，。.!?]/)[0];
    const before=prefix.slice(matches[i-1]?matches[i-1].index+matches[i-1][0].length:0).split(/[,，。.!?]/).at(-1);
    const roleOf=part=>part.match(/복귀|귀환|돌아|정산|종료|출발|출국|시작|신청|결재|처리|부터|까지/)?.[0];
    const role=roleOf(after)||(/(?:출발|시작|복귀|종료)(?:일|은|는|이|:|\s)*$/.test(before)?roleOf(before):null);
    return {date:d.getUTCFullYear()===year&&d.getUTCMonth()===month-1&&d.getUTCDate()===day?`${year}-${String(month).padStart(2,"0")}-${String(day).padStart(2,"0")}`:"invalid",role,index:m.index};
  });
}
function dateFromText(text,kind){
  const dates=datesFromText(text);if(!dates.length)return null;
  const starts=dates.filter(d=>/^(출발|출국|시작|부터)$/.test(d.role||""));
  if(starts.length)return new Set(starts.map(d=>d.date)).size===1?starts[0].date:"ambiguous";
  const applicable=dates.filter(d=>!d.role||kind==="schedule");
  return applicable.length===1?applicable[0].date:dates.length===1&&kind==="schedule"?dates[0].date:"ambiguous";
}
function regionFromText(text){
  if(/비수도권|기타|그 밖|부산|대전|대구|광주|울산|제주|강원|충청|전라|경상/.test(text))return "other";
  if(/수도권|서울|경기|인천/.test(text))return "capital";
  return null;
}
function dateAnswer(kind,date,c,region){
  if(!date||date==="invalid"||date==="ambiguous"){c.clarification={kind,region,date:null};return assistant(kind==="education"?"educationDate":"tripDate");}
  if(date>"2027-01-14"||date<"2025-01-01"){c.clarification=null;return assistant("insufficient");}
  if(kind==="education"){c.clarification=null;return assistant(date<"2026-10-01"?"oldEducation":"policy",{eventDate:date,prospective:date>DEMO_TODAY});}
  if(!region){c.clarification={kind,date};return assistant("tripDate");}
  c.clarification=null;return assistant(date<"2026-10-01"?"historical":"currentTrip",{eventDate:date,region});
}
function scheduleAnswer(text){
  const date=dateFromText(text,"schedule");
  if(date==="invalid"||date==="ambiguous")return assistant("clarify");
  const ids=/보안/.test(text)?["security"]:/협업/.test(text)?["collaboration"]:/VPN/i.test(text)?[]:null;
  if(date){const matched=trainings.filter(t=>(t.id==="security"?"2026-10-20":"2026-10-22")===date&&(!ids||ids.includes(t.id)));return assistant("filteredSchedule",{eventDate:date,trainingIds:matched.map(t=>t.id)});}
  if(ids)return ids.length?assistant("training",{trainingId:ids[0]}):assistant("empty");
  return assistant("schedule");
}
function classify(text){
  const c=conversations.get(activeId),messages=c?.messages||[];
  const education=/교육/.test(text),trip=/숙박|출장/.test(text);
  const lastAnswer=messages.filter(m=>m.role==="assistant").at(-1);
  const educationContext=["policy","oldEducation","educationDate"].includes(lastAnswer?.kind);
  const unsupportedTopic=/휴가|연차|근무시간|급여|퇴직|연락처|전화번호|이메일/.test(text);
  const contact=/연락처|전화번호|이메일/.test(text);
  const itContext=/VPN|IT\s*지원|IT\s*접수|헬프데스크|계정|기기|네트워크/i.test(text);
  const explicitItTarget=/(?:IT\s*지원(?:팀)?|헬프데스크)(?:에|으로)?[\s\S]*(?:접수해|접수하고|접수하겠|등록해|지원\s*요청|요청해|요청을\s*남|요청을\s*준비)/i.test(text);
  const actionIntent=/지원\s*요청|접수(?:해|하고|하|를)|요청.*(?:남기|등록|준비)|등록해/.test(text);
  const enrollment=/교육.*(?:신청|접수)/.test(text);
  if(/^(?:그만|취소|취소할게|날짜 질문 취소|다른 질문 할게)[.!\s]*$/.test(text)){c.clarification=null;return assistant("clarificationCancelled");}
  // Explicit new intents leave clarification state; a service word alone never creates a ticket.
  if(unsupportedTopic){c.clarification=null;return assistant("unsupported");}
  if(!contact&&(explicitItTarget||itContext&&actionIntent&&!enrollment)){
    c.clarification=null;const head=refreshAction(ticketActions.get(actionHeads.get(c.id)));
    return head?.status==="confirmed"?assistant("ticketPreview",{actionId:head.id}):assistant("ticketForm",{fields:blankFields(text)});
  }
  if(enrollment){c.clarification=null;return assistant("enrollmentPeriod");}
  if(/비교/.test(text)&&messages.some(m=>m.kind==="historical"||m.kind==="compare")){const previous=[...messages].reverse().find(m=>m.kind==="historical"||m.kind==="compare");c.clarification=null;return assistant("compare",{eventDate:previous.eventDate||"2026-09-29",region:previous.region||"capital"});}
  const cost=/교육비|교육.*(?:지원.*한도|같은 기준)/.test(text)||educationContext&&education&&/시작|기준|한도/.test(text);
  if(cost){
    let date=dateFromText(text,"education");
    if(/다음 주/.test(text)&&/보안/.test(text)){c.clarification=null;return assistant("trainingCost");}
    if(!date&&/10월/.test(text)&&!/(언제|모르|작년|재작년|20\d{2}년)/.test(text)){c.clarification=null;return assistant("policy");}
    return dateAnswer("education",date,c);
  }
  if(trip){const pending=c.clarification?.kind==="trip"?c.clarification:null;return dateAnswer("trip",dateFromText(text,"trip")||(/현재|현행/.test(text)?DEMO_TODAY:pending?.date),c,regionFromText(text)||pending?.region);}
  if(/불참|참석.*(어려|못)/.test(text)){c.clarification=null;return assistant("educationPolicy");}
  if(/요가|없는.*교육/.test(text)){c.clarification=null;return assistant("empty");}
  if(education||/일정|다음 주/.test(text)){
    c.clarification=null;
    if(/어떤 내용|그중/.test(text)&&/보안|협업/.test(text))return assistant("training",{trainingId:/협업/.test(text)?"collaboration":"security"});
    if(/그 교육|그거/.test(text)&&!datesFromText(text).length)return assistant("clarify");
    return scheduleAnswer(text);
  }
  if(c.clarification){
    const pending=c.clarification,date=dateFromText(text,pending.kind),region=regionFromText(text)||pending.region;
    if(date||regionFromText(text)||/시작|출발|모르|언제/.test(text))return dateAnswer(pending.kind,date||pending.date,c,region);
    // Unknown text is a new unsupported intent, not an endless date-question trap.
    c.clarification=null;return assistant("unsupported");
  }
  return assistant("unsupported");
}

function send(text,forcedKind){
  text=text.trim().slice(0,4000);if(!text||conversations.get(activeId)?.pending)return;
  saveVisibleDrafts();closeDetail({focus:false});toggleMenu(false);
  if(!activeId){activeId=`local-${++counter}`;conversations.set(activeId,{id:activeId,title:text.slice(0,30),messages:[]});}
  const c=conversations.get(activeId);c.messages.push(user(text));c.composerDraft="";homeDraft="";c.pending=true;$("composer-input").value="";render({scroll:true});announce("시안 응답 준비 중");
  window.setTimeout(()=>{c.pending=false;c.messages.push(forcedKind?assistant(forcedKind):classifyForConversation(text,c));if(activeId===c.id){render({scroll:true});announce("시안 응답이 준비되었습니다.");}},350);
}
function classifyForConversation(text,c){const original=activeId;activeId=c.id;const answer=classify(text);activeId=original;return answer;}
function createDraft(fields,conversationId){refreshAction(ticketActions.get(actionHeads.get(conversationId)));const a={id:`demo-action-${++actionCounter}`,fields:{...fields},conversationId,status:"draft",expectedHead:actionHeads.get(conversationId)||null,expectedRevision:headRevisions.get(conversationId)||0,expiresAt:Date.now()+300000,ticketId:null,uncertain:false};ticketActions.set(a.id,a);return a;}
function reviseAction(old,fields){
  refreshAction(old);if(!["draft","pending"].includes(old.status))return null;
  const head=refreshAction(ticketActions.get(actionHeads.get(old.conversationId)));
  if(head?.status==="confirmed"||head?.status==="confirming")return null;
  if(old.status==="draft"&&((actionHeads.get(old.conversationId)||null)!==old.expectedHead||(headRevisions.get(old.conversationId)||0)!==old.expectedRevision))return null;
  if(old.status==="pending"&&head?.id!==old.id)return null;
  const a={...old,id:`demo-action-${++actionCounter}`,fields:{...fields},status:"pending",expiresAt:Date.now()+300000,successorId:null};
  old.status="superseded";old.successorId=a.id;if(head?.status==="pending"){head.status="superseded";head.successorId=a.id;}
  ticketActions.set(a.id,a);actionHeads.set(a.conversationId,a.id);headRevisions.set(a.conversationId,(headRevisions.get(a.conversationId)||0)+1);return a;
}
function showActionUnavailable(a){render();if(detail)paintDetail();announce(a?.status==="expired"?"확인 시간이 지났습니다. 접수되지 않았습니다. 새 요청을 준비해 주세요.":"이 준비는 변경할 수 없습니다. 현재 요청 상태를 확인하세요.");}
function editAction(id){const a=refreshAction(ticketActions.get(id));if(!a||a.status!=="pending"){showActionUnavailable(a);return;}const c=conversations.get(a.conversationId);const m=c.messages.find(m=>m.actionId===id);if(m){m.kind="ticketForm";m.fields={...a.fields};}closeDetail({focus:false});render();document.querySelector(`[data-message-id="${m?.id}"] input[name="subject"]`)?.focus();announce("입력 중에는 기존 준비가 유지됩니다.");}
function cancelEdit(id){const c=conversations.get(activeId),m=c?.messages.find(m=>m.actionId===id);if(!m)return;m.kind="ticketPreview";delete m.fields;render();openDetail("ticket",id);}
function confirmAction(id){
  const a=refreshAction(ticketActions.get(id));if(!a||a.status!=="pending"||actionHeads.get(a.conversationId)!==id){render();if(detail)paintDetail();announce(a?.status==="expired"?"확인 시간이 지났습니다. 접수되지 않았습니다. 새 요청을 준비해 주세요.":"이 준비는 등록할 수 없습니다. 현재 요청 상태를 확인하세요.");return;}
  a.status="confirming";headRevisions.set(a.conversationId,(headRevisions.get(a.conversationId)||0)+1);paintDetail();announce("등록 예시 처리 중");
  window.setTimeout(()=>{a.status="confirmed";a.ticketId=`DEMO-IT-${String(++ticketCounter).padStart(3,"0")}`;if(activeId===a.conversationId){render();if(detail?.type==="ticket"&&detail.key===id){paintDetail();const heading=$("detail-content").querySelector("h3");heading?.setAttribute("tabindex","-1");heading?.focus();}announce("접수 예시 완료. 실제 접수는 아닙니다.");}else{const c=conversations.get(a.conversationId);if(c)c.completionNotice="접수 예시 완료 · 실제 접수는 아닙니다.";render();announce(`${c?.title||"이전 대화"}: 접수 예시가 완료됐습니다. 실제 접수는 아닙니다.`);}},350);
}
function syncDetailMode(){const modal=!!detail&&window.matchMedia("(max-width:1199px)").matches;$("workspace").inert=modal;$("sidebar").inert=modal;if(modal){$("detail-panel").setAttribute("role","dialog");$("detail-panel").setAttribute("aria-modal","true");}else{$("detail-panel").removeAttribute("role");$("detail-panel").removeAttribute("aria-modal");}}


$("plus-icon").innerHTML=icon("plus");$("send-icon").innerHTML=icon("arrow");$("close-detail").innerHTML=icon("close");$("open-menu").innerHTML=icon("menu");$("close-menu").innerHTML=icon("close");
document.addEventListener("click",event=>{
  const b=event.target.closest("button");if(!b)return;
  if(b.dataset.prompt)send(b.dataset.prompt);
  else if(b.dataset.evidence)openDetail("evidence",b.dataset.evidence,b);
  else if(b.dataset.training)openDetail("training",b.dataset.training,b);
  else if(b.dataset.actionDetail)openDetail("ticket",b.dataset.actionDetail,b);
  else if(b.dataset.confirmAction)confirmAction(b.dataset.confirmAction);
  else if(b.dataset.editAction)editAction(b.dataset.editAction);
  else if(b.dataset.rebaseDraft){const c=conversations.get(activeId),m=c?.messages.find(m=>m.id===b.dataset.rebaseDraft);if(m){saveVisibleDrafts();c.messages.push(user("입력한 내용으로 IT 지원 요청을 새로 준비해 줘."));const a=createDraft(m.fields,c.id);m.actionId=a.id;delete m.formError;render();document.querySelector(`[data-message-id="${m.id}"] input[name="subject"]`)?.focus();announce("보존한 입력으로 새 초안을 준비했습니다. 아직 접수되지 않았습니다.");}}
  else if(b.dataset.cancelEdit)cancelEdit(b.dataset.cancelEdit);
  else if(b.hasAttribute("data-restore-session")){const c=conversations.get(activeId);c.messages=c.messages.filter(m=>m.kind!=="sessionExpired");render();$("composer-input").focus();}
  else if(b.dataset.cancelAction){const a=refreshAction(ticketActions.get(b.dataset.cancelAction));if(a?.status==="pending"){a.status="cancelled";headRevisions.set(a.conversationId,(headRevisions.get(a.conversationId)||0)+1);closeDetail({focus:false});render();announce("요청 준비를 취소했습니다. 접수되지 않았습니다.");}else showActionUnavailable(a);}
  else if(b.dataset.checkAction){const a=ticketActions.get(b.dataset.checkAction);if(a){a.uncertain=false;render();openDetail("ticket",a.id);announce("같은 요청의 시안 접수번호를 확인했습니다.");}}
  else if(b.dataset.conversation)showConversation(b.dataset.conversation);
  else if(b.hasAttribute("data-retry"))send("외부교육비 지원 한도를 다시 확인해 줘","policy");
});
document.addEventListener("input",event=>{const form=event.target.closest("[data-ticket-form]");if(form)saveForm(form);});
document.addEventListener("change",event=>{
  const form=event.target.closest("[data-ticket-form]");if(!form)return;
  if(event.target.name==="urgent_work"){const input=form.elements.urgency_reason;input.disabled=event.target.value!=="true";input.required=!input.disabled;}
  if(event.target.name==="request_type")form.elements.occurred_at.required=event.target.value==="incident";saveForm(form);
});
document.addEventListener("submit",event=>{
  const form=event.target.closest("[data-ticket-form]");if(!form)return;event.preventDefault();if(!form.reportValidity())return;
  const fields=Object.fromEntries(new FormData(form));for(const k of Object.keys(fields))fields[k]=fields[k].trim();fields.urgency_reason=fields.urgency_reason||"";fields.asset_identifier=fields.asset_identifier||"";
  for(const name of ["subject","description","target_service","impact_scope",...(fields.urgent_work==="true"?["urgency_reason"]:[])]){if(!fields[name]){const input=form.elements[name];input.setCustomValidity("공백이 아닌 내용을 입력해 주세요.");input.reportValidity();input.addEventListener("input",()=>input.setCustomValidity(""),{once:true});return;}}
  const c=conversations.get(form.dataset.conversationId);const m=messageForForm(form);if(!c||!m)return;
  const previous=refreshAction(ticketActions.get(m.actionId));const a=previous&&reviseAction(previous,fields);
  if(!a){m.fields={...fields};m.formError="준비 상태가 바뀌어 저장하지 못했습니다. 입력은 유지했습니다. 내용을 검토해 새 초안을 준비하세요.";render();announce(m.formError);return;}
  m.kind="ticketPreview";m.actionId=a.id;delete m.fields;delete m.formError;render();openDetail("ticket",a.id);announce("요청 내용을 준비했습니다. 아직 접수되지 않았습니다.");

});
$("new-conversation").addEventListener("click",()=>{showConversation();$("composer-input").focus();});
$("composer").addEventListener("submit",e=>{e.preventDefault();send($("composer-input").value);});
$("composer-input").addEventListener("input",()=>{const c=conversations.get(activeId);if(c)c.composerDraft=$("composer-input").value;else homeDraft=$("composer-input").value;updateSendButton();});
$("composer-input").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();if(!$("send-button").disabled)send($("composer-input").value);}});
$("close-detail").addEventListener("click",()=>closeDetail());$("open-menu").addEventListener("click",()=>toggleMenu(true));
for(const id of ["close-menu","menu-backdrop"])$(id).addEventListener("click",()=>{toggleMenu(false);$("open-menu").focus();});
document.addEventListener("keydown",e=>{
  const modal=detail&&window.matchMedia("(max-width:1199px)").matches?$("detail-panel"):$("sidebar").classList.contains("is-open")?$("sidebar"):null;
  if(e.key==="Tab"&&modal){const controls=[...modal.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(b=>!b.disabled&&b.getClientRects().length);const first=controls[0],last=controls.at(-1);if(e.shiftKey&&(document.activeElement===first||!controls.includes(document.activeElement))){e.preventDefault();last?.focus();}else if(!e.shiftKey&&(document.activeElement===last||!controls.includes(document.activeElement))){e.preventDefault();first?.focus();}}
  if(e.key==="Escape"){if(detail)closeDetail();else if($("sidebar").classList.contains("is-open")){toggleMenu(false);$("open-menu").focus();}}
});
window.matchMedia("(max-width: 767px)").addEventListener("change",()=>{toggleMenu(false);syncDetailMode();});
window.matchMedia("(max-width:1199px)").addEventListener("change",syncDetailMode);
// Explicit QA fixtures, available only with ?qa=1. Never a menu in the employee UI.
if(new URLSearchParams(location.search).get("qa")==="1")window.prototypeQA={
  fixture(kind){if(!["insufficient","restricted","error","sessionExpired","uncertain"].includes(kind))throw new Error("Unknown fixture");if(!activeId){activeId=`qa-${++counter}`;conversations.set(activeId,{id:activeId,title:"검증용 고정 예시",messages:[]});}const c=conversations.get(activeId);if(kind==="uncertain"){const a=ticketActions.get(actionHeads.get(c.id));if(!a||a.status!=="confirmed")throw new Error("Confirm first");a.uncertain=true;}else c.messages.push(assistant(kind));closeDetail({focus:false});render({scroll:true});},
  expire({lazy=false}={}){const a=ticketActions.get(actionHeads.get(activeId));if(!a)throw new Error("Prepare first");a.expiresAt=Date.now()-1;if(!lazy){refreshAction(a);render();if(detail)paintDetail();}},
  snapshot(){return {activeId,heads:Object.fromEntries(actionHeads),headRevisions:Object.fromEntries(headRevisions),actions:[...ticketActions.values()].map(a=>({id:a.id,status:a.status,conversationId:a.conversationId,fields:{...a.fields},ticketId:a.ticketId,uncertain:a.uncertain,expectedHead:a.expectedHead,successorId:a.successorId})),messages:conversations.get(activeId)?.messages.map(m=>({...m}))};}
};
render();
