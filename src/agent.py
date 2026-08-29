"""求解 CLI 与 A/B/C/D 证明修复循环，支持独立的动态检索消融。"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from cache import RequestCache
from compiler import CANDIDATE_POLICY, candidate_safety_violation, compile_candidate, declaration_scope, diagnostics_use_sorry
from diagnostics import normalize_diagnostics
from provider import Generation, build_provider, clean_candidate, generation_finish_reason, redact_sensitive_text
from proof_protocol import PROOF_PROTOCOL
from retriever import diagnostic_query, find_retrieval_leaks, load_examples, retrieve


ROOT = Path(__file__).resolve().parents[1]
PROMPT_TEMPLATES = {
    "A": "theorem_only.txt",
    "B": "feedback.txt",
    "C": "feedback_retrieval.txt",
    "D": "retrieval_only.txt",
}
FORBIDDEN_PROOF_RE = re.compile(r"\b(?:sorryAx|sorry|admit)\b")


def theorem_scope(source: str, theorem_name: str) -> str:
    start, end = declaration_scope(source, theorem_name)
    return source[start:end].strip()


def prompt_for(
    source: str,
    theorem_name: str,
    condition: str,
    feedback: dict,
    examples: list[dict],
    include_context: bool = False,
    start_marker: str = "-- PROOF_START",
    end_marker: str = "-- PROOF_END",
    prompt_templates: dict[str, str] | None = None,
) -> str:
    scope = theorem_scope(source, theorem_name)
    if include_context:
        start, _ = declaration_scope(source, theorem_name)
        scope = source[:start] + "\n" + scope
    template_name = PROMPT_TEMPLATES.get(condition)
    if template_name is None:
        raise ValueError("condition 必须是 A、B、C 或 D")
    template_path = ROOT / "prompts" / template_name
    template = prompt_templates[template_name] if prompt_templates is not None else template_path.read_text(encoding="utf-8")
    contract = (prompt_templates["proof_contract.txt"] if prompt_templates is not None
                else (ROOT / "prompts" / "proof_contract.txt").read_text(encoding="utf-8"))
    return template.format(
        problem_title=scope[:12000],
        theorem=scope[:12000],
        feedback=feedback.get("feedback", "暂无编译反馈。"),
        examples=json.dumps(examples, ensure_ascii=False)[:8000],
    ) + "\n" + contract.format(start_marker=start_marker, end_marker=end_marker)


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def public_source_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def canonical_request(prompt: str, condition: str, provider_metadata: dict[str, object], round_no: int = 1) -> str:
    return json.dumps(
        {"prompt": prompt, "condition": condition, "round": round_no, "provider": provider_metadata,
         "proof_protocol": PROOF_PROTOCOL},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def estimate_cost(usage: dict[str, int], provider_metadata: dict[str, object]) -> float | None:
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    input_price = provider_metadata.get("input_price_per_1k")
    output_price = provider_metadata.get("output_price_per_1k")
    if not isinstance(input_tokens, (int, float)) or not isinstance(output_tokens, (int, float)):
        return None
    if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
        return None
    if min(input_tokens, output_tokens, input_price, output_price) < 0:
        return None
    return round(input_tokens / 1000 * input_price + output_tokens / 1000 * output_price, 8)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def solve_problem(
    source_path: Path,
    theorem_name: str,
    condition: str,
    provider,
    max_rounds: int,
    timeout: float,
    examples_dir: Path,
    cache_path: Path,
    output_dir: Path,
    log_path: Path,
    start_marker: str = "-- PROOF_START",
    end_marker: str = "-- PROOF_END",
    placeholder: str = "sorry",
    benchmark_id: str | None = None,
    tags: list[str] | None = None,
    difficulty: str | None = None,
    experiment_id: str | None = None,
    retrieval_strategy: str = "static",
    use_cache: bool = True,
    record_prompt: bool = False,
    initial_feedback: dict | None = None,
    initial_diagnostics: str = "",
    failure_notes: dict[str, str] | None = None,
    prompt_templates: dict[str, str] | None = None,
) -> dict:
    if condition not in {"A", "B", "C", "D"}:
        raise ValueError("condition 必须是 A、B、C 或 D")
    if retrieval_strategy not in {"static", "diagnostic"}:
        raise ValueError("未知检索策略")
    if retrieval_strategy == "diagnostic" and condition != "C":
        raise ValueError("错误驱动检索仅用于 C 的独立消融；D 不得读取诊断")
    if not 1 <= max_rounds <= 3:
        raise ValueError("max_rounds 必须在 1 到 3 之间")
    source = source_path.read_text(encoding="utf-8")
    examples = load_examples(examples_dir) if condition in {"C", "D"} else []
    if condition in {"C", "D"}:
        leaks = find_retrieval_leaks([(theorem_name, theorem_scope(source, theorem_name))], examples)
        if leaks:
            raise ValueError("检索语料与目标定理声明重合")
    feedback: dict = initial_feedback if condition in {"B", "C"} and initial_feedback else {"category": "no_feedback", "feedback": "暂无编译反馈。"}
    previous_diagnostics = initial_diagnostics if condition in {"B", "C"} else ""
    run_id = str(uuid.uuid4())
    provider_metadata = provider.metadata() if hasattr(provider, "metadata") else {"provider": provider.name}
    problem_id = benchmark_id or safe_name(source_path.stem + "__" + theorem_name)
    last_candidate = ""
    final_result: dict | None = None
    used_requests: set[str] = set()

    with (RequestCache(cache_path) if use_cache else nullcontext(None)) as cache:
        for round_no in range(1, max_rounds + 1):
            retrieved = []
            compiled = None
            query, focus = "", ""
            if condition in {"C", "D"}:
                target = theorem_name + " " + theorem_scope(source, theorem_name)
                query = target
                if retrieval_strategy == "diagnostic":
                    query, focus = diagnostic_query(target, feedback, previous_diagnostics)
                retrieved = retrieve(query, examples, top_k=3, target=target, focus=focus)
                for example in retrieved:
                    if failure_notes and example["path"] in failure_notes:
                        example["failure_context"] = failure_notes[example["path"]][:1600]
            if record_prompt and condition in {"B", "C"}:
                details = feedback.get("feedback", "")
                if previous_diagnostics:
                    from leancapsule.privacy import redact_text
                    details += "\n诊断与目标详情：\n" + redact_text(redact_sensitive_text(previous_diagnostics))[:2400]
                if last_candidate:
                    details += "\n上一轮候选：\n" + last_candidate[:6000]
                feedback = dict(feedback, feedback=details)
            prompt = prompt_for(source, theorem_name, condition, feedback, retrieved, include_context=record_prompt,
                                start_marker=start_marker, end_marker=end_marker, prompt_templates=prompt_templates)
            request_text = canonical_request(prompt, condition, provider_metadata, round_no)
            generation: Generation | None = None if not use_cache or request_text in used_requests else cache.get(request_text)
            used_requests.add(request_text)
            cache_hit = generation is not None
            provider_error = None
            generation_started = time.perf_counter()
            if generation is None:
                try:
                    generation = provider.generate(prompt)
                    if use_cache:
                        cache.put(request_text, generation)
                except Exception as exc:
                    provider_error = redact_sensitive_text(exc)
                    generation = Generation("", {}, provider.name, {"error": provider_error})
            generation_ms = round((time.perf_counter() - generation_started) * 1000, 1)
            # 也清洗缓存中的旧候选，避免历史 Markdown 围栏继续导致语法错误。
            usage = generation.usage if isinstance(generation.usage, dict) else {}
            candidate = clean_candidate(generation.candidate)
            finish_reason = generation_finish_reason(generation.raw)
            generation_status = {"length": "truncated", "stop": "complete", "incomplete": "incomplete"}.get(finish_reason, "unknown")
            candidate_contains_secret = redact_sensitive_text(candidate) != candidate
            if candidate_contains_secret:
                candidate = "<redacted-sensitive-candidate>"
            last_candidate = candidate
            if provider_error:
                diagnostic = {"category": "provider_error", "summary": provider_error[:700], "feedback": "模型 provider 调用失败，请检查 provider 配置或服务状态。", "errors": [], "truncated": len(provider_error) > 700}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = provider_error
            elif candidate_contains_secret:
                diagnostic = {"category": "sensitive_candidate", "summary": "候选疑似包含认证信息，已拒绝记录和编译", "feedback": "不要在候选中返回 API key、token 或 Authorization 内容。", "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = diagnostic["summary"]
            elif generation_status == "truncated":
                diagnostic = {"category": "generation_truncated", "summary": "模型达到输出额度，未正常完成最终证明。",
                    "feedback": "上一轮生成被输出额度截断。请在相同预算内返回简短、完整的证明项，不要只补旧证明的尾部。",
                    "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = diagnostic["summary"]
            elif generation_status == "incomplete":
                diagnostic = {"category": "generation_incomplete", "summary": "模型响应未完成，拒绝编译部分内容。",
                    "feedback": "请返回正常完成的完整证明项。", "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = diagnostic["summary"]
            elif not candidate or start_marker in candidate or end_marker in candidate:
                diagnostic = {"category": "invalid_candidate", "summary": "候选为空或包含禁止标记", "feedback": "请只输出局部 Lean proof term。", "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = diagnostic["summary"]
            elif safety_violation := candidate_safety_violation(candidate):
                diagnostic = {"category": "unsafe_candidate", "summary": safety_violation, "feedback": "只允许局部证明项；不能使用 unsafe 声明、元编程入口或注入额外命令。", "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = safety_violation
            elif FORBIDDEN_PROOF_RE.search(candidate):
                diagnostic = {"category": "placeholder_candidate", "summary": "候选包含占位证明", "feedback": "不能使用 sorry、sorryAx 或 admit，请给出完整证明。", "errors": [], "truncated": False}
                compile_ok = False
                compile_ms = 0.0
                raw_diagnostics = diagnostic["summary"]
            else:
                try:
                    compiled = compile_candidate(source_path, source, candidate, theorem_name, start_marker, end_marker, timeout, placeholder)
                    compile_ms = compiled.elapsed_ms
                    raw_diagnostics = compiled.diagnostics
                    if compiled.ok and diagnostics_use_sorry(raw_diagnostics):
                        compile_ok = False
                        diagnostic = {"category": "incomplete_proof", "summary": "目标证明依赖未完成证明公理", "feedback": "不得使用未完成证明公理，请生成可由内核独立检查的证明。", "errors": [], "truncated": False}
                    else:
                        compile_ok = compiled.ok
                        diagnostic = normalize_diagnostics(raw_diagnostics, returncode=compiled.returncode, timed_out=compiled.timed_out)
                except Exception as exc:
                    security_rejection = "禁止的本机执行构造" in str(exc)
                    diagnostic = {
                        "category": "candidate_security" if security_rejection else "patch_error",
                        "summary": str(exc)[:700],
                        "feedback": "候选触发本机执行安全策略，请只使用纯证明项和受信任 tactic。" if security_rejection else "无法定位或补丁化目标证明区域，请检查定理名和占位符。",
                        "errors": [],
                        "truncated": len(str(exc)) > 700,
                    }
                    compile_ok = False
                    compile_ms = 0.0
                    raw_diagnostics = str(exc)
            record = {
                "run_id": run_id,
                "experiment_id": experiment_id,
                "problem_id": problem_id,
                "benchmark_id": benchmark_id,
                "tags": tags or [],
                "difficulty": difficulty,
                "source_file": public_source_path(source_path),
                "theorem": theorem_name,
                "condition": condition,
                "round": round_no,
                "candidate": candidate,
                "provider": generation.provider,
                "provider_config": provider_metadata,
                "provider_response": {"model": generation.raw.get("model"),
                    "id": generation.raw.get("id"),
                    "finish_reason": finish_reason},
                "generation_status": generation_status,
                "proof_protocol": dict(PROOF_PROTOCOL),
                "provider_error": provider_error,
                "usage": usage,
                "estimated_cost_usd": estimate_cost(usage, provider_metadata),
                "cache_hit": cache_hit,
                "retrieved_examples": retrieved,
                "retrieval_query": query,
                "retrieval_strategy": retrieval_strategy,
                "generation_elapsed_ms": generation_ms,
                "prompt_chars": len(prompt),
                "compile_ok": compile_ok,
                "kernel_pass": bool(compile_ok) if compiled is not None else None,
                "compile_has_warnings": bool(diagnostic.get("warning_count")) if compiled is not None else None,
                "warning_free": bool(compile_ok and not diagnostic.get("warning_count")) if compiled is not None else None,
                "compile_elapsed_ms": compile_ms,
                "compile_invoked": compiled is not None,
                "compile_returncode": compiled.returncode if compiled is not None else None,
                "compile_timed_out": compiled.timed_out if compiled is not None else False,
                "diagnostic": diagnostic,
                "raw_diagnostics": raw_diagnostics[:4000],
                "compiler_command": compiled.compiler_command if compiled is not None else None,
                "candidate_policy": dict(CANDIDATE_POLICY),
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            if record_prompt:
                record["prompt"] = redact_sensitive_text(prompt)
                from leancapsule.privacy import redact_value
                record = redact_value(record, (ROOT,))
            append_jsonl(log_path, record)
            final_result = record
            if provider_error:
                break
            if compile_ok:
                output_path = output_dir / condition / f"{safe_name(source_path.stem)}__{safe_name(theorem_name)}.lean"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(compiled.isolated_source, encoding="utf-8")
                if FORBIDDEN_PROOF_RE.search(compiled.isolated_source):
                    raise RuntimeError("编译成功文件仍包含占位证明")
                break
            feedback = diagnostic
            previous_diagnostics = raw_diagnostics

    if final_result is None:
        raise RuntimeError("没有产生任何尝试")
    if not final_result["compile_ok"]:
        failure_path = output_dir / "failures" / f"{condition}__{safe_name(problem_id)}.txt"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(last_candidate, encoding="utf-8")
    return final_result


def main() -> int:
    parser = argparse.ArgumentParser(description="TRACER proof-repair agent")
    sub = parser.add_subparsers(dest="command", required=True)
    solve = sub.add_parser("solve")
    solve.add_argument("--file", type=Path, required=True)
    solve.add_argument("--theorem", required=True)
    solve.add_argument("--condition", choices=["A", "B", "C", "D"], default="B")
    solve.add_argument("--retrieval-strategy", choices=["static", "diagnostic"], default="static")
    solve.add_argument("--max-rounds", type=int, default=3)
    solve.add_argument("--timeout", type=float, default=20.0)
    solve.add_argument("--provider", choices=["command", "openai_compatible", "mock"], required=True)
    solve.add_argument("--provider-command")
    solve.add_argument("--mock-candidate")
    solve.add_argument("--api-url", help="本次运行使用的 OpenAI 兼容接口地址")
    solve.add_argument("--model", help="本次运行使用的模型名称")
    solve.add_argument("--api-key-prompt", action="store_true", help="在终端安全地输入 API 密钥，不回显且不写入日志")
    solve.add_argument("--api-key-stdin", action="store_true", help="从标准输入读取 API 密钥，不写入日志")
    solve.add_argument("--temperature", type=float)
    solve.add_argument("--max-tokens", type=int)
    solve.add_argument("--wire-api", choices=["chat_completions", "responses"])
    solve.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"])
    solve.add_argument("--disable-response-storage", action="store_true", default=None)
    solve.add_argument("--examples-dir", type=Path, default=ROOT / "examples")
    solve.add_argument("--cache", type=Path, default=ROOT / "results" / "requests.sqlite3")
    solve.add_argument("--output-dir", type=Path, default=ROOT / "results" / "solutions")
    solve.add_argument("--log", type=Path, default=ROOT / "results" / "agent_runs.jsonl")
    solve.add_argument("--start-marker", default="-- PROOF_START")
    solve.add_argument("--end-marker", default="-- PROOF_END")
    solve.add_argument("--placeholder", default="sorry")
    args = parser.parse_args()
    if args.command == "solve":
        api_key = None
        if args.api_key_prompt:
            api_key = getpass.getpass("API key（不会回显）：").strip()
            suffix = api_key[-4:] if len(api_key) >= 4 else "不足四位"
            print(f"已读取 API key：长度={len(api_key)}，末四位={suffix}", file=sys.stderr)
        elif args.api_key_stdin:
            api_key = sys.stdin.read().strip()
        provider = build_provider(
            args.provider,
            args.provider_command,
            args.mock_candidate,
            api_url=args.api_url,
            api_key=api_key,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            wire_api=args.wire_api,
            reasoning_effort=args.reasoning_effort,
            disable_response_storage=args.disable_response_storage,
        )
        result = solve_problem(args.file.resolve(), args.theorem, args.condition, provider, args.max_rounds, args.timeout, args.examples_dir.resolve(), args.cache.resolve(), args.output_dir.resolve(), args.log.resolve(), args.start_marker, args.end_marker, args.placeholder, retrieval_strategy=args.retrieval_strategy)
        response = {
            "compile_ok": result["compile_ok"],
            "round": result["round"],
            "condition": result["condition"],
            "provider": result["provider"],
        }
        if not result["compile_ok"]:
            response["diagnostic"] = result.get("diagnostic", {})
            if result.get("provider_error"):
                response["provider_error"] = result["provider_error"]
        print(json.dumps(response, ensure_ascii=False))
        return 0 if result["compile_ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
