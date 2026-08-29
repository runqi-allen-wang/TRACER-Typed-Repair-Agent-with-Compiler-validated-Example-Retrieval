"""证明生成的模型 provider 边界。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


_SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|yi)-[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(?:api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
)


def redact_sensitive_text(value: object) -> str:
    """脱敏 provider 异常或候选中的认证信息。"""

    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[已隐藏的认证信息]", text)
    return text


def _optional_price(name: str) -> float | None:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else None


def configured_pricing() -> dict[str, float | None]:
    return {
        "input_price_per_1k": _optional_price("LEAN_PROOF_INPUT_PRICE_PER_1K"),
        "output_price_per_1k": _optional_price("LEAN_PROOF_OUTPUT_PRICE_PER_1K"),
    }


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """只允许同来源跳转，防止认证头被转发给其他主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(req.full_url) != _origin(newurl):
            raise RuntimeError("Provider 拒绝携带认证信息进行跨来源重定向")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class Generation:
    candidate: str
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = "unknown"
    raw: dict = field(default_factory=dict)


class Provider:
    name = "provider"

    def generate(self, prompt: str) -> Generation:
        raise NotImplementedError

    def metadata(self) -> dict[str, object]:
        """返回可写入日志和精确请求缓存键的非敏感配置。"""
        return {"provider": self.name, **configured_pricing()}


class CommandProvider(Provider):
    name = "command"

    def __init__(self, command: str, timeout: float = 60.0) -> None:
        if not command.strip():
            raise ValueError("command provider 不能为空")
        self.command = command
        self.timeout = timeout

    def generate(self, prompt: str) -> Generation:
        request = json.dumps({"prompt": prompt}, ensure_ascii=False)
        process = subprocess.run(
            self.command,
            input=request,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.timeout,
            shell=True,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"provider command 失败: {process.stderr[-1000:]}")
        return parse_generation(process.stdout, self.name)

    def metadata(self) -> dict[str, object]:
        return {"provider": self.name, "command": self.command, "timeout_s": self.timeout, **configured_pricing()}


