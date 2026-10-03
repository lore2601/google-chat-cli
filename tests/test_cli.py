from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import responses
from responses import matchers

from gchat_cli import __version__
from tests.conftest import API, Result

Invoke = Callable[..., Result]

MESSAGE = {
    "name": "spaces/A/messages/M1",
    "sender": {"name": "users/1", "type": "HUMAN"},
    "createTime": "2026-01-01T10:00:00Z",
    "text": "hello",
    "thread": {"name": "spaces/A/threads/T1"},
}


def test_version(gchat: Invoke) -> None:
    result = gchat("--version")
    assert result.code == 0
    assert __version__ in result.out


def test_no_args_shows_help(gchat: Invoke) -> None:
    assert gchat().code == 0


def test_usage_error_is_json(gchat: Invoke) -> None:
    result = gchat("messages", "list")
    assert result.code == 3
    assert result.error["reason"] == "invalidArgument"


def test_not_logged_in(gchat: Invoke) -> None:
    result = gchat("spaces", "list")
    assert result.code == 2
    assert result.error["reason"] == "unauthenticated"
    assert "gchat auth login" in result.error["hint"]


def test_spaces_list(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces",
        match=[
            matchers.query_param_matcher(
                {"pageSize": "100", "filter": 'spaceType = "SPACE" OR spaceType = "DIRECT_MESSAGE"'}
            )
        ],
        json={
            "spaces": [
                {"name": "spaces/A", "displayName": "Team", "spaceType": "SPACE"},
                {"name": "spaces/B", "spaceType": "DIRECT_MESSAGE"},
            ]
        },
    )
    result = gchat("spaces", "list", "--type", "space", "--type", "dm")
    assert result.code == 0
    assert result.json == {
        "spaces": [
            {"name": "spaces/A", "displayName": "Team", "spaceType": "SPACE"},
            {"name": "spaces/B", "spaceType": "DIRECT_MESSAGE"},
        ]
    }


