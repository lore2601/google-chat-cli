"""``gchat spaces``: list, inspect, search and create spaces."""

from __future__ import annotations

import uuid

import click

from gchat_cli import validation, views
from gchat_cli.commands._common import join_filters, limit_of, pagination, pass_app, write_options
from gchat_cli.config import WILDCARD
from gchat_cli.context import AppContext
from gchat_cli.errors import PolicyError
from gchat_cli.output import col

SPACE_TYPES = {"space": "SPACE", "group": "GROUP_CHAT", "dm": "DIRECT_MESSAGE"}

COLUMNS = [
    col("name", "name"),
    col("type", "spaceType"),
    col("display name", "displayName", 50),
    col("last active", "lastActiveTime"),
]


@click.group("spaces")
def group() -> None:
    """Spaces, group chats and direct messages."""


@group.command("list")
@click.option(
    "--type",
    "types",
    type=click.Choice(list(SPACE_TYPES)),
    multiple=True,
    help="Only this kind of space. Repeatable.",
)
@click.option("--filter", "raw_filter", default=None, help="Raw API filter expression.")
@pagination(100)
@pass_app
def list_spaces(
    app: AppContext,
    types: tuple[str, ...],
    raw_filter: str | None,
    limit: int,
    fetch_all: bool,
    page_token: str | None,
) -> None:
    """List the spaces you are a member of."""
    type_filter = " OR ".join(f'spaceType = "{SPACE_TYPES[t]}"' for t in types) or None
    page = app.client.list_spaces(
        filter=join_filters(type_filter, raw_filter),
        limit=limit_of(limit, fetch_all),
        page_token=page_token,
    )
    items = [s for s in page.items if app.policy.can_read(str(s.get("name")))]
    app.printer.items(
        [app.view(views.space, s) for s in items],
        COLUMNS,
        next_page_token=page.next_page_token,
        kind="spaces",
    )


@group.command("get")
@click.argument("space")
@pass_app
def get_space(app: AppContext, space: str) -> None:
    """Show one space. SPACE may be spaces/ID, an ID or a Chat URL."""
    name = validation.space_name(space)
    app.policy.require_read(name)
    app.printer.item(app.view(views.space, app.client.get_space(name)))


@group.command("search")
@click.argument("query")
@click.option(
    "--raw-query",
    is_flag=True,
    help="Treat QUERY as a full spaces.search expression instead of a display-name search.",
)
@click.option(
    "--order-by",
    type=click.Choice(["createTime DESC", "relevance DESC"]),
    default=None,
    help="Result ordering.",
)
@pagination(50)
@pass_app
def search(
    app: AppContext,
    query: str,
    raw_query: bool,
    order_by: str | None,
    limit: int,
    fetch_all: bool,
    page_token: str | None,
) -> None:
    """Search named spaces by display name."""
    if not raw_query:
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        query = f'displayName:"{escaped}" AND spaceType = "SPACE"'
    page = app.client.search_spaces(
        query, order_by=order_by, limit=limit_of(limit, fetch_all), page_token=page_token
    )
    items = [s for s in page.items if app.policy.can_read(str(s.get("name")))]
    app.printer.items(
        [app.view(views.space, s) for s in items],
        COLUMNS,
        next_page_token=page.next_page_token,
        kind="spaces",
    )


@group.command("find-dm")
@click.argument("user")
@pass_app
def find_dm(app: AppContext, user: str) -> None:
    """Find your direct-message space with USER (email or users/ID)."""
    space = app.client.find_direct_message(validation.user_name(user))
    app.policy.require_read(str(space.get("name")))
    app.printer.item(app.view(views.space, space))


@group.command("create")
@click.argument("display_name")
@click.option(
    "-m", "--member", "members", multiple=True, metavar="USER", help="Member email or users/ID."
)
@click.option("--description", default=None, help="Space description.")
@write_options
@pass_app
def create(
    app: AppContext,
    display_name: str,
    members: tuple[str, ...],
    description: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Create a named space and optionally add members (needs the 'full' scopes)."""
    if not app.policy.read_only and WILDCARD not in app.policy.write:
        raise PolicyError(
            "Creating spaces requires policy.write to include '*'",
            hint="New spaces cannot be in an allowlist before they exist.",
        )
    if not display_name.strip() or len(display_name) > 128:
        raise click.BadParameter("must be 1-128 characters", param_hint="DISPLAY_NAME")
    space: dict[str, object] = {"spaceType": "SPACE", "displayName": display_name}
    if description:
        space["spaceDetails"] = {"description": description}
    body = {
        "space": space,
        "requestId": str(uuid.uuid4()),
        "memberships": [
            {"member": {"name": validation.user_name(m), "type": "HUMAN"}} for m in members
        ],
    }
    request = {"method": "POST", "path": "spaces:setup", "body": body}
    summary = f"Create space {display_name!r} with {len(members)} member(s)"
    if app.guard_write(
        space=None,
        action="spaces.create",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=summary,
    ):
        app.printer.item(app.view(views.space, app.client.setup_space(body)))
