"""Cross-platform shell resolution helpers for WisprStudio.

Guarantees that POSIX shell resolution on Windows finds native Git Bash (MSYS2)
and NEVER invokes the WSL stub launcher (`C:\\Windows\\System32\\bash.exe`,
`Sysnative\\bash.exe`, or `WindowsApps\\bash.exe`), and builds `PATH` strings
using `os.pathsep` rather than POSIX-only `:` literals.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PureWindowsPath

_WSL_STUB_PARENTS = frozenset({"system32", "sysnative", "windowsapps"})


def is_wsl_bash_stub(path: str | os.PathLike[str] | None) -> bool:
    """Return True if `path` points to a Windows WSL `bash.exe` launcher stub."""
    if not path:
        return False
    raw = os.fspath(path)
    win_parts = [part.casefold() for part in PureWindowsPath(raw).parts]
    if PureWindowsPath(raw).name.casefold() not in {"bash", "bash.exe"}:
        return False
    return any(part in _WSL_STUB_PARENTS for part in win_parts[:-1])


def resolve_posix_bash(
    *,
    which: Callable[[str], str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve a genuine POSIX `bash` executable, refusing Windows WSL stubs."""
    environ = env if env is not None else os.environ
    lookup = which if which is not None else shutil.which

    if os.name == "nt":
        candidates: list[Path] = []
        for env_key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = environ.get(env_key)
            if root:
                candidates.append(Path(root) / "Git" / "usr" / "bin" / "bash.exe")
                candidates.append(Path(root) / "Git" / "bin" / "bash.exe")
        local_app = environ.get("LOCALAPPDATA")
        if local_app:
            candidates.append(Path(local_app) / "Programs" / "Git" / "usr" / "bin" / "bash.exe")
            candidates.append(Path(local_app) / "Programs" / "Git" / "bin" / "bash.exe")
        for candidate in candidates:
            if candidate.is_file() and not is_wsl_bash_stub(candidate):
                return str(candidate)

    found = lookup("bash")
    if found and not is_wsl_bash_stub(found):
        return found
    return None


def posix_bash_path(
    extra_dirs: Sequence[str | os.PathLike[str]] = (),
    *,
    bash_executable: str | os.PathLike[str] | None = None,
) -> str:
    """Build an `os.pathsep`-delimited `PATH` that puts `extra_dirs` ahead of core utilities."""
    entries: list[str] = [os.fspath(d) for d in extra_dirs if d]
    if os.name == "nt":
        bash_str = os.fspath(bash_executable) if bash_executable else resolve_posix_bash()
        if bash_str:
            bash_dir = Path(bash_str).resolve().parent
            if bash_dir.name.lower() == "bin" and bash_dir.parent.name.lower() == "usr":
                git_root = bash_dir.parent.parent
            elif bash_dir.name.lower() == "bin":
                git_root = bash_dir.parent
            else:
                git_root = bash_dir.parent.parent
            for sub in (git_root / "usr" / "bin", bash_dir):
                if sub.is_dir() and str(sub) not in entries:
                    entries.append(str(sub))
    else:
        for std_dir in ("/usr/bin", "/bin"):
            if std_dir not in entries:
                entries.append(std_dir)
    return os.pathsep.join(entries)


def posix_bash_env(
    extra_dirs: Sequence[str | os.PathLike[str]] = (),
    *,
    base_env: Mapping[str, str] | None = None,
    bash_executable: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Return a subprocess environment with UTF-8 mode and a safe `os.pathsep` `PATH`."""
    env = dict(base_env if base_env is not None else os.environ)
    env["PATH"] = posix_bash_path(extra_dirs, bash_executable=bash_executable)
    env.setdefault("PYTHONUTF8", "1")
    if os.name == "nt":
        env.setdefault("MSYS2_PATH_TYPE", "inherit")
    return env
