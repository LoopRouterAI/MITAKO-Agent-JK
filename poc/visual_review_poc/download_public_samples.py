# -*- coding: utf-8 -*-
"""下载视觉审核 POC 用的公开视频样例。

这些样例只用于验证本地视频读取、抽帧、多模态模型调用和报告生成链路，
不能代表甲方真实商品售后或未成年人资料审核准确率。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = Path(__file__).resolve().parent / "sample_videos"
MANIFEST_PATH = SAMPLE_DIR / "download_manifest.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


SAMPLES: List[Dict[str, Any]] = [
    {
        "scenario": "video_unboxing",
        "priority": 10,
        "sample_id": "commons_unboxing_magnetic_balls_360p",
        "title": "Unboxing Magnetic Balls Neodymium Magnets video",
        "url": "https://upload.wikimedia.org/wikipedia/commons/transcoded/d/d2/Unboxing_Magnetic_Balls_Neodymium_Magnets_video.webm/Unboxing_Magnetic_Balls_Neodymium_Magnets_video.webm.360p.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Unboxing_Magnetic_Balls_Neodymium_Magnets_video.webm",
        "license_note": "Wikimedia Commons 文件页标注 CC BY 3.0；用于开箱连续性链路验证。",
        "filename": "video_unboxing_commons_magnetic_balls_360p.webm",
        "business_fit": "最接近开箱场景，可验证拆包装、取出物体、前后帧连续性和物体追踪。",
        "risk": "原始来源为 YouTube 导入；当前网络可能因 Wikimedia 机器人策略拒绝直链下载。",
    },
    {
        "scenario": "product_damage",
        "priority": 10,
        "sample_id": "commons_glass_cup_smash",
        "title": "Glass tea cup smashes on concrete floor - close-up video",
        "url": "https://upload.wikimedia.org/wikipedia/commons/1/1b/Glass_tea_cup_smashes_on_concrete_floor_-_close-up_video.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Glass_tea_cup_smashes_on_concrete_floor_-_close-up_video.webm",
        "license_note": "Wikimedia Commons 文件页标注 CC BY-SA 4.0；用于破损变化链路验证。",
        "filename": "product_damage_commons_glass_cup_smash.webm",
        "business_fit": "可验证破损前后状态变化、碎裂可见性和证据帧抽取。",
        "risk": "不是电商商品售后样本，不能代表商品有伤审核准确率。",
    },
    {
        "scenario": "minor_material",
        "priority": 10,
        "sample_id": "commons_2fa_screen_recording",
        "title": "Enabling 2FA on Wikipedia with KeeWeb",
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/f4/Enabling_2FA_on_Wikipedia_with_KeeWeb.webm",
        "source_page": "https://commons.wikimedia.org/wiki/File:Enabling_2FA_on_Wikipedia_with_KeeWeb.webm",
        "license_note": "Wikimedia Commons 文件页标注视频主体 CC0；用于屏幕资料链路验证。",
        "filename": "minor_material_commons_2fa_screen_recording.webm",
        "business_fit": "可验证资料类视频上传、抽帧、界面文字和敏感区域提示链路。",
        "risk": "不是未成年人资料样本，不能用于真实合规准确率判断。",
    },
    {
        "scenario": "video_unboxing",
        "priority": 50,
        "sample_id": "w3c_sintel_trailer",
        "title": "Sintel trailer",
        "url": "https://media.w3.org/2010/05/sintel/trailer.mp4",
        "source_page": "https://media.w3.org/2010/05/sintel/",
        "license_note": "W3C 公开视频测试素材；只作为稳定下载兜底链路样例。",
        "filename": "video_unboxing_fallback_sintel_trailer.mp4",
        "business_fit": "可稳定验证本地视频读取、抽帧、Gemini/GPT 图像输入链路。",
        "risk": "不是开箱业务视频，不能代表开箱审核准确率。",
    },
    {
        "scenario": "product_damage",
        "priority": 50,
        "sample_id": "w3c_big_buck_bunny_trailer",
        "title": "Big Buck Bunny trailer",
        "url": "https://media.w3.org/2010/05/bunny/trailer.mp4",
        "source_page": "https://media.w3.org/2010/05/bunny/",
        "license_note": "W3C 公开视频测试素材；只作为稳定下载兜底链路样例。",
        "filename": "product_damage_fallback_big_buck_bunny_trailer.mp4",
        "business_fit": "可稳定验证本地视频读取、抽帧和多模态模型调用链路。",
        "risk": "不是商品破损视频，不能代表商品有伤审核准确率。",
    },
    {
        "scenario": "minor_material",
        "priority": 50,
        "sample_id": "mdn_flower_cc0",
        "title": "MDN CC0 flower sample",
        "url": "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
        "source_page": "https://developer.mozilla.org/",
        "license_note": "MDN interactive examples 路径标注 cc0-videos；只作为稳定下载兜底链路样例。",
        "filename": "minor_material_fallback_mdn_flower.mp4",
        "business_fit": "可稳定验证资料类场景的本地视频输入和模型报告生成链路。",
        "risk": "不是资料或人像样本，不能代表未成年人资料审核准确率。",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载视觉审核 POC 公开视频样例")
    parser.add_argument(
        "--scenario",
        choices=["all", "video_unboxing", "product_damage", "minor_material"],
        default="all",
        help="要下载的场景样例，默认 all。",
    )
    parser.add_argument(
        "--all-candidates",
        action="store_true",
        help="下载每个场景的全部候选；默认每个场景只保留第一个成功候选。",
    )
    parser.add_argument("--timeout", type=int, default=90, help="单个下载超时时间，单位秒。")
    return parser.parse_args()


def candidates_for(scenario: str) -> List[Dict[str, Any]]:
    selected = [item for item in SAMPLES if scenario == "all" or item["scenario"] == scenario]
    return sorted(selected, key=lambda item: (item["scenario"], item["priority"]))


def download_one(sample: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    target = SAMPLE_DIR / sample["filename"]
    result: Dict[str, Any] = {
        "sample_id": sample["sample_id"],
        "scenario": sample["scenario"],
        "title": sample["title"],
        "url": sample["url"],
        "source_page": sample["source_page"],
        "license_note": sample["license_note"],
        "business_fit": sample["business_fit"],
        "risk": sample["risk"],
        "target": str(target),
    }
    if target.exists() and target.stat().st_size > 0:
        result.update({"ok": True, "status": "cached", "bytes": target.stat().st_size})
        return result

    headers = {
        "User-Agent": "MITAKO-Agent-POC/1.0; local business demo preparation",
        "Accept": "video/mp4,video/webm,video/*,*/*",
        "Referer": sample["source_page"],
    }
    temp = target.with_suffix(target.suffix + ".download")
    started = time.time()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", sample["url"]) as response:
                result["status_code"] = response.status_code
                result["content_type"] = response.headers.get("content-type")
                if response.status_code >= 400:
                    body = response.read()
                    result.update(
                        {
                            "ok": False,
                            "status": "http_failed",
                            "error": body[:300].decode("utf-8", errors="ignore"),
                            "latency_seconds": round(time.time() - started, 2),
                        }
                    )
                    return result
                with temp.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        if chunk:
                            fh.write(chunk)
        if temp.stat().st_size <= 0:
            result.update({"ok": False, "status": "empty_file"})
            temp.unlink(missing_ok=True)
            return result
        temp.replace(target)
        result.update(
            {
                "ok": True,
                "status": "downloaded",
                "bytes": target.stat().st_size,
                "latency_seconds": round(time.time() - started, 2),
            }
        )
        return result
    except Exception as exc:
        temp.unlink(missing_ok=True)
        result.update(
            {
                "ok": False,
                "status": "download_exception",
                "error": str(exc)[:800],
                "latency_seconds": round(time.time() - started, 2),
            }
        )
        return result


def write_manifest(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    previous: Dict[str, Any] = {}
    if MANIFEST_PATH.exists():
        try:
            previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    history = list(previous.get("download_results", []))
    history.extend(results)

    selected: Dict[str, Dict[str, Any]] = {}
    for item in history:
        if item.get("ok") and item.get("target"):
            scenario = item["scenario"]
            path = Path(item["target"])
            if path.exists() and path.stat().st_size > 0 and scenario not in selected:
                selected[scenario] = item

    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample_dir": str(SAMPLE_DIR),
        "selected_by_scenario": selected,
        "download_results": history[-60:],
        "boundary": "公开视频只验证本地视频链路，不代表甲方真实业务准确率；正式 POC 应替换为甲方脱敏授权样本。",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def scenario_order(scenario: str) -> List[str]:
    if scenario == "all":
        return ["video_unboxing", "product_damage", "minor_material"]
    return [scenario]


def run_download(scenario: str, all_candidates: bool, timeout: int) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for current_scenario in scenario_order(scenario):
        current_candidates = candidates_for(current_scenario)
        scenario_success = False
        for sample in current_candidates:
            result = download_one(sample, timeout)
            results.append(result)
            status = "成功" if result.get("ok") else "失败"
            print(f"[MITAKO] {current_scenario} / {sample['sample_id']} 下载{status}: {result.get('status')}")
            if result.get("ok"):
                scenario_success = True
                if not all_candidates:
                    break
        if not scenario_success:
            print(f"[MITAKO] {current_scenario} 未下载到可用样例，本地 Demo 需要手动传入 --video。")
    manifest = write_manifest(results)
    return {"manifest": manifest, "results": results}


def main() -> int:
    args = parse_args()
    payload = run_download(args.scenario, args.all_candidates, args.timeout)
    ok_count = sum(1 for item in payload["results"] if item.get("ok"))
    print(
        json.dumps(
            {
                "manifest": str(MANIFEST_PATH),
                "sample_dir": str(SAMPLE_DIR),
                "ok_count": ok_count,
                "boundary": payload["manifest"]["boundary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
