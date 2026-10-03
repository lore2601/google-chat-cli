# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-03

### Added

- `auth login | status | logout | scopes`: OAuth Desktop-app login with scope presets
  (`readonly`, `default`, `full`), `0600` token file or OS keyring, `--no-browser` mode,
  7-day Testing-mode warning.
- `spaces list | get | search | find-dm | create`.
- `messages list | get | send | reply | edit | delete`, with time filters (`--since 2h`),
  `--unread`, threads, DMs by email, stdin/file input and attachments.
- `members list | get`, `reactions list | add | remove`, `attachments get | download`,
  `read-state get | mark-read`.
- `api` escape hatch for any Chat REST method, `schema` for machine-readable command
  descriptions, `config show | init`.
- JSON / NDJSON / table output, `--fields`, `--raw`, stable exit codes and JSON errors.
- Safety rails: local read/write allowlists, read-only mode, DM write blocking, mandatory
  `--yes` for non-interactive writes, `--dry-run`, strict resource-name validation.
- Retries with exponential backoff on 429/5xx.
- Agent skill (`skills/gchat/SKILL.md`) and Claude Code plugin marketplace manifest.

[Unreleased]: https://github.com/lore2601/google-chat-cli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lore2601/google-chat-cli/releases/tag/v0.1.0
