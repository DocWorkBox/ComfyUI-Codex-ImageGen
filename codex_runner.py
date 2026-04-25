from __future__ import annotations

import json
import threading
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    from .auth_manager import CodexAuthManager, build_codex_environment, build_codex_not_found_message, resolve_codex_binary
    from .image_io import save_image_tensor_to_comfy_input
    from .output_parser import parse_generated_image_path, parse_last_agent_message, read_text_if_exists
    from .path_utils import cleanup_task_dir, copy_generated_image_to_output, create_task_dir, get_comfy_input_dir, get_comfy_output_dir, parse_image_paths, resolve_working_directory
    from .progress import create_progress, progress_for_jsonl_event, update_progress
    from .prompt_builder import ALLOWED_ASPECT_RATIOS, build_imagegen_prompt
except ImportError:
    from auth_manager import CodexAuthManager, build_codex_environment, build_codex_not_found_message, resolve_codex_binary
    from image_io import save_image_tensor_to_comfy_input
    from output_parser import parse_generated_image_path, parse_last_agent_message, read_text_if_exists
    from path_utils import cleanup_task_dir, copy_generated_image_to_output, create_task_dir, get_comfy_input_dir, get_comfy_output_dir, parse_image_paths, resolve_working_directory
    from progress import create_progress, progress_for_jsonl_event, update_progress
    from prompt_builder import ALLOWED_ASPECT_RATIOS, build_imagegen_prompt


ALLOWED_MODELS = ("gpt-5.4", "gpt-5.5")
ALLOWED_REASONING_EFFORTS = ("low", "medium", "high")
ALLOWED_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")


@dataclass
class RunnerOptions:
    prompt: str
    image_paths: list[Path] = field(default_factory=list)
    aspect_ratio: str = "none"
    model: str = "gpt-5.4"
    reasoning_effort: str = "medium"
    working_directory: Path | None = None
    json_output: bool = True
    output_last_message_path: Path | None = None
    sandbox_mode: str = "workspace-write"
    skip_git_repo_check: bool = True
    ephemeral: bool = True


@dataclass
class RunnerResult:
    generated_image_path: str
    last_message: str
    raw_jsonl: str
    used_prompt: str
    exit_code: int
    success: bool
    task_dir: str = ""
    stderr: str = ""

    def as_node_tuple(self) -> tuple[str, str, str, str, int, bool]:
        return (
            self.generated_image_path,
            self.last_message,
            self.raw_jsonl,
            self.used_prompt,
            self.exit_code,
            self.success,
        )


def build_codex_exec_command(options: RunnerOptions) -> list[str]:
    _validate_options(options)
    command = ["codex", "exec"]
    if options.working_directory is not None:
        command.extend(["--cd", str(options.working_directory)])
    if options.json_output:
        command.append("--json")
    command.extend(["--sandbox", options.sandbox_mode])
    if options.skip_git_repo_check:
        command.append("--skip-git-repo-check")
    if options.ephemeral:
        command.append("--ephemeral")
    if options.image_paths:
        command.extend(["--image", ",".join(str(path) for path in options.image_paths)])
    command.extend(["-m", options.model])
    command.extend(["-c", f"model_reasoning_effort={options.reasoning_effort}"])
    if options.output_last_message_path is not None:
        command.extend(["-o", str(options.output_last_message_path)])
    command.append(build_imagegen_prompt(options.prompt, options.aspect_ratio))
    return command


