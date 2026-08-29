import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from provider import CommandProvider, OpenAICompatibleProvider, SameOriginRedirectHandler, clean_candidate, parse_generation


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class ProviderTest(unittest.TestCase):
    def test_command_json_shape(self):
        result = parse_generation('{"candidate":"by rfl","usage":{"total_tokens":4}}', "command")
        self.assertEqual(result.candidate, "by rfl")
        self.assertEqual(result.usage["total_tokens"], 4)

    def test_openai_chat_shape(self):
        result = parse_generation('{"choices":[{"message":{"content":"by rfl"}}]}', "openai_compatible")
        self.assertEqual(result.candidate, "by rfl")

    def test_openai_responses_shape(self):
        result = parse_generation(
            json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "by\n  rfl"}],
                        }
                    ],
                    "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
                }
            ),
            "openai_compatible",
        )
        self.assertEqual(result.candidate, "by\n  rfl")
        self.assertEqual(result.usage["total_tokens"], 16)

    def test_responses_request_uses_yxai_contract_without_storing(self):
        provider = OpenAICompatibleProvider(
            "https://yxai.chat/v1",
            "secret",
            "gpt-5.6-sol",
            0.0,
            800,
            wire_api="responses",
            reasoning_effort="high",
            disable_response_storage=True,
        )
        body = json.dumps(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "by rfl"}],
                    }
                ]
            }
        ).encode()
        opener = MagicMock()
        opener.open.return_value = FakeResponse(body)
        with patch("urllib.request.build_opener", return_value=opener):
            generation = provider.generate("demo prompt")

        request = opener.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://yxai.chat/v1/responses")
        self.assertEqual(payload["model"], "gpt-5.6-sol")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertFalse(payload["store"])
        self.assertEqual(payload["max_output_tokens"], 800)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("messages", payload)
        self.assertEqual(generation.candidate, "by rfl")
        self.assertNotIn("secret", str(provider.metadata()))
        self.assertEqual(provider.metadata()["wire_api"], "responses")
        self.assertTrue(provider.metadata()["use_responses_api"])
        self.assertFalse(provider.metadata()["store"])

    def test_markdown_lean_fence_is_removed(self):
        self.assertEqual(clean_candidate("```lean\nby\n  rfl\n```"), "by\n  rfl")

    def test_http_error_keeps_provider_response_body(self):
        provider = OpenAICompatibleProvider("https://example.test", "secret", "demo", 0.0, 800)
        error = urllib.error.HTTPError(
            provider.url,
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error":{"message":"invalid model"}}'),
        )
        opener = MagicMock()
        opener.open.side_effect = error
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "invalid model"):
                provider.generate("demo prompt")

    def test_cross_origin_redirect_is_rejected(self):
        handler = SameOriginRedirectHandler()
        request = urllib.request.Request("https://provider.example/v1/chat/completions")
        with self.assertRaisesRegex(RuntimeError, "跨来源"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://collector.example/steal")

    def test_transient_network_error_is_retried(self):
        provider = OpenAICompatibleProvider("https://example.test", "secret", "demo", 0.0, 800)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"by rfl"}}]}'

        opener = MagicMock()
        opener.open.side_effect = [urllib.error.URLError("temporary"), Response()]
        with patch("urllib.request.build_opener", return_value=opener):
            result = provider.generate("demo prompt")
        self.assertEqual(result.candidate, "by rfl")
        self.assertEqual(opener.open.call_count, 2)

    def test_provider_metadata_separates_model_configuration(self):
        left = OpenAICompatibleProvider("https://example.test", "secret", "model-a", 0.0, 800)
        right = OpenAICompatibleProvider("https://example.test", "secret", "model-b", 0.0, 800)
        self.assertNotEqual(left.metadata(), right.metadata())

    def test_command_metadata_contains_command_configuration(self):
        provider = CommandProvider("python provider.py", timeout=12)
        self.assertEqual(provider.metadata()["command"], "python provider.py")
        self.assertEqual(provider.metadata()["timeout_s"], 12)
