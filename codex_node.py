from __future__ import annotations

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


class CodexExecImageGen:
    CATEGORY = "Codex/ImageGen"
    FUNCTION = "execute"
    NOT_IDEMPOTENT = True
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
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "images": ("IMAGE",),
                "aspect_ratio": (list(ALLOWED_ASPECT_RATIOS), {"default": "none"}),
                "model": (["gpt-5.4"], {"default": "gpt-5.4"}),
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
        aspect_ratio="none",
        model="gpt-5.4",
        reasoning_effort="medium",
        working_directory="",
        json_output=True,
        auto_save_to_output=False,
        output_last_message_path="",
        skip_git_repo_check=True,
        ephemeral=True,
    ):
        result = CodexRunner().run(
            prompt=prompt,
            images=images,
            aspect_ratio=aspect_ratio,
            model=model,
            reasoning_effort=reasoning_effort,
            working_directory=working_directory,
            json_output=json_output,
            auto_save_to_output=auto_save_to_output,
            output_last_message_path=output_last_message_path,
            sandbox_mode="danger-full-access",
            skip_git_repo_check=skip_git_repo_check,
            ephemeral=ephemeral,
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
        generated_image_path = result.generated_image_path
        generated_image = (
            load_image_tensor_from_path(generated_image_path)
            if generated_image_path
            else empty_image_tensor()
        )
        if not auto_save_to_output:
            cleanup_generated_source_image(generated_image_path)
            generated_image_path = ""
        return (
            generated_image,
            generated_image_path,
            result.last_message,
            result.raw_jsonl,
            result.used_prompt,
            result.exit_code,
            result.success,
        )


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
