from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from gchat_cli import validation
from gchat_cli.errors import ValidationError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("spaces/AAAA1234", "spaces/AAAA1234"),
        ("AAAA1234", "spaces/AAAA1234"),
        ("  spaces/AbC_-9  ", "spaces/AbC_-9"),
        ("https://chat.google.com/room/AAQAxyz?cls=7", "spaces/AAQAxyz"),
        ("https://mail.google.com/chat/u/0/#chat/space/AAQAxyz", "spaces/AAQAxyz"),
        ("https://chat.google.com/u/1/dm/DMid123", "spaces/DMid123"),
    ],
)
def test_space_name_accepts(value: str, expected: str) -> None:
    assert validation.space_name(value) == expected


@pytest.mark.parametrize(
    "value",
    ["spaces/../users", "spaces/A/B", "spaces/A?x=1", "spaces/A#f", "spaces/A\x00", "", "../.ssh"],
)
def test_space_name_rejects(value: str) -> None:
    with pytest.raises(ValidationError):
        validation.space_name(value)


def test_message_and_thread_names() -> None:
    assert validation.message_name("spaces/A/messages/B.B") == "spaces/A/messages/B.B"
    assert validation.message_name("spaces/A/messages/client-x") == "spaces/A/messages/client-x"
    assert validation.thread_name("spaces/A/threads/T1") == "spaces/A/threads/T1"
    with pytest.raises(ValidationError):
        validation.message_name("spaces/A/messages/../../x")
    with pytest.raises(ValidationError):
        validation.thread_name("spaces/A/messages/B")


def test_other_resource_names() -> None:
    assert validation.reaction_name("spaces/A/messages/B/reactions/C")
    assert validation.attachment_name("spaces/A/messages/B/attachments/C")
    assert validation.member_name("spaces/A/members/123")
    with pytest.raises(ValidationError):
        validation.attachment_name("spaces/A/messages/B")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("someone@example.com", "users/someone@example.com"),
        ("users/123456", "users/123456"),
        ("users/me", "users/me"),
        ("users/a.b@example.co", "users/a.b@example.co"),
    ],
)
def test_user_name(value: str, expected: str) -> None:
    assert validation.user_name(value) == expected
    assert validation.is_user_reference(value)


def test_user_name_rejects() -> None:
    with pytest.raises(ValidationError):
        validation.user_name("users/../../x")
    assert not validation.is_user_reference("spaces/AAAA")


def test_space_of() -> None:
    assert validation.space_of("spaces/A/messages/B") == "spaces/A"
    with pytest.raises(ValidationError):
        validation.space_of("users/me")


def test_client_message_id() -> None:
    assert validation.client_message_id("client-build-42") == "client-build-42"
    for bad in ["build-42", "client-UPPER", "client-" + "a" * 60]:
        with pytest.raises(ValidationError):
            validation.client_message_id(bad)


def test_thread_key() -> None:
    assert validation.thread_key("deploy-123") == "deploy-123"
    with pytest.raises(ValidationError):
        validation.thread_key("x" * 4001)
    with pytest.raises(ValidationError):
        validation.thread_key("")


def test_message_text_limits() -> None:
    assert validation.message_text("ciao") == "ciao"
    with pytest.raises(ValidationError):
        validation.message_text("   ")
    with pytest.raises(ValidationError, match="bytes"):
        validation.message_text("é" * 16_001)


NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2h", "2026-01-10T10:00:00Z"),
        ("30m", "2026-01-10T11:30:00Z"),
        ("1d", "2026-01-09T12:00:00Z"),
        ("1w", "2026-01-03T12:00:00Z"),
        ("2026-01-01", "2026-01-01T00:00:00Z"),
        ("2026-01-01T10:00:00+02:00", "2026-01-01T08:00:00Z"),
        ("2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z"),
    ],
)
def test_timestamp(value: str, expected: str) -> None:
    assert validation.timestamp(value, now=NOW) == expected


def test_timestamp_rejects() -> None:
    with pytest.raises(ValidationError):
        validation.timestamp("yesterday")


def test_output_path(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    assert validation.output_path(str(target), overwrite=False) == target
    target.write_text("x")
    with pytest.raises(ValidationError, match="overwrite"):
        validation.output_path(str(target), overwrite=False)
    assert validation.output_path(str(target), overwrite=True) == target
    with pytest.raises(ValidationError):
        validation.output_path(str(tmp_path), overwrite=True)
    with pytest.raises(ValidationError):
        validation.output_path(str(tmp_path / "missing" / "f"), overwrite=False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\win.ini", "win.ini"),
        (".bashrc", "bashrc"),
        ("bad\x1bname.txt", "badname.txt"),
        ("", "attachment"),
    ],
)
def test_safe_filename(value: str, expected: str) -> None:
    assert validation.safe_filename(value) == expected
