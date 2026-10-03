from __future__ import annotations

from pathlib import Path

import pytest

from gchat_cli import config
from gchat_cli.errors import PolicyError, ValidationError


def write_config(tmp_path: Path, body: str) -> dict[str, str]:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return {"GCHAT_CONFIG": str(path)}


def test_defaults_without_file(tmp_path: Path) -> None:
    cfg = config.load_config({"GCHAT_CONFIG_DIR": str(tmp_path)})
    assert cfg.source is None
    assert cfg.policy.can_read("spaces/A")
    assert cfg.policy.can_write("spaces/A")
    assert cfg.policy.allow_dm_write


def test_paths_follow_env(tmp_path: Path) -> None:
    env = {"GCHAT_CONFIG_DIR": str(tmp_path)}
    assert config.config_file(env) == tmp_path / "config.toml"
    assert config.token_file(env) == tmp_path / "token.json"
    assert config.client_secrets_file(env) == tmp_path / "client_secret.json"
    assert config.token_file({"GCHAT_TOKEN_FILE": "/x/t.json"}) == Path("/x/t.json")
    assert config.config_dir({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "gchat"


def test_file_policy(tmp_path: Path) -> None:
    env = write_config(
        tmp_path,
        """
[policy]
read_only = false
allow_dm_write = false
read = ["*"]
write = ["spaces/AAA", "BBB"]
""",
    )
    policy = config.load_config(env).policy
    assert policy.can_write("spaces/AAA")
    assert policy.can_write("spaces/BBB")
    assert not policy.can_write("spaces/CCC")
    with pytest.raises(PolicyError):
        policy.require_write("spaces/CCC")
    with pytest.raises(PolicyError):
        policy.require_dm_write("spaces/AAA", "DIRECT_MESSAGE")
    policy.require_dm_write("spaces/AAA", "SPACE")


def test_env_overrides_file(tmp_path: Path) -> None:
    env = write_config(tmp_path, '[policy]\nwrite = ["*"]\n')
    env.update({"GCHAT_READ_ONLY": "1", "GCHAT_ALLOW_READ": "spaces/X, spaces/Y"})
    policy = config.load_config(env).policy
    assert policy.read_only
    assert not policy.can_write("spaces/X")
    assert policy.can_read("spaces/Y")
    assert not policy.can_read("spaces/Z")
    with pytest.raises(PolicyError, match="read-only"):
        policy.require_write("spaces/X")
    with pytest.raises(PolicyError):
        policy.require_read("spaces/Z")


@pytest.mark.parametrize(
    "body",
    [
        "[policy]\nunknown = 1\n",
        "[policy]\nread_only = 'maybe'\n",
        "[policy]\nwrite = 3\n",
        "[policy]\nwrite = ['spaces/../x']\n",
        "not valid toml [[[",
        "policy = 3\n",
    ],
)
def test_invalid_config(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValidationError):
        config.load_config(write_config(tmp_path, body))


def test_parse_bool() -> None:
    assert config.parse_bool("yes", "x") is True
    assert config.parse_bool("0", "x") is False
    assert config.parse_bool(True, "x") is True


def test_sample_config_is_valid(tmp_path: Path) -> None:
    cfg = config.load_config(write_config(tmp_path, config.SAMPLE_CONFIG))
    assert cfg.policy.as_dict()["write"] == ["*"]
