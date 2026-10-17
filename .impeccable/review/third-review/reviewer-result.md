# 1. Scope and verdict

**disposition: fix**

Independent full finish review of the third-review static prototype correction, at `C:/LLM-API`. Scope: `prototypes/education-agent/{app.js,index.html,styles.css}`, the browser regression evidence, and the intended contracts in `docs/14-ticket-workflow.md` and `docs/contracts/{00-shared-contracts,03-errors,04-field-origins,05-retrieval-assembly}.md`.

The accepted single employee home, conversation/sidebar/detail arrangement, palette, typography, and responsive composition are preserved. No tabs or employee state selector appeared in the reviewed captures. Two material behavior gaps remain. They require a bounded correction; a redesign or rebuild is not indicated.

# 2. Material findings

## F1 — P2: Expired preview edits and cancellation fail silently

Locations: [app.js:256](C:/LLM-API/prototypes/education-agent/app.js:256), [app.js:278](C:/LLM-API/prototypes/education-agent/app.js:278). Related test coverage: [browser-flows.cjs:69](C:/LLM-API/prototypes/education-agent/tests/browser-flows.cjs:69), [browser-flows.cjs:97](C:/LLM-API/prototypes/education-agent/tests/browser-flows.cjs:97).

Reproduction: prepare a pending request, leave its preview open, let its TTL pass without a render, then click **내용 수정** or **취소**. Each handler calls `refreshAction`, which changes the action to `expired`, but the non-pending path returns without repainting or announcing the problem. The visible pending preview and controls remain stale and the click produces no recovery feedback. The confirm path already repaints and announces expiry; these two sibling controls do not.

An independent source VM probe created and revised a draft, expired its pending action, and called `editAction`: the resulting status was `expired` with **zero DOM calls**. The cancellation branch has the same no-feedback exit by inspection. No ticket is created, but the employee receives no explanation for a control that appears to work.

Required correction: on these invalid/expired operations refresh the visible summary/detail and announce the current state with the explicit new-request recovery. Add separate lazy-expiry click cases for edit and cancel; assert expiry, no ticket, visible expired feedback/recovery, and disappearance of actionable pending controls. The eager expiry test and lazy confirm test cannot cover these exits.

## F2 — P2: Comparison follow-up replaces the user's actual trip date

Locations: [app.js:95](C:/LLM-API/prototypes/education-agent/app.js:95), [app.js:211](C:/LLM-API/prototypes/education-agent/app.js:211).

Reproduction: ask **9월30일 출발한 부산 출장 숙박비**, then select **현재 기준과 비교해 줘**. The first answer correctly stores `eventDate=2026-09-30` and `region=other`. The classifier then creates a `compare` message without that context, and the comparison renderer labels both its historical column and its concluding statement **9월29일 시작**. A supported 2025 historical date is likewise replaced by the fixed example date. This changes a user-supplied fact while presenting the result as the existing trip's comparison.

An independent source VM probe confirmed the first answer's event date and the subsequent rendered `9월29일` comparison text. The amounts happen to use the same old edition in this example; the date statement is still false.

Required correction: bind comparison to the applicable preceding trip event and render its actual full date. Preserve that context on repeated comparison follow-ups, or explicitly ask for clarification when unavailable. Add regressions using a non-seed date such as 2026-09-30 and a 2025 date, asserting the rendered original date and absence of the substituted seed date.

# 3. Evidence reviewed

- Read `PRODUCT.md`, `DESIGN.md`, `.impeccable/design.json`, the target surface brief, and Impeccable's new-work/craft-floor guidance. The incumbent is the visual reference; there is no approved raster comp and no claim of comp fidelity.
- Opened all 12 required PNGs under `.impeccable/review/third-review/`: desktop, compact, and mobile × home, form, form-end, preview. All are valid images of the named states at 1440×900, 1280×720, and 390×844. Form/form-end are intentional top/end pairs of the internal scrolling viewport. No blank, malformed, or wrong-state capture requires recapture.
- Reviewed `third-review-browser-results.json`: 83 checks, no reported browser exceptions. Current SHA-256 values for `app.js` and `tests/browser-flows.cjs` match `source-fingerprints.json`, connecting that report to the reviewed source. The prior 54-check report remains separately present.
- The strengthened tests check recovered ticket identity, preserved head payload/status on a stale draft, and expired state/no ticket/no edit control. The added counterexamples cover departure selection, explicit/relative years, unsupported topics, IT versus education intent, clarification escape, dated education, lazy confirm expiry, exact-message edit focus, and background confirmation notification. These materially improve the evidence, but omit F1's two click paths and F2's dynamic comparison context.
- Reviewed the one detector result: the sole warning is pre-existing 11px secondary text. The accepted system already records this limitation; it does not justify an unauthorized visual redesign in this correction.
- The reviewed documents coherently describe independent root drafts with a single pending/confirmed head, field-origin validation, error order, normative-gap abstention, and token-budget/support-group evidence assembly. They remove the fixed five-passage cap and explicitly avoid promising discovery of every required source. No additional material contradiction was identified in those requested contracts.

# 4. Limits

This is a static prototype source/capture review, supplemented by source VM probes. I did not run a browser session or independently rerun the supplied 83-check suite. Screenshots establish the captured visual states, not every interaction or accessibility condition.

The verdict does not establish backend authentication, authorization/ACL enforcement, database concurrency or atomicity, idempotency, real ticket creation, field-origin enforcement, retrieval completeness, or RAG answer accuracy. Contract coherence is design evidence, not implementation proof. PDFs were outside the write/revalidation scope. The deterministic parser is intentionally bounded; requesting clarification for an unrecognized phrasing is not itself treated as a failure.

# 5. Required action

Fix F1 and F2 together in the authorized static prototype/test scope, preserve the accepted design, and rerun the relevant regression suite into a separate explicit output directory. Recapture the same 12 required states against the corrected source and verify their validity. Return that evidence for a verdict pass scoring **F1 and F2** as resolved, partial, or unresolved. Do not rerun the design detector or infer a whole-system approval from this review.
