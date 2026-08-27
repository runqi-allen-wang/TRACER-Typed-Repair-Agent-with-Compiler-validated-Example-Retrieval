"""证明生成的模型 provider 边界。"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field


MAX_PROVIDER_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PROVIDER_ERROR_BYTES = 8 * 1024
SENSITIVE_ENV_NAME_RE = re.compile(
    r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION|CREDENTIAL|COOKIE|SESSION)",
    re.IGNORECASE,
)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{6,}", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)((?:api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token|id[_ -]?token)"
    r"\s*[:=]\s*[\"']?)[^\s\"',}]{4,}"
)
SECRET_ARGUMENT_RE = re.compile(r"(?i)(--api-key(?:=|\s+))\S+")
FENCED_CANDIDATE_RE = re.compile(
    r"\A```(?:lean4?|text)?[ \t]*\r?\n(?P<body>.*)\r?\n```[ \t]*\Z",
    re.IGNORECASE | re.DOTALL,
)


class ProviderSecurityError(RuntimeError):
    """Provider 请求违反认证或传输安全边界。"""


def _known_secret_values() -> list[str]:
    return [
        value
        for name, value in os.environ.items()
        if SENSITIVE_ENV_NAME_RE.search(name) and len(value.strip()) >= 8
    ]


def redact_sensitive_text(text: object, secrets: tuple[str, ...] = ()) -> str:
    """移除异常、日志和元数据中的已知密钥及常见认证字段。"""

    cleaned = str(text)
    values = [*secrets, *_known_secret_values()]
    for secret in sorted({value for value in values if len(value) >= 4}, key=len, reverse=True):
        cleaned = cleaned.replace(secret, "<redacted>")
    cleaned = BEARER_RE.sub("Bearer <redacted>", cleaned)
    cleaned = SECRET_ASSIGNMENT_RE.sub(r"\1<redacted>", cleaned)
    cleaned = SECRET_ARGUMENT_RE.sub(r"\1<redacted>", cleaned)
    return cleaned


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_provider_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderSecurityError("provider URL 必须是有效的 HTTP(S) 地址")
    try:
        parsed.port
    except ValueError as exc:
        raise ProviderSecurityError("provider URL 端口无效") from exc
    if parsed.username or parsed.password:
        raise ProviderSecurityError("provider URL 不能嵌入用户名或密码")
    if parsed.fragment:
        raise ProviderSecurityError("provider URL 不能包含 fragment")
    if any(SENSITIVE_ENV_NAME_RE.search(name) for name, _ in urllib.parse.parse_qsl(parsed.query)):
        raise ProviderSecurityError("provider 密钥不能放在 URL query 中；请使用独立 API key")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ProviderSecurityError("远程 provider 必须使用 HTTPS；HTTP 仅允许 loopback")
    return parsed


def _origin(url: str) -> tuple[str, str, int]:
    parsed = validate_provider_url(url)
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or default_port


def redact_url(url: str) -> str:
    parsed = validate_provider_url(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [
        (name, "<redacted>" if SENSITIVE_ENV_NAME_RE.search(name) else value)
        for name, value in query
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_query), "")
    )


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """仅允许同源重定向，防止 Authorization 被发送给另一个主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urljoin(req.full_url, newurl)
        if _origin(req.full_url) != _origin(target):
            raise ProviderSecurityError("拒绝携带认证信息跨源重定向 provider 请求")
        return super().redirect_request(req, fp, code, msg, headers, target)


