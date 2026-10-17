# Contract fixes documentation result

2026-10-17 · approved input-border system delta · source-only documentation pass

**Result: the approved input boundary correction is documented within the incumbent visual system.** The existing composition, fonts, palette roles, focus treatment, and removed-toolbar direction remain the authority. This pass did not introduce a new visual identity.

## Files changed

- [DESIGN.md](../../DESIGN.md:148): added application guidance for the existing `colors.input-border` primitive: question composer and IT request input, select, and textarea boundaries. The composer description now names that token. The previously added primitive and scope note were preserved.
- [design.json](../design.json:105): added only `extensions.colorMeta.input-border` with neutral role, the display name “입력 경계 회청색”, and an eight-step dark-to-light OKLCH preview ramp derived from the approved color. Updated only the composer snippet's former literal `#bccbd8` border to `var(--color-input-border,#75899b)` at line 276.
- This result record.

## Source evidence

- [Surface direction contract](../surfaces/prototypes-education-agent-index-html.md:24) records the approved input-border correction and limits the design-document changes to the related token/component. It retains the first screen, color/font/layout direction, and manual-state-menu removal.
- [PRODUCT.md](../../PRODUCT.md:39) retains the accepted conversation list, central conversation, optional detail/source structure, and incumbent visual principles.
- [styles.css](../../prototypes/education-agent/styles.css:10) defines `--color-input-border: #75899b`; the [composer](../../prototypes/education-agent/styles.css:127) and [form fields](../../prototypes/education-agent/styles.css:166) use it. The existing composer focus treatment remains at line 128.
- [document.md](C:/Users/GUNWOO/.codex/skills/impeccable/reference/document.md) keeps primitives in DESIGN.md and extension metadata/component snippets in the schemaVersion 2 sidecar. The tonal ramp is panel preview metadata, not an additional adopted UI scale.

## Verification and preserved boundaries

Parsed the sidecar successfully as JSON and compared its parsed content with the pre-edit source. Removing the new metadata entry and reversing the single composer border substitution reproduces the entire previous sidecar. Schema version 2, title, component count of seven, all existing metadata, narrative, and other HTML/CSS snippets are unchanged. DESIGN.md differs only in the added color application bullet and the composer description's token reference.

No token primitives were duplicated into the sidecar. The preexisting frontmatter placement and stale toolbar wording were left as supplied. No UI source, other documentation, browser state, detector, or PDF was changed by this pass. Browser captures and functional checks are the parent task's independent work; this record makes no claim about their results or production/service testing.
