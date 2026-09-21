"""从正式六臂发布包生成 README 使用的确定性 SVG 图表。"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "published" / "research-six-arm-313f437f" / "summary.json"
OUTPUT = ROOT / "docs" / "assets" / "repair24-six-arm-results.svg"
ARMS = ("A", "B", "C", "D", "C_dynamic", "C_failure")
DISPLAY = {
    "A": "R-A",
    "B": "R-B",
    "C": "R-C",
    "D": "R-D",
    "C_dynamic": "R-E",
    "C_failure": "R-F",
}
MODELS = (
    ("deepseek_flash_v41", "DeepSeek Flash v4.1", "#2563eb", "#bfdbfe"),
    ("deepseek_v4_pro_0813", "DeepSeek Pro 0813", "#c2410c", "#fed7aa"),
)


def text(x: float, y: float, value: str, css: str, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css}" '
        f'text-anchor="{anchor}">{escape(value)}</text>'
    )


def render_panel(
    x0: float, model_id: str, title: str, dark: str, light: str, rows: list[dict]
) -> list[str]:
    top, bottom, width = 166.0, 556.0, 510.0
    y_min, y_max = 70.0, 100.0

    def y(value: float) -> float:
        return bottom - (value - y_min) / (y_max - y_min) * (bottom - top)

    svg = [
        f'<rect x="{x0:.1f}" y="122" width="{width:.1f}" height="480" rx="12" class="panel"/>',
        text(x0 + 22, 151, title, "panel-title", "start"),
    ]
    for tick in (70, 80, 90, 100):
        yy = y(float(tick))
        svg.append(f'<line x1="{x0 + 48:.1f}" y1="{yy:.1f}" x2="{x0 + width - 20:.1f}" y2="{yy:.1f}" class="grid"/>')
        svg.append(text(x0 + 39, yy + 4, f"{tick}%", "axis", "end"))

    group_width = 70.0
    start_x = x0 + 75.0
    for index, row in enumerate(rows):
        center = start_x + index * group_width
        first = 100.0 * row["first"] / row["tasks"]
        final = 100.0 * row["success"] / row["tasks"]
        for bx, value, color, stage in (
            (center - 24, first, light, "first"),
            (center + 2, final, dark, "within_3"),
        ):
            yy = y(value)
            height = bottom - yy
            svg.append(
                f'<rect x="{bx:.1f}" y="{yy:.1f}" width="22" height="{height:.1f}" '
                f'rx="3" fill="{color}" data-model="{escape(model_id)}" '
                f'data-arm="{escape(row["arm"])}" data-stage="{stage}" data-value="{value:.6f}"/>'
            )
        svg.append(text(center, 581, DISPLAY[row["arm"]], "arm"))
        svg.append(text(center + 13, y(final) - 8, f"{final:.1f}%", "value"))
        svg.append(text(center, 622, f"+{final - first:.1f} pp", "delta"))

    baseline = next(row for row in rows if row["arm"] == "A")
    baseline_rate = 100.0 * baseline["success"] / baseline["tasks"]
    baseline_y = y(baseline_rate)
    svg.append(
        f'<line x1="{x0 + 48:.1f}" y1="{baseline_y:.1f}" x2="{x0 + width - 20:.1f}" '
        f'y2="{baseline_y:.1f}" class="baseline"/>'
    )
    svg.append(text(x0 + width - 24, baseline_y - 6, "R-A final baseline", "baseline-label", "end"))
    return svg


def main() -> int:
    payload = json.loads(SUMMARY.read_text(encoding="utf-8"))
    rows = payload.get("summary", [])
    indexed = {(row.get("model"), row.get("arm")): row for row in rows}
    if len(rows) != 12 or set(indexed) != {(model, arm) for model, *_ in MODELS for arm in ARMS}:
        raise ValueError("正式六臂 summary.json 不符合 2 模型 × 6 臂合同")
    if any(row.get("tasks") != 72 for row in rows):
        raise ValueError("每个模型与研究臂必须恰好包含 72 个任务")

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="700" viewBox="0 0 1280 700" role="img" aria-labelledby="title desc">',
        '<title id="title">repair24 first-candidate and three-round success rates</title>',
        '<desc id="desc">Two panels compare first-candidate success with success within three rounds for six TRACER research arms and two DeepSeek model configurations.</desc>',
        """<style>
        .background { fill: #ffffff; }
        .panel { fill: #f8fafc; stroke: #cbd5e1; stroke-width: 1; }
        .title { font: 700 26px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #0f172a; }
        .subtitle { font: 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #475569; }
        .panel-title { font: 700 17px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #0f172a; }
        .axis { font: 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #64748b; }
        .arm { font: 700 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #334155; }
        .value { font: 700 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #0f172a; }
        .delta { font: 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #475569; }
        .legend { font: 13px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #334155; }
        .note { font: 12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #64748b; }
        .grid { stroke: #e2e8f0; stroke-width: 1; }
        .baseline { stroke: #64748b; stroke-width: 1.2; stroke-dasharray: 5 4; }
        .baseline-label { font: 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #475569; }
        </style>""",
        '<rect width="1280" height="700" class="background"/>',
        text(52, 43, "repair24: first candidate vs. up to three repair rounds", "title", "start"),
        text(52, 70, "24 problems × 3 repeats per model and arm; bars are descriptive paired outcomes", "subtitle", "start"),
        '<rect x="860" y="34" width="16" height="16" rx="2" fill="#dbeafe"/>',
        text(884, 47, "First candidate", "legend", "start"),
        '<rect x="1001" y="34" width="16" height="16" rx="2" fill="#1d4ed8"/>',
        text(1025, 47, "Within 3 rounds", "legend", "start"),
    ]
    for panel_x, (model, title, dark, light) in zip((52.0, 688.0), MODELS):
        svg.extend(
            render_panel(panel_x, model, title, dark, light, [indexed[(model, arm)] for arm in ARMS])
        )
    svg.extend([
        text(52, 666, "Delta labels show within-task improvement from the first candidate to the final three-round outcome.", "note", "start"),
        text(52, 684, "R-A is the no-feedback/no-retrieval baseline. Differences between arms are not causal or significance estimates.", "note", "start"),
        "</svg>",
    ])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(svg) + "\n", encoding="utf-8", newline="\n")
    print(OUTPUT.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
