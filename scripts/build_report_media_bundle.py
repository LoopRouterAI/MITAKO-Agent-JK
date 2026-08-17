from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "甲方沟通交付文档" / "四场景审核报告"
CASES = {
    "592717": "product_damage",
    "611941": "product_damage",
    "515028": "wrong_item",
    "310508": "wrong_item",
    "289433": "missing_item",
    "319303": "missing_item",
    "511007": "minor_refund",
    "554611": "minor_refund",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _image_files(path: Path) -> list[Path]:
    def key(item: Path) -> tuple[int, str]:
        match = re.match(r"(\d+)", item.stem)
        return (int(match.group(1)) if match else 99999, item.name.lower())

    return sorted(
        (item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS),
        key=key,
    )


def _case_dir(case_id: str) -> Path:
    base = Path("E:/AIGC/0 Mitako样本")
    candidates = list(base.glob(f"第一批次样本/客户第一批样本*/*/*/{case_id}"))
    candidates += list(base.glob(f"第二批次样本/客户第二批样本*/*/{case_id}"))
    candidates = [
        path for path in candidates
        if path.is_dir() and _image_files(path) and "ticket_" not in str(path).lower()
    ]
    if not candidates:
        raise FileNotFoundError(f"找不到样本图片目录：{case_id}")
    return sorted(candidates, key=lambda path: (-len(_image_files(path)), len(str(path))))[0]


def _order_snapshot(case_id: str) -> Path | None:
    base = Path("E:/AIGC/0 Mitako样本")
    candidates = list(base.glob(f"第一批次样本/按订单id-第一批次样本对应的订单信息/**/ticket_{case_id}/order_info_snapshot.json"))
    candidates += list(base.glob(f"第二批次样本/按订单id-第二批次样本对应的订单信息/**/ticket_{case_id}/order_info_snapshot.json"))
    return sorted(candidates, key=lambda path: len(str(path)))[0] if candidates else None


def _official_urls(case_id: str, limit: int) -> list[str]:
    snapshot = _order_snapshot(case_id)
    if snapshot is None:
        return []
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    urls = []
    for item in data.get("goods_list") or []:
        reference = str(item.get("main_img") or "").replace("\\", "/").lstrip("/")
        if reference:
            urls.append("https://cdn-qiniu.danhaotuan.com/storage/mnt/zhonggu/" + reference)
    return urls[:limit]


def _write_webp(payload: bytes, output: Path) -> dict[str, object]:
    with Image.open(BytesIO(payload)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max(image.size) > 2560:
            image.thumbnail((2560, 2560), Image.Resampling.LANCZOS)
        lossless = BytesIO()
        image.save(lossless, format="WEBP", lossless=True, method=6)
        encoded = lossless.getvalue()
        encoding = "lossless"
        if len(encoded) >= len(payload):
            quality90 = BytesIO()
            image.save(quality90, format="WEBP", quality=90, method=6)
            encoded = quality90.getvalue()
            encoding = "quality90"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
        return {
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "width": image.width,
            "height": image.height,
            "encoding": encoding,
            "source_bytes": len(payload),
        }


def _existing_webp_info(output: Path) -> dict[str, object] | None:
    """复用已生成资产，避免重复下载和重复转码。"""
    if not output.is_file():
        return None
    with Image.open(output) as image:
        return {
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "width": image.width,
            "height": image.height,
            "encoding": "existing",
        }


def _title_number(label: str) -> int | None:
    if "视频" in label or "官方商品参考图" in label:
        return None
    match = re.search(r"图片\s*(\d+)", label)
    return int(match.group(1)) if match else None


def _replace_preview_buttons(text: str, paths: dict[tuple[str, int], str]) -> str:
    def replace(match: re.Match[str]) -> str:
        block = match.group(0)
        title_match = re.search(r'data-preview-title="([^"]+)"', block)
        if title_match is None:
            return block
        label = html.unescape(title_match.group(1))
        number = _title_number(label)
        if number is None:
            return block
        kind = "official" if "官方商品参考图" in label else "user"
        relative_path = paths.get((kind, number))
        if relative_path is None:
            return block
        block = re.sub(
            r'(data-preview-src=")([^"]+)(")',
            lambda item: item.group(1) + relative_path + item.group(3),
            block,
        )
        return re.sub(
            r'(<img\b[^>]*\bsrc=")([^"]+)(")',
            lambda item: item.group(1) + relative_path + item.group(3),
            block,
        )

    return re.sub(r"<button\b[^>]*>.*?</button>", replace, text, flags=re.S)


def build() -> dict[str, object]:
    media_dir = REPORT_DIR / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "version": "2026-08-17.1",
        "scope": "internal_review_only",
        "privacy_note": "含未成年人材料的静态证据，仅随内部研发包和本地验收目录保留；甲方客户 ZIP 不携带该目录。",
        "reports": {},
        "assets": [],
    }
    assets = manifest["assets"]
    reports = manifest["reports"]
    assert isinstance(assets, list)
    assert isinstance(reports, dict)

    for case_id, scene in CASES.items():
        source_images = _image_files(_case_dir(case_id))
        report = REPORT_DIR / f"review_0816_blind_{scene}_{case_id}.html"
        text = report.read_text(encoding="utf-8")
        user_numbers: set[int] = set()
        official_numbers: set[int] = set()
        for match in re.finditer(r'data-preview-title="([^"]+)"', text):
            label = html.unescape(match.group(1))
            number = _title_number(label)
            if number is None:
                if "官方商品参考图" in label:
                    official_match = re.search(r"(\d+)", label)
                    if official_match:
                        official_numbers.add(int(official_match.group(1)))
                continue
            user_numbers.add(number)

        paths: dict[tuple[str, int], str] = {}
        for number in sorted(user_numbers):
            if not 1 <= number <= len(source_images):
                continue
            relative = f"media/{case_id}/user_{number:03d}.webp"
            output = REPORT_DIR / relative
            info = _existing_webp_info(output) or _write_webp(source_images[number - 1].read_bytes(), output)
            info.update({"case_id": case_id, "role": "user_upload", "asset": relative})
            assets.append(info)
            paths[("user", number)] = relative

        official_urls = _official_urls(case_id, max(official_numbers, default=0))
        for number in sorted(official_numbers):
            if number > len(official_urls):
                continue
            try:
                relative = f"media/{case_id}/official_{number:03d}.webp"
                output = REPORT_DIR / relative
                info = _existing_webp_info(output)
                if info is not None:
                    info.update({"case_id": case_id, "role": "official_reference", "asset": relative})
                    assets.append(info)
                    paths[("official", number)] = relative
                    continue
                request = urllib.request.Request(
                    official_urls[number - 1], headers={"User-Agent": "MITAKO-Report-Bundle/1.0"}
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = response.read()
                info = _write_webp(payload, output)
                info.update({"case_id": case_id, "role": "official_reference", "asset": relative})
                assets.append(info)
                paths[("official", number)] = relative
            except Exception as exc:  # pragma: no cover - network availability is environment-specific
                print(f"官方商品图下载失败 {case_id}#{number}: {exc}")

        report.write_text(_replace_preview_buttons(text, paths), encoding="utf-8")
        reports[case_id] = {
            "file": report.name,
            "source_image_count": len(source_images),
            "bundled_user_images": sum(kind == "user" for kind, _ in paths),
            "bundled_official_images": sum(kind == "official" for kind, _ in paths),
        }

    output = media_dir / "manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"reports": len(reports), "assets": len(assets), "bytes": sum(int(item["bytes"]) for item in assets)}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
