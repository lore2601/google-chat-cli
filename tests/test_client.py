from __future__ import annotations

from pathlib import Path

import pytest
import requests
import responses
from responses import matchers

from gchat_cli.client import ChatClient
from gchat_cli.errors import ApiError, GchatError

API = "https://chat.googleapis.com/v1"


@pytest.fixture
def client() -> ChatClient:
    return ChatClient(requests.Session(), sleep=lambda _s: None)


@responses.activate
def test_collect_respects_limit_across_pages(client: ChatClient) -> None:
    responses.get(
        f"{API}/spaces",
        match=[matchers.query_param_matcher({"pageSize": "3"})],
        json={"spaces": [{"name": "spaces/1"}, {"name": "spaces/2"}], "nextPageToken": "p2"},
    )
    responses.get(
        f"{API}/spaces",
        match=[matchers.query_param_matcher({"pageSize": "1", "pageToken": "p2"})],
        json={"spaces": [{"name": "spaces/3"}], "nextPageToken": "p3"},
    )
    page = client.list_spaces(limit=3)
    assert [s["name"] for s in page.items] == ["spaces/1", "spaces/2", "spaces/3"]
    assert page.next_page_token == "p3"


@responses.activate
def test_collect_all_pages(client: ChatClient) -> None:
    responses.get(
        f"{API}/spaces/A/members", json={"memberships": [{"name": "m1"}], "nextPageToken": "n"}
    )
    responses.get(f"{API}/spaces/A/members", json={"memberships": [{"name": "m2"}]})
    page = client.list_members("spaces/A", limit=None)
    assert [m["name"] for m in page.items] == ["m1", "m2"]
    assert page.next_page_token is None


@responses.activate
def test_retries_on_429_then_succeeds(client: ChatClient) -> None:
    responses.get(f"{API}/spaces/A", status=429, headers={"Retry-After": "1"})
    responses.get(f"{API}/spaces/A", status=503)
    responses.get(f"{API}/spaces/A", json={"name": "spaces/A"})
    assert client.get_space("spaces/A") == {"name": "spaces/A"}
    assert len(responses.calls) == 3


@responses.activate
def test_gives_up_after_max_retries() -> None:
    client = ChatClient(requests.Session(), sleep=lambda _s: None, max_retries=1)
    responses.get(f"{API}/spaces/A", status=500, json={"error": {"message": "backend"}})
    with pytest.raises(ApiError) as info:
        client.get_space("spaces/A")
    assert info.value.http_status == 500
    assert len(responses.calls) == 2


@responses.activate
def test_network_error_is_wrapped() -> None:
    client = ChatClient(requests.Session(), sleep=lambda _s: None, max_retries=0)
    responses.get(f"{API}/spaces/A", body=requests.ConnectionError("down"))
    with pytest.raises(GchatError, match="Network error"):
        client.get_space("spaces/A")


@responses.activate
def test_api_error_parsing(client: ChatClient) -> None:
    responses.get(
        f"{API}/spaces/A",
        status=403,
        json={
            "error": {
                "code": 403,
                "message": "Google Chat API has not been used in project 1",
                "status": "PERMISSION_DENIED",
                "details": [
                    {
                        "reason": "SERVICE_DISABLED",
                        "metadata": {"activationUrl": "https://console.cloud.google.com/x"},
                    }
                ],
            }
        },
    )
    with pytest.raises(ApiError) as info:
        client.get_space("spaces/A")
    payload = info.value.to_dict()["error"]
    assert payload["reason"] == "SERVICE_DISABLED"
    assert payload["status"] == "PERMISSION_DENIED"
    assert payload["enableUrl"] == "https://console.cloud.google.com/x"
    assert "Enable the Google Chat API" in payload["hint"]
    assert payload["exitCode"] == 1


