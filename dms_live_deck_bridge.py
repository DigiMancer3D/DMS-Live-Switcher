"""Small, in-process Deck Card Widget adapter; installed next to existing Tk app.

The runtime command file is only written by the separately launched local switcher.
No global key injection, HTTP server, Qt, or OBS changes.
"""
from __future__ import annotations
import json, os, re, tempfile, time
from pathlib import Path

def read(path):
    try:return json.loads(Path(path).read_text('utf-8'))
    except (OSError,ValueError):return {}

def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.dms-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

BORDER_STYLES = {'SPONSOR':'#ff2424','PARTNER':'#2f78ff','DEETS':'#a34dff',
                 'FAN':'#38b86b','SPECIAL':'#ff5ca8','UNI':'#26d9e8','OBS':'#ff00ff'}

def border_color(card):
    category=str(card.get('deck_border_type','')).upper().strip()
    if category in BORDER_STYLES: return BORDER_STYLES[category]
    style=card.get('style',{}) if isinstance(card.get('style'),dict) else {}
    border=card.get('border',{}) if isinstance(card.get('border'),dict) else {}
    value=card.get('special_border_color') or card.get('border_color') or style.get('special_border_color') or (border.get('color') if border.get('enabled') else None)
    return value if isinstance(value,str) and re.fullmatch(r'#[A-Fa-f0-9]{6}',value) else '#666c78'

def attach(app, runtime):
    app._dms_runtime=Path(runtime)
    app._dms_cmdfile=app._dms_runtime/'dms_live_command.json'
    # Ignore leftovers on restart. Every live user press produces a newer seq.
    app._dms_seq=int(read(app._dms_cmdfile).get('seq',0) or 0)
    app._dms_error=''
    app.root.after(450,lambda:_tick(app))

def _switch(app,payload):
    path=Path(str(payload.get('path',''))).expanduser().resolve()
    if path.suffix.lower()!='.buttstore' or not path.is_file():
        raise ValueError('Requested .buttstore is missing')
    # Only read existing files; no automatic default-store creation for arbitrary input.
    header=read(path)
    if header.get('buttstore_format')!='3DCP-BUTTSTORE':
        raise ValueError('Unsupported .buttstore format')
    target=str(payload.get('card_id',''))
    if not any(c.get('id')==target for c in header.get('body',{}).get('cards',[]) if isinstance(c,dict)):
        raise ValueError('Requested card no longer exists in that store')
    if app.store.path.resolve()!=path:
        # Preserve any edits in the old store before switching context.
        app.save_now()
        app.store=type(app.store).load_or_create(path)
        under=app.store.data['under_header']
        app.scan_loop_var.set(bool(under.get('scan_loop',False)))
        app.output_visible_var.set(bool(under.get('output_visible',True)))
        app.resource_profile_var.set(app.store.data['header'].get('resource_profile','low'))
        app.scan_speed_var.set(int(under.get('scan_speed_ms',67)))
        app.scanner_color_var.set(under.get('scanner_color','#00ff99'))
        app.speed_scale.set(app.scan_speed_var.get())
        app.speed_label.configure(text=f'{app.scan_speed_var.get()} ms')
        app.qr_cache_key=None;app.qr_photo=None
        app.base_image_cache={};app.rendered_image_cache={}
        app.refresh_deck_buttons()
        # CRITICAL: reset old-store editor fields before select_card writes them to the new store.
        app.load_active_card_into_editor()
    app.select_card(target)
    app.status_var.set(f'Live Switcher: {app.store.active_card().get("label",target)}')

def _tick(app):
    try:
        cmd=read(app._dms_cmdfile)
        seq=int(cmd.get('seq',0) or 0)
        if seq>app._dms_seq:
            app._dms_seq=seq
            try:
                if cmd.get('command')=='load_and_select':
                    _switch(app,cmd.get('payload',{}) or {})
                    app._dms_error=''
                else:raise ValueError('Unknown DMS action')
            except Exception as exc:
                app._dms_error=str(exc)
                app.status_var.set('Live Switcher error: '+str(exc))
        cards=[{'id':str(c.get('id','')),'label':str(c.get('label','Card')),'color':border_color(c)}
            for c in app.store.cards() if isinstance(c,dict)]
        put(app._dms_runtime/'dms_live_status.json',{
            'pid':os.getpid(), 'heartbeat':time.time(),'store_path':str(app.store.path.resolve()),
            'active_card_id':app.store.data['header'].get('active_card_id',''),
            'cards':cards,'ack_seq':app._dms_seq,'last_error':app._dms_error})
    except Exception as exc:
        print('[DMS Live Switcher bridge]',exc)
    finally:
        app.root.after(500,lambda:_tick(app))
