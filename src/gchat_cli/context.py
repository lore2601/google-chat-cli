"""Shared state passed to every command, plus the write-guard used by mutations."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import click

from gchat_cli.client import BASE_URL, ChatClient
from gchat_cli.config import Config, Policy
from gchat_cli.errors import ConfirmationRequired, PolicyError
from gchat_cli.output import Printer


@dataclass
class AppContext:
    config: Config
    printer: Printer
    raw: bool = False
    debug: bool = False
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    client_factory: Callable[[], ChatClient] | None = None
    _client: ChatClient | None = None

    @property
    def policy(self) -> Policy:
        return self.config.policy

    @property
    def client(self) -> ChatClient:
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory()
            else:
                from google.auth.transport.requests import AuthorizedSession

                from gchat_cli.auth import load_credentials

                session = AuthorizedSession(load_credentials(self.env))
                self._client = ChatClient(session)
        return self._client

    def view(self, fn: Callable[[dict[str, Any]], dict[str, Any]], item: dict[str, Any]) -> Any:
        return item if self.raw else fn(item)

    # ------------------------------------------------------------------ writes

    def guard_write(
        self,
        *,
        space: str | None,
        action: str,
        request: dict[str, Any],
        yes: bool,
        dry_run: bool,
        summary: str,
        check_dm: bool = True,
    ) -> bool:
        """Apply policy, dry-run and confirmation to a mutation.

        Returns ``True`` when the caller should perform the request.
        """
        if space is not None:
            self.policy.require_write(space)
        elif self.policy.read_only:
            raise PolicyError("Writes are disabled (read-only mode)")

        if dry_run:
            self.printer.item({"dryRun": True, "action": action, "request": _describe(request)})
            return False

        if space is not None and check_dm and not self.policy.allow_dm_write:
            space_type = self.client.get_space(space).get("spaceType")
            self.policy.require_dm_write(space, space_type)

        confirm(summary, yes=yes, action=action, target=space)
        return True


def _describe(request: dict[str, Any]) -> dict[str, Any]:
    described = dict(request)
    path = described.pop("path", None)
    if path is not None:
        described["url"] = f"{BASE_URL}/{path}"
    return {k: v for k, v in described.items() if v not in (None, {}, [])}


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def confirm(summary: str, *, yes: bool, action: str, target: str | None) -> None:
    """Ask for confirmation on a TTY; require ``--yes`` otherwise."""
    if yes:
        return
    if _interactive():
        click.echo(summary, err=True)
        if not click.confirm("Proceed?", default=False, err=True):
            raise ConfirmationRequired("Cancelled by user", reason="cancelled")
        return
    raise ConfirmationRequired(
        f"{action} needs confirmation",
        hint="Review the action (use --dry-run to preview it), then re-run with --yes.",
        details={"action": action, "target": target},
    )
