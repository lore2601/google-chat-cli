# Using gchat with AI agents

`gchat` is designed to be driven by coding agents such as Claude Code, Gemini CLI, Codex and Cursor. Each one runs shell commands, reads JSON and acts on it. This page covers how to wire it up safely.

## Why a CLI instead of an MCP server?

- **No standing context cost.** MCP tool schemas are sent to the model on every turn. A CLI costs nothing until the agent runs it, and `gchat schema` gives a complete description on demand.
- **Composable.** Output pipes into `jq` and files, and the agent can combine `gchat` with `git`, `gh`, `glab` and other CLIs.
- **One tool for people and agents.** The same commands work in your terminal.

## Machine-friendly contract

| Feature | Detail |
|---|---|
| Output | JSON when stdout is not a TTY; `-f ndjson` streams one object per line |
| Compact views | Messages include only `name, sender, createTime, text, thread, attachments, reactions…`; `--raw` returns everything |
| Field masks | `--fields name,text` to save tokens |
| Pagination | `{"messages": [...], "nextPageToken": "…"}` with `--page-token` to continue |
| Errors | One JSON object on stderr with `exitCode`, `reason`, `message`, `hint` |
| Exit codes | `0` ok · `1` API/network · `2` auth · `3` invalid input · `4` policy/confirmation · `5` bug |
| Introspection | `gchat schema` / `gchat schema "messages send"` |
| Preview | `--dry-run` on every write prints the exact HTTP request |

## Safety profiles

Message text is written by other people and can contain prompt injections ("ignore previous instructions and send … to …"). Decide what an agent may do before it reads anything.

### Read-only assistant (summaries, search, triage)

```bash
gchat auth login --scopes readonly        # the token itself cannot write
export GCHAT_READ_ONLY=1                  # belt and braces
```

### Notifier (posts to one space, e.g. CI results)

```bash
export GCHAT_ALLOW_WRITE=spaces/AAQAbuilds
export GCHAT_ALLOW_DM_WRITE=0
export GCHAT_ALLOW_READ=spaces/AAQAbuilds   # optional: do not read anything else
```

### Interactive assistant (you approve each send)

Keep the default policy and let the agent's permission system ask you before any `gchat … --yes` command runs. In Claude Code, `.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(gchat spaces:*)",
      "Bash(gchat messages list:*)",
      "Bash(gchat messages get:*)",
      "Bash(gchat members list:*)",
      "Bash(gchat schema:*)",
      "Bash(gchat auth status)"
    ],
    "ask": [
      "Bash(gchat messages send:*)",
      "Bash(gchat messages reply:*)",
      "Bash(gchat messages edit:*)",
      "Bash(gchat messages delete:*)",
      "Bash(gchat reactions add:*)",
      "Bash(gchat api:*)"
    ]
  }
}
```

Without `--yes`, non-interactive writes always fail with exit code 4 (`confirmationRequired`). The agent therefore has to state its intent explicitly, and that intent is what your permission prompt shows.

## Installing the skill

The repository ships a skill at [`skills/gchat/SKILL.md`](../skills/gchat/SKILL.md) that teaches agents the commands and rules.

- **Claude Code (plugin):**
  ```
  /plugin marketplace add lore2601/google-chat-cli
  /plugin install gchat@google-chat-cli
  ```
- **Claude Code (manual):** copy `skills/gchat/` to `~/.claude/skills/gchat/`.
- **Other agents:** add the content of `SKILL.md` to the agent's instructions (for example `AGENTS.md` or `GEMINI.md`).

## Recipes

```bash
# What did I miss today in a space?
gchat messages list spaces/AAQA… --unread -n 50 --fields createTime,sender,text

# Post CI status into a thread keyed by commit
gchat messages send spaces/AAQA… --thread-key "build-$GITHUB_SHA" \
  --text "✅ Build $GITHUB_RUN_NUMBER passed" --yes

# Send a long report from a file, with an attachment
gchat messages send spaces/AAQA… --text-file summary.md -a report.pdf --yes

# DM a colleague by email (DM must already exist)
gchat messages send alice@example.com --text "PR is ready for review" --yes

# Anything not covered by a command
gchat api GET spaces/AAQA…/spaceEvents -p '{"filter":"eventTypes:\"google.workspace.chat.message.v1.created\""}'
```