@pytest.mark.parametrize(
    ("status", "message", "fragment"),
    [
        (401, "bad", "gchat auth login"),
        (403, "Request had insufficient authentication scopes.", "scope"),
        (403, "nope", "member"),
        (404, "missing", "Not found"),
        (429, "slow down", "Rate limited"),
    ],
)
@responses.activate
def test_error_hints(status: int, message: str, fragment: str) -> None:
    client = ChatClient(requests.Session(), sleep=lambda _s: None, max_retries=0)
    responses.get(f"{API}/spaces/A", status=status, json={"error": {"message": message}})
    with pytest.raises(ApiError) as info:
        client.get_space("spaces/A")
    assert fragment in (info.value.hint or "")


@responses.activate
def test_non_json_error(client: ChatClient) -> None:
    responses.get(f"{API}/spaces/A", status=400, body="plain failure")
    with pytest.raises(ApiError, match="plain failure"):
        client.get_space("spaces/A")


@responses.activate
def test_create_message_sends_params(client: ChatClient) -> None:
    responses.post(
        f"{API}/spaces/A/messages",
        match=[
            matchers.query_param_matcher(
                {"requestId": "rid", "messageReplyOption": "REPLY_MESSAGE_OR_FAIL"}
            ),
            matchers.json_params_matcher({"text": "hi", "thread": {"name": "spaces/A/threads/T"}}),
        ],
        json={"name": "spaces/A/messages/M"},
    )
    created = client.create_message(
        "spaces/A",
        {"text": "hi", "thread": {"name": "spaces/A/threads/T"}},
        reply_option="REPLY_MESSAGE_OR_FAIL",
        request_id="rid",
    )
    assert created["name"] == "spaces/A/messages/M"


@responses.activate
def test_delete_returns_empty(client: ChatClient) -> None:
    responses.delete(f"{API}/spaces/A/messages/M", body="")
    assert client.delete_message("spaces/A/messages/M") == {}


@responses.activate
def test_upload_and_download(client: ChatClient, tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello")
    responses.post(
        "https://chat.googleapis.com/upload/v1/spaces/A/attachments:upload",
        json={"attachmentDataRef": {"resourceName": "res", "attachmentUploadToken": "tok"}},
    )
    ref = client.upload_attachment("spaces/A", source)
    assert ref == {"resourceName": "res", "attachmentUploadToken": "tok"}
    sent = responses.calls[0].request
    assert sent.headers["Content-Type"].startswith("multipart/related; boundary=")
    assert b'"filename": "notes.txt"' in sent.body
    assert b"hello" in sent.body

    responses.get(f"{API}/media/res", body=b"payload-bytes")
    dest = tmp_path / "out.bin"
    assert client.download_media("res", dest) == len(b"payload-bytes")
    assert dest.read_bytes() == b"payload-bytes"
    assert not (tmp_path / ".out.bin.part").exists()


@responses.activate
def test_search_unwraps_results(client: ChatClient) -> None:
    responses.get(f"{API}/spaces:search", json={"results": [{"space": {"name": "spaces/S"}}]})
    page = client.search_spaces('displayName:"x" AND spaceType = "SPACE"', limit=10)
    assert page.items == [{"name": "spaces/S"}]


@responses.activate
def test_read_state(client: ChatClient) -> None:
    responses.get(f"{API}/users/me/spaces/A/spaceReadState", json={"lastReadTime": "t"})
    responses.patch(
        f"{API}/users/me/spaces/A/spaceReadState",
        match=[matchers.query_param_matcher({"updateMask": "lastReadTime"})],
        json={"lastReadTime": "t2"},
    )
    assert client.get_read_state("spaces/A") == {"lastReadTime": "t"}
    assert client.update_read_state("spaces/A", "t2") == {"lastReadTime": "t2"}


def test_backoff_bounds() -> None:
    assert ChatClient._backoff(0, "5") == 5.0
    assert ChatClient._backoff(0, "999") == 64.0
    assert 1 <= ChatClient._backoff(0, "soon") < 2
    assert ChatClient._backoff(10, None) == 32.0
