from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_DIR / "runtime"


def create_task_dir(runtime_dir: Path | None = None) -> Path:
    base = runtime_dir or RUNTIME_DIR
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_dir = base / f"{timestamp}_{uuid4().hex[:8]}"
    task_dir.mkdir(parents=True, exist_ok=False)
    return task_dir


def parse_image_paths(images: str | None) -> list[Path]:
    paths: list[Path] = []
    for raw_line in (images or "").splitlines():
        value = raw_line.strip().strip('"').strip("'")
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"Input image path does not exist: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Input image path is not a file: {path}")
        paths.append(path)
    return paths


def resolve_working_directory(value: str | None, task_dir: Path) -> Path:
    if value and value.strip():
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            path = path.resolve()
        return path
    return task_dir


def get_comfy_input_dir() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.get_input_directory())
    except Exception:
        path = Path(gettempdir()) / "comfyui_codex_imagegen_input"
        path.mkdir(parents=True, exist_ok=True)
        return path


def get_comfy_output_dir() -> Path:
    try:
        import folder_paths

        return Path(folder_paths.get_output_directory())
    except Exception:
        path = Path(gettempdir()) / "comfyui_codex_imagegen_output"
        path.mkdir(parents=True, exist_ok=True)
        return path


def copy_generated_image_to_output(source: Path | str, output_dir: Path, task_name: str) -> Path:
    source_path = Path(source)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        source_path.resolve().relative_to(output_dir.resolve())
        return source_path
    except ValueError:
        pass

    target = output_dir / f"codex_imagegen_{task_name}_{source_path.name}"
    shutil.copy2(source_path, target)
    _remove_source_image_and_empty_parents(source_path)
    return target


def cleanup_generated_source_image(source: Path | str) -> None:
    source_path = Path(source)
    if not _looks_like_codex_generated_image(source_path):
        return
    _remove_source_image_and_empty_parents(source_path)


def cleanup_task_dir(task_dir: Path | str) -> None:
    path = Path(task_dir)
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _remove_source_image_and_empty_parents(source_path: Path) -> None:
    parent = source_path.parent
    source_path.unlink(missing_ok=True)
    try:
        parent.rmdir()
    except OSError:
        pass


def _looks_like_codex_generated_image(source_path: Path) -> bool:
    parts = {part.lower() for part in source_path.parts}
    return "codex_home" in parts and "generated_images" in parts
