from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class IdempotencyStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, provider: str, operation: str, key: str) -> dict[str, Any] | None:
        data = self._read()
        return data.get(provider, {}).get(operation, {}).get(key)

    def put(self, provider: str, operation: str, key: str, record: dict[str, Any]) -> None:
        data = self._read()
        data.setdefault(provider, {}).setdefault(operation, {})[key] = record
        self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def content_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

