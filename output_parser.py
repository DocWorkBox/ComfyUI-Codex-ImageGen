from __future__ import annotations

import json
import re
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\\\\)[^\n\r\"'<>|]+?\.(?:png|jpg|jpeg|webp))",
    re.IGNORECASE,
)


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def parse_last_agent_message(raw_jsonl: str) -> str:
    last_message = ""
    for line in (raw_jsonl or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str) and item["text"].strip():
            last_message = item["text"]
    return last_message


def parse_generated_image_path(
    last_message: str,
    task_dir: Path,
    comfy_output_dir: Path | None = None,
    min_mtime: float | None = None,
    additional_output_dirs: list[Path] | None = None,
) -> str:
    for match in PATH_PATTERN.finditer(last_message or ""):
        candidate = Path(match.group("path").strip().rstrip(".,;)"))
        if candidate.exists() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            return str(candidate)

    output_dirs = [comfy_output_dir, task_dir, *(additional_output_dirs or [])]
    for outputs_dir in output_dirs:
        if outputs_dir is None or not outputs_dir.exists():
            continue
        images = [
            path
            for path in outputs_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            and (min_mtime is None or path.stat().st_mtime >= min_mtime)
        ]
        if images:
            return str(max(images, key=lambda path: path.stat().st_mtime))

    return ""
