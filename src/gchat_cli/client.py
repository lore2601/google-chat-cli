"""A small, dependency-light client for the Google Chat REST API (v1).

Requests go straight to ``https://chat.googleapis.com/v1`` through an
authorized ``requests`` session. Transient failures (429 and 5xx) are retried
with truncated exponential backoff, as recommended by the Chat API docs.
"""

from __future__ import annotations

import json
import mimetypes
import random
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from gchat_cli import __version__
from gchat_cli.errors import ApiError, GchatError, NetworkError

BASE_URL = "https://chat.googleapis.com/v1"
UPLOAD_URL = "https://chat.googleapis.com/upload/v1"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = f"google-chat-cli/{__version__}"


@dataclass
class Page:
    """A (possibly partial) list result."""

    items: list[dict[str, Any]]
    next_page_token: str | None = None


def _path(name: str) -> str:
    """Encode a resource name for use in a URL path (keeps ``/``, encodes the rest)."""
    return quote(name, safe="/@:-._~")


class ChatClient:
    def __init__(
        self,
        session: requests.Session,
        *,
        base_url: str = BASE_URL,
        upload_url: str = UPLOAD_URL,
        timeout: float = 30.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.session = session
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.base_url = base_url.rstrip("/")
        self.upload_url = upload_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))

    # ------------------------------------------------------------------ transport

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    params=clean or None,
                    json=json_body,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                    stream=stream,
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise NetworkError(f"Network error: {exc}") from exc
                self._sleep(self._backoff(attempt, None))
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if not response.ok:
                raise ApiError.from_response(response)
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 64.0)
            except ValueError:
                pass
        return float(min(2**attempt + random.random(), 32.0))  # noqa: S311 - jitter only

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        """Call ``{base_url}/{path}`` and return the decoded JSON body."""
        url = f"{self.base_url}/{_path(path.lstrip('/'))}"
        response = self._send(method, url, params=params, json_body=body)
        if not response.content:
            return {}
        try:
            decoded = response.json()
        except ValueError as exc:
            raise GchatError("The API returned a non-JSON response") from exc
        return decoded if isinstance(decoded, dict) else {"result": decoded}

    def iter_pages(
        self, path: str, key: str, params: dict[str, Any], page_token: str | None = None
    ) -> Iterator[Page]:
        token = page_token
        while True:
            data = self.request("GET", path, params={**params, "pageToken": token})
            next_token = data.get("nextPageToken") or None
            yield Page(list(data.get(key) or []), next_token)
            if not next_token:
                return
            token = next_token

    def collect(
        self,
        path: str,
        key: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None,
        page_token: str | None = None,
        max_page_size: int = 1000,
    ) -> Page:
        """Collect up to ``limit`` items (``None`` = all) across pages."""
        params = dict(params or {})
        items: list[dict[str, Any]] = []
        next_token: str | None = None
        if limit is not None:
            params["pageSize"] = min(limit, max_page_size)
        else:
            params["pageSize"] = max_page_size
        for page in self.iter_pages(path, key, params, page_token):
            items.extend(page.items)
            next_token = page.next_page_token
            if limit is not None and len(items) >= limit:
                items = items[:limit]  # defensive: pageSize already caps each page
                break
            if limit is not None:
                params["pageSize"] = min(limit - len(items), max_page_size)
        return Page(items, next_token)

    # ------------------------------------------------------------------ spaces

    def list_spaces(
        self, *, filter: str | None = None, limit: int | None = 100, page_token: str | None = None
    ) -> Page:
        return self.collect(
            "spaces", "spaces", {"filter": filter}, limit=limit, page_token=page_token
        )

    def get_space(self, name: str) -> dict[str, Any]:
        return self.request("GET", name)

    def search_spaces(
        self,
        query: str,
        *,
        order_by: str | None = None,
        limit: int | None = 100,
        page_token: str | None = None,
    ) -> Page:
        page = self.collect(
            "spaces:search",
            "results",
            {"query": query, "orderBy": order_by},
            limit=limit,
            page_token=page_token,
            max_page_size=100,
        )
        spaces = [r.get("space", r) for r in page.items]
        return Page(spaces, page.next_page_token)

    def find_direct_message(self, user: str) -> dict[str, Any]:
        return self.request("GET", "spaces:findDirectMessage", params={"name": user})

    def setup_space(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "spaces:setup", body=body)

    # ------------------------------------------------------------------ messages

    def list_messages(
        self,
        space: str,
        *,
        filter: str | None = None,
        order_by: str | None = None,
        show_deleted: bool = False,
        limit: int | None = 25,
        page_token: str | None = None,
    ) -> Page:
        params = {
            "filter": filter,
            "orderBy": order_by,
            "showDeleted": "true" if show_deleted else None,
        }
        return self.collect(
            f"{space}/messages", "messages", params, limit=limit, page_token=page_token
        )

    def get_message(self, name: str) -> dict[str, Any]:
        return self.request("GET", name)

    def create_message(
        self,
        space: str,
        body: dict[str, Any],
        *,
        reply_option: str | None = None,
        request_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "messageReplyOption": reply_option,
            "requestId": request_id or str(uuid.uuid4()),
            "messageId": message_id,
        }
        return self.request("POST", f"{space}/messages", params=params, body=body)

    def update_message(self, name: str, text: str) -> dict[str, Any]:
        return self.request("PATCH", name, params={"updateMask": "text"}, body={"text": text})

    def delete_message(self, name: str, *, force: bool = False) -> dict[str, Any]:
        return self.request("DELETE", name, params={"force": "true" if force else None})

    # ------------------------------------------------------------------ members

    def list_members(
        self,
        space: str,
        *,
        filter: str | None = None,
        show_groups: bool = False,
        show_invited: bool = False,
        limit: int | None = 100,
        page_token: str | None = None,
    ) -> Page:
        params = {
            "filter": filter,
            "showGroups": "true" if show_groups else None,
            "showInvited": "true" if show_invited else None,
        }
        return self.collect(
            f"{space}/members", "memberships", params, limit=limit, page_token=page_token
        )

    def get_member(self, name: str) -> dict[str, Any]:
        return self.request("GET", name)

    # ------------------------------------------------------------------ reactions

    def list_reactions(
        self,
        message: str,
        *,
        filter: str | None = None,
        limit: int | None = 25,
        page_token: str | None = None,
    ) -> Page:
        return self.collect(
            f"{message}/reactions",
            "reactions",
            {"filter": filter},
            limit=limit,
            page_token=page_token,
            max_page_size=200,
        )

    def create_reaction(self, message: str, emoji: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"{message}/reactions", body={"emoji": emoji})

    def delete_reaction(self, name: str) -> dict[str, Any]:
        return self.request("DELETE", name)

    # ------------------------------------------------------------------ attachments

    def get_attachment(self, name: str) -> dict[str, Any]:
        return self.request("GET", name)

    def download_media(self, resource_name: str, destination: Path) -> int:
        """Stream ``media.download`` into ``destination``; return the byte count."""
        url = f"{self.base_url}/media/{_path(resource_name)}"
        response = self._send("GET", url, params={"alt": "media"}, stream=True)
        written = 0
        tmp = destination.with_name(f".{destination.name}.part")
        try:
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    handle.write(chunk)
                    written += len(chunk)
            tmp.replace(destination)
        finally:
            if tmp.exists():
                tmp.unlink()
        return written

    def upload_attachment(self, space: str, path: Path) -> dict[str, Any]:
        """Upload a file with ``media.upload``; return the ``attachmentDataRef``."""
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        boundary = f"gchat-{uuid.uuid4().hex}"
        metadata = json.dumps({"filename": path.name}).encode("utf-8")
        body = b"".join(
            [
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
                metadata,
                f"\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode(),
                path.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        url = f"{self.upload_url}/{_path(space)}/attachments:upload"
        response = self._send(
            "POST",
            url,
            params={"uploadType": "multipart"},
            data=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        data: dict[str, Any] = response.json()
        return dict(data.get("attachmentDataRef") or data)

    # ------------------------------------------------------------------ read state

    def get_read_state(self, space: str) -> dict[str, Any]:
        return self.request("GET", f"users/me/{space}/spaceReadState")

    def update_read_state(self, space: str, last_read_time: str) -> dict[str, Any]:
        return self.request(
            "PATCH",
            f"users/me/{space}/spaceReadState",
            params={"updateMask": "lastReadTime"},
            body={"lastReadTime": last_read_time},
        )
