from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError


APP_NAME = "taskcli"


@dataclass
class Config:
    provider: str = "beca"
    project: str | None = None
    current_sprint: str | None = None
    assignee: str | None = None
    parent_id: str | None = None
    data_path: Path | None = None
    idempotency_path: Path | None = None
    timeout: float = 30
    verbose: bool = False
    beca_username: str | None = None
    beca_password: str | None = None
    beca_cookie: str | None = None


def xdg_config_home() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


def xdg_state_home() -> Path:
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def default_config_path() -> Path:
    return xdg_config_home() / APP_NAME / "config.toml"


def default_data_path() -> Path:
    return xdg_state_home() / APP_NAME / "mock_store.json"


def default_idempotency_path() -> Path:
    return xdg_state_home() / APP_NAME / "idempotency.json"


def load_config(
    config_path: str | None = None,
    env: dict[str, str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    env = env or os.environ
    load_dotenv(env)
    path = Path(config_path or env.get("TASKCLI_CONFIG") or default_config_path()).expanduser()
    data = read_toml(path)
    provider_section = data.get("provider", {})
    provider_data = provider_section if isinstance(provider_section, dict) else {}
    provider_name = provider_data.get("name") if provider_data else provider_section
    defaults_data = data.get("defaults", {})
    beca_data = data.get("beca", {})
    mock_data = data.get("mock", {})

    config = Config(
        provider=str(provider_name or "beca"),
        project=string_or_none(defaults_data.get("project")),
        current_sprint=string_or_none(defaults_data.get("current_sprint")),
        assignee=string_or_none(defaults_data.get("assignee")),
        parent_id=string_or_none(defaults_data.get("parent_id")),
        data_path=path_or_none(mock_data.get("data_path")),
        idempotency_path=path_or_none(provider_data.get("idempotency_path")),
        timeout=float(provider_data.get("timeout") or 30),
        verbose=bool(provider_data.get("verbose") or False),
        beca_username=string_or_none(beca_data.get("username")),
        beca_password=string_or_none(beca_data.get("password")),
        beca_cookie=string_or_none(beca_data.get("cookie")),
    )

    apply_env(config, env)
    apply_overrides(config, overrides or {})

    if config.data_path is None:
        config.data_path = default_data_path()
    if config.idempotency_path is None:
        config.idempotency_path = default_idempotency_path()
    return config


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid config TOML: {path}", {"error": str(exc)}) from exc


def apply_env(config: Config, env: dict[str, str]) -> None:
    mapping = {
        "TASKCLI_PROVIDER": "provider",
        "TASKCLI_PROJECT": "project",
        "TASKCLI_CURRENT_SPRINT": "current_sprint",
        "TASKCLI_ASSIGNEE": "assignee",
        "TASKCLI_PARENT_ID": "parent_id",
        "TASKCLI_DATA_PATH": "data_path",
        "TASKCLI_IDEMPOTENCY_PATH": "idempotency_path",
        "TASKCLI_TIMEOUT": "timeout",
        "TASKCLI_VERBOSE": "verbose",
        "TASKCLI_BECA_USERNAME": "beca_username",
        "TASKCLI_BECA_PASSWORD": "beca_password",
        "TASKCLI_BECA_COOKIE": "beca_cookie",
    }
    for env_name, attr in mapping.items():
        value = env.get(env_name)
        if value is None or value == "":
            continue
        set_config_value(config, attr, value)

    # Existing credential names are accepted, but workflow/project ids are not.
    # Those should be provided as explicit CLI flags or TASKCLI_* defaults.
    if env.get("BECA_USERNAME") and not env.get("TASKCLI_BECA_USERNAME"):
        config.beca_username = env["BECA_USERNAME"]
    if env.get("BECA_PASSWORD") and not env.get("TASKCLI_BECA_PASSWORD"):
        config.beca_password = env["BECA_PASSWORD"]
    if env.get("BECA_COOKIE") and not env.get("TASKCLI_BECA_COOKIE"):
        config.beca_cookie = env["BECA_COOKIE"]


def apply_overrides(config: Config, overrides: dict[str, Any]) -> None:
    for attr, value in overrides.items():
        if value is None or value == "":
            continue
        set_config_value(config, attr, value)


def set_config_value(config: Config, attr: str, value: Any) -> None:
    if attr in {"data_path", "idempotency_path"}:
        setattr(config, attr, Path(str(value)).expanduser())
    elif attr == "timeout":
        setattr(config, attr, float(value))
    elif attr == "verbose":
        setattr(config, attr, parse_bool(value))
    else:
        setattr(config, attr, str(value))


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def path_or_none(value: Any) -> Path | None:
    text = string_or_none(value)
    return Path(text).expanduser() if text else None


def load_dotenv(env: dict[str, str], path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
