# 1. Verdict and scope

**disposition: fix**

Independent finish review of the static correction in `prototypes/education-agent/`, dated 2026-10-17. The accepted single-home chat composition, existing palette/type, optional detail area, and mobile navigation are preserved. No redesign or backend implementation is requested. Two material classification defects remain within the supplied date-clarification and enrollment-routing repair scope.

# 2. Findings

| ID | Severity | Location | Finding and user impact |
|---|---|---|---|
| F1 | P2 | `prototypes/education-agent/app.js:163` and `:165` | A trip clarification retains the first answer's date only when the next message contains neither `출장` nor `숙박`. Reproduction: `출장비 알려줘` → `9월 29일이야` → `기타 지역 출장이야`. The last message takes the fresh trip branch, passes a null date, and replaces `{kind: "trip", date: "2026-09-29"}` with `{kind: "trip", region: "other"}`. The assistant asks for the start date again although it was already supplied. Merge evidence for the same pending event before classifying a continuation as a new trip. |
| F2 | P2 | `prototypes/education-agent/app.js:160` through `:166` | `VPN` alone makes the IT branch win before the education-enrollment branch. `VPN 교육 신청 접수 기간 알려줘` returns `ticketForm`, clears date context, and asks the user for IT request details. The user's explicit education application-period intent should reach the enrollment response (or a relevant clarification), even if the course name includes an IT service term. |

The detector's existing secondary 11px-text warning is acknowledged, documented in the incumbent design, and not a material correction request in this narrowly authorized functional pass.

# 3. Evidence

- Read `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`, the target surface brief, `docs/14-ticket-workflow.md`, `docs/contracts/02-business-dates.md`, and the Impeccable craft floor / finish instructions. Read `app.js`, `index.html`, `styles.css`, prototype/test READMEs, and `tests/browser-flows.cjs`.
- Opened and visually inspected all 12 required captures: `state-contract-{desktop,compact,mobile}-{home,form,form-end,preview}.png`. Dimensions correspond to 1440×900, 1280×720, and 390×844. Each shows the named surface, with no blank, black, loading, or wrong-state evidence. Form and form-end are valid internal-scroll top/bottom viewport pairs; they are not full-form or full-page claims. Compact preview continues in its scrollable panel as expected.
- The captures preserve the calm single-home workflow, distinguish input fields, show a separate unregistered preview, expose explicit confirmation/revision/cancellation controls, and retain the static-demo disclosure. No tabs or employee-facing state selector appear.
- Supplied browser report records 52 passing checks and zero browser exceptions, covering the listed deterministic flows, form/message binding, input preservation, draft/revision/confirmation/expiry, escaping, fixtures, geometry, and focus. Its coverage does not include F1 or F2. Supplied specification report records 48 Markdown files, 189 local links, 100 PDFs, 16 contracts, 12 modules, 35 test IDs, and no errors.
- Independently evaluated the unchanged `classify` / `dateAnswer` source in a Node VM without a browser. The three-turn F1 sequence returned `tripDate` three times and dropped the retained date on the last turn; the F2 prompt returned `ticketForm`. This confirms the source paths rather than inferring their behavior from screenshots.

# 4. Limits

This verdict covers the supplied static source, deterministic test evidence, and the 12 named viewport captures. No approved raster comp exists; fidelity is assessed against the incumbent accepted UI and written direction contract. I did not run a browser or a new detector, modify application/specification/design/PDF files, or inspect actual backend behavior. The report does not establish database atomicity, authorization, RAG accuracy, model quality, real ticket creation, or operating performance.

# 5. Required action

Fix F1 and F2 together without changing the approved composition or visual tokens. Add regression cases for a pending trip's region answer containing `출장` and for education enrollment intent containing `VPN`. Rerun the relevant static browser flow checks, recapture the same named viewport/state set over the corrected source, and return those captures and results to this reviewer for a verdict pass scoring F1 and F2. No visual rebuild or scope expansion is required.
