#!/usr/bin/env python3
"""Verify and optionally install surgical, reversible local app bridges."""
from __future__ import annotations
import argparse, shutil, sys, time, json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from switch_core import discover_sbc, discover_deck, APPDATA, atomic_json, load_json

PIN_ANCHOR='        elif command == "close":\n'
PIN_INJECT='''        elif command == "swap_state":  # DMS_LIVE_SWITCHER_V1
            try:
                external = Path(str(payload.get("path", ""))).expanduser().resolve()
                if external.suffix.lower() != ".sboard" or not external.is_file():
                    raise ValueError("Missing .sboard preset")
                check = read_json(external, {})
                if not isinstance(check, dict) or not isinstance(check.get("pins"), list):
                    raise ValueError("Malformed board preset")
                self.load_board(external)
            except Exception as exc:
                print("DMS Live Switcher pinboard load rejected:", exc)
'''
DECK_ANCHOR='        self.root.after(1200, self.archive_duplicate_buttstores_after_load)\n'
DECK_INJECT='''        from dms_live_deck_bridge import attach as _dms_attach  # DMS_LIVE_SWITCHER_V1
        _dms_attach(self, RUNTIME_DIR)
'''


def edited_pin(text):
    if 'elif command == "swap_state"' in text:
        # Current GitHub source already implements the native, OBS-stable command.
        return text
    if 'DMS_LIVE_SWITCHER_V1' in text:return text
    if text.count(PIN_ANCHOR)!=1 or 'def apply_command(' not in text or 'def load_board(' not in text:
        raise ValueError('Pinboard source version does not match safe patch anchors; unchanged')
    return text.replace(PIN_ANCHOR,PIN_INJECT+PIN_ANCHOR,1)

def edited_deck(text):
    if 'DMS_LIVE_SWITCHER_V1' in text:return text
    if text.count(DECK_ANCHOR)!=1 or 'class PerspectiveConsoleApp:' not in text or 'RUNTIME_DIR =' not in text:
        raise ValueError('Deck source version does not match safe patch anchors; unchanged')
    return text.replace(DECK_ANCHOR,DECK_ANCHOR+DECK_INJECT,1)

def process(root,file,transform,write=False,backup=None):
    target=root/file
    if not target.is_file():raise FileNotFoundError(target)
    old=target.read_text(encoding='utf8')
    new=transform(old)
    compile(new,str(target),'exec')
    if not write:return ('READY' if new!=old else 'INSTALLED'),target
    if new==old:return 'INSTALLED',target
    original=backup/file
    original.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(target,original)
    target.write_text(new,encoding='utf8')
    return 'PATCHED',target

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sbc',help='Streamer Board Console repo folder')
    parser.add_argument('--deck',help='Deck Card Widget repo folder')
    parser.add_argument('--apply',action='store_true',help='Back up then patch both apps; default is read-only check')
    parser.add_argument('--rollback',action='store_true',help='Restore last installer backups (close both apps first)')
    args=parser.parse_args()
    manifest=APPDATA/'patch_manifest.json'
    if args.rollback:
        data=load_json(manifest,{})
        if not data.get('files'):raise SystemExit('No rollback manifest found')
        for src,dst in data['files']:
            if not Path(src).is_file():raise SystemExit('Missing backup '+src)
            shutil.copy2(src,dst);print('RESTORED',dst)
        print('Rollback finished; restart apps.');return
    sbc=discover_sbc(args.sbc or '')
    deck=discover_deck(args.deck or '')
    if not sbc or not deck:raise SystemExit('Locate both repos and pass --sbc /path --deck /path; no files changed.')
    backup=APPDATA/'backups'/time.strftime('%Y%m%d-%H%M%S')
    plan=[(sbc,'pin_board_instance.py',edited_pin), (deck,'3dcp_perspective_console.py',edited_deck)]
    # Preflight BOTH before modifying EITHER.
    for root,name,transform in plan:
        state,path=process(root,name,transform)
        print(state,path)
    bridge_dest=deck/'dms_live_deck_bridge.py'
    if bridge_dest.exists():
        old=bridge_dest.read_bytes()
        desired=(HERE/'dms_live_deck_bridge.py').read_bytes()
        if old!=desired and b'DMS Live Switcher' not in old and b'Live Switcher' not in old:
            raise SystemExit('An unrelated file called dms_live_deck_bridge.py exists. Refusing overwrite.')
    if not args.apply:
        print('READ-ONLY verification passed; add --apply after closing both live applications.')
        return
    restored=[]
    for root,name,transform in plan:
        state,path=process(root,name,transform,True,backup/(root.name))
        if state=='PATCHED':restored.append((str(backup/root.name/name),str(path)))
        print(state,path)
    if bridge_dest.exists():
        target_backup=backup/deck.name/'dms_live_deck_bridge.py'
        target_backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(bridge_dest,target_backup)
        restored.append((str(target_backup),str(bridge_dest)))
    else:
        # On rollback, bridge file can remain inert (not imported when patch is reverted).
        pass
    shutil.copy2(HERE/'dms_live_deck_bridge.py',bridge_dest)
    atomic_json(manifest,{'files':restored,'applied':time.strftime('%Y-%m-%dT%H:%M:%S')})
    print('BRIDGES INSTALLED. Restart both applications. Backups:',backup)

if __name__=='__main__':run()
