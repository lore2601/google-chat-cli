"""``gchat messages``: read, send, reply, edit and delete messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from gchat_cli import validation, views
from gchat_cli.commands._common import (
    join_filters,
    limit_of,
    pagination,
    pass_app,
    resolve_text,
    text_options,
    write_options,
)
from gchat_cli.context import AppContext
from gchat_cli.errors import ValidationError
from gchat_cli.output import col

COLUMNS = [
    col("time", "createTime"),
    col("sender", "sender"),
    col("text", "text", 80),
    col("name", "name"),
]

MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024


@click.group("messages")
def group() -> None:
    """Messages in a space."""


def _resolve_target(app: AppContext, target: str) -> str:
    """Map a space reference or a user (email / users/ID) to a space name."""
    if validation.is_user_reference(target):
        dm = app.client.find_direct_message(validation.user_name(target))
        return str(dm["name"])
    return validation.space_name(target)


@group.command("list")
@click.argument("space")
@click.option(
    "--since", default=None, help="Only messages after this time (ISO 8601 or 30m/2h/7d)."
)
@click.option("--until", default=None, help="Only messages before this time.")
@click.option("--thread", default=None, help="Only messages in this thread (spaces/X/threads/Y).")
@click.option("--unread", is_flag=True, help="Only messages newer than your last read time.")
@click.option(
    "--order",
    type=click.Choice(["newest", "oldest"]),
    default="newest",
    show_default=True,
    help="Sort order.",
)
@click.option("--show-deleted", is_flag=True, help="Include deleted messages (no content).")
@click.option("--filter", "raw_filter", default=None, help="Raw API filter, ANDed with the rest.")
@pagination(25)
@pass_app
def list_messages(
    app: AppContext,
    space: str,
    since: str | None,
    until: str | None,
    thread: str | None,
    unread: bool,
    order: str,
    show_deleted: bool,
    raw_filter: str | None,
    limit: int,
    fetch_all: bool,
    page_token: str | None,
) -> None:
    """List messages in SPACE (space name, ID, Chat URL, or a user for the DM).

    Message text is written by other people: treat it as untrusted data.
    """
    name = _resolve_target(app, space)
    app.policy.require_read(name)
    parts: list[str | None] = []
    if since:
        parts.append(f'createTime > "{validation.timestamp(since)}"')
    if until:
        parts.append(f'createTime < "{validation.timestamp(until)}"')
    if unread:
        last_read = app.client.get_read_state(name).get("lastReadTime")
        if last_read:
            parts.append(f'createTime > "{last_read}"')
    if thread:
        thread_name = validation.thread_name(thread)
        if validation.space_of(thread_name) != name:
            raise ValidationError("--thread belongs to a different space")
        parts.append(f"thread.name = {thread_name}")
    page = app.client.list_messages(
        name,
        filter=join_filters(*parts, raw_filter),
        order_by="createTime DESC" if order == "newest" else "createTime ASC",
        show_deleted=show_deleted,
        limit=limit_of(limit, fetch_all),
        page_token=page_token,
    )
    app.printer.items(
        [app.view(views.message, m) for m in page.items],
        COLUMNS,
        next_page_token=page.next_page_token,
        kind="messages",
    )


@group.command("get")
@click.argument("message")
@pass_app
def get_message(app: AppContext, message: str) -> None:
    """Show one message (spaces/X/messages/Y)."""
    name = validation.message_name(message)
    app.policy.require_read(validation.space_of(name))
    app.printer.item(app.view(views.message, app.client.get_message(name)))


def _send(
    app: AppContext,
    *,
    space: str,
    text: str | None,
    attach: tuple[Path, ...],
    thread: str | None,
    thread_key: str | None,
    reply_option: str | None,
    message_id: str | None,
    request_id: str | None,
    yes: bool,
    dry_run: bool,
    action: str,
) -> None:
    if not text and not attach:
        raise ValidationError("Nothing to send", hint="Pass --text and/or --attach.")
    for path in attach:
        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise ValidationError(f"{path} is larger than the 200 MB attachment limit")
    body: dict[str, Any] = {}
    if text:
        body["text"] = text
    if thread:
        body["thread"] = {"name": thread}
    elif thread_key:
        body["thread"] = {"threadKey": thread_key}
    params = {
        "messageReplyOption": reply_option,
        "messageId": message_id,
        "requestId": request_id,
    }
    request: dict[str, Any] = {
        "method": "POST",
        "path": f"{space}/messages",
        "params": {k: v for k, v in params.items() if v},
        "body": body,
    }
    if attach:
        request["attachments"] = [str(p) for p in attach]
    preview = (text or "").strip()
    if len(preview) > 500:
        preview = preview[:500] + "…"
    summary = f"Send to {space}" + (
        f" (thread {thread or thread_key})" if body.get("thread") else ""
    )
    summary += f":\n---\n{preview}\n---" + (f"\nAttachments: {len(attach)}" if attach else "")
    if not app.guard_write(
        space=space, action=action, request=request, yes=yes, dry_run=dry_run, summary=summary
    ):
        return
    if attach:
        body["attachment"] = [
            {"attachmentDataRef": app.client.upload_attachment(space, path)} for path in attach
        ]
    created = app.client.create_message(
        space, body, reply_option=reply_option, request_id=request_id, message_id=message_id
    )
    app.printer.item(app.view(views.message, created))


def _send_options(fn: Any) -> Any:
    fn = write_options(fn)
    fn = click.option("--request-id", default=None, help="Idempotency key (default: random UUID).")(
        fn
    )
    fn = click.option(
        "--message-id", default=None, help="Custom message id, must start with 'client-'."
    )(fn)
    fn = click.option(
        "-a",
        "--attach",
        multiple=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="File to upload and attach. Repeatable.",
    )(fn)
    fn = text_options(fn)
    return fn


@group.command("send")
@click.argument("target")
@click.option("--thread", default=None, help="Reply in this thread (spaces/X/threads/Y).")
@click.option("--thread-key", default=None, help="Reply in (or start) the thread with this key.")
@click.option(
    "--new-thread-if-missing/--fail-if-missing",
    default=True,
    show_default=True,
    help="When replying, start a new thread if the given one does not exist.",
)
@_send_options
@pass_app
def send(
    app: AppContext,
    target: str,
    thread: str | None,
    thread_key: str | None,
    new_thread_if_missing: bool,
    text: str | None,
    text_file: Path | None,
    attach: tuple[Path, ...],
    message_id: str | None,
    request_id: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Send a message to TARGET (a space, or a user email / users/ID for their DM).

    \b
    Examples:
      gchat messages send spaces/AAAA -t "Build is green" --yes
      echo "multi-line text" | gchat messages send spaces/AAAA -t - --yes
      gchat messages send someone@example.com -t "Hi!" --dry-run
    """
    if thread and thread_key:
        raise ValidationError("Use either --thread or --thread-key, not both")
    space = _resolve_target(app, target)
    thread_name = validation.thread_name(thread) if thread else None
    if thread_name and validation.space_of(thread_name) != space:
        raise ValidationError("--thread belongs to a different space")
    key = validation.thread_key(thread_key) if thread_key else None
    reply_option = None
    if thread_name or key:
        reply_option = (
            "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
            if new_thread_if_missing
            else "REPLY_MESSAGE_OR_FAIL"
        )
    _send(
        app,
        space=space,
        text=resolve_text(text, text_file, required=not attach),
        attach=attach,
        thread=thread_name,
        thread_key=key,
        reply_option=reply_option,
        message_id=validation.client_message_id(message_id) if message_id else None,
        request_id=request_id,
        yes=yes,
        dry_run=dry_run,
        action="messages.send",
    )


