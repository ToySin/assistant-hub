# /add-command — Create a new command or skill

Meta-skill: scaffold a new `.claude/commands/<name>.md` (or skill
bundle under `.claude/skills/<name>/`), with the right shape and an
entry in `CLAUDE.md`.

## 0. Prerequisite reading

Before writing the new skill, look at one or two existing ones in
`.claude/commands/` and `.claude/skills/` so the shape matches. The
existing patterns:

- **Single-file command**: `.claude/commands/<name>.md` — most skills
  here. Steps + Notes pattern.
- **Skill bundle (router)**: `.claude/commands/<name>.md` + a
  `.claude/skills/<name>/{_rules,sub1,sub2}.md` directory. Use this
  when the skill has 3+ distinct branches that share rules
  (`/ws-config`, `/idea`).

## 1. Gather basics

Confirm with the user (infer from args / conversation when obvious):

| Item | Description | Default |
|------|-------------|---------|
| Name | kebab-case, single word preferred | from args |
| Type | single command vs skill bundle | single unless 3+ branches |
| Purpose | one-line description | — |
| Auto-trigger? | should the agent propose this skill on certain phrases? | no |
| Companion python helper? | does it need state / queries / non-trivial logic? | no — most skills are pure prompt |

Stop and ask only for fields you can't infer.

## 2. Scaffold

### Single command

Create `.claude/commands/<name>.md`. Skeleton:

```markdown
# /<name> — <one-line purpose>

<short paragraph: what it does, when to use it, what NOT to use it for
(point at the closest neighbor skill).>

## Procedure

### Step 1. ...
### Step 2. ...

## Notes

- <gotcha or constraint>
```

Match the existing tone: tight, no filler, example commands inline.

### Skill bundle

Create:

- `.claude/commands/<name>.md` — router. Lists subcommands and points
  at the matching `.claude/skills/<name>/<sub>.md`.
- `.claude/skills/<name>/_rules.md` — hard rules shared by every
  branch.
- `.claude/skills/<name>/<sub>.md` — one per branch.

Match `/ws-config` and `/idea` shape.

### Auto-trigger language

If the skill should be proposed proactively, add a "When to use
proactively" section near the top with example trigger phrases. Don't
make the trigger too broad — the agent will fire too often.

## 3. Companion helper (optional)

If the skill genuinely needs Python code (state, queries, non-trivial
logic), create `library/<name>.py` with a CLI entry:

```python
def main():
    ...

if __name__ == "__main__":
    main()
```

Invoke it from the skill via `python -m library.<name>`. Keep the
skill in charge of the conversation; the helper does mechanical work.

Don't create a helper for skills that are pure orchestration prompts
(`/debug`, `/infra`, `/code-infra` for example).

## 4. Update the index

Add an entry to the Skills table in `CLAUDE.md`:

```markdown
| [`<name>`](./.claude/commands/<name>.md) | <one-line purpose> | <when to use> |
```

If a Python helper was created, also add it to the Code table.

## 5. Verify

- Read the new file end to end. Does a fresh agent know exactly
  what to do, with no ambient context?
- For auto-trigger skills: re-read the trigger phrases. Are they
  specific enough that the skill won't fire on unrelated content?
- If the description / trigger is too broad, narrow it. A noisy
  auto-trigger is worse than no auto-trigger.

## 6. Test

- Single command: invoke `/<name>` in a fresh conversation. Does it
  do what the skill says?
- Auto-trigger skill: try a sample phrase that *should* trigger and
  one that shouldn't. Tune trigger language as needed.

Don't ship without one round of self-test.

## Notes

- Don't create a skill for something `gh`/`grep`/`python -m` already
  does in one line. Skills are for multi-step procedures with
  judgment.
- Don't duplicate functionality. If the new skill overlaps an
  existing one, propose extending the existing one instead.
- File content goes in English; conversational tone in skills can be
  Korean if that's what the workspace uses (see existing skills).
