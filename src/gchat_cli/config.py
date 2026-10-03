"""Paths, configuration file and the local safety policy.

The policy lets an operator constrain what the CLI may do *before* any request
reaches Google, which is the main safeguard when an AI agent drives the CLI:

.. code-block:: toml

    # ~/.config/gchat/config.toml
    [policy]
    read_only = false            # refuse every write
    allow_dm_write = true        # allow writes to DMs and group chats
    read = ["*"]                 # spaces that may be read ("*" = any)
    write = ["spaces/AAAA"]      # spaces that may be written

Environment variables override the file: ``GCHAT_READ_ONLY``,
``GCHAT_ALLOW_DM_WRITE``, ``GCHAT_ALLOW_READ`` and ``GCHAT_ALLOW_WRITE``
(comma-separated space names or ``*``).
"""

from __future__ import annotations

import os
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gchat_cli.errors import PolicyError, ValidationError

APP_NAME = "gchat"
WILDCARD = "*"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


def config_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("GCHAT_CONFIG_DIR"):
        return Path(env["GCHAT_CONFIG_DIR"]).expanduser()
    if sys.platform == "win32" and env.get("APPDATA"):  # pragma: no cover - platform specific
        return Path(env["APPDATA"]) / APP_NAME
    base = env.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / APP_NAME


def config_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("GCHAT_CONFIG"):
        return Path(env["GCHAT_CONFIG"]).expanduser()
    return config_dir(env) / "config.toml"


def client_secrets_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("GCHAT_CLIENT_SECRETS"):
        return Path(env["GCHAT_CLIENT_SECRETS"]).expanduser()
    return config_dir(env) / "client_secret.json"


def token_file(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("GCHAT_TOKEN_FILE"):
        return Path(env["GCHAT_TOKEN_FILE"]).expanduser()
    return config_dir(env) / "token.json"


def parse_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValidationError(f"{name} must be a boolean, got {value!r}")


def _parse_list(value: Any, name: str) -> frozenset[str]:
    from gchat_cli import validation

    if isinstance(value, str):
        items: Iterable[Any] = [v for v in value.split(",") if v.strip()]
    elif isinstance(value, list):
        items = value
    else:
        raise ValidationError(f"{name} must be a list of space names")
    result: set[str] = set()
    for item in items:
        text = str(item).strip()
        result.add(WILDCARD if text == WILDCARD else validation.space_name(text))
    return frozenset(result)


@dataclass(frozen=True)
class Policy:
    """Client-side restrictions applied before any API call."""

    read_only: bool = False
    allow_dm_write: bool = True
    read: frozenset[str] = field(default_factory=lambda: frozenset({WILDCARD}))
    write: frozenset[str] = field(default_factory=lambda: frozenset({WILDCARD}))

    def can_read(self, space: str) -> bool:
        return WILDCARD in self.read or space in self.read

    def can_write(self, space: str) -> bool:
        if self.read_only:
            return False
        return WILDCARD in self.write or space in self.write

    def require_read(self, space: str) -> None:
        if not self.can_read(space):
            raise PolicyError(
                f"Reading {space} is not allowed by the local policy",
                hint="Add the space to policy.read in the config file or GCHAT_ALLOW_READ.",
            )

    def require_write(self, space: str) -> None:
        if self.read_only:
            raise PolicyError(
                "Writes are disabled (read-only mode)",
                hint="Unset GCHAT_READ_ONLY or policy.read_only to allow writes.",
            )
        if not self.can_write(space):
            raise PolicyError(
                f"Writing to {space} is not allowed by the local policy",
                hint="Add the space to policy.write in the config file or GCHAT_ALLOW_WRITE.",
            )

    def require_dm_write(self, space: str, space_type: str | None) -> None:
        if not self.allow_dm_write and space_type in {"DIRECT_MESSAGE", "GROUP_CHAT"}:
            raise PolicyError(
                f"Writing to direct messages and group chats is disabled ({space})",
                hint="Set policy.allow_dm_write = true or GCHAT_ALLOW_DM_WRITE=1 to allow it.",
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "read_only": self.read_only,
            "allow_dm_write": self.allow_dm_write,
            "read": sorted(self.read),
            "write": sorted(self.write),
        }


@dataclass(frozen=True)
class Config:
    policy: Policy = field(default_factory=Policy)
    defaults: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Load the config file (if any) and apply environment overrides."""
    env = os.environ if env is None else env
    path = config_file(env)
    data: dict[str, Any] = {}
    source: Path | None = None
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValidationError(f"Cannot read config file {path}: {exc}") from exc
        source = path

    raw_policy = data.get("policy") or {}
    if not isinstance(raw_policy, dict):
        raise ValidationError("[policy] must be a table")
    unknown = set(raw_policy) - {"read_only", "allow_dm_write", "read", "write"}
    if unknown:
        raise ValidationError(f"Unknown policy keys: {', '.join(sorted(unknown))}")

    read_only = parse_bool(raw_policy.get("read_only", False), "policy.read_only")
    allow_dm = parse_bool(raw_policy.get("allow_dm_write", True), "policy.allow_dm_write")
    read = _parse_list(raw_policy.get("read", [WILDCARD]), "policy.read")
    write = _parse_list(raw_policy.get("write", [WILDCARD]), "policy.write")

    if "GCHAT_READ_ONLY" in env:
        read_only = parse_bool(env["GCHAT_READ_ONLY"], "GCHAT_READ_ONLY")
    if "GCHAT_ALLOW_DM_WRITE" in env:
        allow_dm = parse_bool(env["GCHAT_ALLOW_DM_WRITE"], "GCHAT_ALLOW_DM_WRITE")
    if "GCHAT_ALLOW_READ" in env:
        read = _parse_list(env["GCHAT_ALLOW_READ"], "GCHAT_ALLOW_READ")
    if "GCHAT_ALLOW_WRITE" in env:
        write = _parse_list(env["GCHAT_ALLOW_WRITE"], "GCHAT_ALLOW_WRITE")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValidationError("[defaults] must be a table")

    return Config(
        policy=Policy(read_only=read_only, allow_dm_write=allow_dm, read=read, write=write),
        defaults=defaults,
        source=source,
    )


SAMPLE_CONFIG = """\
# gchat configuration. Environment variables take precedence over this file.

[defaults]
# Output format when --format is not given: auto | json | ndjson | table
# format = "auto"

[policy]
# Refuse every write operation (send, edit, delete, react, mark-read).
read_only = false

# Allow writes to direct messages and group chats.
allow_dm_write = true

# Spaces that may be read / written. "*" means any space.
read = ["*"]
write = ["*"]
"""
