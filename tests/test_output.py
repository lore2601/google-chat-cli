from __future__ import annotations

import io
import json

from gchat_cli import output, views


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_project_dotted_fields() -> None:
    item = {"name": "a", "sender": {"name": "users/1", "type": "HUMAN"}, "text": "hi"}
    assert output.project(item, ["name", "sender.name"]) == {
        "name": "a",
        "sender": {"name": "users/1"},
    }
    assert output.project(item, []) == item
    assert output.project(item, ["missing"]) == {}


def test_sanitize_terminal() -> None:
    assert output.sanitize_terminal("\x1b[31mred\x1b[0m\x07bell") == "redbell"
    assert output.sanitize_terminal("\x1b]0;title\x07ok") == "ok"


def test_resolve_format() -> None:
    assert output.resolve_format("auto", io.StringIO()) == "json"
    assert output.resolve_format("auto", TTY()) == "table"
    assert output.resolve_format("ndjson", TTY()) == "ndjson"


def test_printer_json_and_ndjson() -> None:
    buf = io.StringIO()
    printer = output.Printer("json", out=buf)
    printer.items([{"a": 1}], [output.col("a", "a")], next_page_token="tok", kind="things")
    assert json.loads(buf.getvalue()) == {"things": [{"a": 1}], "nextPageToken": "tok"}

    buf = io.StringIO()
    output.Printer("ndjson", out=buf).items([{"a": 1}, {"a": 2}], [])
    assert [json.loads(line) for line in buf.getvalue().splitlines()] == [{"a": 1}, {"a": 2}]


def test_printer_table() -> None:
    buf = TTY()
    printer = output.Printer("table", out=buf)
    printer.items(
        [{"name": "spaces/A", "text": "line1\nline2 \x1b[2Jcleared"}],
        [output.col("name", "name"), output.col("text", "text", 12)],
    )
    text = buf.getvalue()
    assert "NAME" in text
    assert "\x1b" not in text
    assert "…" in text

    buf = TTY()
    output.Printer("table", out=buf).items([], [])
    assert "no results" in buf.getvalue()

    buf = TTY()
    output.Printer("table", out=buf).item({"key": True, "list": [1]})
    assert "yes" in buf.getvalue()


def test_print_error_human(capsys: object) -> None:
    output.print_error({"error": {"message": "boom", "hint": "fix"}}, "table")
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "error: boom" in err
    assert "hint: fix" in err


def test_message_view() -> None:
    raw = {
        "name": "spaces/A/messages/M",
        "sender": {"name": "users/1", "type": "HUMAN"},
        "createTime": "2026-01-01T00:00:00Z",
        "text": "hello",
        "thread": {"name": "spaces/A/threads/T"},
        "attachment": [{"name": "att", "contentName": "f.pdf", "source": "UPLOADED_CONTENT"}],
        "emojiReactionSummaries": [{"emoji": {"unicode": "👍"}, "reactionCount": 2}],
        "space": {"name": "spaces/A"},
    }
    view = views.message(raw)
    assert view["sender"] == "users/1"
    assert view["thread"] == "spaces/A/threads/T"
    assert view["reactions"] == [{"emoji": "👍", "count": 2}]
    assert view["attachments"][0]["contentName"] == "f.pdf"
    assert "space" not in view
    assert "deleted" not in view


def test_other_views() -> None:
    assert views.space({"name": "spaces/A", "singleUserBotDm": True})["displayName"] == "(app DM)"
    member = views.member({"name": "m", "groupMember": {"name": "groups/g"}, "role": "ROLE_MEMBER"})
    assert member["type"] == "GROUP"
    reaction = views.reaction({"emoji": {"customEmoji": {"emojiName": ":party:"}}})
    assert reaction["emoji"] == ":party:"
    att = views.attachment({"name": "a", "attachmentDataRef": {"resourceName": "r"}})
    assert att["resourceName"] == "r"
