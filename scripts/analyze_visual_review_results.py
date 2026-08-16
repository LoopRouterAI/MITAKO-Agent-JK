# -*- coding: utf-8 -*-
"""对已经完成推理的视觉审核结果做离线统计，不参与审核任务运行。"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


LABELS = ("positive", "negative", "review")
PUBLIC_LABELS = {"positive": "支持诉求", "negative": "不支持诉求", "review": "需人工复核"}
FIELD_ALIASES = {
    "human": ("human_label", "manual_label", "final_label", "人工结论", "最终人工结论", "结论"),
    "predicted": ("predicted_label", "model_label", "review_label", "辅助结论", "系统结论", "预测结论"),
    "confidence": ("confidence", "model_confidence", "置信度", "系统置信度"),
    "scenario": ("scenario", "task", "业务场景", "审核场景", "场景"),
    "status": ("status", "job_status", "任务状态", "审核状态"),
}


def _value(row: Dict[str, Any], aliases: Sequence[str]) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
        value = lowered.get(alias.lower())
        if value not in (None, ""):
            return value
    return ""


def normalize_label(value: Any) -> str:
    compact = str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    if compact in {"positive", "pass", "passed", "support", "supported", "yes", "true", "正向", "通过", "支持", "成立", "认可"}:
        return "positive"
    if compact in {"negative", "fail", "failed", "reject", "rejected", "no", "false", "负向", "不通过", "不支持", "拒绝", "不成立"}:
        return "negative"
    if compact in {"review", "manualreview", "uncertain", "pending", "需复核", "人工复核", "待复核", "不确定", "存疑"}:
        return "review"
    return ""


def _confidence(value: Any) -> Optional[float]:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number > 1 and number <= 100:
        number /= 100
    if not math.isfinite(number) or number < 0 or number > 1:
        return None
    return number


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 6) if denominator else None


def _wilson(successes: int, total: int, z: float = 1.96) -> List[Optional[float]]:
    if total <= 0:
        return [None, None]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def load_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            payload = payload.get("rows") or payload.get("samples") or payload.get("results") or []
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ValueError("JSON 必须是对象数组，或包含 rows/samples/results 数组")
        return list(payload)
    raise ValueError("仅支持 CSV 或 JSON 结果文件")


def _calibration(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = [pair for pair in pairs if pair["confidence"] is not None]
    bins: List[Dict[str, Any]] = []
    ece = 0.0
    for index in range(5):
        low, high = index / 5, (index + 1) / 5
        bucket = [
            pair for pair in available
            if low <= pair["confidence"] <= high if index == 4
        ] if index == 4 else [pair for pair in available if low <= pair["confidence"] < high]
        if not bucket:
            bins.append({"range": [low, high], "count": 0, "average_confidence": None, "accuracy": None})
            continue
        average = sum(pair["confidence"] for pair in bucket) / len(bucket)
        accuracy = sum(pair["human"] == pair["predicted"] for pair in bucket) / len(bucket)
        ece += len(bucket) / len(available) * abs(average - accuracy)
        bins.append({
            "range": [low, high],
            "count": len(bucket),
            "average_confidence": round(average, 6),
            "accuracy": round(accuracy, 6),
        })
    brier = None
    if available:
        brier = round(sum(
            (pair["confidence"] - (1.0 if pair["human"] == pair["predicted"] else 0.0)) ** 2
            for pair in available
        ) / len(available), 6)
    return {
        "samples": len(available),
        "coverage": _rate(len(available), len(pairs)),
        "ece_5_bins": round(ece, 6) if available else None,
        "brier_correctness": brier,
        "bins": bins,
        "interpretation": "置信度校准只评估系统自报置信度与标签一致性的对应关系，不证明标签本身正确。",
    }


def analyze_rows(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    raw_rows = list(rows)
    pairs: List[Dict[str, Any]] = []
    invalid = 0
    status_counts: Dict[str, int] = {}
    scenario_counts: Dict[str, int] = {}
    for index, row in enumerate(raw_rows, start=1):
        human = normalize_label(_value(row, FIELD_ALIASES["human"]))
        predicted = normalize_label(_value(row, FIELD_ALIASES["predicted"]))
        status = str(_value(row, FIELD_ALIASES["status"]) or "未提供").strip()
        scenario = str(_value(row, FIELD_ALIASES["scenario"]) or "未提供").strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
        if human not in LABELS or predicted not in LABELS:
            invalid += 1
            continue
        pairs.append({
            "row": index,
            "human": human,
            "predicted": predicted,
            "confidence": _confidence(_value(row, FIELD_ALIASES["confidence"])),
            "scenario": scenario,
        })

    confusion = {human: {predicted: 0 for predicted in LABELS} for human in LABELS}
    for pair in pairs:
        confusion[pair["human"]][pair["predicted"]] += 1

    per_class: Dict[str, Any] = {}
    for label in LABELS:
        true_positive = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_total = sum(confusion[human][label] for human in LABELS)
        precision = _rate(true_positive, predicted_total)
        recall = _rate(true_positive, support)
        f1 = None
        if precision is not None and recall is not None:
            f1 = round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0
        per_class[label] = {
            "label": PUBLIC_LABELS[label],
            "support": support,
            "predicted": predicted_total,
            "precision": precision,
            "recall": recall,
            "recall_ci95": _wilson(true_positive, support),
            "f1": f1,
        }

    correct = sum(confusion[label][label] for label in LABELS)
    decisive_truth = [pair for pair in pairs if pair["human"] in {"positive", "negative"}]
    decisive_predictions = [pair for pair in decisive_truth if pair["predicted"] in {"positive", "negative"}]
    decisive_correct = sum(pair["human"] == pair["predicted"] for pair in decisive_predictions)
    negative_rows = [pair for pair in pairs if pair["human"] == "negative"]
    positive_rows = [pair for pair in pairs if pair["human"] == "positive"]
    f1_values = [item["f1"] for item in per_class.values() if item["f1"] is not None]

    return {
        "protocol": "offline_post_inference_evaluation_v1",
        "boundary": "本工具仅在推理完成后分析结果；不参与审核任务、不向模型传递人工标签，也不要求双人标注或仲裁字段。",
        "label_assumption": "指标以输入文件中的人工标签为外部前提；标签语义和质量需由双方在评测流程中另行确认。",
        "input": {
            "rows": len(raw_rows),
            "evaluable": len(pairs),
            "unmapped_or_incomplete": invalid,
            "status_counts": status_counts,
            "scenario_counts": scenario_counts,
        },
        "metrics": {
            "exact_agreement": _rate(correct, len(pairs)),
            "exact_agreement_ci95": _wilson(correct, len(pairs)),
            "correct": correct,
            "macro_f1": round(sum(f1_values) / len(f1_values), 6) if f1_values else None,
            "review_route_rate": _rate(sum(pair["predicted"] == "review" for pair in pairs), len(pairs)),
            "decisive_coverage": _rate(len(decisive_predictions), len(decisive_truth)),
            "decisive_accuracy": _rate(decisive_correct, len(decisive_predictions)),
            "negative_to_positive_risk": _rate(sum(pair["predicted"] == "positive" for pair in negative_rows), len(negative_rows)),
            "negative_safe_route": _rate(sum(pair["predicted"] in {"negative", "review"} for pair in negative_rows), len(negative_rows)),
            "positive_to_negative_risk": _rate(sum(pair["predicted"] == "negative" for pair in positive_rows), len(positive_rows)),
        },
        "confusion_matrix": confusion,
        "per_class": per_class,
        "calibration": _calibration(pairs),
    }


def _percent(value: Any) -> str:
    return "-" if value is None else f"{float(value) * 100:.2f}%"


def render_html(report: Dict[str, Any], title: str) -> str:
    esc = lambda value: html.escape(str(value if value is not None else ""))
    metrics = report["metrics"]
    confusion = report["confusion_matrix"]
    class_rows = "".join(
        f"<tr><th>{esc(item['label'])}</th><td>{item['support']}</td><td>{_percent(item['precision'])}</td>"
        f"<td>{_percent(item['recall'])}</td><td>{_percent(item['f1'])}</td></tr>"
        for item in report["per_class"].values()
    )
    matrix_rows = "".join(
        f"<tr><th>{esc(PUBLIC_LABELS[human])}</th>" + "".join(f"<td>{confusion[human][predicted]}</td>" for predicted in LABELS) + "</tr>"
        for human in LABELS
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>
body{{margin:0;background:#f4f6f7;color:#17201e;font-family:Inter,"Microsoft YaHei",Arial,sans-serif}}main{{max-width:1120px;margin:auto;padding:32px 18px 56px}}header{{border-top:6px solid #75a43a;padding:28px 0 20px}}h1{{font-size:30px;margin:0 0 10px}}h2{{font-size:20px;margin:0 0 14px}}p,li{{line-height:1.75}}section{{padding:22px 0;border-top:1px solid #d9dfdd}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}.metric{{background:#fff;border:1px solid #d9dfdd;border-radius:6px;padding:14px}}.metric small{{display:block;color:#66716e;margin-bottom:7px}}.metric strong{{font-size:24px}}table{{width:100%;border-collapse:collapse;background:#fff}}th,td{{border:1px solid #d9dfdd;padding:10px;text-align:center}}th{{background:#eef3ed}}.note{{border-left:4px solid #d5a928;background:#fff9e8;padding:12px 15px}}code{{word-break:break-all}}@media(max-width:640px){{h1{{font-size:24px}}main{{padding:20px 12px 40px}}.table-wrap{{overflow-x:auto}}}}
</style></head><body><main><header><p>视觉审核 · 推理后离线评测</p><h1>{esc(title)}</h1><p>{esc(report['boundary'])}</p></header>
<section><h2>核心指标</h2><div class="metrics">
<div class="metric"><small>可比样本</small><strong>{report['input']['evaluable']}</strong></div>
<div class="metric"><small>三分类一致率</small><strong>{_percent(metrics['exact_agreement'])}</strong></div>
<div class="metric"><small>需人工复核率</small><strong>{_percent(metrics['review_route_rate'])}</strong></div>
<div class="metric"><small>自动判定覆盖率</small><strong>{_percent(metrics['decisive_coverage'])}</strong></div>
<div class="metric"><small>负向误接纳风险</small><strong>{_percent(metrics['negative_to_positive_risk'])}</strong></div>
<div class="metric"><small>负向安全路由</small><strong>{_percent(metrics['negative_safe_route'])}</strong></div>
</div></section>
<section><h2>混淆矩阵</h2><div class="table-wrap"><table><thead><tr><th>人工 \ 系统</th>{''.join(f'<th>{esc(PUBLIC_LABELS[label])}</th>' for label in LABELS)}</tr></thead><tbody>{matrix_rows}</tbody></table></div></section>
<section><h2>分类型指标</h2><div class="table-wrap"><table><thead><tr><th>人工标签</th><th>样本数</th><th>精确率</th><th>召回率</th><th>F1</th></tr></thead><tbody>{class_rows}</tbody></table></div></section>
<section><h2>解释边界</h2><p class="note">{esc(report['label_assumption'])}</p><p>`review` 是人工复核路由，不等同于自动通过或自动拒绝；工程成功率、413/415、延迟与成本应另行统计，不能混入模型准确率分母。</p></section>
</main></body></html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="视觉审核结果离线评测")
    parser.add_argument("--input", required=True, help="推理完成后的 CSV 或 JSON 结果")
    parser.add_argument("--output-json", default="", help="JSON 报告路径")
    parser.add_argument("--output-html", default="", help="HTML 报告路径")
    parser.add_argument("--title", default="视觉审核离线评测报告")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input).resolve()
    report = analyze_rows(load_rows(source))
    json_path = Path(args.output_json).resolve() if args.output_json else source.with_suffix(".evaluation.json")
    html_path = Path(args.output_html).resolve() if args.output_html else source.with_suffix(".evaluation.html")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report, args.title), encoding="utf-8")
    print(json.dumps({"ok": True, "json": str(json_path), "html": str(html_path), "metrics": report["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
