# gchat: Google Chat from the command line

[![CI](https://github.com/lore2601/google-chat-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/lore2601/google-chat-cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/google-chat-cli)](https://pypi.org/project/google-chat-cli/)
[![CodeQL](https://github.com/lore2601/google-chat-cli/actions/workflows/codeql.yml/badge.svg)](https://github.com/lore2601/google-chat-cli/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

`gchat` is a command-line interface for the [Google Chat API](https://developers.google.com/workspace/chat/api/reference/rest). It is meant for **AI agents** (Claude Code, Gemini CLI, Codex, custom scripts) and works just as well for people. You can read spaces, search, send and reply to messages, react, download attachments and mark spaces as read, all with predictable JSON output and safety rails.

> **Unofficial.** This project is not affiliated with or endorsed by Google.

```console
$ gchat spaces list --type space
NAME              TYPE   DISPLAY NAME        LAST ACTIVE
spaces/AAQAxyz12  SPACE  Platform team       2026-10-02T16:41:10Z
spaces/AAQAabc34  SPACE  Release managers    2026-10-01T09:12:55Z

$ gchat messages list spaces/AAQAxyz12 --since 1d -n 2 -f json
{"messages":[{"name":"spaces/AAQAxyz12/messages/k1.k1","sender":"users/1067…","senderType":"HUMAN","createTime":"2026-10-02T16:41:10Z","text":"Deploy done ✅","thread":"spaces/AAQAxyz12/threads/k1"}]}

$ gchat messages reply spaces/AAQAxyz12/messages/k1.k1 --text "Thanks, verified on staging" --yes
```

## Why another tool?

| | `gchat` | MCP servers | `gws` (Google Workspace CLI) |
|---|---|---|---|
| Zero context cost until used | ✅ plain CLI | ❌ tool schemas loaded every turn | ✅ |
| Chat-specific helpers (reply, unread, DM by email, attach) | ✅ | varies | partly (`+send`) |
| Compact, token-efficient output by default | ✅ `--raw` for full objects | varies | `--fields` |
| Local safety policy (allowlists, read-only, DM block) | ✅ | some | ❌ |
| Mandatory `--yes` for writes when non-interactive | ✅ | client-side | ❌ |
| Install | `pipx`/`uv tool` | per-client config | binary/npm |

The design borrows proven ideas from [googleworkspace/cli](https://github.com/googleworkspace/cli): structured JSON, stable exit codes, `--dry-run`, field masks, schema introspection and agent skills. It also takes the per-space read/write allowlist and DM protection from [nuccio/google-chat-mcp](https://github.com/nuccio/google-chat-mcp).

## Install

Requires Python 3.11+.

```bash
pipx install google-chat-cli        # or: uv tool install google-chat-cli
# latest development version:
pipx install git+https://github.com/lore2601/google-chat-cli
```

Optional: store the token in the OS keyring instead of a file:

```bash
pipx install "google-chat-cli[keyring]"
export GCHAT_TOKEN_STORE=keyring
```

## Set up (5 minutes, once)

The Chat API needs a Google Cloud project with the Chat API enabled and an OAuth **Desktop app** client. The full walkthrough is in **[docs/setup.md](docs/setup.md)**. In short:

1. Create or choose a Google Cloud project and enable the **Google Chat API**.
2. Configure the Chat app (name, avatar, description) in *Chat API → Configuration*. This is required even for user-auth clients.
3. Configure the OAuth consent screen (Internal for Workspace orgs) and create an OAuth client ID of type **Desktop app**. Download its JSON.
4. Log in:

```bash
gchat auth login --client-secrets ~/Downloads/client_secret_XXXX.json
gchat auth status
```

Scope presets: `readonly`, `default` (read + send, react, mark read) and `full` (adds space/member management). For example: `gchat auth login --scopes readonly`.

## Commands

| Command | What it does |
|---|---|
| `gchat auth login \| status \| logout \| scopes` | OAuth login (browser), inspection, revocation |
| `gchat spaces list [--type space\|group\|dm]` | Spaces, group chats and DMs you belong to |
| `gchat spaces get SPACE` | Space details (accepts `spaces/ID`, `ID` or a Chat URL) |
| `gchat spaces search QUERY` | Find named spaces by display name |
| `gchat spaces find-dm USER` | Your DM space with a user (email or `users/ID`) |
| `gchat spaces create NAME [-m USER]…` | Create a space (scope `full`) |
| `gchat messages list SPACE [--since 2h] [--until …] [--thread …] [--unread]` | Read messages, newest first |
| `gchat messages get MESSAGE` | One message |
| `gchat messages send TARGET -t TEXT [--thread …\|--thread-key …] [-a FILE]…` | Send to a space, or to a user's DM by email |
| `gchat messages reply MESSAGE -t TEXT` | Reply in the thread of a message |
| `gchat messages edit MESSAGE -t TEXT` / `delete MESSAGE` | Edit or delete your messages |
| `gchat members list SPACE [--humans-only]` | Space members |
| `gchat reactions list\|add\|remove` | Emoji reactions |
| `gchat attachments get\|download` | Attachment metadata and download |
| `gchat read-state get\|mark-read SPACE` | Read position, mark as read |
| `gchat api METHOD PATH [-p JSON] [-b JSON]` | Escape hatch: any Chat REST method |
| `gchat config show\|init` | Effective policy and file locations |
| `gchat schema [COMMAND]` | Every command, option and exit code as JSON |

Run `gchat COMMAND --help` for details. Text can come from `--text`, from stdin with `--text -`, or from `--text-file`.

## Output and exit codes

- **stdout carries only data.** In a terminal you get tables. When piped or run by an agent you get JSON. Force a format with `-f json|ndjson|table` or `GCHAT_FORMAT`.
- Lists return `{"<kind>": [...], "nextPageToken": "..."}`. Use `--limit/-n`, `--all` and `--page-token` to paginate.
- `--fields name,text,sender` trims output (dotted paths allowed). `--raw` returns untouched API objects.
- **Errors** are a single JSON object on stderr, for example `{"error": {"exitCode": 4, "reason": "confirmationRequired", "message": "…", "hint": "…"}}`.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Google Chat API or network error |
| 2 | Authentication problem (not logged in, token revoked, …) |
| 3 | Invalid input (bad resource name, malformed JSON, text too long, …) |
| 4 | Blocked by local policy, or confirmation (`--yes`) missing |
| 5 | Internal error (please report it) |

## Safety model

Agents can be steered by what they read, and chat messages are written by other people. `gchat` puts guard rails **in front of** the API:

- **Writes need explicit confirmation.** On a terminal you are prompted. Without a TTY (agents, scripts) every write fails with exit code 4 unless you pass `--yes`. `--dry-run` shows the exact request without sending it.
- **Local policy** in `~/.config/gchat/config.toml` or environment variables:

  ```toml
  [policy]
  read_only = false              # GCHAT_READ_ONLY=1 blocks every write
  allow_dm_write = false         # GCHAT_ALLOW_DM_WRITE=0 blocks writes to DMs / group chats
  read  = ["*"]                  # GCHAT_ALLOW_READ="spaces/AAA,spaces/BBB"
  write = ["spaces/AAQAxyz12"]   # GCHAT_ALLOW_WRITE=...
  ```

- **Strict input validation.** Resource names are checked against strict patterns, so arguments like `spaces/../users` or `?`/`#` injections are rejected. Download filenames are reduced to safe basenames, and existing files are never overwritten without `--overwrite`.
- **Terminal-safe tables.** ANSI escape sequences and control characters in message text are stripped before printing.
- **Credentials** are stored with `0600` permissions (or in the OS keyring) and are never printed by any command.

See [docs/agents.md](docs/agents.md) for recommended agent profiles.

## Using gchat with AI agents

- **Claude Code plugin:** `/plugin marketplace add lore2601/google-chat-cli`, then `/plugin install gchat@google-chat-cli`. This installs the [`gchat` skill](skills/gchat/SKILL.md), which teaches the agent the commands, the safety rules and that message content is untrusted.
- **Any agent:** copy [`skills/gchat/SKILL.md`](skills/gchat/SKILL.md) into your agent's skills folder, or point it at `gchat schema`.
- Recommended for unattended agents: `GCHAT_ALLOW_WRITE=<one space>`, `GCHAT_ALLOW_DM_WRITE=0` and an allow-rule in your agent for `gchat * --dry-run` only.

## Configuration reference

| Variable | Purpose |
|---|---|
| `GCHAT_CONFIG_DIR` | Config directory (default `~/.config/gchat`) |
| `GCHAT_CONFIG` | Config file path (default `$GCHAT_CONFIG_DIR/config.toml`) |
| `GCHAT_CLIENT_SECRETS` | OAuth client JSON (default `$GCHAT_CONFIG_DIR/client_secret.json`) |
| `GCHAT_CLIENT_ID` / `GCHAT_CLIENT_SECRET` | OAuth client given inline instead of the JSON file |
| `GCHAT_TOKEN_FILE` | Token file (default `$GCHAT_CONFIG_DIR/token.json`) |
| `GCHAT_TOKEN_STORE` | `file` (default) or `keyring` |
| `GCHAT_ACCESS_TOKEN` | Use this raw access token (CI, short-lived jobs) |
| `GCHAT_CREDENTIALS_FILE` | Use an `authorized_user` JSON (e.g. exported from another machine) |
| `GCHAT_FORMAT` | Default output format |
| `GCHAT_READ_ONLY`, `GCHAT_ALLOW_READ`, `GCHAT_ALLOW_WRITE`, `GCHAT_ALLOW_DM_WRITE` | Policy overrides |

## Limitations

- User authentication only. Sending as a Chat **app** (bot) or incoming webhooks are out of scope.
- With user auth, Google Chat returns sender **IDs**, not display names, unless the sender shares a space with you. Use `gchat members list` to map IDs.
- Files shared from Google Drive cannot be downloaded through the Chat API.
- If your OAuth consent screen is in *Testing* mode, Google expires refresh tokens after 7 days. `gchat auth status` warns you.

## Contributing

Issues and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report security issues privately (see [SECURITY.md](SECURITY.md)).

## License

[Apache-2.0](LICENSE)
