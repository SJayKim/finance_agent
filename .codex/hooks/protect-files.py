import json
import re
import sys


_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to): ([^\r\n]+)$",
    re.MULTILINE,
)


def _paths(payload: dict[str, object]) -> list[str]:
    tool_input = payload.get("tool_input", payload)
    if not isinstance(tool_input, dict):
        return []

    paths = []
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str):
        paths.append(file_path)

    command = tool_input.get("command")
    if isinstance(command, str):
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name.casefold() in {
            "bash",
            "shell_command",
        }:
            paths.append(command)
        else:
            paths.extend(_PATCH_PATH.findall(command))
    return paths


def _is_protected(path: str) -> bool:
    normalized = path.casefold().replace("\\", "/")
    return (
        ".env" in normalized
        or "secret" in normalized
        or ".pem" in normalized
        or ".key" in normalized
        or ".codex/hooks.json" in normalized
        or ".codex/hooks/protect-files.py" in normalized
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("Blocked: could not parse hook input", file=sys.stderr)
        return 2

    if not isinstance(payload, dict):
        print("Blocked: invalid hook input", file=sys.stderr)
        return 2

    paths = _paths(payload)
    if not paths:
        print("Blocked: unsupported hook input", file=sys.stderr)
        return 2

    for path in paths:
        if _is_protected(path):
            print(f"Blocked: protected file ({path})", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
