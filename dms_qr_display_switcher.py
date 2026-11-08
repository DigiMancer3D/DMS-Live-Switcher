"""Non-invasive Tk add-on: DMS QR-data control + local FGF pairing endpoint.

Runs only inside DMS Live Switcher. No network access outside 127.0.0.1.
Requires Deck Card Widget alpha.2 and dms_qr_display_deck bridge.
"""
from __future__ import annotations
import http.server
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
from tkinter import ttk

PORT = 48373
_STATE_DIR = Path(os.environ.get('DMS_LIVE_SWITCH_DATA', Path.home() / '.local/share/dms-live-switcher')).expanduser()
_PAIR_FILE = _STATE_DIR / 'fgf_qr_pairing_token.txt'
_INSTALLED = False


def _read(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.display-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as file:
            json.dump(data, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _token():
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if _PAIR_FILE.is_file():
        value = _PAIR_FILE.read_text(encoding='utf8').strip()
        if len(value) >= 32:
            return value
    value = secrets.token_urlsafe(32)
    fd = os.open(str(_PAIR_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf8') as file:
        file.write(value + '\n')
    return value


def _widget_caption(widget):
    try:
        value = widget.cget('text')
        if value:
            return str(value)
    except tk.TclError:
        pass
    try:
        name = widget.cget('textvariable')
        return str(widget.getvar(name)) if name else ''
    except (tk.TclError, AttributeError):
        return ''


def _walk(parent):
    for child in parent.winfo_children():
        yield child
        yield from _walk(child)


class Controller:
    def __init__(self, root):
        self.root = root
        self.button = None
        self.runtime = None
        self.requested_seq = 0
        self.last_notice = ''
        self.token = _token()
        self.server = None
        self.try_attach()

    def deck_runtime(self):
        # Mirrors the existing DMS switch_core.deck_runtime conventions.
        env = os.environ.get('DCP3_CONSOLE_USER_DATA', '')
        if env:
            return Path(env).expanduser() / 'runtime'
        config = _read(_STATE_DIR / 'switcher.json')
        specified = os.environ.get('DMS_DECK_ROOT', '') or str(config.get('deck', ''))
        roots = [specified, '~/SBC_Streamer_Apps/Deck-Card-Widget', '~/Deck-Card-Widget']
        for candidate in roots:
            if candidate:
                path = Path(candidate).expanduser()
                if (path / '3dcp_perspective_console.py').is_file():
                    return path.parent / 'user_data/runtime'
        return None

    def status(self):
        runtime = self.deck_runtime()
        data = _read(runtime / 'dms_qr_display_status.json') if runtime else {}
        try:
            alive = bool(data.get('heartbeat')) and time.time() - float(data['heartbeat']) <= 3.5
        except (TypeError, ValueError):
            alive = False
        return {'connected': alive, 'live_qr_data': bool(data.get('live_qr_data')) if alive else False,
                'saved_mode': data.get('saved_mode', '') if alive else '',
                'effective_mode': data.get('effective_mode', '') if alive else '',
                'ack_seq': data.get('ack_seq', 0) if alive else 0,
                'last_error': data.get('last_error', '') if alive else ''}

    def set_mode(self, mode):
        state = self.status()
        runtime = self.deck_runtime()
        if not state['connected'] or runtime is None:
            raise RuntimeError('Deck Card Widget QR bridge is offline; restart the updated Deck app')
        # Avoid duplicate toggles before the Deck event loop confirms the first one.
        if self.requested_seq and int(state.get('ack_seq', 0)) < self.requested_seq:
            raise RuntimeError('Previous display change is still pending')
        if mode not in ('qr-data', 'full-data', 'toggle'):
            raise ValueError('Invalid mode')
        wanted = (not state['live_qr_data']) if mode == 'toggle' else (mode == 'qr-data')
        command = runtime / 'dms_qr_display_command.json'
        old = _read(command)
        seq = max(int(old.get('seq', 0) or 0) + 1, time.time_ns())
        _write(command, {'schema': 'dms.qr-display/1', 'seq': seq,
                         'command': 'set_live_qr_data', 'payload': {'enabled': wanted}})
        self.requested_seq = seq
        return {'accepted': True, 'pending': True, 'requested_qr_data': wanted, 'seq': seq}

    def set_studio_cue(self, payload):
        """Only select existing items in the DMS rails; FGF never supplies a filesystem path."""
        import re
        import switch_core as core
        cue = payload.get('cue') if isinstance(payload, dict) else None
        if not isinstance(cue, dict):
            raise ValueError('Expected a studio cue object')
        if set(cue) - {'card', 'board', 'display', 'scope', 'pageId', 'ref'}:
            raise ValueError('Unsupported studio cue fields')
        data = _read(_STATE_DIR / 'switcher.json')
        if not isinstance(data.get('decks', []), list) or not isinstance(data.get('boards', []), list):
            raise ValueError('DMS rail catalog is invalid')
        card, board, display = cue.get('card'), cue.get('board', ''), cue.get('display', 'keep')
        if card is not None and not isinstance(card, dict):
            raise ValueError('Invalid Deck Card identifier')
        if not isinstance(board, str) or not isinstance(display, str) or display not in ('keep', 'qr-data', 'full-data'):
            raise ValueError('Invalid pinboard or display selection')
        if not card and not board and display == 'keep':
            raise ValueError('Nothing is assigned to this cue')
        deck_command = None
        board_command = None
        if card:
            if set(card) != {'collection', 'id'}:
                raise ValueError('Deck Card must specify a collection filename and card ID')
            collection, ident = card['collection'], card['id']
            if not isinstance(collection, str) or not isinstance(ident, str) or not collection or not ident or len(ident)>120:
                raise ValueError('Invalid Deck Card reference')
            if collection != Path(collection).name or not collection.lower().endswith('.buttstore'):
                raise ValueError('Use an exact .buttstore filename, not a path')
            candidates = [x for x in data['decks'] if isinstance(x,dict) and x.get('id') == ident
                          and Path(str(x.get('source',''))).name == collection]
            if len(candidates) != 1:
                raise ValueError('Card not uniquely registered in DMS rails: ' + collection + ' / ' + ident)
            path = Path(candidates[0]['source']).expanduser().resolve()
            if path.suffix.lower() != '.buttstore' or not path.is_file():
                raise ValueError('Registered .buttstore file is missing')
            store = _read(path)
            if store.get('buttstore_format') != '3DCP-BUTTSTORE' or not any(
                isinstance(c,dict) and c.get('id')==ident for c in store.get('body',{}).get('cards',[])):
                raise ValueError('Registered card is missing from the selected .buttstore')
            runtime = self.deck_runtime()
            if runtime is None:
                raise RuntimeError('Deck Card Widget was not located by DMS')
            status = _read(runtime / 'dms_live_status.json')
            if time.time()-float(status.get('heartbeat',0) or 0)>5:
                raise RuntimeError('Deck Card Widget card-selection bridge is offline')
            deck_command = (runtime / 'dms_live_command.json', {'path':str(path), 'card_id':ident})
        if board:
            if board != Path(board).name or not board.lower().endswith('.sboard'):
                raise ValueError('Use an exact .sboard filename, not a path')
            candidates=[x for x in data['boards'] if isinstance(x,dict) and Path(str(x.get('path',''))).name == board]
            if len(candidates) != 1:
                raise ValueError('Board not uniquely registered in DMS rails: '+board)
            path=Path(candidates[0]['path']).expanduser().resolve()
            if path.suffix.lower()!='.sboard' or not path.is_file():
                raise ValueError('Registered .sboard preset is missing')
            root=core.discover_sbc(str(data.get('sbc','')))
            if not root:
                raise RuntimeError('Streamer Board Console is not configured')
            slot=int(data.get('slot',1) or 1)
            if not 1<=slot<=64:
                raise ValueError('Invalid DMS pinboard slot')
            active=core.live_board(root,slot)
            if not active or not active.get('instance_id'):
                raise RuntimeError(f'Pinboard slot {slot} is not running')
            command=core.sbc_userdata(root)/'board_instances'/'commands'/(str(active['instance_id'])+'.command.json')
            board_command=(command,{'path':str(path)})
        if display != 'keep':
            state=self.status()
            if not state['connected']:
                raise RuntimeError('Deck QR-data bridge is offline')
            if self.requested_seq and int(state.get('ack_seq',0))<self.requested_seq:
                raise RuntimeError('QR-data mode change is still pending')
        # Validated ALL requested targets before queuing a single action.
        results=[]
        if deck_command:
            p,info=deck_command
            old=_read(p)
            seq=max(int(old.get('seq',0) or 0)+1,time.time_ns())
            _write(p,{'seq':seq,'command':'load_and_select','payload':info})
            results.append({'target':'deck','state':'queued','seq':seq})
        if board_command:
            p,info=board_command
            old=_read(p)
            seq=max(int(old.get('seq',0) or 0)+1,time.time_ns())
            _write(p,{'seq':seq,'command':'swap_state','payload':info})
            results.append({'target':'pinboard','state':'queued','seq':seq})
        if display != 'keep':
            result=self.set_mode(display)
            results.append({'target':'display','state':'queued','seq':result['seq']})
        return {'accepted':True,'queued':results,'status':'queued_not_confirmed'}

    def toggle(self):
        try:
            self.set_mode('toggle')
            self.button.configure(text='Change Display: SWITCHING…')
        except Exception as exc:
            messagebox.showwarning('QR-data display', str(exc), parent=self.root)

    def pair_menu(self, ev=None):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label='Copy FGF pairing code', command=self.copy_token)
        menu.add_command(label='Check Deck QR connection', command=self.connection_info)
        if self.server is None:
            menu.add_command(label='FGF control server not running', state='disabled')
        menu.tk_popup(ev.x_root if ev else self.root.winfo_rootx(), ev.y_root if ev else self.root.winfo_rooty())

    def copy_token(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.token)
        self.root.update_idletasks()
        messagebox.showinfo('FGF pairing', 'Pairing code copied to clipboard. Paste it into the FGF broadcaster when asked. Avoid showing it on stream.', parent=self.root)

    def connection_info(self):
        state = self.status()
        messagebox.showinfo('Deck QR connection', f"Connected: {state['connected']}\nLive QR-data: {state['live_qr_data']}\nEffective active card: {state['effective_mode']}", parent=self.root)

    def try_attach(self, attempts=0):
        if not self.root.winfo_exists():
            return
        matches = [w for w in _walk(self.root) if isinstance(w, (tk.Button, ttk.Button)) and 'Hide Click:' in _widget_caption(w)]
        if not matches:
            if attempts < 30:
                self.root.after(250, lambda: self.try_attach(attempts + 1))
            return
        hide = matches[0]
        parent = hide.master
        # Keep the exact parent/row, place to the left of Hide Click. Do not replace widgets.
        cls = ttk.Button if isinstance(hide, ttk.Button) else tk.Button
        settings = {'text': 'Change Display: OFFLINE', 'command': self.toggle}
        if cls is tk.Button:
            for attr in ('background', 'foreground', 'activebackground', 'relief', 'bd'):
                try:
                    settings[attr] = hide.cget(attr)
                except tk.TclError:
                    pass
        button = cls(parent, **settings)
        manager = hide.winfo_manager()
        if manager == 'pack':
            info = hide.pack_info()
            side = info.get('side', 'right')
            if side != 'right':
                # Any placement other than a right-aligned header is ambiguous: fail closed.
                button.destroy()
                return
            button.pack(side='right', after=hide, padx=(0, 8), pady=info.get('pady', 0))
        elif manager == 'grid':
            info = hide.grid_info()
            row = int(info.get('row', 0)); column = int(info.get('column', 0))
            occupants = [w for w in parent.winfo_children() if w is not hide and w.winfo_manager() == 'grid'
                         and int(w.grid_info().get('row', -1)) == row and int(w.grid_info().get('column', -1)) == column - 1]
            if column == 0 or occupants:
                # Cannot guarantee non-overlapping placement; leave existing app unchanged.
                button.destroy()
                return
            button.grid(row=row, column=column-1, padx=(4, 8), pady=info.get('pady', 0), sticky=info.get('sticky', 'e'))
        else:
            button.destroy()
            return
        button.bind('<Button-3>', self.pair_menu)
        self.button = button
        self.start_local_server()
        self.tick()

    def tick(self):
        if not self.button or not self.button.winfo_exists():
            return
        state = self.status()
        label = 'OFFLINE' if not state['connected'] else ('QR-DATA' if state['live_qr_data'] else 'FULL-DATA')
        if self.requested_seq and state['connected'] and int(state.get('ack_seq', 0)) < self.requested_seq:
            label = 'SWITCHING…'
        if self.requested_seq and state['connected'] and int(state.get('ack_seq', 0)) >= self.requested_seq:
            self.requested_seq = 0
        if state['connected'] and state.get('last_error'):
            label = 'ERROR'
        self.button.configure(text='Change Display: ' + label)
        self.root.after(850, self.tick)

    def start_local_server(self):
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return
            def _headers(self, status=200):
                self.send_response(status)
                origin = self.headers.get('Origin', '')
                # Only local broadcaster files or local web hosts, paired with secret token.
                if origin == 'null' or origin.startswith('http://127.0.0.1:') or origin.startswith('http://localhost:'):
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-DMS-Pairing')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
            def _reply(self, value, status=200):
                self._headers(status)
                self.wfile.write(json.dumps(value).encode('utf8'))
            def _allowed(self):
                return secrets.compare_digest(self.headers.get('X-DMS-Pairing', ''), owner.token)
            def do_OPTIONS(self):
                self._headers(204)
            def do_GET(self):
                if self.path != '/v1/status':
                    return self._reply({'error': 'Unknown resource'}, 404)
                if not self._allowed():
                    return self._reply({'error': 'Pairing required'}, 403)
                return self._reply(owner.status())
            def do_POST(self):
                if self.path not in ('/v1/display', '/v1/cue'):
                    return self._reply({'error': 'Unknown resource'}, 404)
                if not self._allowed():
                    return self._reply({'error': 'Pairing required'}, 403)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if length < 1 or length > 2048:
                        raise ValueError('Invalid request length')
                    payload = json.loads(self.rfile.read(length))
                    result = owner.set_studio_cue(payload) if self.path == '/v1/cue' else owner.set_mode(payload.get('mode', 'toggle'))
                    return self._reply(result)
                except (ValueError, RuntimeError, TypeError) as exc:
                    return self._reply({'error': str(exc)}, 409)
        try:
            server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
            server.daemon_threads = True
        except OSError as exc:
            print('[DMS FGF QR bridge] 127.0.0.1 port unavailable:', exc)
            return
        self.server = server
        thread = threading.Thread(target=server.serve_forever, daemon=True, name='DMS-FGF-QR-Bridge')
        thread.start()
        self.root.bind('<Destroy>', lambda e: server.shutdown() if e.widget is self.root else None, add='+')


def install():
    """Hook only Tk root creation, leaving the existing DMS source/flow intact."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    old_init = tk.Tk.__init__
    def init(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        self.after(750, lambda: Controller(self))
    tk.Tk.__init__ = init