def test_spaces_list_filtered_by_read_policy(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_READ", "spaces/A")
    api.get(f"{API}/spaces", json={"spaces": [{"name": "spaces/A"}, {"name": "spaces/B"}]})
    result = gchat("spaces", "list")
    assert [s["name"] for s in result.json["spaces"]] == ["spaces/A"]


def test_fields_and_ndjson(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/spaces", json={"spaces": [{"name": "spaces/A", "displayName": "Team"}]})
    result = gchat("-f", "ndjson", "--fields", "name", "spaces", "list")
    assert result.out.strip() == '{"name":"spaces/A"}'


def test_raw_output(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/spaces/A", json={"name": "spaces/A", "spaceHistoryState": "HISTORY_ON"})
    result = gchat("--raw", "spaces", "get", "A")
    assert result.json["spaceHistoryState"] == "HISTORY_ON"


def test_spaces_search_builds_query(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces:search",
        match=[
            matchers.query_param_matcher(
                {"query": 'displayName:"Team \\"X\\"" AND spaceType = "SPACE"', "pageSize": "50"}
            )
        ],
        json={"results": [{"space": {"name": "spaces/S", "displayName": 'Team "X"'}}]},
    )
    result = gchat("spaces", "search", 'Team "X"')
    assert result.json["spaces"][0]["name"] == "spaces/S"


def test_find_dm(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces:findDirectMessage",
        match=[matchers.query_param_matcher({"name": "users/bob@example.com"})],
        json={"name": "spaces/DM", "spaceType": "DIRECT_MESSAGE"},
    )
    assert gchat("spaces", "find-dm", "bob@example.com").json["name"] == "spaces/DM"


def test_spaces_create(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.post(f"{API}/spaces:setup", json={"name": "spaces/NEW", "displayName": "Proj"})
    result = gchat("spaces", "create", "Proj", "-m", "a@example.com", "--yes")
    assert result.code == 0
    body = json.loads(api.calls[0].request.body)
    assert body["space"] == {"spaceType": "SPACE", "displayName": "Proj"}
    assert body["memberships"][0]["member"]["name"] == "users/a@example.com"


def test_spaces_create_needs_wildcard(gchat: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_WRITE", "spaces/A")
    assert gchat("spaces", "create", "Proj", "--yes").code == 4


def test_messages_list_builds_filter(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces/A/messages",
        match=[
            matchers.query_param_matcher(
                {
                    "pageSize": "1",
                    "orderBy": "createTime ASC",
                    "filter": 'createTime > "2026-01-01T00:00:00Z" AND '
                    "thread.name = spaces/A/threads/T1",
                }
            )
        ],
        json={"messages": [MESSAGE], "nextPageToken": "next"},
    )
    result = gchat(
        "messages",
        "list",
        "spaces/A",
        "--since",
        "2026-01-01",
        "--thread",
        "spaces/A/threads/T1",
        "--order",
        "oldest",
        "-n",
        "1",
    )
    assert result.code == 0, result.err
    assert result.json["nextPageToken"] == "next"
    assert result.json["messages"][0]["text"] == "hello"
    assert result.json["messages"][0]["sender"] == "users/1"


def test_messages_list_unread(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/users/me/spaces/A/spaceReadState", json={"lastReadTime": "2026-02-01T00:00:00Z"}
    )
    api.get(
        f"{API}/spaces/A/messages",
        match=[
            matchers.query_param_matcher(
                {
                    "pageSize": "25",
                    "orderBy": "createTime DESC",
                    "filter": 'createTime > "2026-02-01T00:00:00Z"',
                }
            )
        ],
        json={},
    )
    result = gchat("messages", "list", "A", "--unread")
    assert result.json == {"messages": []}


def test_messages_list_thread_from_other_space(gchat: Invoke, api: responses.RequestsMock) -> None:
    result = gchat("messages", "list", "spaces/A", "--thread", "spaces/B/threads/T")
    assert result.code == 3


def test_messages_list_read_policy(gchat: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_READ", "spaces/OTHER")
    result = gchat("messages", "list", "spaces/A")
    assert result.code == 4
    assert result.error["reason"] == "policyDenied"


def test_messages_get(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/spaces/A/messages/M1", json=MESSAGE)
    assert gchat("messages", "get", "spaces/A/messages/M1").json["name"] == "spaces/A/messages/M1"


def test_send_requires_yes_when_not_interactive(gchat: Invoke, api: responses.RequestsMock) -> None:
    result = gchat("messages", "send", "spaces/A", "-t", "hi")
    assert result.code == 4
    assert result.error["reason"] == "confirmationRequired"
    assert len(api.calls) == 0


def test_send_dry_run_makes_no_calls(gchat: Invoke, api: responses.RequestsMock) -> None:
    result = gchat("messages", "send", "spaces/A", "-t", "hi", "--thread-key", "k", "--dry-run")
    assert result.code == 0
    assert result.json["dryRun"] is True
    request = result.json["request"]
    assert request["url"] == f"{API}/spaces/A/messages"
    assert request["body"] == {"text": "hi", "thread": {"threadKey": "k"}}
    assert request["params"] == {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}
    assert len(api.calls) == 0


def test_send_with_yes(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.post(
        f"{API}/spaces/A/messages",
        match=[matchers.json_params_matcher({"text": "hi"})],
        json={**MESSAGE, "text": "hi"},
    )
    result = gchat("messages", "send", "spaces/A", "-t", "hi", "--yes")
    assert result.code == 0
    assert result.json["text"] == "hi"
    assert "requestId" in api.calls[0].request.url


def test_send_from_stdin(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("line 1\nline 2\n"))
    api.post(f"{API}/spaces/A/messages", json=MESSAGE)
    assert gchat("messages", "send", "spaces/A", "-t", "-", "-y").code == 0
    assert json.loads(api.calls[0].request.body)["text"] == "line 1\nline 2\n"


def test_send_text_file_and_conflicts(gchat: Invoke, tmp_path: Path) -> None:
    text_file = tmp_path / "msg.txt"
    text_file.write_text("from file")
    result = gchat("messages", "send", "spaces/A", "--text-file", str(text_file), "--dry-run")
    assert result.json["request"]["body"]["text"] == "from file"
    result = gchat("messages", "send", "spaces/A", "-t", "x", "--text-file", str(text_file))
    assert result.code == 3
    assert gchat("messages", "send", "spaces/A", "--dry-run").code == 3
    result = gchat(
        "messages",
        "send",
        "spaces/A",
        "-t",
        "x",
        "--thread",
        "spaces/A/threads/T",
        "--thread-key",
        "k",
    )
    assert result.code == 3


def test_send_too_long(gchat: Invoke) -> None:
    result = gchat("messages", "send", "spaces/A", "-t", "x" * 32_001, "--dry-run")
    assert result.code == 3
    assert "32000" in result.error["message"]


def test_send_to_user_resolves_dm(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/spaces:findDirectMessage", json={"name": "spaces/DM"})
    api.post(f"{API}/spaces/DM/messages", json={**MESSAGE, "name": "spaces/DM/messages/X"})
    result = gchat("messages", "send", "bob@example.com", "-t", "hi", "-y")
    assert result.json["name"] == "spaces/DM/messages/X"


def test_send_blocked_by_read_only(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCHAT_READ_ONLY", "true")
    result = gchat("messages", "send", "spaces/A", "-t", "hi", "-y")
    assert result.code == 4
    assert len(api.calls) == 0


def test_send_blocked_by_write_allowlist(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_WRITE", "spaces/OK")
    assert gchat("messages", "send", "spaces/A", "-t", "hi", "-y").code == 4
    api.post(f"{API}/spaces/OK/messages", json=MESSAGE)
    assert gchat("messages", "send", "spaces/OK", "-t", "hi", "-y").code == 0


def test_send_dm_blocked(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_DM_WRITE", "0")
    api.get(f"{API}/spaces/DM", json={"name": "spaces/DM", "spaceType": "DIRECT_MESSAGE"})
    result = gchat("messages", "send", "spaces/DM", "-t", "hi", "-y")
    assert result.code == 4
    assert "direct messages" in result.error["message"]
    assert all(c.request.method == "GET" for c in api.calls)


def test_send_with_attachment(gchat: Invoke, api: responses.RequestsMock, tmp_path: Path) -> None:
    file = tmp_path / "report.csv"
    file.write_text("a,b\n")
    api.post(
        "https://chat.googleapis.com/upload/v1/spaces/A/attachments:upload",
        json={"attachmentDataRef": {"resourceName": "r1"}},
    )
    api.post(f"{API}/spaces/A/messages", json=MESSAGE)
    result = gchat("messages", "send", "spaces/A", "--attach", str(file), "-y")
    assert result.code == 0
    body = json.loads(api.calls[1].request.body)
    assert body == {"attachment": [{"attachmentDataRef": {"resourceName": "r1"}}]}


def test_reply_uses_thread(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/spaces/A/messages/M1", json=MESSAGE)
    api.post(
        f"{API}/spaces/A/messages",
        match=[
            matchers.json_params_matcher({"text": "ack", "thread": {"name": "spaces/A/threads/T1"}})
        ],
        json=MESSAGE,
    )
    result = gchat("messages", "reply", "spaces/A/messages/M1", "-t", "ack", "-y")
    assert result.code == 0
    assert "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD" in api.calls[1].request.url


def test_edit_and_delete(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.patch(
        f"{API}/spaces/A/messages/M1",
        match=[matchers.query_param_matcher({"updateMask": "text"})],
        json={**MESSAGE, "text": "fixed"},
    )
    assert gchat("messages", "edit", "spaces/A/messages/M1", "-t", "fixed", "-y").json["text"] == (
        "fixed"
    )
    api.delete(
        f"{API}/spaces/A/messages/M1",
        match=[matchers.query_param_matcher({"force": "true"})],
        body="",
    )
    result = gchat("messages", "delete", "spaces/A/messages/M1", "--force", "-y")
    assert result.json == {"deleted": "spaces/A/messages/M1"}


def test_api_error_exit_code(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces/A/messages/NOPE",
        status=404,
        json={"error": {"code": 404, "message": "Message not found", "status": "NOT_FOUND"}},
    )
    result = gchat("messages", "get", "spaces/A/messages/NOPE")
    assert result.code == 1
    assert result.error["status"] == "NOT_FOUND"
    assert result.error["httpStatus"] == 404


def test_members_list(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces/A/members",
        match=[
            matchers.query_param_matcher(
                {"pageSize": "100", "filter": 'member.type = "HUMAN"', "showInvited": "true"}
            )
        ],
        json={
            "memberships": [
                {
                    "name": "spaces/A/members/1",
                    "member": {"name": "users/1", "type": "HUMAN"},
                    "role": "ROLE_MEMBER",
                    "state": "JOINED",
                }
            ]
        },
    )
    result = gchat("members", "list", "A", "--humans-only", "--include-invited")
    assert result.json["members"][0]["member"] == "users/1"
    api.get(f"{API}/spaces/A/members/1", json={"name": "spaces/A/members/1"})
    assert gchat("members", "get", "spaces/A/members/1").code == 0


def test_reactions(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces/A/messages/M1/reactions",
        match=[matchers.query_param_matcher({"pageSize": "25", "filter": 'emoji.unicode = "👍"'})],
        json={
            "reactions": [{"name": "r", "emoji": {"unicode": "👍"}, "user": {"name": "users/1"}}]
        },
    )
    result = gchat("reactions", "list", "spaces/A/messages/M1", "--emoji", "👍")
    assert result.json["reactions"] == [{"name": "r", "emoji": "👍", "user": "users/1"}]

    api.post(
        f"{API}/spaces/A/messages/M1/reactions", json={"name": "r2", "emoji": {"unicode": "🎉"}}
    )
    assert gchat("reactions", "add", "spaces/A/messages/M1", "🎉", "-y").json["emoji"] == "🎉"
    assert gchat("reactions", "add", "spaces/A/messages/M1", "ok", "-y").code == 3

    api.delete(f"{API}/spaces/A/messages/M1/reactions/r2", body="")
    result = gchat("reactions", "remove", "spaces/A/messages/M1/reactions/r2", "-y")
    assert result.json == {"deleted": "spaces/A/messages/M1/reactions/r2"}


def test_attachment_download(
    gchat: Invoke, api: responses.RequestsMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    name = "spaces/A/messages/M1/attachments/AT"
    api.get(
        f"{API}/{name}",
        json={
            "name": name,
            "contentName": "../../evil.txt",
            "contentType": "text/plain",
            "attachmentDataRef": {"resourceName": "res-1"},
        },
    )
    api.get(f"{API}/media/res-1", body=b"content")
    result = gchat("attachments", "download", name)
    assert result.code == 0
    assert (tmp_path / "evil.txt").read_bytes() == b"content"
    assert result.json["bytes"] == 7
    assert gchat("attachments", "download", name).code == 3  # refuses to overwrite
    assert gchat("attachments", "get", name).json["resourceName"] == "res-1"


def test_attachment_drive_file(gchat: Invoke, api: responses.RequestsMock) -> None:
    name = "spaces/A/messages/M1/attachments/AT"
    api.get(f"{API}/{name}", json={"name": name, "driveDataRef": {"driveFileId": "d1"}})
    result = gchat("attachments", "download", name)
    assert result.code == 3
    assert "d1" in result.error["hint"]


def test_read_state(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(f"{API}/users/me/spaces/A/spaceReadState", json={"lastReadTime": "t"})
    assert gchat("read-state", "get", "A").json == {"lastReadTime": "t"}
    api.patch(f"{API}/users/me/spaces/A/spaceReadState", json={"lastReadTime": "t2"})
    assert gchat("read-state", "mark-read", "A", "-y").json == {"lastReadTime": "t2"}


def test_api_command(gchat: Invoke, api: responses.RequestsMock) -> None:
    api.get(
        f"{API}/spaces/A/messages",
        match=[matchers.query_param_matcher({"pageSize": "2"})],
        json={"messages": []},
    )
    assert gchat("api", "get", "/v1/spaces/A/messages", "-p", '{"pageSize": 2}').json == {
        "messages": []
    }
    assert gchat("api", "POST", "spaces/A/messages", "-b", '{"text":"x"}').code == 4
    dry = gchat("api", "POST", "spaces/A/messages", "-b", '{"text":"x"}', "--dry-run")
    assert dry.json["request"]["body"] == {"text": "x"}
    assert gchat("api", "GET", "spaces/../x").code == 3
    assert gchat("api", "GET", "spaces/A?x=1").code == 3
    assert gchat("api", "GET", "spaces/A", "-p", "[1]").code == 3
    assert gchat("api", "GET", "spaces/A", "-p", "{bad").code == 3
    assert gchat("api", "GET", "spaces/A", "--dry-run").json["dryRun"] is True


def test_api_command_respects_read_policy(gchat: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCHAT_ALLOW_READ", "spaces/B")
    assert gchat("api", "GET", "users/me/spaces/A/spaceReadState").code == 4


def test_schema(gchat: Invoke) -> None:
    result = gchat("schema")
    data: dict[str, Any] = result.json
    commands = {c["command"] for c in data["commands"]}
    assert {"gchat messages send", "gchat spaces list", "gchat auth login"} <= commands
    assert data["exitCodes"]["policy"] == 4
    one = gchat("schema", "messages send").json
    assert any(p["name"] == "yes" for p in one["params"])
    assert gchat("schema", "nope").code == 3


def test_config_show_and_init(gchat: Invoke, tmp_path: Path) -> None:
    shown = gchat("config", "show").json
    assert shown["configLoaded"] is False
    assert shown["policy"]["read"] == ["*"]
    created = gchat("config", "init")
    assert created.code == 0
    assert Path(created.json["created"]).is_file()
    assert gchat("config", "init").code == 3
    assert gchat("config", "init", "--force").code == 0
    assert gchat("config", "show").json["configLoaded"] is True


def test_invalid_config_reports_error(gchat: Invoke, tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.toml").write_text("[policy]\nbogus = 1\n")
    result = gchat("spaces", "list")
    assert result.code == 3


def test_auth_commands(gchat: Invoke, tmp_path: Path) -> None:
    status = gchat("auth", "status").json
    assert status["authenticated"] is False
    presets = gchat("auth", "scopes").json["presets"]
    assert [p["preset"] for p in presets] == ["readonly", "default", "full"]
    assert gchat("auth", "logout", "--no-revoke").json["removed"] is False


def test_auth_login_copies_client_secrets(
    gchat: Invoke, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = tmp_path / "downloaded.json"
    secrets.write_text('{"installed": {"client_id": "x"}}')
    captured: dict[str, Any] = {}

    def fake_login(scopes: list[str], **kwargs: Any) -> dict[str, Any]:
        captured["scopes"] = scopes
        captured.update(kwargs)
        return {"authenticated": True}

    monkeypatch.setattr("gchat_cli.auth.login", fake_login)
    result = gchat(
        "auth", "login", "--scopes", "readonly", "--client-secrets", str(secrets), "--no-browser"
    )
    assert result.code == 0
    assert result.json["clientSecretsSavedTo"].endswith("client_secret.json")
    assert captured["open_browser"] is False
    assert all(s.endswith("readonly") for s in captured["scopes"])


def test_internal_error_is_reported(
    gchat: Invoke, api: responses.RequestsMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr("gchat_cli.client.ChatClient.get_space", boom)
    result = gchat("spaces", "get", "A")
    assert result.code == 5
    assert "kaboom" in result.error["message"]


def test_format_env_validation(gchat: Invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCHAT_FORMAT", "xml")
    assert gchat("config", "show").code == 3
