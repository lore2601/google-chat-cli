from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import responses
from google.oauth2.credentials import Credentials

from gchat_cli.cli import run

API = "https://chat.googleapis.com/v1"


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def json(self) -> Any:
        return json.loads(self.out)

    @property
    def error(self) -> dict[str, Any]:
        return dict(json.loads(self.err.strip().splitlines()[-1])["error"])


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests away from the real config directory and environment."""
    for var in [
        "GCHAT_CONFIG",
        "GCHAT_FORMAT",
        "GCHAT_READ_ONLY",
        "GCHAT_ALLOW_READ",
        "GCHAT_ALLOW_WRITE",
        "GCHAT_ALLOW_DM_WRITE",
        "GCHAT_ACCESS_TOKEN",
        "GCHAT_CREDENTIALS_FILE",
        "GCHAT_CLIENT_ID",
        "GCHAT_CLIENT_SECRET",
        "GCHAT_CLIENT_SECRETS",
        "GCHAT_TOKEN_FILE",
        "GCHAT_TOKEN_STORE",
    ]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GCHAT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("gchat_cli.client.time.sleep", lambda _s: None)


@pytest.fixture
def fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gchat_cli.auth.load_credentials", lambda env=None: Credentials(token="test-token")
    )


@pytest.fixture
def api(fake_auth: None) -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def gchat(capsys: pytest.CaptureFixture[str]) -> Callable[..., Result]:
    def invoke(*args: str) -> Result:
        code = run(list(args))
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return invoke
