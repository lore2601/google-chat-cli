"""``gchat auth``: log in, inspect and revoke credentials."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

from gchat_cli import auth, config
from gchat_cli.commands._common import pass_app
from gchat_cli.context import AppContext


@click.group("auth")
def group() -> None:
    """Manage OAuth credentials."""


@group.command("login")
@click.option(
    "--scopes",
    "preset",
    type=click.Choice(list(auth.SCOPE_PRESETS)),
    default="default",
    show_default=True,
    help="Scope preset to request (see `gchat auth scopes`).",
)
@click.option(
    "--scope",
    "extra",
    multiple=True,
    metavar="SCOPE",
    help="Additional scope, short (chat.spaces) or full URL. Repeatable.",
)
@click.option(
    "--client-secrets",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="OAuth 'Desktop app' client JSON. It is copied to the config directory.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Print the authorization URL instead of opening a browser.",
)
@click.option(
    "--port",
    type=click.IntRange(0, 65535),
    default=0,
    show_default=True,
    help="Local callback port (0 = random free port).",
)
@pass_app
def login(
    app: AppContext,
    preset: str,
    extra: tuple[str, ...],
    client_secrets: Path | None,
    no_browser: bool,
    port: int,
) -> None:
    """Authorize gchat with your Google account (browser-based OAuth)."""
    env = dict(app.env)
    saved_to = None
    if client_secrets is not None:
        target = config.client_secrets_file(env)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if client_secrets.resolve() != target.resolve():
            shutil.copyfile(client_secrets, target)
            os.chmod(target, 0o600)
            saved_to = str(target)
    scopes = auth.expand_scopes([preset], extra)
    result = auth.login(scopes, open_browser=not no_browser, port=port, env=env)
    if saved_to:
        result["clientSecretsSavedTo"] = saved_to
    app.printer.item(result)


@group.command("status")
@pass_app
def status(app: AppContext) -> None:
    """Show whether you are logged in, with which scopes (never prints secrets)."""
    app.printer.item(auth.status(app.env))


@group.command("logout")
@click.option("--no-revoke", is_flag=True, help="Only delete local credentials, do not revoke.")
@pass_app
def logout(app: AppContext, no_revoke: bool) -> None:
    """Revoke the refresh token and delete stored credentials."""
    app.printer.item(auth.logout(revoke=not no_revoke, env=app.env))


@group.command("scopes")
@pass_app
def scopes(app: AppContext) -> None:
    """List the available scope presets."""
    items = [
        {"preset": name, "scopes": ", ".join(values)} for name, values in auth.SCOPE_PRESETS.items()
    ]
    from gchat_cli.output import col

    app.printer.items(items, [col("preset", "preset"), col("scopes", "scopes")], kind="presets")
