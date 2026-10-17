"use strict";
// npm install --no-save playwright, or supply NODE_PATH to the bundled runtime.
const {chromium}=require("playwright");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const base=process.env.PROTOTYPE_URL||"http://127.0.0.1:8787/prototypes/education-agent/";
if(!process.env.PROTOTYPE_RESULTS_DIR)throw new Error("Set PROTOTYPE_RESULTS_DIR explicitly; historical results must not be overwritten.");
const output=path.resolve(process.env.PROTOTYPE_RESULTS_DIR);
console.log("Verified output path: "+output);
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const executablePath=process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
 const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const errors=[],checks=[];page.on("pageerror",e=>errors.push(e.message));
 const check=(name,ok)=>{assert.ok(ok,name);checks.push(name);};
 const text=()=>page.locator("#conversation-content").innerText();
 async function fresh(){if(!await page.locator("#new-conversation").isVisible())await page.getByRole("button",{name:"대화 목록 열기",exact:true}).click();await page.locator("#new-conversation").click();}
 async function send(q){await page.locator("#composer-input").fill(q);await page.locator("#send-button").click();await page.locator('#composer[aria-busy="false"]').waitFor();}
 async function fill(form,subject="VPN 문의"){
  await form.locator('[name="request_type"]').selectOption("incident");await form.locator('[name="category"]').selectOption("network");
  await form.locator('[name="target_service"]').fill("VPN");await form.locator('[name="subject"]').fill(subject);await form.locator('[name="description"]').fill("인증이 반복됩니다.");
  await form.locator('[name="occurred_at"]').fill("2026-10-16T09:30");await form.locator('[name="impact_scope"]').fill("본인 기기, 타인 영향 미확인");await form.locator('[name="urgent_work"]').selectOption("false");
 }
 async function snap(){return page.evaluate(()=>window.prototypeQA.snapshot());}
 const latest=async()=>{const s=await snap();return s.messages?.filter(m=>m.role==="assistant").at(-1);};
 async function question(q){await fresh();await send(q);return latest();}
 try{
 await page.goto(base+"?qa=1");
 check("single home, no state tabs",await page.locator(".home").isVisible()&&await page.getByRole("tab").count()===0);
 await send("9월에 시작한 외부교육비는?");check("education date clarification",(await text()).includes("정확한 교육 시작일"));
 await send("9월 30일에 시작해");check("short date reply completes old policy",(await text()).includes("1회 최대100만원"));
 await page.locator('#conversation-content [data-evidence="oldEducation"]').last().click();
 check("historical education PDF link",(await page.locator(".pdf-link").getAttribute("href")).includes("ED-031"));await page.locator("#close-detail").click();
 await fresh();await send("출장 숙박비 한도 알려줘");await send("9월 29일 출발이고 수도권이야");check("short trip reply completes",(await text()).includes("1박 8만원"));
 await fresh();await send("출장비 알려줘");await send("9월 29일이야");await send("기타 지역이야");check("date and region in separate turns",(await text()).includes("1박 7만원"));
 await fresh();await send("출장비 알려줘");await send("9월 29일이야");await send("기타 지역 출장 이야");check("region reply containing trip retains date",(await text()).includes("1박 7만원"));
 await fresh();await send("9월에 시작한 교육비는?");await send("9월 31일이야");check("invalid calendar date remains clarification",!(await text()).includes("1회 최대100만원"));await send("9월30일에 시작한 교육이야");check("full date reply does not loop",(await text()).includes("1회 최대100만원"));
 await fresh();await send("다음 주 보안교육의 교육비 기준은?");check("future training is supported",(await text()).includes("현재 공개된 규정 기준"));check("internal course does not inherit external allowance",!(await text()).includes("1회 최대 150만원"));
 await fresh();await send("교육 신청 접수 기간 알려줘");check("education enrollment never routes to IT",await page.locator("[data-ticket-form]").count()===0&&(await text()).includes("확정된 접수 기간"));
 await fresh();await send("VPN 교육 신청 접수 기간 알려줘");check("VPN course enrollment stays educational",await page.locator("[data-ticket-form]").count()===0&&(await text()).includes("확정된 접수 기간"));
 await fresh();await send("VPN 연결이 안 돼. IT 지원 요청을 남기고 싶어");let form=page.locator("[data-ticket-form]").last();
 check("occurred time blank",await form.locator('[name="occurred_at"]').inputValue()==="");
 check("impact blank",await form.locator('[name="impact_scope"]').inputValue()==="");
 check("urgency unselected",await form.locator('[name="urgent_work"]').inputValue()==="");
 check("only literal user description",(await form.locator('[name="description"]').inputValue()).includes("VPN 연결이 안 돼"));
 let state=await snap(),conversation=state.activeId;const draftId=state.actions.at(-1).id;
 check("agent first creates draft",state.actions.at(-1).status==="draft");
 await form.locator('[name="subject"]').fill("보존될 입력");await page.locator("#composer-input").fill("전송 전 질문");
 await page.locator('[data-conversation="schedule"]').click();await page.locator(`[data-conversation="${conversation}"]`).click();form=page.locator("[data-ticket-form]").last();
 check("form input survives navigation",await form.locator('[name="subject"]').inputValue()==="보존될 입력");check("composer survives navigation",await page.locator("#composer-input").inputValue()==="전송 전 질문");
 await fill(form);await form.getByRole("button",{name:"요청 내용 확인",exact:true}).click();state=await snap();let pending=state.actions.find(a=>a.status==="pending");check("revise makes pending",!!pending);check("draft superseded only on submit",state.actions.find(a=>a.id===draftId).status==="superseded");
 await page.getByRole("button",{name:"내용 수정",exact:true}).click();check("opening edit preserves pending",(await snap()).actions.find(a=>a.id===pending.id).status==="pending");
 await page.locator('[name="subject"]').fill("취소할 입력 <img src=x onerror=alert(1)>");await page.getByRole("button",{name:"수정 취소",exact:true}).click();
 check("cancel edit preserves original payload",(await snap()).actions.find(a=>a.id===pending.id).fields.subject==="VPN 문의");
 check("cancel edit preserves pending",(await snap()).actions.find(a=>a.id===pending.id).status==="pending");
 await page.getByRole("button",{name:"내용 수정",exact:true}).click();await page.locator('[name="subject"]').fill('수정 <img src=x onerror=alert(1)>');await page.getByRole("button",{name:"요청 내용 확인",exact:true}).click();state=await snap();
 check("successful edit supersedes old pending",state.actions.find(a=>a.id===pending.id).status==="superseded");check("new preview renders escaped input",await page.locator("#detail-content img").count()===0&&(await page.locator("#detail-content").innerText()).includes("<img"));
 await page.getByRole("button",{name:"이 내용으로 등록 (시안)",exact:true}).click();await page.locator(".ticket-status").waitFor();state=await snap();check("single confirmed ticket",state.actions.filter(a=>a.status==="confirmed").length===1);
 const ticketId=state.actions.find(a=>a.status==="confirmed").ticketId;
 await page.locator("#close-detail").click();await page.evaluate(()=>window.prototypeQA.fixture("uncertain"));check("uncertain result reachable",(await text()).includes("등록 결과 확인이 필요"));await page.getByRole("button",{name:"접수 상태 다시 확인",exact:true}).click();const recovered=await snap();const recoveredAction=recovered.actions.find(a=>a.ticketId===ticketId);check("recovery keeps same ticket",recoveredAction?.status==="confirmed"&&recoveredAction.uncertain===false&&recovered.actions.filter(a=>a.ticketId).length===1&&(await page.locator("#detail-content").innerText()).includes(ticketId));await page.locator("#close-detail").click();
 // Multiple forms: submitting the first must not mutate the second.
 await fresh();await send("VPN 오류 지원 요청");await send("IT 지원 요청을 새로 준비하고 싶어");check("two distinct forms available",await page.locator("[data-ticket-form]").count()===2);
 await fill(page.locator("[data-ticket-form]").first(),"첫 번째 폼");await page.locator("[data-ticket-form]").first().getByRole("button",{name:"요청 내용 확인"}).click();state=await snap();check("submission binds exact message",state.messages.filter(m=>m.kind==="ticketPreview").length===1&&state.messages.filter(m=>m.kind==="ticketForm").length===1);await page.locator("#close-detail").click();
 // Other draft retains expected head; it cannot silently replace newer pending.
 const originalHead=(await snap()).heads[(await snap()).activeId];const originalPayload=(await snap()).actions.find(a=>a.id===originalHead).fields;await fill(page.locator("[data-ticket-form]").last(),"오래된 두 번째 폼");await page.locator("[data-ticket-form]").last().getByRole("button",{name:"요청 내용 확인"}).click();state=await snap();check("stale draft does not replace head",state.heads[state.activeId]===originalHead&&JSON.stringify(state.actions.find(a=>a.id===originalHead).fields)===JSON.stringify(originalPayload)&&state.actions.find(a=>a.id===originalHead).status==="pending");
 check("rejected form keeps user input",await page.locator("[data-ticket-form]").last().locator('[name="subject"]').inputValue()==="오래된 두 번째 폼");
 await page.evaluate(()=>window.prototypeQA.expire());check("expired cannot be edited",(await snap()).actions.find(a=>a.id===originalHead).status==="expired"&&(await snap()).actions.find(a=>a.id===originalHead).ticketId===null&&await page.locator('[data-edit-action]:visible').count()===0);check("expiry offers explicit new request",(await text()).includes("확인 시간이 지났습니다"));
 for(const [kind,phrase] of [["insufficient","근거가 부족"],["restricted","표시할 수 없습니다"],["error","불러오지 못했습니다"],["sessionExpired","세션이 만료"]]){await fresh();await page.evaluate(kind=>window.prototypeQA.fixture(kind),kind);check(`QA fixture ${kind}`,(await text()).includes(phrase));}
 await page.getByRole("button",{name:"데모 세션 다시 시작"}).click();check("session recovery control works",await page.locator("#composer-input").evaluate(e=>e===document.activeElement));
 await fresh();await send('<img src=x onerror="alert(1)">');check("chat escapes user markup",await page.locator("#conversation-content img").count()===0);

 // Third-review counterexamples assert selected event/edition and rendered result, not check counts alone.
 let answer=await question("10월 3일 복귀, 9월 30일 출발한 수도권 출장의 숙박비는?");
 check("return-first trip selects departure and old amount",answer.kind==="historical"&&answer.eventDate==="2026-09-30"&&(await text()).includes("1박 8만원")&&!(await text()).includes("수도권 1박12만원"));
 answer=await question("9월 30일 출발, 10월 3일 복귀한 수도권 출장의 숙박비는?");check("departure-first trip also uses old amount",answer.kind==="historical"&&answer.eventDate==="2026-09-30");
 answer=await question("9월 30일 복귀, 10월 3일 출발한 수도권 출장");check("does not simply choose earliest date",answer.kind==="currentTrip"&&answer.eventDate==="2026-10-03");
 answer=await question("10월 3일 복귀한 수도권 출장의 숙박비");check("return date alone is not departure",answer.kind==="tripDate");
 answer=await question("9월 29일과 10월 3일 수도권 출장 숙박비");check("ambiguous dates request clarification",answer.kind==="tripDate");
 answer=await question("작년 10월 2일 시작한 외부교육비는?");check("last year uses 2025 old education",answer.kind==="oldEducation"&&answer.eventDate==="2025-10-02"&&(await text()).includes("최대100만원"));
 answer=await question("2025년 10월 2일 시작한 외부교육비는?");check("adjacent explicit year remains supported",answer.kind==="oldEducation"&&answer.eventDate==="2025-10-02");
 answer=await question("2025년에 다녀온 교육이야. 10월 2일 시작한 외부교육비는?");check("detached explicit year preserved",answer.kind==="oldEducation"&&answer.eventDate==="2025-10-02");
 answer=await question("작년 10월 2일 출발한 서울 출장의 숙박비는?");check("last year trip and Seoul synonym",answer.kind==="historical"&&answer.eventDate==="2025-10-02"&&answer.region==="capital");
 answer=await question("9월 30일 출발한 경기 출장의 숙박비는?");check("Gyeonggi is capital region",answer.kind==="historical"&&answer.region==="capital");
 for(const q of ["휴가 규정","근무시간 규정","지원 한도 규정"]){answer=await question(q);check("unsupported policy: "+q,answer.kind==="unsupported"&&!(await text()).includes("150만원")&&!(await text()).includes("100만원"));}
 answer=await question("VPN 교육은 언제야");check("VPN training is schedule intent, never ticket",answer.kind==="empty"&&await page.locator("[data-ticket-form]").count()===0);
 answer=await question("IT 지원팀 연락처");check("IT contact is not a submission",answer.kind==="unsupported"&&await page.locator("[data-ticket-form]").count()===0);
 answer=await question("교육 장애를 IT 지원팀에 접수해줘");check("education-related IT submission is not enrollment",answer.kind==="ticketForm"&&await page.locator("[data-ticket-form]").count()===1);
 answer=await question("IT 지원팀 VPN 교육 신청 접수 기간 알려줘");check("IT name in enrollment query does not create ticket",answer.kind==="enrollmentPeriod");
 await question("출장 숙박비 알려줘");await send("다음 주 교육 일정 알려줘");check("new schedule intent exits trip clarification",(await latest()).kind==="schedule");
 await question("9월에 시작한 외부교육비는?");await send("취소할게");check("explicit clarification cancellation",(await latest()).kind==="clarificationCancelled");await send("휴가 규정");check("after cancellation no stale date slot",(await latest()).kind==="unsupported");
 answer=await question("10월 2일 시작 교육은?");check("new dated education query filters schedule",answer.kind==="filteredSchedule"&&answer.eventDate==="2026-10-02"&&answer.trainingIds.length===0&&!(await text()).includes("다음 주 예정 교육은"));
 await question("10월에 시작한 외부교육비는?");await send("9월 30일 시작 교육은?");check("dated education followup retains cost topic",(await latest()).kind==="oldEducation");
 await question("VPN 오류 지원 요청");await fill(page.locator("[data-ticket-form]").last());await page.getByRole("button",{name:"요청 내용 확인",exact:true}).click();
 const beforeExpiry=await snap(),expiryId=beforeExpiry.heads[beforeExpiry.activeId];await page.evaluate(()=>window.prototypeQA.expire({lazy:true}));await page.getByRole("button",{name:"이 내용으로 등록 (시안)",exact:true}).click();
 state=await snap();check("click after lazy expiry creates no ticket",state.actions.find(a=>a.id===expiryId).status==="expired"&&state.actions.find(a=>a.id===expiryId).ticketId===null);
 check("click after expiry announces recovery",(await page.locator("#announcement").innerText()).includes("확인 시간이 지났습니다"));await page.locator("#close-detail").click();
 await question("VPN 오류 지원 요청");await send("IT 지원 요청을 새로 준비하고 싶어");await fill(page.locator("[data-ticket-form]").last(),"두 번째 편집 대상");await page.locator("[data-ticket-form]").last().getByRole("button",{name:"요청 내용 확인"}).click();
 const secondMessageId=(await snap()).messages.find(m=>m.kind==="ticketPreview").id;await page.getByRole("button",{name:"내용 수정",exact:true}).click();
 check("edit focus targets bound message",await page.locator(`[data-message-id="${secondMessageId}"] [name="subject"]`).evaluate(e=>e===document.activeElement));
 await page.getByRole("button",{name:"수정 취소",exact:true}).click();
 const finishing=await snap(),finishingId=finishing.activeId,finishingAction=finishing.heads[finishingId];
 await page.getByRole("button",{name:"이 내용으로 등록 (시안)",exact:true}).click();await page.locator('[data-conversation="schedule"]').click();
 await page.waitForFunction(id=>window.prototypeQA.snapshot().actions.find(a=>a.id===id)?.status==="confirmed",finishingAction);
 check("background confirmation announces completion",(await page.locator("#announcement").innerText()).includes("접수 예시가 완료"));
 check("background conversation has completion marker",(await page.locator(`[data-conversation="${finishingId}"]`).innerText()).includes("접수 예시 완료"));
 await page.locator(`[data-conversation="${finishingId}"]`).click();check("return shows actual confirmed result",(await text()).includes("접수 예시가 완료"));


 // Independent finish-review corrections: retained comparison dates and every stale action control.
 for(const [q,date] of [["9월 30일 출발한 수도권 출장 숙박비","2026-09-30"],["작년 10월 2일 출발한 수도권 출장 숙박비","2025-10-02"]]){
   await question(q);await send("현재 기준과 비교해 줘");const comparison=await latest();check("comparison retains actual event "+date,comparison.kind==="compare"&&comparison.eventDate===date&&(await text()).includes(date));
   check("comparison header does not invent September29 "+date,!(await page.locator(".comparison-table").innerText()).includes("9월29일"));
 }
 for(const label of ["내용 수정","취소"]){
   await question("VPN 오류 지원 요청");await fill(page.locator("[data-ticket-form]").last());await page.getByRole("button",{name:"요청 내용 확인",exact:true}).click();
   const prior=await snap(),id=prior.heads[prior.activeId];await page.evaluate(()=>window.prototypeQA.expire({lazy:true}));await page.locator("#detail-content").getByRole("button",{name:label,exact:true}).click();
   const expired=await snap();check("lazy expiry action blocked: "+label,expired.actions.find(a=>a.id===id).status==="expired"&&expired.actions.find(a=>a.id===id).ticketId===null&&expired.heads[expired.activeId]===id);
   check("lazy expiry action announces: "+label,(await page.locator("#announcement").innerText()).includes("확인 시간이 지났습니다")&&await page.locator('#detail-content [data-confirm-action]').count()===0);await page.locator("#close-detail").click();
 }

 // One batched visual/geometry pass across the supported device classes.
 const screenshots=[];
 for(const [name,width,height] of [["desktop",1440,900],["compact",1280,720],["mobile",390,844]]){
  await page.setViewportSize({width,height});await page.goto(base+"?qa=1");await fresh();await page.screenshot({path:path.join(output,`third-review-${name}-home.png`)});screenshots.push(`third-review-${name}-home.png`);
  check(`${name} no horizontal overflow`,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await send("VPN 오류 지원 요청");await fill(page.locator("[data-ticket-form]").last());await page.locator("#conversation-scroll").evaluate(e=>e.scrollTop=0);await page.screenshot({path:path.join(output,`third-review-${name}-form.png`)});screenshots.push(`third-review-${name}-form.png`);
  await page.locator("#conversation-scroll").evaluate(e=>e.scrollTop=e.scrollHeight);await page.screenshot({path:path.join(output,`third-review-${name}-form-end.png`)});screenshots.push(`third-review-${name}-form-end.png`);
  await page.getByRole("button",{name:"요청 내용 확인",exact:true}).click();await page.screenshot({path:path.join(output,`third-review-${name}-preview.png`)});screenshots.push(`third-review-${name}-preview.png`);
  check(`${name} detail stays within viewport`,await page.locator("#detail-panel").evaluate(e=>e.getBoundingClientRect().right<=innerWidth+1));
  if(width<1200){check(`${name} modal semantics`,await page.locator('#detail-panel[role="dialog"][aria-modal="true"]').count()===1);await page.locator("#close-detail").focus();await page.keyboard.press("Shift+Tab");check(`${name} modal traps focus`,await page.locator("#detail-panel").evaluate(e=>e.contains(document.activeElement)));}
  await page.keyboard.press("Escape");check(`${name} Escape restores focus`,await page.locator("[data-action-detail]").last().evaluate(e=>e===document.activeElement));
 }
 check("no browser exceptions",errors.length===0);
 // Product URL has no QA hook or user-facing state selector.
 await page.goto(base);check("QA hook absent from ordinary URL",await page.evaluate(()=>typeof window.prototypeQA==="undefined"));
 const report={scope:"Static prototype only; not backend/ACL/concurrency/model verification",timestamp:new Date().toISOString(),base,checks,passed:checks.length,errors,screenshots};
 fs.writeFileSync(path.join(output,"third-review-browser-results.json"),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }catch(e){console.error(e);process.exitCode=1;}finally{await browser.close();}
})();
