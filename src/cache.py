"""由 SQLite 支持的持久化精确请求缓存。"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from provider import Generation


def canonical_request(problem_id: str, feedback: str, round_no: int) -> str:
    """精确序列化修复请求，保证测试夹具稳定。"""
    return json.dumps(
        {"problem_id": problem_id, "feedback": feedback, "round": round_no},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class RequestCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS requests (request_text TEXT PRIMARY KEY, candidate TEXT NOT NULL, usage_json TEXT NOT NULL, provider TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self.connection.commit()

    def get(self, request_text: str) -> Generation | None:
        row = self.connection.execute(
            "SELECT candidate, usage_json, provider FROM requests WHERE request_text = ?", (request_text,)
        ).fetchone()
        if row is None:
            return None
        return Generation(row[0], json.loads(row[1]), row[2])

    def put(self, request_text: str, generation: Generation) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO requests(request_text,candidate,usage_json,provider,created_at) VALUES(?,?,?,?,?)",
            (request_text, generation.candidate, json.dumps(generation.usage, ensure_ascii=False), generation.provider, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "RequestCache":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
