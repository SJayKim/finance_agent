import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
HOOK = ROOT / ".codex" / "hooks" / "protect-files.py"


def _run_hook(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload, indent=2),
        capture_output=True,
        check=False,
        text=True,
    )


def _run_hook_bytes(payload: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "path",
    [".env", "config/Secret.txt", "cert.PEM", "private.KEY"],
)
def test_protected_file_path_is_blocked(path: str) -> None:
    result = _run_hook({"tool_input": {"file_path": path}})

    assert result.returncode == 2


def test_protected_apply_patch_path_is_blocked() -> None:
    result = _run_hook(
        {
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: config/.env.local\n*** End Patch"
            }
        }
    )

    assert result.returncode == 2


def test_crlf_apply_patch_path_is_blocked() -> None:
    result = _run_hook(
        {
            "tool_input": {
                "command": "*** Begin Patch\r\n*** Update File: private.KEY\r\n*** End Patch"
            }
        }
    )

    assert result.returncode == 2


def test_protected_shell_reference_is_blocked() -> None:
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "Set-Content .env 'value'"},
        }
    )

    assert result.returncode == 2


@pytest.mark.parametrize(
    "path",
    [".codex/hooks.json", ".codex/hooks/protect-files.py"],
)
def test_hook_files_are_protected(path: str) -> None:
    result = _run_hook({"tool_input": {"command": f"*** Update File: {path}"}})

    assert result.returncode == 2


def test_safe_paths_are_allowed() -> None:
    result = _run_hook(
        {
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: docs/notes.md\n*** End Patch"
            }
        }
    )

    assert result.returncode == 0


def test_utf8_bom_input_is_allowed() -> None:
    payload = json.dumps({"tool_input": {"file_path": "docs/notes.md"}}).encode()

    result = _run_hook_bytes(b"\xef\xbb\xbf" + payload)

    assert result.returncode == 0


def test_unknown_input_shape_is_blocked() -> None:
    result = _run_hook({"path": ".env"})

    assert result.returncode == 2


def test_hook_command_is_repository_relative() -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    assert "C:\\Users\\" not in command
    assert command.startswith("uv run --no-sync python -c")
    assert config["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 5


@pytest.mark.parametrize("cwd", [ROOT, ROOT / "docs"])
def test_configured_hook_command_runs(cwd: Path) -> None:
    config = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    result = subprocess.run(
        command,
        cwd=cwd,
        input=json.dumps({"tool_input": {"file_path": "docs/notes.md"}}),
        capture_output=True,
        check=False,
        shell=True,
        text=True,
    )

    assert result.returncode == 0
