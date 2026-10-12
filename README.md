# DMS Live Switcher

**An independent, local desktop control panel for live-streaming pinboards and deckcards.**

DMS Live Switcher provides two horizontally scrollable button rails: one for switching **Streamer Board Console** `.sboard` pinboards and one for selecting cards from **Deck Card Widget** `.buttstore` collections. It is designed for quick changes during live broadcasts without rebuilding an OBS scene or opening multiple editing windows.

> **Release:** `v0.1.0-alpha.1-r1` (public preview)  
> **Platform:** Linux desktop; developed for CachyOS / KDE Plasma 6  
> **Runtime:** Python 3 and Tkinter; no network service or account required  
> **Status:** The maintainer has reported successful launch through Streamer Board Console and successful control of both target applications. Compatibility with other versions and setups is not guaranteed.

## Features

- **Top rail — Pinboards:** Add `.sboard` presets, click to swap the state of an existing Streamer Board Console pinboard instance, and scroll through as many saved buttons as needed.
- **Bottom rail — Deckcards:** Use **Sync running** to read cards from an open Deck Card Widget, or **Load .buttstore** to add cards from a saved collection. Click a card to select it in the running widget.
- **Hold a button** (approximately 600 ms) for management actions. Pinboards: **Reload / Swap / Name / Drop**. Deckcards: **Reload / Name / Drop**. Dropping a button removes it *from the switcher*, not from its source file.
- **Color cues:** Regular pinboards are green; labels containing `EP` followed by a number are purple; the active pinboard is red. Deck buttons are grey unless the card has a supported special border color. Native Deck Card Widget border types include Sponsor, Partner, Deets, Fan, Special, Uni, and OBS.
- **Local-only communication:** Commands and status use local files; no HTTP listener, cloud connection, or simulated global keyboard input.
- **KDE desktop integration:** Application menu launcher, icon and taskbar matching; optional registration in Streamer Board Console's built-in **Adapter Templates** system.
- **Saved switcher layout:** Button labels and references persist in `~/.local/share/dms-live-switcher/switcher.json`, outside the installation folder.

## Get the program

The project is intended to live at **`DigiMancer3D/DMS-Live-Switcher`** on GitHub. Once that repository has been created and published, choose either:

**Option A — GitHub Releases:** Open the repository's **Releases** page, download the latest `*_PUBLIC.zip` release, and extract it.

**Option B — Clone the repository:**

```bash
git clone https://github.com/DigiMancer3D/DMS-Live-Switcher.git
cd DMS-Live-Switcher
```

The clone URL becomes usable **after the repository is created**. This preview also supports running directly from the extracted source directory without desktop registration using `bash run.sh`.

## Requirements

