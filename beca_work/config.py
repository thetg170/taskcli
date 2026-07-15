from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_OUTPUT_PATH = "output.json"


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env: {name}")
    return value


def write_output(data: object, path: str | None = None) -> None:
    output_path = Path(path or os.getenv("OUTPUT_PATH") or DEFAULT_OUTPUT_PATH)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Saved output:", output_path)
