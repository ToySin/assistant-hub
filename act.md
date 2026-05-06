# /act — Assess + prioritize what to tackle next

Read the workspace graph, classify open items P0–P3 by graph signals
(blockers, in-flight PRs, status), and recommend a concrete next step.
Different from `/briefing` (which is a state snapshot): act is the
prioritization layer.

## Prerequisites

- `ASSISTHUB_WORKSPACE` is set or pointer file is configured.
- The workspace's graph DB exists (run an ETL first if you haven't).

## Procedure

### Step 1. Refresh state (optional but recommended)

If the data might be stale (e.g., issues closed or assigned since the
last sync):

```bash
python -m library.sources.run    # delta sync, fast
```

### Step 2. Run the data layer

```bash
python -m library.act
```

This prints buckets P0 (unblockers — do first), P1 (in flight —
finish), P2 (open backlog), P3 (blocked — wait), with a short reason
under each item.

### Step 3. Add the recommendation

The python module gives the buckets. Your job is to **pick one**:

- If P0 is non-empty: take the first P0 item — it unblocks the most
  downstream work.
- If P0 is empty but P1 is non-empty: pick the P1 closest to landing
  (PR with reviews approved, or status="In Review").
- If only P2 remains: pick the smallest one if energy is low, the
  highest-leverage one if energy is high. State which heuristic you
  used.
- If only P3 remains: explain what would unblock and propose surfacing
  it to the blocker's owner.

Keep it tight: one recommendation, one sentence on why, optionally a
"runner-up if you prefer X" line.

### Step 4. (Optional) start the work

If the user confirms, begin the actual work:

- Read the chosen issue body to load the task spec.
- For ports of hub features (`B3.*` issues), read the corresponding
  `~/repositories/hub/*.md` and the linked source files.
- Default to making changes in `assistant-hub/` core unless the work
  is workspace-specific.

## Notes

- Scoring is **graph-driven**, not LLM-driven — same input always
  gives the same buckets. As more data flows in (assignees, statuses,
  PRs implementing issues, blockers), the buckets get richer
  automatically without code changes.
- This skill does not auto-execute (yet). Hub's `/act` runs
  approved-and-CI-green PR merges, runbook steps, etc.; for
  assistant-hub MVP we stop at the recommendation. Auto-execution
  comes after `/monitor` (#10) lands.
