"""Local file-only control protocol, no HTTP sockets or cloud services."""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
from pathlib import Path

APPDATA = Path(os.environ.get('DMS_LIVE_SWITCH_DATA', str(Path.home()/'.local/share/dms-live-switcher'))).expanduser()
STATE = APPDATA / 'switcher.json'
EP_RE = re.compile(r'(?i)(?<![a-z0-9])ep\s*[-#:]*\s*\d+')
BORDER_STYLES = {'SPONSOR':'#ff2424','PARTNER':'#2f78ff','DEETS':'#a34dff',
                 'FAN':'#38b86b','SPECIAL':'#ff5ca8','UNI':'#26d9e8','OBS':'#ff00ff'}


def load_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {} if default is None else default


def atomic_json(p: Path, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.dms-', suffix='.tmp', dir=p.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, p)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def next_command(path: Path, action: str, payload: dict):
    old = load_json(path, {})
    seq = max(int(old.get('seq', 0) or 0) + 1, time.time_ns())
    atomic_json(path, {'seq': seq, 'command': action, 'payload': payload})
    return seq


def is_pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, TypeError, ProcessLookupError, PermissionError, OSError):
        return False


def board_color(name: str, active: bool = False):
    return '#b52a38' if active else ('#7139ba' if EP_RE.search(name) else '#23734f')


def card_color(card: dict):
    """Only explicit card-level styling, never the shared/global label border."""
    category = str(card.get('deck_border_type','')).upper().strip()
    if category in BORDER_STYLES:
        return BORDER_STYLES[category]
    style = card.get('style', {}) if isinstance(card.get('style'), dict) else {}
    border = card.get('border', {}) if isinstance(card.get('border'), dict) else {}
    color = card.get('special_border_color') or card.get('border_color') or style.get('special_border_color') or (border.get('color') if border.get('enabled') else None)
    if isinstance(color, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        return color
    return '#666c78'


def label_color(bg: str):
    r,g,b = (int(bg[i:i+2], 16) for i in (1,3,5))
    return '#121212' if (r*299+g*587+b*114)/1000 > 170 else '#ffffff'


def read_buttstore(path: Path):
    data = load_json(path, {})
    if data.get('buttstore_format') != '3DCP-BUTTSTORE':
        raise ValueError('Not a supported 3DCP .buttstore file')
    cards = data.get('body', {}).get('cards', [])
    if not isinstance(cards, list):
        raise ValueError('No card list in .buttstore')
    return [{'id':str(c.get('id','')), 'label':str(c.get('label',c.get('id','Card'))), 'color':card_color(c)} for c in cards if isinstance(c,dict) and c.get('id')]


def discover_sbc(explicit: str = ''):
    candidates = [explicit, os.environ.get('SBC_ROOT',''), '~/streamer-board-console', '~/Streamer-Board-Console', '~/SBC_Streamer_Apps/Streamer-Board-Console', '~/SBC_Streamer_Apps/Streamer_Board_Console']
    for entry in candidates:
        if entry:
            p=Path(entry).expanduser()
            if (p/'pin_board_instance.py').is_file() and (p/'sbc_core/board_registry.py').is_file():
                return p.resolve()
    return None


def discover_deck(explicit: str = ''):
    candidates = [explicit, os.environ.get('DMS_DECK_ROOT',''), '~/SBC_Streamer_Apps/Deck-Card-Widget', '~/SBC_Streamer_Apps/Deck_Card_Widget', '~/Deck-Card-Widget', '~/Deck_Card_Widget']
    for entry in candidates:
        if entry:
            p=Path(entry).expanduser()
            if (p/'3dcp_perspective_console.py').is_file():
                return p.resolve()
    return None


def sbc_userdata(root: Path):
    return Path(os.environ.get('SBC_USER_DATA') or (root/'user_data')).expanduser()


def deck_runtime(root: Path):
    override=os.environ.get('DCP3_CONSOLE_USER_DATA')
    data=Path(override).expanduser() if override else (root.parent/'user_data')
    return data/'runtime'


def live_board(sbc_root: Path, slot=1):
    folder=sbc_userdata(sbc_root)/'board_instances'
    best=None
    for p in folder.glob('*.status.json'):
        info=load_json(p, {})
        try:
            fresh = time.time()-float(info.get('heartbeat',0)) < 10
            if int(info.get('slot',0)) != slot or not fresh or not is_pid_alive(info.get('pid')):
                continue
            if best is None or float(info['heartbeat']) > float(best['heartbeat']):
                best=info
        except (ValueError, TypeError):
            continue
    return best


def safe_path(path: str, suffix: str):
    p=Path(path).expanduser().resolve()
    if p.suffix.lower()!=suffix or not p.is_file():
        raise ValueError(f'Expected an existing {suffix} file: {p}')
    return p