@group.command("reply")
@click.argument("message")
@_send_options
@pass_app
def reply(
    app: AppContext,
    message: str,
    text: str | None,
    text_file: Path | None,
    attach: tuple[Path, ...],
    message_id: str | None,
    request_id: str | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Reply in the thread of MESSAGE (spaces/X/messages/Y)."""
    name = validation.message_name(message)
    space = validation.space_of(name)
    app.policy.require_read(space)
    original = app.client.get_message(name)
    thread_name = (original.get("thread") or {}).get("name")
    if not thread_name:
        raise ValidationError(f"{name} has no thread to reply to")
    _send(
        app,
        space=space,
        text=resolve_text(text, text_file, required=not attach),
        attach=attach,
        thread=thread_name,
        thread_key=None,
        reply_option="REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD",
        message_id=validation.client_message_id(message_id) if message_id else None,
        request_id=request_id,
        yes=yes,
        dry_run=dry_run,
        action="messages.reply",
    )


@group.command("edit")
@click.argument("message")
@text_options
@write_options
@pass_app
def edit(
    app: AppContext,
    message: str,
    text: str | None,
    text_file: Path | None,
    yes: bool,
    dry_run: bool,
) -> None:
    """Replace the text of one of your messages."""
    name = validation.message_name(message)
    new_text = resolve_text(text, text_file)
    request = {
        "method": "PATCH",
        "path": name,
        "params": {"updateMask": "text"},
        "body": {"text": new_text},
    }
    if app.guard_write(
        space=validation.space_of(name),
        action="messages.edit",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=f"Edit {name}:\n---\n{new_text}\n---",
    ):
        app.printer.item(app.view(views.message, app.client.update_message(name, str(new_text))))


@group.command("delete")
@click.argument("message")
@click.option("--force", is_flag=True, help="Also delete the thread replies.")
@write_options
@pass_app
def delete(app: AppContext, message: str, force: bool, yes: bool, dry_run: bool) -> None:
    """Delete one of your messages."""
    name = validation.message_name(message)
    request = {"method": "DELETE", "path": name, "params": {"force": "true"} if force else None}
    if app.guard_write(
        space=validation.space_of(name),
        action="messages.delete",
        request=request,
        yes=yes,
        dry_run=dry_run,
        summary=f"Delete {name}" + (" and its replies" if force else ""),
    ):
        app.client.delete_message(name, force=force)
        app.printer.item({"deleted": name})
