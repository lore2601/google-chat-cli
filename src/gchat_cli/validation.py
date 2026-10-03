"""Input validation and normalisation.

Command-line arguments are frequently produced by AI agents, which may in turn
be steered by untrusted content (for example, the text of a chat message). All
resource names are therefore validated strictly before they are interpolated
into request URLs, and free text is checked against the API limits.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gchat_cli.errors import ValidationError

_ID = r"[A-Za-z0-9_-]+"
_MSG_ID = r"[A-Za-z0-9_.-]+"

_SPACE_RE = re.compile(rf"^spaces/{_ID}$")
_MESSAGE_RE = re.compile(rf"^(spaces/{_ID})/messages/{_MSG_ID}$")
_THREAD_RE = re.compile(rf"^(spaces/{_ID})/threads/{_MSG_ID}$")
_REACTION_RE = re.compile(rf"^(spaces/{_ID})/messages/{_MSG_ID}/reactions/{_MSG_ID}$")
_ATTACHMENT_RE = re.compile(rf"^(spaces/{_ID})/messages/{_MSG_ID}/attachments/{_MSG_ID}$")
_MEMBER_RE = re.compile(rf"^(spaces/{_ID})/members/[A-Za-z0-9_.@+-]+$")
_USER_RE = re.compile(r"^users/(me|[0-9]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_CHAT_URL_RE = re.compile(
    rf"^https://(?:mail\.google\.com/chat/u/\d+/#chat/(?:space|dm)/|chat\.google\.com/(?:u/\d+/)?(?:room|dm)/)({_ID})"
)
_CLIENT_MESSAGE_ID_RE = re.compile(r"^client-[a-z0-9-]{1,56}$")
_RELATIVE_RE = re.compile(r"^(\d+)\s*([smhdw])$")

MAX_MESSAGE_BYTES = 32_000
MAX_THREAD_KEY = 4_000

_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def _reject_control_chars(value: str, what: str) -> None:
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValidationError(f"{what} contains control characters")


def _check(pattern: re.Pattern[str], value: str, what: str, example: str) -> str:
    value = value.strip()
    _reject_control_chars(value, what)
    if not pattern.match(value):
        raise ValidationError(
            f"Invalid {what}: {value!r}",
            hint=f"Expected a resource name like {example}",
        )
    return value


def space_name(value: str) -> str:
    """Normalise a space reference.

    Accepts ``spaces/AAAA``, a bare ``AAAA`` id, or a Google Chat URL.
    """
    value = value.strip()
    _reject_control_chars(value, "space")
    url = _CHAT_URL_RE.match(value)
    if url:
        return f"spaces/{url.group(1)}"
    if re.fullmatch(_ID, value):
        return f"spaces/{value}"
    return _check(_SPACE_RE, value, "space", "spaces/AAAAxxxx")


def message_name(value: str) -> str:
    return _check(_MESSAGE_RE, value, "message", "spaces/AAAA/messages/BBBB.BBBB")


def thread_name(value: str) -> str:
    return _check(_THREAD_RE, value, "thread", "spaces/AAAA/threads/CCCC")


def reaction_name(value: str) -> str:
    return _check(_REACTION_RE, value, "reaction", "spaces/AAAA/messages/BBBB/reactions/DDDD")


def attachment_name(value: str) -> str:
    return _check(_ATTACHMENT_RE, value, "attachment", "spaces/AAAA/messages/BBBB/attachments/EE")


def member_name(value: str) -> str:
    return _check(_MEMBER_RE, value, "membership", "spaces/AAAA/members/123456")


def user_name(value: str) -> str:
    """Normalise a user reference: ``users/123``, ``users/me``, ``users/a@b.c`` or ``a@b.c``."""
    value = value.strip()
    _reject_control_chars(value, "user")
    if _EMAIL_RE.match(value):
        return f"users/{value}"
    return _check(_USER_RE, value, "user", "users/123456789 or someone@example.com")


def is_user_reference(value: str) -> bool:
    value = value.strip()
    return bool(_EMAIL_RE.match(value) or _USER_RE.match(value))


def space_of(resource: str) -> str:
    """Return the ``spaces/X`` prefix of any space-scoped resource name."""
    parts = resource.split("/")
    if len(parts) < 2 or parts[0] != "spaces":
        raise ValidationError(f"Not a space-scoped resource: {resource!r}")
    return "/".join(parts[:2])


def client_message_id(value: str) -> str:
    value = value.strip()
    if not _CLIENT_MESSAGE_ID_RE.match(value):
        raise ValidationError(
            f"Invalid message id: {value!r}",
            hint="Custom message ids must start with 'client-' and contain only "
            "lowercase letters, digits and hyphens (max 63 characters).",
        )
    return value


def thread_key(value: str) -> str:
    _reject_control_chars(value, "thread key")
    if not value or len(value) > MAX_THREAD_KEY:
        raise ValidationError(f"Thread keys must be 1-{MAX_THREAD_KEY} characters long")
    return value


def message_text(value: str, *, allow_empty: bool = False) -> str:
    """Validate message text against Google Chat's size limit."""
    if not value.strip() and not allow_empty:
        raise ValidationError("Message text is empty")
    size = len(value.encode("utf-8"))
    if size > MAX_MESSAGE_BYTES:
        raise ValidationError(
            f"Message is {size} bytes; Google Chat accepts at most {MAX_MESSAGE_BYTES}",
            hint="Split the text into several messages or attach it as a file.",
        )
    return value


def timestamp(value: str, *, now: datetime | None = None) -> str:
    """Parse an absolute or relative time into an RFC 3339 UTC timestamp.

    Accepted forms: ISO 8601 (``2026-01-31``, ``2026-01-31T10:00:00+02:00``)
    or a relative duration in the past (``30m``, ``2h``, ``7d``, ``1w``).
    """
    raw = value.strip()
    now = now or datetime.now(UTC)
    rel = _RELATIVE_RE.match(raw)
    if rel:
        amount, unit = int(rel.group(1)), rel.group(2)
        moment = now - timedelta(**{_UNITS[unit]: amount})
    else:
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError(
                f"Invalid time: {value!r}",
                hint="Use ISO 8601 (2026-01-31T09:00:00Z) or a relative duration (30m, 2h, 7d).",
            ) from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def output_path(value: str, *, overwrite: bool) -> Path:
    """Validate a download destination."""
    _reject_control_chars(value, "output path")
    path = Path(value).expanduser()
    if path.exists() and path.is_dir():
        raise ValidationError(f"Output path is a directory: {path}")
    if path.exists() and not overwrite:
        raise ValidationError(
            f"Refusing to overwrite existing file: {path}", hint="Pass --overwrite to replace it."
        )
    if not path.parent.exists():
        raise ValidationError(f"Directory does not exist: {path.parent}")
    return path


def safe_filename(name: str) -> str:
    """Reduce an attachment name to a safe basename for the local filesystem."""
    base = Path(name.replace("\\", "/")).name
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C")
    base = base.strip().lstrip(".")
    return base or "attachment"