class CodexRunner:
    def __init__(
        self,
        codex_binary: str = "codex",
        auth_manager: CodexAuthManager | None = None,
        runtime_dir: Path | None = None,
        comfy_input_dir: Path | None = None,
        comfy_output_dir: Path | None = None,
    ) -> None:
        self.codex_binary = resolve_codex_binary(codex_binary)
        self.runtime_dir = runtime_dir
        self.codex_home = (runtime_dir or Path(__file__).resolve().parent / "runtime") / "codex_home"
        self.codex_env = build_codex_environment(self.codex_home)
        self.auth_manager = auth_manager or CodexAuthManager(codex_binary=self.codex_binary, codex_home=self.codex_home)
        self.comfy_input_dir = comfy_input_dir
        self.comfy_output_dir = comfy_output_dir

    def run(
        self,
        prompt: str,
        images=None,
        image_paths_text: str = "",
        aspect_ratio: str = "none",
        model: str = "gpt-5.4",
        reasoning_effort: str = "medium",
        working_directory: str = "",
        json_output: bool = True,
        output_last_message_path: str = "",
        sandbox_mode: str = "workspace-write",
        skip_git_repo_check: bool = True,
        ephemeral: bool = True,
        auto_save_to_output: bool = False,
        timeout_seconds: int = 600,
    ) -> RunnerResult:
        task_dir = create_task_dir(self.runtime_dir)
        stdout_path = task_dir / "stdout.jsonl"
        stderr_path = task_dir / "stderr.txt"
        prompt_path = task_dir / "prompt.txt"
        meta_path = task_dir / "meta.json"
        used_prompt = build_imagegen_prompt(prompt, aspect_ratio)
        prompt_path.write_text(used_prompt, encoding="utf-8")
        progress = create_progress(100)
        update_progress(progress, 5)

        try:
            input_dir = self.comfy_input_dir or get_comfy_input_dir()
            output_dir = self.comfy_output_dir or get_comfy_output_dir()
            parsed_images = parse_image_paths(image_paths_text)
            tensor_images = save_image_tensor_to_comfy_input(
                images,
                input_dir,
                f"codex_imagegen_{task_dir.name}",
            )
            image_paths = [*parsed_images, *tensor_images]
            workdir = resolve_working_directory(working_directory, output_dir)
            if not workdir.exists() or not workdir.is_dir():
                raise FileNotFoundError(f"Working directory does not exist: {workdir}")

            last_message_path = (
                Path(output_last_message_path).expanduser()
                if output_last_message_path and output_last_message_path.strip()
                else task_dir / "last_message.txt"
            )
            if not last_message_path.is_absolute():
                last_message_path = last_message_path.resolve()
            last_message_path.parent.mkdir(parents=True, exist_ok=True)

            auth = self.auth_manager.ensure_login(interactive=True)
            if not auth.success:
                return self._failure(task_dir, 1, auth.message, used_prompt, stdout_path, stderr_path)
            update_progress(progress, 15)

            options = RunnerOptions(
                prompt=prompt,
                image_paths=image_paths,
                aspect_ratio=aspect_ratio,
                model=model,
                reasoning_effort=reasoning_effort,
                working_directory=workdir,
                json_output=json_output,
                output_last_message_path=last_message_path,
                sandbox_mode=sandbox_mode,
                skip_git_repo_check=skip_git_repo_check,
                ephemeral=ephemeral,
            )
            command = build_codex_exec_command(options)
            command[0] = self.codex_binary
            meta_path.write_text(
                json.dumps(
                    {
                        "command": command[:-1] + ["<prompt>"],
                        "task_dir": str(task_dir),
                        "working_directory": str(workdir),
                        "last_message_path": str(last_message_path),
                        "comfy_input_dir": str(input_dir),
                        "comfy_output_dir": str(output_dir),
                        "codex_home": str(self.codex_home),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            process_started_at = time.time()
            exit_code = self._run_process(command, stdout_path, stderr_path, timeout_seconds, progress)
            last_message = read_text_if_exists(last_message_path)
            raw_jsonl = read_text_if_exists(stdout_path) if json_output else ""
            stderr = read_text_if_exists(stderr_path)
            if not last_message and raw_jsonl:
                last_message = parse_last_agent_message(raw_jsonl)
            if exit_code != 0 and not last_message:
                last_message = stderr or f"codex exec failed with exit code {exit_code}."
                if raw_jsonl:
                    last_message = f"{last_message}\n\nstdout.jsonl:\n{_tail_text(raw_jsonl)}"
            generated = parse_generated_image_path(
                last_message,
                task_dir,
                output_dir,
                min_mtime=process_started_at,
                additional_output_dirs=[self.codex_home / "generated_images"],
            )
            if generated:
                update_progress(progress, 95)
                if auto_save_to_output:
                    generated = str(copy_generated_image_to_output(Path(generated), output_dir, task_dir.name))
                update_progress(progress, 100)
            result = RunnerResult(
                generated_image_path=generated,
                last_message=last_message,
                raw_jsonl=raw_jsonl,
                used_prompt=used_prompt,
                exit_code=exit_code,
                success=exit_code == 0,
                task_dir=str(task_dir),
                stderr=stderr,
            )
            if result.success and result.generated_image_path and not _path_is_inside(result.generated_image_path, task_dir):
                cleanup_task_dir(task_dir)
            return result
        except FileNotFoundError as exc:
            message = str(exc)
            code = 127 if self.codex_binary in message else 1
            return self._failure(task_dir, code, message, used_prompt, stdout_path, stderr_path)
        except ValueError as exc:
            return self._failure(task_dir, 1, str(exc), used_prompt, stdout_path, stderr_path)
        except Exception as exc:
            return self._failure(task_dir, 1, f"Unexpected Codex node error: {exc}", used_prompt, stdout_path, stderr_path)

    def _run_process(self, command: list[str], stdout_path: Path, stderr_path: Path, timeout_seconds: int, progress) -> int:
        try:
            update_progress(progress, 20)
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=self.codex_env,
                    bufsize=1,
                )
                stderr_thread = threading.Thread(
                    target=_copy_stream,
                    args=(process.stderr, stderr_file),
                    daemon=True,
                )
                stderr_thread.start()
                deadline = time.monotonic() + timeout_seconds
                while True:
                    if process.stdout is None:
                        break
                    line = process.stdout.readline()
                    if line:
                        stdout_file.write(line)
                        stdout_file.flush()
                        progress_value = progress_for_jsonl_event(line)
                        if progress_value is not None:
                            update_progress(progress, progress_value)
                    elif process.poll() is not None:
                        break
                    elif time.monotonic() > deadline:
                        process.kill()
                        process.wait()
                        stderr_file.write(f"\nTimed out after {timeout_seconds} seconds; process killed.\n")
                        stderr_file.flush()
                        return 124
                    else:
                        time.sleep(0.05)
                try:
                    return process.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    stderr_file.write(f"\nTimed out after {timeout_seconds} seconds; process killed.\n")
                    stderr_file.flush()
                    return 124
                finally:
                    stderr_thread.join(timeout=1)
        except FileNotFoundError:
            stderr_path.write_text(build_codex_not_found_message(self.codex_binary) + "\n", encoding="utf-8")
            return 127

    def _failure(
        self,
        task_dir: Path,
        exit_code: int,
        message: str,
        used_prompt: str,
        stdout_path: Path,
        stderr_path: Path,
    ) -> RunnerResult:
        stderr_path.write_text(message, encoding="utf-8")
        return RunnerResult(
            generated_image_path="",
            last_message=message,
            raw_jsonl=read_text_if_exists(stdout_path),
            used_prompt=used_prompt,
            exit_code=exit_code,
            success=False,
            task_dir=str(task_dir),
            stderr=message,
        )


def _validate_options(options: RunnerOptions) -> None:
    if options.model not in ALLOWED_MODELS:
        raise ValueError(f"Unsupported Codex model: {options.model}")
    if options.aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise ValueError(f"Unsupported aspect_ratio: {options.aspect_ratio}")
    if options.reasoning_effort not in ALLOWED_REASONING_EFFORTS:
        raise ValueError(f"Unsupported reasoning_effort: {options.reasoning_effort}")
    if options.sandbox_mode not in ALLOWED_SANDBOX_MODES:
        raise ValueError(f"Unsupported sandbox_mode: {options.sandbox_mode}")


def _tail_text(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _path_is_inside(path: str | Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _copy_stream(stream, output_file) -> None:
    if stream is None:
        return
    for line in stream:
        output_file.write(line)
        output_file.flush()
