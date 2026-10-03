# Notes for coding agents working on this repository

- Python 3.11+, package in `src/gchat_cli`, CLI built with `click`, HTTP with `requests`
  through `google.auth.transport.requests.AuthorizedSession`.
- Layout: `client.py` (REST calls, retries, pagination), `auth.py` (OAuth and token
  storage), `config.py` (paths and `Policy`), `validation.py` (resource names, text, time),
  `views.py` (compact output), `output.py` (formats), `context.py` (`AppContext`,
  `guard_write`), `commands/*` (one click group per module), `cli.py` (root and error
  handling).
- Run `uv run ruff format src tests && uv run ruff check src tests && uv run mypy && uv run pytest`
  before finishing. Coverage must stay at or above 80%.
- Every new write command must call `app.guard_write(...)`, and every resource-name
  argument must go through `validation.*`. Add tests for rejected input.
- Never add network calls to unit tests. Mock them with `responses`.
- Keep `skills/gchat/SKILL.md` and `README.md` in sync with the command surface.
