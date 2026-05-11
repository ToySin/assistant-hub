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
under each item. It also prints an **Orphan issues** section: open
issues with no PR, not blocking/blocked — these are stuck in backlog
and need a decision (close, defer, or start a PR).

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
- If there's a large orphan list: propose a backlog pruning pass
  (mark done / defer / assign PRs) before picking new work.

Keep it tight: one recommendation, one sentence on why, optionally a
"runner-up if you prefer X" line.

### Step 4. (Optional) start the work

If the user confirms, begin the actual work:

- Read the chosen issue body to load the task spec.
- For ports of hub features (`B3.*` issues), read the corresponding
  `~/repositories/hub/*.md` and the linked source files.
- Default to making changes in `assistant-hub/` core unless the work
  is workspace-specific.

### Step 5. Record the resolution

After handling an event manually, close the loop so the system learns:

```bash
# Mark event resolved (outcome defaults to 'success')
python -m library.act --resolve <event_id>

# If the fix failed or was only partial
python -m library.act --resolve <event_id> --outcome fail

# With a note (stored on the resolution record)
python -m library.act --resolve <event_id> --note "squash-merged, fixed in PR #42"
```

What happens:
- If a runbook already matches the event → `record_outcome` is called, which may **promote** the runbook's automation level (manual → semi-auto → auto after enough successes).
- If no runbook matches and outcome is `success` → a new **semi-auto** runbook is auto-created from the event pattern. Next time this kind+source fires, it will be surfaced as a proposal.
- The event row is marked `status=resolved` and disappears from future `/briefing` and `/act` replay sections.

This is the self-reinforcing loop: manual work surfaces patterns; patterns become proposals; proposals become automations.

### Step 6. (When applicable) fire AUTO runbooks

`/act` reads recent monitor events (since-last-replay) and matches
them against `/runbooks`. The output ends with a "Runbook proposals"
section labelling each match `AUTO` / `PROPOSE` / `MANUAL` based on
the runbook's automation level.

```bash
python -m library.act --execute   # fires AUTO-level matches
```

`--execute` runs each `auto`-level proposal's commands via shell,
records success/fail on the runbook (which can promote/demote per
the policy), and emits an `act runbook.executed.<outcome>` audit
event. `semi-auto` and `manual` proposals are never auto-fired —
they're surfaced for the user/agent to decide.

## Notes

- Scoring is **graph-driven**, not LLM-driven — same input always
  gives the same buckets. As more data flows in (assignees, statuses,
  PRs implementing issues, blockers), the buckets get richer
  automatically without code changes.
- `--execute` is opt-in for safety. Default `/act` is read-only.
