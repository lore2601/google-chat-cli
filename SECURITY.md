# Security policy

## Supported versions

Only the latest released version receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through
[GitHub Security Advisories](https://github.com/lore2601/google-chat-cli/security/advisories/new).
Include steps to reproduce and the impact. You should get an answer within 7 days.

## Scope and threat model

`gchat` acts with the OAuth credentials of the person who logged in. The main risks are:

- **Credential exposure.** Tokens are stored in `~/.config/gchat/token.json` (mode
  `0600`) or in the OS keyring, and must never be printed or logged.
- **Prompt injection through chat content.** An agent may be manipulated by message text
  into sending or deleting messages. Mitigations are the local policy (allowlists,
  read-only mode, DM blocking), mandatory `--yes` and strict argument validation.
  Bypasses of these controls are in scope.
- **Path traversal or terminal injection** through attachment names or message text.

Out of scope: issues in Google's APIs themselves, and a compromised local user account.
