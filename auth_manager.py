from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoginResult:
    success: bool
    message: str


class CodexAuthManager:
    def __init__(
        self,
        codex_binary: str = "codex",
        timeout_seconds: int = 120,
        codex_home: Path | None = None,
    ) -> None:
        self.codex_binary = resolve_codex_binary(codex_binary)
        self.timeout_seconds = timeout_seconds
        self.codex_home = codex_home
        self.env = build_codex_environment(codex_home)

    def check_login_status(self) -> LoginResult:
        try:
            completed = subprocess.run(
                [self.codex_binary, "login", "status"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=self.env,
            )
        except FileNotFoundError:
            return LoginResult(False, build_codex_not_found_message(self.codex_binary))
        except subprocess.TimeoutExpired:
            return LoginResult(False, "Timed out while checking Codex login status.")

        output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
        if completed.returncode == 0:
            return LoginResult(True, output or "Codex login status is valid.")
        return LoginResult(False, output or "Codex CLI is not logged in.")

    def ensure_login(self, interactive: bool = True) -> LoginResult:
        status = self.check_login_status()
        if status.success:
            return status
        if not interactive:
            return status

        login_result = self._run_login(["login"])
        if not login_result.success:
            login_result = self._run_login(["login", "--device-auth"])
            if not login_result.success:
                return login_result

        return self.check_login_status()

    def _run_login(self, args: list[str]) -> LoginResult:
        try:
            completed = subprocess.run(
                [self.codex_binary, *args],
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=self.env,
            )
        except FileNotFoundError:
            return LoginResult(False, build_codex_not_found_message(self.codex_binary))
        except subprocess.TimeoutExpired:
            return LoginResult(False, f"Timed out while running codex {' '.join(args)}.")

        if completed.returncode == 0:
            return LoginResult(True, f"codex {' '.join(args)} completed.")
        return LoginResult(False, f"codex {' '.join(args)} failed with exit code {completed.returncode}.")


def resolve_codex_binary(codex_binary: str = "codex") -> str:
    if codex_binary != "codex":
        return str(Path(codex_binary).expanduser())

    env_path = os.environ.get("CODEX_CLI_PATH", "").strip()
    if env_path:
        return str(Path(env_path).expanduser())

    found = shutil.which("codex")
    if found:
        return found

    for candidate in _common_codex_paths():
        if candidate.exists():
            return str(candidate)

    return codex_binary


def build_codex_environment(codex_home: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if codex_home is not None:
        codex_home.mkdir(parents=True, exist_ok=True)
        env["CODEX_HOME"] = str(codex_home)
    return env


def build_codex_not_found_message(codex_binary: str = "codex") -> str:
    path_preview = os.environ.get("PATH", "")
    if len(path_preview) > 600:
        path_preview = path_preview[:600] + "..."
    return (
        "Codex CLI is not installed or not in PATH. "
        f"Tried executable: {codex_binary}. "
        "Set CODEX_CLI_PATH to the full Codex executable path, or start ComfyUI from a shell where `codex` works. "
        f"Current PATH begins with: {path_preview}"
    )


def _common_codex_paths() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "AppData" / "Roaming" / "npm" / "codex.cmd",
        home / "AppData" / "Roaming" / "npm" / "codex.exe",
        home / "AppData" / "Roaming" / "npm" / "codex",
        home / ".codex" / "bin" / "wsl" / "codex",
        home / ".codex" / "bin" / "codex",
        home / ".codex" / ".sandbox-bin" / "codex",
        home / ".codex" / ".sandbox-bin" / "codex.exe",
    ]

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        profile = Path(userprofile)
        candidates.extend(
            [
                profile / "AppData" / "Roaming" / "npm" / "codex.cmd",
                profile / "AppData" / "Roaming" / "npm" / "codex.exe",
                profile / "AppData" / "Roaming" / "npm" / "codex",
                profile / ".codex" / "bin" / "wsl" / "codex",
                profile / ".codex" / "bin" / "codex",
                profile / ".codex" / ".sandbox-bin" / "codex.exe",
            ]
        )

    appdata = os.environ.get("APPDATA")
    if appdata:
        npm_dir = Path(appdata) / "npm"
        candidates.extend([npm_dir / "codex.cmd", npm_dir / "codex.exe", npm_dir / "codex"])

    users_dir = Path("/mnt/c/Users")
    if users_dir.exists():
        candidates.extend(users_dir.glob("*/.codex/bin/wsl/codex"))
        candidates.extend(users_dir.glob("*/.codex/.sandbox-bin/codex.exe"))

    return candidates
