# Requirements Index

One row per REQ. Kept in sync with the REQ files by `steward lint` (status must match).
Move a REQ's row in the **same commit** as the REQ frontmatter and the code.

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | Tandoor Recipes fork — north star | DONE | [REQ-001](REQ-001.md) | – |
| REQ-002 | Fork image delivery — CI-built arm64 image and a backup-gated, repeatable deploy | DONE | [REQ-002](REQ-002.md) | REQ-001 |
| REQ-003 | Human-readable durations — render recipe and step times as hours and minutes | DONE | [REQ-003](REQ-003.md) | REQ-001, REQ-002 |
| REQ-004 | Bake schedule — back-chain step start times from a finish time | DONE | [REQ-004](REQ-004.md) | REQ-001, REQ-002, REQ-003 |
| REQ-005 | Offer readable durations upstream — a sanitized PR against TandoorRecipes/recipes | OPEN | [REQ-005](REQ-005.md) | REQ-001, REQ-003 |
| REQ-006 | Word importer — a .docx import path for the household's recipe collection | OPEN | [REQ-006](REQ-006.md) | REQ-001, REQ-002 |
| REQ-007 | Import repairs — a concrete repair list that fixes ingredient parsing at Word import | DRAFT | [REQ-007](REQ-007.md) | REQ-002, REQ-006 |

New requirement template: [`_templates/req.md`](_templates/req.md)
