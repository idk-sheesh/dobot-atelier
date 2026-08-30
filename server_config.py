from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def normalize_server_executable(value: str) -> Path:
    return Path(os.path.expandvars(value.strip())).expanduser()


def default_server_executable(
    app_dir: Path,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    override = environment.get("DOBOT_SERVER_EXE", "").strip()
    if override:
        return normalize_server_executable(override)

    user_home = Path.home() if home is None else home
    candidates = (
        app_dir / "DobotServer.exe",
        user_home / "Documents" / "Codex" / "DobotTools-V1.0" / "installed" / "DobotServer.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