def _safe_urlopen(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(SameOriginRedirectHandler())
    return opener.open(request, timeout=timeout)


def _read_limited(response, limit: int) -> bytes:  # noqa: ANN001
    declared = response.headers.get("Content-Length") if getattr(response, "headers", None) else None
    if declared:
        try:
            if int(declared) > limit:
                raise RuntimeError(f"provider 响应超过 {limit} 字节上限")
        except ValueError:
            pass
    data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError(f"provider 响应超过 {limit} 字节上限")
    return data


def _provider_error_detail(raw: bytes, reason: object, api_key: str) -> str:
    """仅提取有界结构化错误消息；非 JSON 正文不进入日志。"""

    detail: object = reason
    try:
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            detail = error["message"]
        elif isinstance(error, str):
            detail = error
        elif isinstance(body.get("message"), str):
            detail = body["message"]
    return redact_sensitive_text(detail, (api_key,))[:700]


def configured_pricing() -> dict[str, float]:
    return {
        "input_price_per_1k": float(os.environ.get("LEAN_PROOF_INPUT_PRICE_PER_1K", "0")),
        "output_price_per_1k": float(os.environ.get("LEAN_PROOF_OUTPUT_PRICE_PER_1K", "0")),
    }


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
            detail = redact_sensitive_text(process.stderr[-1000:])
            raise RuntimeError(f"provider command 失败: {detail}")
        return parse_generation(process.stdout, self.name)

    def metadata(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "command": redact_sensitive_text(self.command),
            "timeout_s": self.timeout,
            **configured_pricing(),
        }


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
    ) -> None:
        parsed = validate_provider_url(url)
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
        validate_provider_url(normalized_url)
        if reasoning_effort is not None and reasoning_effort not in {"minimal", "low", "medium", "high"}:
            raise ValueError("reasoning_effort must be minimal, low, medium, or high")
        self.url = normalized_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.disable_response_storage = bool(disable_response_storage)

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
        return {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def generate(self, prompt: str) -> Generation:
        payload = self._payload(prompt)
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with _safe_urlopen(request, timeout=90) as response:
                body = json.loads(_read_limited(response, MAX_PROVIDER_RESPONSE_BYTES).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read(MAX_PROVIDER_ERROR_BYTES + 1)
            if len(response_body) > MAX_PROVIDER_ERROR_BYTES:
                response_body = response_body[:MAX_PROVIDER_ERROR_BYTES]
            detail = _provider_error_detail(response_body, exc.reason, self.api_key)
            raise RuntimeError(f"HTTP {exc.code} from provider: {detail}") from exc
        generation = parse_generation(json.dumps(body, ensure_ascii=False), self.name)
        if self.api_key and self.api_key in generation.candidate:
            raise ProviderSecurityError("provider 响应包含认证密钥，已拒绝记录候选")
        return generation

    def metadata(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "url": redact_url(self.url),
            "model": self.model,
            "wire_api": self.wire_api,
            "use_responses_api": self.wire_api == "responses",
            "temperature": self.temperature if self.wire_api == "chat_completions" else None,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "disable_response_storage": self.disable_response_storage,
            "store": not self.disable_response_storage,
            "redirect_policy": "same_origin_only",
            "max_response_bytes": MAX_PROVIDER_RESPONSE_BYTES,
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
    """仅移除完整包裹响应的单个 Markdown 围栏，不扫描 Lean 字符串内部。"""
    candidate = text.strip()
    fenced = FENCED_CANDIDATE_RE.fullmatch(candidate)
    return (fenced.group("body") if fenced else candidate).strip()


def parse_generation(text: str, provider_name: str) -> Generation:
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return Generation(clean_candidate(text), {}, provider_name)
    if "candidate" in body:
        return Generation(clean_candidate(str(body["candidate"])), body.get("usage", {}), provider_name, body)
    choices = body.get("choices") or []
    if choices:
        content = choices[0].get("message", {}).get("content", "")
        return Generation(clean_candidate(str(content)), body.get("usage", {}), provider_name, body)
    if "output_text" in body:
        return Generation(clean_candidate(str(body["output_text"])), body.get("usage", {}), provider_name, body)
    output_text = "\n".join(
        str(content.get("text", ""))
        for item in body.get("output", [])
        if isinstance(item, dict) and item.get("type") == "message"
        for content in item.get("content", [])
        if isinstance(content, dict) and content.get("type") == "output_text"
    ).strip()
    if output_text:
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
        )
    if name == "mock":
        if mock_candidate is None:
            raise ValueError("mock provider 需要 --mock-candidate，仅用于测试")
        return MockProvider(mock_candidate)
    raise ValueError(f"未知 provider: {name}")
