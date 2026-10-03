"""``gchat attachments``: inspect and download message attachments."""

from __future__ import annotations

from pathlib import Path

import click

from gchat_cli import validation, views
from gchat_cli.commands._common import pass_app
from gchat_cli.context import AppContext
from gchat_cli.errors import ValidationError


@click.group("attachments")
def group() -> None:
    """Message attachments (to send files use `gchat messages send --attach`)."""


@group.command("get")
@click.argument("attachment")
@pass_app
def get_attachment(app: AppContext, attachment: str) -> None:
    """Show attachment metadata (spaces/X/messages/Y/attachments/Z)."""
    name = validation.attachment_name(attachment)
    app.policy.require_read(validation.space_of(name))
    app.printer.item(app.view(views.attachment, app.client.get_attachment(name)))


@group.command("download")
@click.argument("attachment")
@click.option(
    "-o",
    "--output",
    default=None,
    help="Destination file (default: the attachment name in the current directory).",
)
@click.option("--overwrite", is_flag=True, help="Replace the destination if it exists.")
@pass_app
def download(app: AppContext, attachment: str, output: str | None, overwrite: bool) -> None:
    """Download an uploaded attachment. Google Drive files are not supported."""
    name = validation.attachment_name(attachment)
    app.policy.require_read(validation.space_of(name))
    meta = app.client.get_attachment(name)
    resource = (meta.get("attachmentDataRef") or {}).get("resourceName")
    if not resource:
        drive_id = (meta.get("driveDataRef") or {}).get("driveFileId")
        raise ValidationError(
            "This attachment is not downloadable through the Chat API",
            hint=f"It is a Google Drive file (id {drive_id}); use Drive to fetch it."
            if drive_id
            else None,
        )
    target = output or validation.safe_filename(str(meta.get("contentName") or "attachment"))
    path = validation.output_path(target, overwrite=overwrite)
    size = app.client.download_media(str(resource), path)
    app.printer.item(
        {
            "name": name,
            "path": str(Path(path).resolve()),
            "bytes": size,
            "contentType": meta.get("contentType"),
        }
    )
