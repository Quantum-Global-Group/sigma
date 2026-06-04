# ADR 001 — Merge PR #1 with squash (not rebase)

**Status:** Accepted (2026-06)  
**Context:** Sprint 0 — close out the razorBill + sigma + tradeFlux merge ([PR #1](https://github.com/Quantum-Global-Group/sigma/pull/1)) with ~18 commits and one large WIP commit (`81ee40b`).

---

## Decision

**Squash-merge PR #1 into `main`** as a single commit (or a small number of logical commits if the WIP blob is split first). Do **not** rebase the feature branch onto `main` for this merge.

---

## Options considered

| Option | Pros | Cons |
|--------|------|------|
| **Squash merge** | Clean `main` history; one reviewable diff; no force-push on shared branch | Loses per-commit granularity on `main` (still in PR on GitHub) |
| **Rebase + merge** | Linear history with individual commits | Painful conflict resolution across 18 commits + WIP; easy to break local clones; little value for solo/side-project |
| **Merge commit** | Preserves branch topology | Noisy `main` graph; WIP commit message pollutes default log |
| **Reset + re-stage** | Maximum control | High operator time; only worth it if splitting `81ee40b` into reviewable chunks |

---

## Rationale

1. **Solo operator** — no team depends on per-commit bisect on `main`; GitHub PR timeline retains the original commits.
2. **WIP commit** — squash collapses experimental WIP into one intentional snapshot; optional follow-up: cherry-pick or split `81ee40b` *before* squash if a subset must land separately.
3. **CI / deploy** — first green baseline on `main` matters more than commit archaeology for M1 Fly deploy.
4. **Future PRs** — normal merge or squash per PR; this ADR does not forbid rebase on short-lived feature branches before opening a PR.

---

## Consequences

- After merge: delete `feat/razorbill-merge` locally and on remote (ROADMAP Sprint 0 checklist).
- Document in PR description: "Merged with squash per ADR 001."
- If `81ee40b` must not ship: reset/re-stage that commit **before** squash-merge, not after.

---

## Related

- [`docs/ROADMAP.md`](../ROADMAP.md) — Sprint 0 active items
- Planned: `docs/decisions/001-alpha-outcome.md` (Sprint 4 M1 → M2 go/no-go) — separate decision, not merge mechanics
