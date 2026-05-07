# Hard rules — apply to every /ws-config branch

- **Never write to `.env`.** Credentials stay in the user's hands. If a
  step needs new env vars, print the lines they should add and stop.
  Even if asked, refuse and remind why.
- **Never blank out a source the user didn't touch this session.** If
  jira was enabled with config and the user didn't pick jira this time,
  leave jira alone.
- **Preserve file structure.** Keep category comments, the `auth_env`
  pointer style, and field ordering as they were in the template.
- **Validate before recording.** Path doesn't exist → ask again. URL
  unreachable → flag it (don't fail, but tell the user).
- **One thing at a time.** Don't ask 5 questions in one block.
- **Bail gracefully.** If the user says "skip" / "cancel" / "stop",
  acknowledge and exit without writing.

## When a discovery tool errors out

If an MCP / CLI tool errors out (auth missing, network, etc.), do NOT
loop on retries. Tell the user briefly, then ask them to type the
value manually. Note in the final summary: "Atlassian MCP not available, `project_keys` entered manually".
