"""TRACER 本地 HTTP API。

默认只监听本机。API 密钥仅在当前请求内存中使用，不写入日志、缓存或结果文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from agent import ROOT, solve_problem
from provider import build_provider


def _response_payload(result: dict[str, Any]) -> dict[str, Any]:
    """只返回运行结果，不返回候选 provider 的敏感配置。"""

    return {
        "compile_ok": result.get("compile_ok", False),
        "round": result.get("round"),
        "condition": result.get("condition"),
        "provider": result.get("provider"),
        "problem_id": result.get("problem_id"),
        "diagnostic": result.get("diagnostic"),
        "usage": result.get("usage", {}),
        "estimated_cost_usd": result.get("estimated_cost_usd"),
    }


def make_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        """处理健康检查与证明修复请求。"""

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, {"ok": True, "service": "TRACER"})
            else:
                self._send(404, {"ok": False, "error": "未找到接口"})

        def do_POST(self) -> None:
            if self.path != "/solve":
                self._send(404, {"ok": False, "error": "未找到接口"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = _solve_payload(payload)
                self._send(200, {"ok": bool(result.get("compile_ok")), "result": _response_payload(result)})
            except Exception as exc:
                self._send(400, {"ok": False, "error": str(exc)[:500]})

        def log_message(self, fmt: str, *args: object) -> None:
            """不记录请求体，避免密钥意外进入终端日志。"""

            sys.stderr.write("[TRACER API] " + (fmt % args) + "\n")

    return Handler


def _solve_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """从 JSON 请求创建一次性 provider 并运行修复循环。"""

    required = ("file", "theorem", "condition", "api_url", "api_key", "model")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError("缺少字段: " + ", ".join(missing))
    source = Path(str(payload["file"])).expanduser().resolve()
    provider = build_provider(
        "openai_compatible",
        api_url=str(payload["api_url"]),
        api_key=str(payload["api_key"]),
        model=str(payload["model"]),
        temperature=float(payload.get("temperature", 0)),
        max_tokens=int(payload.get("max_tokens", 800)),
    )
    result = solve_problem(
        source,
        str(payload["theorem"]),
        str(payload["condition"]),
        provider,
        int(payload.get("max_rounds", 3)),
        float(payload.get("timeout", 20)),
        Path(str(payload.get("examples_dir", ROOT / "examples"))).resolve(),
        Path(str(payload.get("cache", ROOT / "results" / "requests.sqlite3"))).resolve(),
        Path(str(payload.get("output_dir", ROOT / "results" / "solutions"))).resolve(),
        Path(str(payload.get("log", ROOT / "results" / "agent_runs.jsonl"))).resolve(),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 TRACER 本地 HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler())
    print(f"TRACER API 已启动：http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
