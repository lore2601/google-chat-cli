"""``gchat members``: space memberships."""

from __future__ import annotations

import click

from gchat_cli import validation, views
from gchat_cli.commands._common import join_filters, limit_of, pagination, pass_app
from gchat_cli.context import AppContext
from gchat_cli.output import col

COLUMNS = [
    col("member", "member"),
    col("display name", "displayName", 40),
    col("type", "type"),
    col("role", "role"),
    col("state", "state"),
]


@click.group("members")
def group() -> None:
    """Members of a space."""


@group.command("list")
@click.argument("space")
@click.option("--humans-only", is_flag=True, help="Exclude Chat apps.")
@click.option("--managers-only", is_flag=True, help="Only space managers.")
@click.option("--include-groups", is_flag=True, help="Include Google Group memberships.")
@click.option("--include-invited", is_flag=True, help="Include pending invitations.")
@click.option("--filter", "raw_filter", default=None, help="Raw API filter, ANDed with the rest.")
@pagination(100)
@pass_app
def list_members(
    app: AppContext,
    space: str,
    humans_only: bool,
    managers_only: bool,
    include_groups: bool,
    include_invited: bool,
    raw_filter: str | None,
    limit: int,
    fetch_all: bool,
    page_token: str | None,
) -> None:
    """List the members of SPACE."""
    name = validation.space_name(space)
    app.policy.require_read(name)
    page = app.client.list_members(
        name,
        filter=join_filters(
            'member.type = "HUMAN"' if humans_only else None,
            'role = "ROLE_MANAGER"' if managers_only else None,
            raw_filter,
        ),
        show_groups=include_groups,
        show_invited=include_invited,
        limit=limit_of(limit, fetch_all),
        page_token=page_token,
    )
    app.printer.items(
        [app.view(views.member, m) for m in page.items],
        COLUMNS,
        next_page_token=page.next_page_token,
        kind="members",
    )


@group.command("get")
@click.argument("membership")
@pass_app
def get_member(app: AppContext, membership: str) -> None:
    """Show one membership (spaces/X/members/Y)."""
    name = validation.member_name(membership)
    app.policy.require_read(validation.space_of(name))
    app.printer.item(app.view(views.member, app.client.get_member(name)))
