from __future__ import annotations

import json
import shutil
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TOOLS_DIR = BASE_DIR / "tools"
RCONCLI_DIR = TOOLS_DIR / "RconCli"

LAUNCHER_PATHS_FILE = BASE_DIR / "launcher_paths.json"

DOWNLOADS = {
    "TheIsle_RCON.py": {
        "url": "https://raw.githubusercontent.com/karben4/The-Isle-Evrima-Server-Tools/main/TheIsle_RCON.py",
        "target": TOOLS_DIR / "TheIsle_RCON.py",
    },
}

RCONCLI_BUNDLE_FILES = [
    "RconCli.exe",
    "RconCli.dll",
    "RconCli.deps.json",
    "RconCli.runtimeconfig.json",
    "TheIsleEvrimaRconClient.dll",
    "TheIsleEvrimaRconClient.Extensions.dll",
]



def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True



def ensure_rconcli_bundle() -> Path | None:
    source_dir = BASE_DIR / "RconCli" / "bin" / "Release" / "net8.0"
    copied_any = False

    for filename in RCONCLI_BUNDLE_FILES:
        copied_any = copy_if_exists(source_dir / filename, RCONCLI_DIR / filename) or copied_any

    exe_path = RCONCLI_DIR / "RconCli.exe"
    return exe_path if copied_any and exe_path.exists() else None



def ensure_download(filename: str, spec: dict) -> Path | None:
    target = Path(spec["target"])
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(spec["url"], timeout=20) as response:
            data = response.read()
        target.write_bytes(data)
        return target
    except Exception as exc:
        print(f"[launcher] failed to download {filename}: {exc}")
        return None



def main() -> int:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    rconcli_path = ensure_rconcli_bundle()

    resolved = {
        "rconcli_path": str(rconcli_path) if rconcli_path else "",
        "rcon_script_path": "",
    }

    for filename, spec in DOWNLOADS.items():
        out = ensure_download(filename, spec)
        if filename == "TheIsle_RCON.py" and out:
            resolved["rcon_script_path"] = str(out)

    LAUNCHER_PATHS_FILE.write_text(json.dumps(resolved, indent=2), encoding="utf-8")

    print("[launcher] setup complete")
    print(f"[launcher] rconcli_path={resolved['rconcli_path'] or 'NOT FOUND'}")
    print(f"[launcher] rcon_script_path={resolved['rcon_script_path'] or 'NOT FOUND'}")
    print(f"[launcher] wrote {LAUNCHER_PATHS_FILE.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
