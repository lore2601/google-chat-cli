"""Option decorators and helpers shared by command modules."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click

from gchat_cli import validation
from gchat_cli.context import AppContext
from gchat_cli.errors import ValidationError

F = TypeVar("F", bound=Callable[..., Any])

pass_app = click.make_pass_decorator(AppContext)


def pagination(default_limit: int) -> Callable[[F], F]:
    """Add ``--limit``, ``--all`` and ``--page-token``."""

    def decorator(fn: F) -> F:
        fn = click.option(
            "--page-token", default=None, metavar="TOKEN", help="Resume from a previous page."
        )(fn)
        fn = click.option(
            "--all", "fetch_all", is_flag=True, help="Fetch every page (ignores --limit)."
        )(fn)
        fn = click.option(
            "-n",
            "--limit",
            type=click.IntRange(min=1),
            default=default_limit,
            show_default=True,
            help="Maximum number of results.",
        )(fn)
        return fn

    return decorator


def write_options(fn: F) -> F:
    """Add ``--yes`` and ``--dry-run`` to a mutating command."""
    fn = click.option(
        "--dry-run", is_flag=True, help="Print the request that would be sent and exit."
    )(fn)
    fn = click.option(
        "-y",
        "--yes",
        is_flag=True,
        help="Do not ask for confirmation (required when not on a TTY).",
    )(fn)
    return fn


def text_options(fn: F) -> F:
    fn = click.option(
        "--text-file",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        default=None,
        help="Read the message text from a UTF-8 file.",
    )(fn)
    fn = click.option(
        "-t", "--text", default=None, help="Message text. Use '-' to read it from stdin."
    )(fn)
    return fn


def resolve_text(text: str | None, text_file: Path | None, *, required: bool = True) -> str | None:
    if text is not None and text_file is not None:
        raise ValidationError("Use either --text or --text-file, not both")
    if text == "-":
        value: str | None = sys.stdin.read()
    elif text_file is not None:
        try:
            value = text_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValidationError(f"Cannot read {text_file}: {exc}") from exc
    else:
        value = text
    if value is None:
        if required:
            raise ValidationError(
                "Message text is required", hint="Pass --text, --text -, or --text-file."
            )
        return None
    return validation.message_text(value)


def limit_of(limit: int, fetch_all: bool) -> int | None:
    return None if fetch_all else limit


def join_filters(*parts: str | None) -> str | None:
    present = [p for p in parts if p]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return " AND ".join(f"({p})" if " OR " in p else p for p in present)
