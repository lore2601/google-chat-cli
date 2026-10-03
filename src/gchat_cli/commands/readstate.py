"""``gchat read-state``: your read position in a space."""

from __future__ import annotations

import click

from gchat_cli import validation
from gchat_cli.commands._common import pass_app, write_options
from gchat_cli.context import AppContext


@click.group("read-state")
def group() -> None:
    """Read / unread state of spaces."""


@group.command("get")
@click.argument("space")
@pass_app
def get_state(app: AppContext, space: str) -> None:
    """Show when you last read SPACE."""
    name = validation.space_name(space)
    app.policy.require_read(name)
    app.printer.item(app.client.get_read_state(name))


@group.command("mark-read")
@click.argument("space")
@click.option(
    "--time",
    "when",
    default=None,
    help="Mark as read up to this time (default: now). ISO 8601 or 30m/2h/7d ago.",
)
@write_options
@pass_app
def mark_read(app: AppContext, space: str, when: str | None, yes: bool, dry_run: bool) -> None:
    """Mark SPACE as read."""
    name = validation.space_name(space)
    timestamp = validation.timestamp(when or "0s")
    request = {
        "method": "PATCH",
        "path": f"users/me/{name}/spaceReadState",
        "params": {"updateMask": "lastReadTime"},
        "body": {"lastReadTime": timestamp},
    }
    if app.guard_write(
        space=name,
        action="read-state.mark-read",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=f"Mark {name} as read up to {timestamp}",
        check_dm=False,
    ):
        app.printer.item(app.client.update_read_state(name, timestamp))