class OpenAICompatibleProvider(Provider):
    name = "openai_compatible"

    def __init__(
        self,
        url: str,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        *,
        wire_api: str | None = None,
        reasoning_effort: str | None = None,
        disable_response_storage: bool = False,
        thinking: str | None = None,
        max_attempts: int = 3,
        request_timeout: float = 90,
    ) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("API URL 必须是有效的 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password:
            raise ValueError("API URL 不能内嵌认证信息")
        inferred_wire_api = "responses" if parsed.path.rstrip("/").endswith("/responses") else "chat_completions"
        self.wire_api = (wire_api or inferred_wire_api).strip().lower()
        if self.wire_api not in {"chat_completions", "responses"}:
            raise ValueError("wire_api must be chat_completions or responses")
        suffix = "/responses" if self.wire_api == "responses" else "/chat/completions"
        normalized_url = url.rstrip("/")
        if wire_api and not parsed.path.rstrip("/").endswith(suffix):
            normalized_url = urllib.parse.urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path.rstrip("/") + suffix,
                    parsed.query,
                    "",
                )
            )
        allowed_efforts = {"minimal", "low", "medium", "high"} if self.wire_api == "responses" else {"low", "high", "max"}
        if reasoning_effort is not None and reasoning_effort not in allowed_efforts:
            raise ValueError("reasoning_effort 与当前接口协议不兼容")
        if thinking not in {None, "enabled", "disabled"} or (thinking is not None and self.wire_api != "chat_completions"):
            raise ValueError("thinking 仅适用于支持该参数的 Chat 接口")
        if not 1 <= max_attempts <= 3 or request_timeout <= 0:
            raise ValueError("请求重试次数或超时无效")
        self.url = normalized_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.disable_response_storage = bool(disable_response_storage)
        self.thinking = thinking
        self.max_attempts, self.request_timeout = max_attempts, request_timeout

    def _payload(self, prompt: str) -> dict[str, object]:
        messages = [
            {"role": "system", "content": "You repair Lean 4 proofs. Output only a local proof term."},
            {"role": "user", "content": prompt},
        ]
        if self.wire_api == "responses":
            payload: dict[str, object] = {
                "model": self.model,
                "input": messages,
                "max_output_tokens": self.max_tokens,
                "store": not self.disable_response_storage,
            }
            if self.reasoning_effort:
                payload["reasoning"] = {"effort": self.reasoning_effort}
            return payload
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.thinking is not None:
            payload["thinking"] = {"type": self.thinking}
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def generate(self, prompt: str) -> Generation:
        payload = self._payload(prompt)
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        opener = urllib.request.build_opener(SameOriginRedirectHandler())
        for attempt in range(self.max_attempts):
            try:
                with opener.open(request, timeout=self.request_timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                response_body = exc.read().decode("utf-8", errors="replace").strip()
                detail = response_body[:2000] if response_body else str(exc.reason)
                detail = detail.replace(self.api_key, "[已隐藏的 API 密钥]")
                raise RuntimeError(f"HTTP {exc.code} from provider: {detail}") from exc
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.max_attempts - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
        return parse_generation(json.dumps(body, ensure_ascii=False), self.name)

    def metadata(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "url": self.url,
            "model": self.model,
            "wire_api": self.wire_api,
            "use_responses_api": self.wire_api == "responses",
            "temperature": self.temperature if self.wire_api == "chat_completions" else None,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            **({"thinking": self.thinking} if self.thinking is not None else {}),
            "max_http_attempts": self.max_attempts,
            "request_timeout": self.request_timeout,
            "disable_response_storage": self.disable_response_storage,
            "store": not self.disable_response_storage,
            **configured_pricing(),
        }


class MockProvider(Provider):
    """仅用于测试的 provider，正式评测应使用命令或 API provider。"""

    name = "mock"

    def __init__(self, candidate: str) -> None:
        self.candidate = candidate

    def generate(self, prompt: str) -> Generation:
        return Generation(self.candidate, {"prompt_chars": len(prompt)}, self.name)

    def metadata(self) -> dict[str, object]:
        return {"provider": self.name, "test_only": True, **configured_pricing()}


def clean_candidate(text: str) -> str:
    """提取模型输出中的 Lean 代码，兼容常见 Markdown 代码围栏。"""
    candidate = text.strip()
    fenced = re.search(r"```(?:lean4?|text)?\s*\n?(.*?)```", candidate, flags=re.IGNORECASE | re.DOTALL)
    return (fenced.group(1) if fenced else candidate).strip()


def generation_finish_reason(body: dict) -> str | None:
    """将两种接口的完成状态转为统一日志字段，不将未完成响应送入编译器。"""
    choices = body.get("choices") or []
    if choices:
        return choices[0].get("finish_reason")
    if body.get("status") == "completed":
        return "stop"
    if body.get("status") == "incomplete":
        reason = (body.get("incomplete_details") or {}).get("reason")
        return "length" if reason == "max_output_tokens" else "incomplete"
    if body.get("status") in {"failed", "cancelled", "queued", "in_progress"}:
        return "incomplete"
    return None


def parse_generation(text: str, provider_name: str) -> Generation:
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return Generation(clean_candidate(text), {}, provider_name)
    if "candidate" in body:
        return Generation(clean_candidate(str(body["candidate"])), body.get("usage", {}), provider_name, body)
    choices = body.get("choices") or []
    if choices:
        content = choices[0].get("message", {}).get("content")
        # 只有推理而没有最终答案时 content 可能为 null，不能把它变成 Lean 标识符 None。
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ValueError("provider 的最终证明 content 必须为文本或 null")
        return Generation(clean_candidate(content), body.get("usage", {}), provider_name, body)
    if "output_text" in body:
        content = body["output_text"]
        if content is not None and not isinstance(content, str):
            raise ValueError("provider 的 output_text 必须为文本或 null")
        return Generation(clean_candidate(content or ""), body.get("usage", {}), provider_name, body)
    output_text = "\n".join(
        str(content.get("text", ""))
        for item in body.get("output", [])
        if isinstance(item, dict) and item.get("type") == "message"
        for content in item.get("content", [])
        if isinstance(content, dict) and content.get("type") == "output_text"
    ).strip()
    if output_text or isinstance(body.get("output"), list):
        # 未输出最终文本的 Responses 响应仍保留用量和终止原因。
        return Generation(clean_candidate(output_text), body.get("usage", {}), provider_name, body)
    raise ValueError("provider 输出缺少 candidate/choices/output_text/output[].content[].text")


def build_provider(
    name: str,
    command: str | None = None,
    mock_candidate: str | None = None,
    *,
    api_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    wire_api: str | None = None,
    reasoning_effort: str | None = None,
    disable_response_storage: bool | None = None,
    thinking: str | None = None,
    max_attempts: int = 3,
    request_timeout: float = 90,
) -> Provider:
    if name == "command":
        return CommandProvider(command or os.environ.get("LEAN_PROOF_PROVIDER_COMMAND", ""))
    if name == "openai_compatible":
        url = (api_url or os.environ.get("LEAN_PROOF_API_URL", "")).strip()
        key = (api_key or os.environ.get("LEAN_PROOF_API_KEY", "")).strip()
        model_name = model or os.environ.get("LEAN_PROOF_MODEL", "gpt-4.1-mini")
        if not url or not key:
            raise ValueError("openai_compatible 需要 LEAN_PROOF_API_URL 和 LEAN_PROOF_API_KEY")
        temperature_value = temperature if temperature is not None else float(os.environ.get("LEAN_PROOF_TEMPERATURE", "0"))
        max_tokens_value = max_tokens if max_tokens is not None else int(os.environ.get("LEAN_PROOF_MAX_TOKENS", "800"))
        wire_api_value = wire_api or os.environ.get("LEAN_PROOF_WIRE_API") or None
        reasoning_effort_value = reasoning_effort or os.environ.get("LEAN_PROOF_REASONING_EFFORT") or None
        if disable_response_storage is None:
            disable_response_storage = os.environ.get(
                "LEAN_PROOF_DISABLE_RESPONSE_STORAGE", "false"
            ).strip().lower() in {"1", "true", "yes", "on"}
        return OpenAICompatibleProvider(
            url,
            key,
            model_name,
            temperature_value,
            max_tokens_value,
            wire_api=wire_api_value,
            reasoning_effort=reasoning_effort_value,
            disable_response_storage=disable_response_storage,
            thinking=thinking, max_attempts=max_attempts, request_timeout=request_timeout,
        )
    if name == "mock":
        if mock_candidate is None:
            raise ValueError("mock provider 需要 --mock-candidate，仅用于测试")
        return MockProvider(mock_candidate)
    raise ValueError(f"未知 provider: {name}")
