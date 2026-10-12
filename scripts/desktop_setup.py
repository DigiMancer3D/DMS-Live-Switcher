#!/usr/bin/env python3
"""Local KDE desktop installation; no sudo, network or changes to app bridges.

The app lives at ~/Applications/DMS_Live_Switcher; state lives elsewhere.
Run via `bash scripts/install_desktop.sh install` even on exFAT filesystems.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
HOME = Path.home()
APPDIR = HOME / "Applications" / "DMS_Live_Switcher"
DESKTOP = HOME / ".local/share/applications/dms-live-switcher.desktop"
ICON_DIR = HOME / ".local/share/icons/hicolor"
ICONS = [
    (HERE / "assets/dms-live-switcher.svg", ICON_DIR / "scalable/apps/dms-live-switcher.svg"),
    (HERE / "assets/dms-live-switcher-256.png", ICON_DIR / "256x256/apps/dms-live-switcher.png"),
    (HERE / "assets/dms-live-switcher-128.png", ICON_DIR / "128x128/apps/dms-live-switcher.png"),
    (HERE / "assets/dms-live-switcher-64.png", ICON_DIR / "64x64/apps/dms-live-switcher.png"),
]


def desktop_arg(value: str) -> str:
    """Quote and desktop-escape a single Exec argument (never start a shell)."""
    if "\n" in value or "\r" in value:
        raise ValueError("Newline in installation directory is unsupported")
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{value}"'


def desktop_contents():
    if "\n" in str(APPDIR):
        raise ValueError("Newline in installation directory is unsupported")
    # Keep the desktop icon and filename constant for reliable KDE task manager matching.
    return "\n".join([
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        "Name=DMS Live Switcher",
        "GenericName=Pinboard and Deck Card Controller",
        "Comment=Switch Streamer Board pinboards and Deck Card Widget cards",
        "Exec=/usr/bin/env bash " + desktop_arg(str(APPDIR / 'run.sh')),
        "Path=" + str(APPDIR).replace("%", "%%"),
        "TryExec=python3",
        "Icon=dms-live-switcher",
        "Terminal=false",
        "StartupNotify=true",
        "StartupWMClass=Dmsliveswitcher",
        "Categories=Utility;",
        "Keywords=DMS;Streamer;Pinboard;Deck;OBS;",
        "X-KDE-SubstituteUID=false",
        "",
    ])


def refresh_kde():
    # Best-effort, not a hard requirement; launcher is discoverable at next login as well.
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        path = shutil.which(tool)
        if path:
            try:
                subprocess.run([path, "--noincremental"], check=False, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                pass
            break


def check_source(source: Path):
    for rel in ["run.sh", "dms_live_switcher.py", "switch_core.py",
                "scripts/install_bridges.py", "assets/dms-live-switcher.svg",
                "assets/dms-live-switcher-128.png"]:
        if not (source / rel).is_file():
            raise ValueError(f"Missing package member: {source / rel}")


def install(upgrade: bool = False):
    check_source(HERE)
    APPDIR.parent.mkdir(parents=True, exist_ok=True)
    same = HERE.resolve() == APPDIR.resolve()
    backup = None
    if not same:
        if APPDIR.exists():
            if not upgrade:
                raise FileExistsError(
                    f"Existing installation at {APPDIR}. No changes made. "
                    "Run `bash scripts/install_desktop.sh upgrade` to back it up and update."
                )
            backups = HOME / ".local/share/dms-live-switcher/desktop-backups"
            backups.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = backups / f"DMS_Live_Switcher-{stamp}"
        # Copy before renaming any existing app. State/backups are outside APPDIR.
        stage = Path(tempfile.mkdtemp(prefix=".dms-live-switcher-", dir=APPDIR.parent))
        try:
            shutil.copytree(HERE, stage, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", ".pytest_cache"))
            if APPDIR.exists():
                APPDIR.rename(backup)
            try:
                stage.rename(APPDIR)
            except Exception:
                if backup and backup.exists() and not APPDIR.exists():
                    backup.rename(APPDIR)
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    for src, dst in ICONS:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(APPDIR / src.relative_to(HERE), dst)
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text(desktop_contents(), encoding="utf-8")
    DESKTOP.chmod(0o644)
    refresh_kde()
    print("DMS Live Switcher desktop application installed.")
    print("Program:  ", APPDIR)
    print("Launcher: ", DESKTOP)
    if backup:
        print("Backup:   ", backup)
    print("SBC Apps / Adapter Templates:")
    print("  Path:   ", APPDIR)
    print("  Entry:   run.sh")
    print("Bridge changes: NONE (install these separately after compatibility check).")
    print("User layout and backup data preserved under ~/.local/share/dms-live-switcher/")


def remove():
    # The installed program and valuable user presets are intentionally left alone.
    if DESKTOP.exists():
        txt = DESKTOP.read_text(encoding="utf-8")
        if "Name=DMS Live Switcher" not in txt:
            raise ValueError("Desktop entry was replaced by another app; refusing to remove it")
        DESKTOP.unlink()
    for _src, dst in ICONS:
        if dst.exists():
            dst.unlink()
    refresh_kde()
    print("Desktop launcher and icon removed. Program, Streamer Board registry, bridges, and user data were not removed.")
    print("Program remains:", APPDIR)


def status():
    for label, path in [("Program", APPDIR), ("Launcher", DESKTOP),
                        ("PNG icon", ICONS[1][1])]:
        print(f"{label}: {'OK' if path.exists() else 'MISSING'} — {path}")
    print("Registration: Apps → Adapter Templates; Path =", APPDIR, "; Entry = run.sh")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "upgrade", "remove", "status"], nargs="?", default="install")
    args = parser.parse_args()
    try:
        if args.action == "status": status()
        elif args.action == "remove": remove()
        else: install(upgrade=args.action == "upgrade")
    except (OSError, ValueError) as error:
        print("DMS desktop setup error:", error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
