"""``gchat reactions``: emoji reactions on messages."""

from __future__ import annotations

import click

from gchat_cli import validation, views
from gchat_cli.commands._common import limit_of, pagination, pass_app, write_options
from gchat_cli.context import AppContext
from gchat_cli.errors import ValidationError
from gchat_cli.output import col

COLUMNS = [col("emoji", "emoji"), col("user", "user"), col("name", "name")]


@click.group("reactions")
def group() -> None:
    """Emoji reactions."""


@group.command("list")
@click.argument("message")
@click.option("--emoji", default=None, help="Only this unicode emoji.")
@pagination(25)
@pass_app
def list_reactions(
    app: AppContext,
    message: str,
    emoji: str | None,
    limit: int,
    fetch_all: bool,
    page_token: str | None,
) -> None:
    """List reactions on MESSAGE."""
    name = validation.message_name(message)
    app.policy.require_read(validation.space_of(name))
    flt = None
    if emoji:
        if '"' in emoji or "\\" in emoji:
            raise ValidationError("Invalid emoji")
        flt = f'emoji.unicode = "{emoji}"'
    page = app.client.list_reactions(
        name, filter=flt, limit=limit_of(limit, fetch_all), page_token=page_token
    )
    app.printer.items(
        [app.view(views.reaction, r) for r in page.items],
        COLUMNS,
        next_page_token=page.next_page_token,
        kind="reactions",
    )


@group.command("add")
@click.argument("message")
@click.argument("emoji")
@write_options
@pass_app
def add(app: AppContext, message: str, emoji: str, yes: bool, dry_run: bool) -> None:
    """React to MESSAGE with a unicode EMOJI (e.g. 👍)."""
    name = validation.message_name(message)
    if not emoji.strip() or len(emoji) > 16 or emoji.isascii():
        raise ValidationError(f"Invalid emoji {emoji!r}", hint="Pass a unicode emoji such as 👍")
    body = {"emoji": {"unicode": emoji}}
    request = {"method": "POST", "path": f"{name}/reactions", "body": body}
    if app.guard_write(
        space=validation.space_of(name),
        action="reactions.add",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=f"React {emoji} to {name}",
    ):
        created = app.client.create_reaction(name, body["emoji"])
        app.printer.item(app.view(views.reaction, created))


@group.command("remove")
@click.argument("reaction")
@write_options
@pass_app
def remove(app: AppContext, reaction: str, yes: bool, dry_run: bool) -> None:
    """Remove one of your reactions (spaces/X/messages/Y/reactions/Z)."""
    name = validation.reaction_name(reaction)
    request = {"method": "DELETE", "path": name}
    if app.guard_write(
        space=validation.space_of(name),
        action="reactions.remove",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=f"Remove reaction {name}",
    ):
        app.client.delete_reaction(name)
        app.printer.item({"deleted": name})
