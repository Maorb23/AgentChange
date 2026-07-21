"""Install the working tree into the documented personal plugin marketplace."""

from __future__ import annotations

import json
import shutil
import argparse
from pathlib import Path

PLUGIN_NAME = "agentchange"
ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
TARGET = HOME / "plugins" / PLUGIN_NAME
MARKETPLACE = HOME / ".agents" / "plugins" / "marketplace.json"
COPY_PATHS = [".codex-plugin", "hooks", "skills", "agentchange", "scripts", "pyproject.toml", "README.md"]


def copy_source() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for relative in COPY_PATHS:
        source = ROOT / relative
        destination = TARGET / relative
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        elif source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def update_marketplace() -> str:
    MARKETPLACE.parent.mkdir(parents=True, exist_ok=True)
    if MARKETPLACE.exists():
        data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    else:
        data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    data.setdefault("interface", {}).setdefault("displayName", "Personal")
    plugins = data.setdefault("plugins", [])
    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Developer Tools",
    }
    plugins[:] = [plugin for plugin in plugins if plugin.get("name") != PLUGIN_NAME]
    plugins.append(entry)
    temporary = MARKETPLACE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MARKETPLACE)
    return str(data["name"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--copy-only", action="store_true", help="update an existing personal plugin source without rewriting its marketplace entry")
    args = parser.parse_args()
    copy_source()
    print(f"Installed source at {TARGET}")
    if args.copy_only:
        print("Preserved the existing marketplace entry (--copy-only).")
        marketplace_name = "<existing-marketplace>"
    else:
        marketplace_name = update_marketplace()
        print(f"Registered in {MARKETPLACE} as {PLUGIN_NAME}@{marketplace_name}")
    print(f"Install the runner: python -m pip install {TARGET}")
    print(f"Next: codex plugin add {PLUGIN_NAME}@{marketplace_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