- Linux desktop with a graphical session (tested in a development environment with Python 3, Tkinter and KDE-style launchers).
- Python 3 with the Tk GUI module (`tkinter`). On CachyOS / Arch-based systems, the usual packages are `python` and `tk`.
- For actual content switching: compatible local installations of **[Streamer Board Console](https://github.com/DigiMancer3D/Streamer-Board-Console)** and **[Deck Card Widget](https://github.com/DigiMancer3D/Deck-Card-Widget)**. The apps must be running for live switching.
- No Python packages from `pip` are required for the switcher itself.

## Install a desktop application (CachyOS / KDE)

**Do not install into a temporary extracted-release folder or an external drive you may unmount.** The desktop installer copies the program into a stable location under your home directory.

From a terminal opened in the extracted source folder:

```bash
bash scripts/install_desktop.sh install
```

This installs the program to:

```text
$HOME/Applications/DMS_Live_Switcher
```

It also creates a **DMS Live Switcher** entry in the KDE applications menu and installs icons in your user profile. No `sudo` is required. Launch it from KDE, or run:

```bash
bash "$HOME/Applications/DMS_Live_Switcher/run.sh"
```

If that permanent directory already exists, `install` **refuses to overwrite it**. To install a future source release over an existing installation, run `bash scripts/install_desktop.sh upgrade` **from the new extracted release**. This backs up the previous program directory; your switcher layout remains outside it.

To remove *only* the menu launcher/icons (not the app or data):

```bash
bash "$HOME/Applications/DMS_Live_Switcher/scripts/install_desktop.sh" remove
```

## Add to Streamer Board Console's built-in Apps system

The Streamer Board Console application manager can launch and monitor DMS Live Switcher independently of the pinboard/deck bridges:

1. Open Streamer Board Console and select **Apps → Adapter Templates → New Template Entry**.
2. Set **Path** to the **absolute** permanent installation directory, e.g. `/home/YOUR_USER/Applications/DMS_Live_Switcher` (replace `YOUR_USER` with your Linux username).
3. Set **Entry** to `run.sh`.
4. Click **Create Template From Entry**, then **Refresh Templates**.
5. Verify **Path OK = YES**, **Entry OK = YES**, then **Enable Selected Template**.
6. **Completely close and reopen Streamer Board Console** so it rebuilds its active application controls. Merely refreshing the templates list may not update active adapters.
7. Find DMS Live Switcher under **Active App Adapters** and launch it.

**Important:** Use `$HOME/Applications/DMS_Live_Switcher`, **not** the download/extraction directory. If a previously registered template points to a former location, **edit the existing template path** instead of adding a duplicate.

See [`docs/STREAMER_BOARD_CONSOLE_REGISTRATION.md`](docs/STREAMER_BOARD_CONSOLE_REGISTRATION.md) for troubleshooting.

## Connect pinboards and deckcards (bridges)

**Desktop/App registration does not install the live-control bridges.** The pinboard path uses Streamer Board Console's native `swap_state` action where available; the Deck Card Widget requires a small in-process bridge. Both original programs keep ownership of their output windows.

First, locate the **actual** source directories for your installed target applications. From the permanent DMS installation folder, with both target applications closed:

```bash
cd "$HOME/Applications/DMS_Live_Switcher"
bash verify.sh \
  --sbc "/path/to/Streamer-Board-Console" \
  --deck "/path/to/Deck-Card-Widget"
```

The verification performs tests and a **read-only** source compatibility check; it does not change either application. If it passes and the paths match your installations, apply the reversible integration:

```bash
python3 scripts/install_bridges.py \
  --sbc "/path/to/Streamer-Board-Console" \
  --deck "/path/to/Deck-Card-Widget" \
  --apply
```

The installer backs up modified files and stores its rollback manifest in `~/.local/share/dms-live-switcher/`. It only applies changes when expected source-code anchors match; if a version differs, the safe response is to stop and update the bridge compatibility, not force the patch.

Restart Streamer Board Console (including its active pinboard instance) and Deck Card Widget, then open DMS. Use **Locate apps** if the switcher doesn't find both source directories.

**Rollback:** Close both target applications, then run:

```bash
python3 scripts/install_bridges.py --rollback
```

This restores installer-backed-up source files. It does not delete existing user boards or cards. For additional details, read [`docs/BRIDGE_AND_DATA_SAFETY.md`](docs/BRIDGE_AND_DATA_SAFETY.md).

## Using the rails

**Pinboard rail:** Select `+ Add .sboard` and choose board preset files. To swap, first launch a pinboard instance inside Streamer Board Console; select the matching slot (1–64) in DMS, then click a preset. The currently displayed board is marked live. The pinboard instance/window stays in place for capture in OBS.

**Deckcard rail:** Open Deck Card Widget, click **Sync running**, or click **Load .buttstore** to import card references. Clicking a button requests the card in its original `.buttstore` using the bridge. The actual source card storage remains managed by Deck Card Widget.

The colored controls are status cues, not an indication that a stream has started: **red on a pinboard indicates the active preset**, not confirmation from OBS that you are broadcasting.

## Test and troubleshoot

Run unit tests (does not need installed target apps):

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

For integration verification with the actual apps use `bash verify.sh --sbc ... --deck ...` as shown earlier.

| Symptom | Check |
| --- | --- |
| DMS is enabled in Adapter Templates but missing under active apps | Fully restart Streamer Board Console. |
| Console cannot launch DMS | Make sure Path points to the **permanent** installed folder and Entry is `run.sh`. |
| KDE icon appears generic | Launch from the KDE application menu once, then re-pin the running app. |
| Pinboard switch fails | Check that a pinboard slot is running and that the `.sboard` is valid. |
| Deck bridge doesn't respond | Confirm the Deck application was restarted from the modified source directory and that the bridge installation succeeded. |
| Bridge compatibility check rejects local source | Do not force patching; check target app version/paths and report the mismatch. |

## Local data and privacy

- The source release contains **no saved user layouts, board collections, deckcard libraries, accounts, or credentials**.
- Live layout preferences may include **personal file paths and button labels** in `~/.local/share/dms-live-switcher/switcher.json`; don't commit or share those without reviewing them.
- Bridge backups may contain modified source files from local installations and are **not included** in the repository/release.
- No analytics, login, or cloud sync is implemented. The app uses local filesystem commands/status, intended for the same trusted desktop account.
- Only load `.sboard`/`.buttstore` files you trust, and test compatibility off-air before using it in a production show.

## Project organization

```text
DMS-Live-Switcher/
├── README.md
├── dms_live_switcher.py       # Tk control panel
├── switch_core.py             # File protocol and color logic
├── dms_live_deck_bridge.py    # Deck Card Widget integration
├── run.sh
├── verify.sh
├── assets/                    # Desktop icons
├── scripts/                   # Desktop + bridge installers
├── docs/                      # Integration, safety and compatibility
└── tests/                     # Automated checks
```

## Related projects

- [Streamer Board Console](https://github.com/DigiMancer3D/Streamer-Board-Console) — streaming console and pinboards.
- [Deck Card Widget](https://github.com/DigiMancer3D/Deck-Card-Widget) — card creator and player.

This is a companion controller, **not** a replacement for either project. It does not install or bundle their full source code.

## Development and release status

This is an **alpha**: API/source patch anchors can change in newer versions of the companion applications. Keep backups and test off-air. The source release preserves the code from the `v0.1.0-alpha.1-r1` desktop build and removes unrelated private production materials.

**Licensing:** A license has not yet been selected for this project. Before inviting public redistribution or contributions, add an explicit `LICENSE` file reflecting your chosen terms. A public GitHub repository is not automatically open-source licensed.
