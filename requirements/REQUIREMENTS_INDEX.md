# Requirements Index

One row per REQ. Kept in sync with the REQ files by `steward lint` (status must match).
Move a REQ's row in the **same commit** as the REQ frontmatter and the code.

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | Tandoor Recipes fork — north star | DONE | [REQ-001](REQ-001.md) | – |
| REQ-002 | Fork image delivery — CI-built arm64 image and a backup-gated, repeatable deploy | DONE | [REQ-002](REQ-002.md) | REQ-001 |
| REQ-003 | Human-readable durations — render recipe and step times as hours and minutes | DONE | [REQ-003](REQ-003.md) | REQ-001, REQ-002 |

New requirement template: [`_templates/req.md`](_templates/req.md)
