"""``gchat api``: call any Google Chat REST method directly.

An escape hatch for methods without a dedicated command. The local policy
still applies: GET requests need read access to the space in the path, any
other method needs write access and confirmation.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

import click

from gchat_cli.commands._common import pass_app, write_options
from gchat_cli.context import AppContext
from gchat_cli.errors import ValidationError

_PATH_RE = re.compile(r"^[A-Za-z0-9_.@:~/-]+$")


def _parse_json(value: str | None, what: str) -> Any:
    if value is None:
        return None
    if value == "-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        try:
            with open(value[1:], encoding="utf-8") as handle:
                value = handle.read()
        except OSError as exc:
            raise ValidationError(f"Cannot read {what} file: {exc}") from exc
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{what} is not valid JSON: {exc}") from exc


def _validate_path(path: str) -> str:
    path = path.strip().removeprefix("/").removeprefix("v1/")
    if not path or not _PATH_RE.match(path) or ".." in path.split("/"):
        raise ValidationError(
            f"Invalid API path: {path!r}",
            hint="Pass a v1 resource path such as spaces/AAAA/messages (no query string).",
        )
    return path


def _space_in(path: str) -> str | None:
    match = re.match(r"^(?:users/[^/]+/)?(spaces/[A-Za-z0-9_-]+)", path)
    return match.group(1) if match else None


@click.command("api")
@click.argument(
    "method", type=click.Choice(["GET", "POST", "PATCH", "PUT", "DELETE"], case_sensitive=False)
)
@click.argument("path")
@click.option("-p", "--params", default=None, help="Query parameters as a JSON object.")
@click.option("-b", "--body", default=None, help="Request body as JSON, @file or '-' for stdin.")
@write_options
@pass_app
def group(
    app: AppContext,
    method: str,
    path: str,
    params: str | None,
    body: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Call any Chat REST method directly (escape hatch).

    \b
    Example:
      gchat api GET spaces/AAAA/messages -p '{"pageSize": 5}'

    PATH is relative to https://chat.googleapis.com/v1/. Output is the raw API response.
    """
    method = method.upper()
    path = _validate_path(path)
    query = _parse_json(params, "--params")
    if query is not None and not isinstance(query, dict):
        raise ValidationError("--params must be a JSON object")
    payload = _parse_json(body, "--body")
    space = _space_in(path)
    if method == "GET":
        if space:
            app.policy.require_read(space)
        if dry_run:
            app.printer.item(
                {"dryRun": True, "request": {"method": method, "path": path, "params": query}}
            )
            return
    else:
        request = {"method": method, "path": path, "params": query, "body": payload}
        if not app.guard_write(
            space=space,
            action=f"api.{method.lower()}",
            request=request,
            yes=yes,
            dry_run=dry_run,
            summary=f"{method} {path}\n{json.dumps(payload, indent=2) if payload else ''}",
        ):
            return
    app.printer.item(app.client.request(method, path, params=query, body=payload))
