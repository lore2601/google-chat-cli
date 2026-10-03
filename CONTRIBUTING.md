# Contributing

Thanks for helping improve `gchat`!

## Development setup

```bash
git clone git@github.com:lore2601/google-chat-cli.git
cd google-chat-cli
uv sync                     # creates .venv with runtime + dev dependencies
uv run gchat --help
uv run pre-commit install   # optional: uvx pre-commit install
```

## Checks (same as CI)

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run mypy
uv run pytest --cov
```

Unit tests never touch the network: HTTP is mocked with
[`responses`](https://github.com/getsentry/responses).

## Design guidelines

- **stdout is data only.** Diagnostics go to stderr. Every failure raises a
  `GchatError` subclass, which maps to a documented exit code.
- **Every mutation goes through `AppContext.guard_write`**. It applies the policy,
  `--dry-run` and confirmation.
- **Validate every resource name** with `gchat_cli.validation` before it reaches a URL.
  Treat arguments as untrusted, because agents generate them.
- **Keep default output compact** (`views.py`). Expose full objects only with `--raw`.
- Add a dedicated command only when it adds value over `gchat api` (validation,
  multi-step logic, friendlier inputs).
- Update `README.md`, `docs/`, `skills/gchat/SKILL.md` and `CHANGELOG.md` (Unreleased)
  for user-facing changes.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
`docs:`, `ci:`, `refactor:`, `test:`, `deps:`).

## Releasing (maintainers)

1. Update `__version__` in `src/gchat_cli/__init__.py`, the versions in
   `.claude-plugin/*.json`, and move the `Unreleased` notes in `CHANGELOG.md` under
   the new version.
2. Commit, then tag and push: `git tag v0.2.0 && git push origin v0.2.0`.
3. The **Release** workflow tests, builds, attests and creates the GitHub release.

### Enabling PyPI publishing (one-time)

1. On PyPI, add a *pending trusted publisher*: project `google-chat-cli`, owner
   `lore2601`, repository `google-chat-cli`, workflow `release.yml`, environment `pypi`.
2. In GitHub → Settings → Environments, create the environment `pypi`. Optionally
   require reviewers.
3. In GitHub → Settings → Variables → Actions, add `PYPI_PUBLISH` = `true`.
