from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

try:
    from .codex_runner import CodexRunner
    from .image_io import empty_image_tensor, load_image_tensor_from_path
    from .path_utils import cleanup_generated_source_image
    from .prompt_builder import ALLOWED_ASPECT_RATIOS
except ImportError:
    from codex_runner import CodexRunner
    from image_io import empty_image_tensor, load_image_tensor_from_path
    from path_utils import cleanup_generated_source_image
    from prompt_builder import ALLOWED_ASPECT_RATIOS


MAX_CONCURRENCY = 8
CONCURRENCY_OPTIONS = [str(value) for value in range(1, MAX_CONCURRENCY + 1)]


@dataclass(frozen=True)
class _GenerationRequest:
    index: int
    prompt: str
    images: object | None


class CodexExecImageGen:
    CATEGORY = "Codex/ImageGen"
    FUNCTION = "execute"
    NOT_IDEMPOTENT = True
    OUTPUT_IS_LIST = (True, False, False, False, False, False, False)
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "STRING", "INT", "BOOLEAN")
    RETURN_NAMES = (
        "generated_image",
        "generated_image_path",
        "last_message",
        "raw_jsonl",
        "used_prompt",
        "exit_code",
        "success",
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "concurrency_count": (CONCURRENCY_OPTIONS, {"default": "1"}),
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "images": ("IMAGE",),
                **{
                    f"prompt_{index}": ("STRING", {"multiline": True})
                    for index in range(2, MAX_CONCURRENCY + 1)
                },
                **{
                    f"images_{index}": ("IMAGE",)
                    for index in range(2, MAX_CONCURRENCY + 1)
                },
                "aspect_ratio": (list(ALLOWED_ASPECT_RATIOS), {"default": "none"}),
                "model": (["gpt-5.4", "gpt-5.5"], {"default": "gpt-5.4"}),
                "reasoning_effort": (["low", "medium", "high"], {"default": "medium"}),
                "working_directory": ("STRING", {"default": ""}),
                "json_output": ("BOOLEAN", {"default": True}),
                "auto_save_to_output": ("BOOLEAN", {"default": False}),
                "output_last_message_path": ("STRING", {"default": ""}),
                "skip_git_repo_check": ("BOOLEAN", {"default": True}),
                "ephemeral": ("BOOLEAN", {"default": True}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("NaN")

    def execute(
        self,
        prompt,
        images=None,
        concurrency_count="1",
        aspect_ratio="none",
        model="gpt-5.4",
        reasoning_effort="medium",
        working_directory="",
        json_output=True,
        auto_save_to_output=False,
        output_last_message_path="",
        skip_git_repo_check=True,
        ephemeral=True,
        **kwargs,
    ):
        requests = _build_generation_requests(prompt, images, concurrency_count, kwargs)
        results = _run_generation_requests(
            requests,
            aspect_ratio=aspect_ratio,
            model=model,
            reasoning_effort=reasoning_effort,
            working_directory=working_directory,
            json_output=json_output,
            auto_save_to_output=auto_save_to_output,
            output_last_message_path=output_last_message_path,
            skip_git_repo_check=skip_git_repo_check,
            ephemeral=ephemeral,
        )
        return _build_node_output(results, auto_save_to_output)


def _build_generation_requests(prompt, images, concurrency_count, kwargs) -> list[_GenerationRequest]:
    count = int(concurrency_count)
    if count < 1 or count > MAX_CONCURRENCY:
        raise ValueError(f"concurrency_count must be between 1 and {MAX_CONCURRENCY}.")

    requests: list[_GenerationRequest] = []
    for index in range(1, count + 1):
        prompt_value = prompt if index == 1 else kwargs.get(f"prompt_{index}", "")
        image_value = images if index == 1 else kwargs.get(f"images_{index}")
        if not str(prompt_value or "").strip():
            name = "prompt" if index == 1 else f"prompt_{index}"
            raise ValueError(f"{name} is required when concurrency_count is {count}.")
        requests.append(_GenerationRequest(index=index, prompt=str(prompt_value), images=image_value))
    return requests


def _run_generation_requests(requests: list[_GenerationRequest], **options):
    results = [None] * len(requests)
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = {
            executor.submit(_run_single_generation, request, **options): request
            for request in requests
        }
        for future in as_completed(futures):
            request = futures[future]
            try:
                results[request.index - 1] = future.result()
            except Exception as exc:
                raise RuntimeError(f"Generation task {request.index} failed: {exc}") from exc
    return results


def _run_single_generation(request: _GenerationRequest, **options):
    output_last_message_path = options["output_last_message_path"]
    if str(output_last_message_path or "").strip():
        output_last_message_path = _indexed_path(output_last_message_path, request.index)

    result = CodexRunner().run(
        prompt=request.prompt,
        images=request.images,
        aspect_ratio=options["aspect_ratio"],
        model=options["model"],
        reasoning_effort=options["reasoning_effort"],
        working_directory=options["working_directory"],
        json_output=options["json_output"],
        auto_save_to_output=options["auto_save_to_output"],
        output_last_message_path=output_last_message_path,
        sandbox_mode="danger-full-access",
        skip_git_repo_check=options["skip_git_repo_check"],
        ephemeral=options["ephemeral"],
    )
    if not result.success:
        raise RuntimeError(
            f"Codex exec failed with exit code {result.exit_code}: {result.last_message}"
        )
    if not result.generated_image_path:
        hint = _build_no_image_hint(result.last_message)
        raise RuntimeError(
            "No generated image was found. "
            f"Codex exit code: {result.exit_code}. Last message: {result.last_message}{hint}"
        )
    return result


def _build_node_output(results, auto_save_to_output):
    generated_images = []
    generated_image_paths = []
    last_messages = []
    raw_jsonl_values = []
    used_prompts = []
    success_values = []

    for result in results:
        generated_image_path = result.generated_image_path
        generated_images.append(
            load_image_tensor_from_path(generated_image_path)
            if generated_image_path
            else empty_image_tensor()
        )
        if not auto_save_to_output:
            cleanup_generated_source_image(generated_image_path)
            generated_image_path = ""
        generated_image_paths.append(generated_image_path)
        last_messages.append(result.last_message)
        raw_jsonl_values.append(result.raw_jsonl)
        used_prompts.append(result.used_prompt)
        success_values.append(result.success)

    return (
        generated_images,
        "\n".join(path for path in generated_image_paths if path),
        _join_indexed(last_messages),
        _join_indexed(raw_jsonl_values),
        _join_indexed(used_prompts),
        0 if all(success_values) else 1,
        all(success_values),
    )


def _join_indexed(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return "\n\n".join(f"[{index}] {value}" for index, value in enumerate(values, start=1))


def _indexed_path(path: str, index: int) -> str:
    if index == 1:
        return path
    value = Path(path).expanduser()
    return str(value.with_name(f"{value.stem}_{index}{value.suffix}"))


def _build_no_image_hint(last_message: str) -> str:
    text = last_message or ""
    blocked_markers = ("只读沙箱", "网络受限", "network", "read-only", "sandbox", "策略拦截")
    if any(marker.lower() in text.lower() for marker in blocked_markers):
        return (
            "\nHint: image generation needs write and network access. "
            "The node already runs Codex with --sandbox danger-full-access. "
            "If it is still blocked, start ComfyUI from an environment where Codex CLI has network access."
        )
    return ""
