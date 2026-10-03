"""OAuth 2.0 user authentication and credential storage.

Credential resolution order (first match wins):

1. ``GCHAT_ACCESS_TOKEN``: a raw OAuth access token (no refresh).
2. ``GCHAT_CREDENTIALS_FILE``: an ``authorized_user`` JSON file.
3. The token saved by ``gchat auth login`` (file or OS keyring).
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from gchat_cli import config
from gchat_cli.errors import AuthError, ValidationError

SCOPE_PREFIX = "https://www.googleapis.com/auth/"

SCOPE_PRESETS: dict[str, tuple[str, ...]] = {
    "readonly": (
        "chat.spaces.readonly",
        "chat.messages.readonly",
        "chat.memberships.readonly",
        "chat.messages.reactions.readonly",
        "chat.users.readstate.readonly",
    ),
    "default": (
        "chat.spaces.readonly",
        "chat.messages",
        "chat.memberships.readonly",
        "chat.messages.reactions",
        "chat.users.readstate",
    ),
    "full": (
        "chat.spaces",
        "chat.messages",
        "chat.memberships",
        "chat.messages.reactions",
        "chat.users.readstate",
    ),
}

KEYRING_SERVICE = "google-chat-cli"
KEYRING_USER = "default"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
TESTING_MODE_WARN_DAYS = 6


def expand_scopes(presets: Iterable[str] = (), extra: Iterable[str] = ()) -> list[str]:
    """Expand preset names and short scope names into full scope URLs."""
    scopes: list[str] = []
    for preset in presets:
        if preset not in SCOPE_PRESETS:
            raise ValidationError(
                f"Unknown scope preset {preset!r}",
                hint=f"Choose one of: {', '.join(SCOPE_PRESETS)}",
            )
        scopes.extend(SCOPE_PRESETS[preset])
    scopes.extend(extra)
    full: list[str] = []
    for scope in scopes:
        scope = scope.strip()
        if not scope:
            continue
        url = scope if scope.startswith("https://") else SCOPE_PREFIX + scope
        if url not in full:
            full.append(url)
    if not full:
        raise ValidationError("No OAuth scopes selected")
    return full


def short_scope(scope: str) -> str:
    return scope.removeprefix(SCOPE_PREFIX)


# --------------------------------------------------------------------------- storage


class TokenStore:
    """Persists the authorized-user credentials (file with 0600 perms, or keyring)."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = os.environ if env is None else env
        backend = self.env.get("GCHAT_TOKEN_STORE", "file").strip().lower()
        if backend not in {"file", "keyring"}:
            raise ValidationError("GCHAT_TOKEN_STORE must be 'file' or 'keyring'")
        self.backend = backend
        self.path = config.token_file(self.env)

    @property
    def location(self) -> str:
        if self.backend == "keyring":
            return f"keyring:{KEYRING_SERVICE}"
        return str(self.path)

    def _keyring(self) -> Any:
        try:
            import keyring
        except ImportError as exc:
            raise AuthError(
                "GCHAT_TOKEN_STORE=keyring requires the optional 'keyring' package",
                hint="Install it with: pip install 'google-chat-cli[keyring]'",
            ) from exc
        return keyring

    def load(self) -> dict[str, Any] | None:
        if self.backend == "keyring":
            raw = self._keyring().get_password(KEYRING_SERVICE, KEYRING_USER)
        else:
            if not self.path.is_file():
                return None
            raw = self.path.read_text(encoding="utf-8")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthError(
                f"Stored token at {self.location} is corrupted",
                hint="Run `gchat auth logout` and `gchat auth login` again.",
            ) from exc
        return data if isinstance(data, dict) else None

    def save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2)
        if self.backend == "keyring":
            self._keyring().set_password(KEYRING_SERVICE, KEYRING_USER, payload)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".token-", suffix=".json")
        try:
            os.chmod(tmp, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def delete(self) -> bool:
        if self.backend == "keyring":
            keyring = self._keyring()
            if keyring.get_password(KEYRING_SERVICE, KEYRING_USER) is None:
                return False
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            return True
        if self.path.is_file():
            self.path.unlink()
            return True
        return False


def _credentials_to_dict(creds: Credentials, authorized_at: str | None) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(creds.to_json())
    if authorized_at:
        data["authorized_at"] = authorized_at
    return data


# --------------------------------------------------------------------------- login


def _client_config(env: Mapping[str, str]) -> dict[str, Any]:
    client_id = env.get("GCHAT_CLIENT_ID")
    client_secret = env.get("GCHAT_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
    path = config.client_secrets_file(env)
    if not path.is_file():
        raise AuthError(
            f"OAuth client file not found: {path}",
            hint=(
                "Create a 'Desktop app' OAuth client in Google Cloud Console and save the JSON "
                f"as {path} (or pass --client-secrets / set GCHAT_CLIENT_ID and "
                "GCHAT_CLIENT_SECRET). See docs/setup.md."
            ),
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthError(f"Cannot read OAuth client file {path}: {exc}") from exc
    if not isinstance(data, dict) or not ({"installed", "web"} & data.keys()):
        raise AuthError(
            f"{path} is not an OAuth client file",
            hint="Download the JSON of a 'Desktop app' OAuth client from Google Cloud Console.",
        )
    return data


def login(
    scopes: list[str],
    *,
    open_browser: bool = True,
    port: int = 0,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the installed-app OAuth flow and persist the resulting credentials."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    env = os.environ if env is None else env
    flow = InstalledAppFlow.from_client_config(_client_config(env), scopes=scopes)
    # The OAuth library prints the authorization URL to stdout; keep stdout clean for JSON.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            creds = flow.run_local_server(
                port=port,
                open_browser=open_browser,
                prompt="consent",
                access_type="offline",
                authorization_prompt_message=(
                    "Open this URL in a browser to authorize gchat:\n{url}\n"
                ),
                success_message="gchat is authorized. You can close this window.",
            )
        except Exception as exc:
            raise AuthError(f"OAuth flow failed: {exc}") from exc
    authorized_at = datetime.now(UTC).isoformat()
    store = TokenStore(env)
    store.save(_credentials_to_dict(creds, authorized_at))
    return {
        "authenticated": True,
        "scopes": sorted(short_scope(s) for s in (creds.scopes or scopes)),
        "store": store.location,
        "authorizedAt": authorized_at,
    }


# --------------------------------------------------------------------------- loading


def _refresh(creds: Credentials) -> None:
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise AuthError(
            f"Could not refresh the access token: {exc}",
            hint="The refresh token was revoked or expired. Run `gchat auth login`.",
        ) from exc
    except TransportError as exc:
        raise AuthError(f"Network error while refreshing the token: {exc}") from exc


def load_credentials(env: Mapping[str, str] | None = None) -> Credentials:
    """Return valid credentials, refreshing (and re-saving) them when needed."""
    env = os.environ if env is None else env

    token = env.get("GCHAT_ACCESS_TOKEN")
    if token:
        return Credentials(token=token)

    creds_file = env.get("GCHAT_CREDENTIALS_FILE")
    if creds_file:
        path = Path(creds_file).expanduser()
        try:
            creds = Credentials.from_authorized_user_file(str(path))
        except (OSError, ValueError) as exc:
            raise AuthError(f"Cannot load GCHAT_CREDENTIALS_FILE {path}: {exc}") from exc
        if not creds.valid:
            _refresh(creds)
        return creds

    store = TokenStore(env)
    data = store.load()
    if data is None:
        raise AuthError("Not logged in", hint="Run `gchat auth login` first.")
    try:
        creds = Credentials.from_authorized_user_info(data)
    except ValueError as exc:
        raise AuthError(
            f"Stored token at {store.location} is invalid: {exc}",
            hint="Run `gchat auth login` again.",
        ) from exc
    if not creds.valid:
        if not creds.refresh_token:
            raise AuthError(
                "Access token expired and no refresh token is stored",
                hint="Run `gchat auth login` again.",
            )
        _refresh(creds)
        store.save(_credentials_to_dict(creds, data.get("authorized_at")))
    return creds


def status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Describe the current authentication state without printing any secret."""
    env = os.environ if env is None else env
    if env.get("GCHAT_ACCESS_TOKEN"):
        return {"authenticated": True, "source": "GCHAT_ACCESS_TOKEN"}
    if env.get("GCHAT_CREDENTIALS_FILE"):
        return {
            "authenticated": Path(env["GCHAT_CREDENTIALS_FILE"]).expanduser().is_file(),
            "source": "GCHAT_CREDENTIALS_FILE",
            "path": env["GCHAT_CREDENTIALS_FILE"],
        }
    store = TokenStore(env)
    result: dict[str, Any] = {
        "source": "store",
        "store": store.location,
        "clientSecretsFound": bool(env.get("GCHAT_CLIENT_ID"))
        or config.client_secrets_file(env).is_file(),
    }
    data = store.load()
    if not data:
        result["authenticated"] = False
        result["hint"] = "Run `gchat auth login`."
        return result
    result["authenticated"] = bool(data.get("refresh_token") or data.get("token"))
    result["scopes"] = sorted(short_scope(s) for s in data.get("scopes") or [])
    result["hasRefreshToken"] = bool(data.get("refresh_token"))
    if data.get("expiry"):
        result["accessTokenExpiry"] = data["expiry"]
    authorized_at = data.get("authorized_at")
    if authorized_at:
        result["authorizedAt"] = authorized_at
        with contextlib.suppress(ValueError):
            age = datetime.now(UTC) - datetime.fromisoformat(authorized_at)
            result["ageDays"] = age.days
            if age.days >= TESTING_MODE_WARN_DAYS:
                result["warning"] = (
                    "If your OAuth consent screen is in 'Testing' mode, Google expires refresh "
                    "tokens after 7 days. Run `gchat auth login` again if calls start failing."
                )
    return result


def logout(*, revoke: bool = True, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Revoke (best effort) and delete the stored credentials."""
    store = TokenStore(env)
    data = store.load()
    revoked = False
    if data and revoke:
        token = data.get("refresh_token") or data.get("token")
        if token:
            with contextlib.suppress(requests.RequestException):
                response = requests.post(
                    REVOKE_URL,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15,
                )
                revoked = response.ok
    removed = store.delete()
    return {"loggedOut": True, "removed": removed, "revoked": revoked, "store": store.location}
