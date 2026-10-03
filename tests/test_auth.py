from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import responses

from gchat_cli import auth
from gchat_cli.errors import AuthError, ValidationError


def env_for(tmp_path: Path) -> dict[str, str]:
    return {"GCHAT_CONFIG_DIR": str(tmp_path)}


def stored_token(**extra: object) -> dict[str, object]:
    data: dict[str, object] = {
        "token": "access",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "secret",
        "scopes": ["https://www.googleapis.com/auth/chat.messages"],
        "expiry": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    data.update(extra)
    return data


def test_expand_scopes() -> None:
    scopes = auth.expand_scopes(["readonly"], ["chat.spaces", "chat.spaces.readonly"])
    assert scopes[0] == "https://www.googleapis.com/auth/chat.spaces.readonly"
    assert "https://www.googleapis.com/auth/chat.spaces" in scopes
    assert len(scopes) == len(set(scopes))
    with pytest.raises(ValidationError):
        auth.expand_scopes(["nope"])
    with pytest.raises(ValidationError):
        auth.expand_scopes([], [" "])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_token_store_file_permissions(tmp_path: Path) -> None:
    store = auth.TokenStore(env_for(tmp_path))
    assert store.load() is None
    store.save({"token": "x"})
    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600
    assert store.load() == {"token": "x"}
    assert store.delete() is True
    assert store.delete() is False


def test_token_store_corrupted(tmp_path: Path) -> None:
    store = auth.TokenStore(env_for(tmp_path))
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json")
    with pytest.raises(AuthError, match="corrupted"):
        store.load()


def test_token_store_backend_validation(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        auth.TokenStore({**env_for(tmp_path), "GCHAT_TOKEN_STORE": "vault"})


def test_load_credentials_from_env_token(tmp_path: Path) -> None:
    creds = auth.load_credentials({**env_for(tmp_path), "GCHAT_ACCESS_TOKEN": "abc"})
    assert creds.token == "abc"


def test_load_credentials_not_logged_in(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="Not logged in"):
        auth.load_credentials(env_for(tmp_path))


def test_load_credentials_from_store(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    auth.TokenStore(env).save(stored_token())
    creds = auth.load_credentials(env)
    assert creds.token == "access"


@responses.activate
def test_load_credentials_refreshes_and_saves(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    expired = stored_token(expiry="2020-01-01T00:00:00.000000Z", authorized_at="2026-01-01")
    auth.TokenStore(env).save(expired)
    responses.post(
        "https://oauth2.googleapis.com/token",
        json={"access_token": "new-access", "expires_in": 3600, "token_type": "Bearer"},
    )
    creds = auth.load_credentials(env)
    assert creds.token == "new-access"
    saved = auth.TokenStore(env).load()
    assert saved is not None
    assert saved["token"] == "new-access"
    assert saved["authorized_at"] == "2026-01-01"


@responses.activate
def test_refresh_failure_is_auth_error(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    auth.TokenStore(env).save(stored_token(expiry="2020-01-01T00:00:00.000000Z"))
    responses.post(
        "https://oauth2.googleapis.com/token",
        status=400,
        json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
    )
    with pytest.raises(AuthError, match="refresh"):
        auth.load_credentials(env)


def test_credentials_file(tmp_path: Path) -> None:
    path = tmp_path / "creds.json"
    path.write_text(json.dumps(stored_token()))
    creds = auth.load_credentials({"GCHAT_CREDENTIALS_FILE": str(path)})
    assert creds.refresh_token == "refresh"
    with pytest.raises(AuthError):
        auth.load_credentials({"GCHAT_CREDENTIALS_FILE": str(tmp_path / "missing.json")})


def test_status(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    assert auth.status(env)["authenticated"] is False
    old = (datetime.now(UTC) - timedelta(days=6, hours=1)).isoformat()
    auth.TokenStore(env).save(stored_token(authorized_at=old))
    result = auth.status(env)
    assert result["authenticated"] is True
    assert result["scopes"] == ["chat.messages"]
    assert result["ageDays"] == 6
    assert "7 days" in result["warning"]
    dumped = json.dumps(result)
    assert "secret" not in dumped
    assert '"access"' not in dumped
    assert auth.status({"GCHAT_ACCESS_TOKEN": "x"})["source"] == "GCHAT_ACCESS_TOKEN"


@responses.activate
def test_logout_revokes_and_deletes(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    auth.TokenStore(env).save(stored_token())
    responses.post(auth.REVOKE_URL, status=200)
    result = auth.logout(env=env)
    assert result == {
        "loggedOut": True,
        "removed": True,
        "revoked": True,
        "store": str(tmp_path / "token.json"),
    }
    assert auth.TokenStore(env).load() is None


def test_client_config_sources(tmp_path: Path) -> None:
    env = env_for(tmp_path)
    with pytest.raises(AuthError, match="not found"):
        auth._client_config(env)
    cfg = auth._client_config({**env, "GCHAT_CLIENT_ID": "id", "GCHAT_CLIENT_SECRET": "s"})
    assert cfg["installed"]["client_id"] == "id"
    secrets = tmp_path / "client_secret.json"
    secrets.write_text(json.dumps({"other": {}}))
    with pytest.raises(AuthError, match="not an OAuth client"):
        auth._client_config(env)
    secrets.write_text(json.dumps({"installed": {"client_id": "x"}}))
    assert auth._client_config(env)["installed"]["client_id"] == "x"


def test_login_saves_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from google.oauth2.credentials import Credentials

    env = {**env_for(tmp_path), "GCHAT_CLIENT_ID": "id", "GCHAT_CLIENT_SECRET": "s"}
    seen: dict[str, object] = {}

    class FakeFlow:
        @classmethod
        def from_client_config(cls, config: dict[str, object], scopes: list[str]) -> FakeFlow:
            seen["scopes"] = scopes
            return cls()

        def run_local_server(self, **kwargs: object) -> Credentials:
            seen.update(kwargs)
            return Credentials(
                token="t",
                refresh_token="r",
                token_uri="https://oauth2.googleapis.com/token",
                client_id="id",
                client_secret="s",
                scopes=seen["scopes"],
            )

    monkeypatch.setattr("google_auth_oauthlib.flow.InstalledAppFlow", FakeFlow)
    result = auth.login(auth.expand_scopes(["default"]), open_browser=False, env=env)
    assert result["authenticated"] is True
    assert seen["open_browser"] is False
    assert seen["prompt"] == "consent"
    saved = auth.TokenStore(env).load()
    assert saved is not None
    assert saved["refresh_token"] == "r"
    assert "authorized_at" in saved
