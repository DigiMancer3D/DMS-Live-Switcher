#!/usr/bin/env python3
"""Two-rail in-process SBC/Deck switch controller for KDE/OBS (Tkinter)."""
from __future__ import annotations
# DMS FGF QR bridge alpha.1 (non-invasive Tk integration)
import dms_qr_display_switcher as _dms_qr_display
_dms_qr_display.install()
import json
import re
import time
from tether_core import normalize_tethers, normalize_row, delay_seconds, matching_actions, detach_matching, delete_tether_row, remove_row_triggers, clear_all_fields, BLANK_ID
from deck_order import DEFAULT_ORDER, CATEGORIES, normalize_order, toggle_category, swap_category, order_stores, order_cards
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from switch_core import (APPDATA, STATE, load_json, atomic_json, next_command,
    board_color, card_color, label_color, discover_sbc, discover_deck,
    sbc_userdata, deck_runtime, live_board, safe_path, read_buttstore, enrich_deck_refs)

BG='#15191f'; PANEL='#212630'; TEXT='#e8ecf2'; MUTED='#aeb7c3'
VERSION='v0.1.0-alpha.8'

class ScrollRail(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self, height=82, background=PANEL, highlightthickness=0)
        self.canvas.pack(fill='x', expand=True)
        self.bar=ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.bar.pack(fill='x')
        self.canvas.configure(xscrollcommand=self.bar.set)
        self.inner=tk.Frame(self.canvas, background=PANEL)
        self.win=self.canvas.create_window((0,0),window=self.inner,anchor='nw')
        self.inner.bind('<Configure>', lambda _e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e:self.canvas.itemconfigure(self.win,height=e.height))
        # Shift+wheel horizontal; otherwise wheel scrolls the rail as well.
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>',lambda e:self.canvas.xview_scroll(-3,'units'))
        self.canvas.bind('<Button-5>',lambda e:self.canvas.xview_scroll(3,'units'))
        self.inner.bind('<MouseWheel>',self._wheel)
    def _wheel(self,e):
        self.canvas.xview_scroll(-3 if e.delta>0 else 3,'units')
    def clear(self):
        for widget in self.inner.winfo_children():widget.destroy()

class HoldButton(tk.Button):
    """Physical hold opens a menu; release after a hold never triggers a live swap."""
    def __init__(self, parent, *, tap, hold, **kw):
        super().__init__(parent, **kw)
        self.tap_action=tap; self.hold_action=hold; self.job=None; self.held=False
        self.bind('<ButtonPress-1>',self.press)
        self.bind('<ButtonRelease-1>',self.release)
        self.bind('<Leave>',self.cancel)
    def press(self,e):
        self.cancel(); self.held=False
        self.job=self.after(600, self.trigger_hold)
    def trigger_hold(self):
        self.job=None; self.held=True
        self.hold_action(self)
    def release(self,e):
        pending=self.job is not None
        self.cancel()
        if pending and not self.held and 0<=e.x<self.winfo_width() and 0<=e.y<self.winfo_height():
            self.tap_action()
    def cancel(self,e=None):
        if self.job is not None:self.after_cancel(self.job);self.job=None

class LiveSwitcher:
    def __init__(self):
        self.data=load_json(STATE, {})
        self.boards=self.data.get('boards',[])
        self.decks=enrich_deck_refs(self.data.get('decks',[]))
        self.hidden_stores=set(self.data.get('hidden_stores',[]))
        self.show_only=set(self.data.get('show_only',[]))
        try:self.auto_order=normalize_order(self.data.get('auto_order'))
        except ValueError:self.auto_order=list(DEFAULT_ORDER)
        self.swap_category_pending=None
        self.hidden_click=bool(self.data.get('hidden_click',False))
        self.auto_hidden=set()
        self.last_active=None
        self.select_mode=False
        self.selected=set()
        self.store_order=list(dict.fromkeys(self.data.get('store_order',[]) + [c['source'] for c in self.decks]))
        self.blank_requested=bool(self.data.get('blank_requested',False))
        self.blank_path=str((APPDATA/'blank_pinboard.sboard').resolve())
        self.tethers=normalize_tethers(self.data.get('tethers',[]))
        self.pres_open=False;self.pres_line=0;self.pres_page='dc_load'
        self.pres_board=None;self.pres_deck=None
        self.pres_buttons=[];self.pending_jobs=[];self.ignore_events={}
        self.observed_board=None;self.observed_deck=None
        self.last_ack_seq=None;self.manual_deck_ack=None;self.manual_deck_target=None
        self.sbc=discover_sbc(self.data.get('sbc',''))
        self.deck=discover_deck(self.data.get('deck',''))
        self.root=tk.Tk(className='Dmsliveswitcher');self.root.title('DMS Live Switcher — Pinboards + Deck Cards')
        # Match KDE's StartupWMClass and provide a real taskbar/window icon.
        try:
            self.root.iconphoto(True, tk.PhotoImage(file=str(Path(__file__).resolve().parent/'assets/dms-live-switcher-128.png')))
        except (tk.TclError, OSError):
            pass
        self.slot=tk.IntVar(value=int(self.data.get('slot',1)))
        self.root.geometry('980x410');self.root.minsize(650,360)
        self.root.configure(background=BG)
        self.status=tk.StringVar(value='Ready; install both bridges before live use.')
        self._build()
        self.paint()
        self.root.after(800, self.poll)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
    def _build(self):
        style=ttk.Style();style.theme_use('clam')
        style.configure('TFrame', background=BG)
        style.configure('TLabel',background=BG,foreground=TEXT)
        style.configure('TButton',padding=5)
        title=ttk.Frame(self.root);title.pack(fill='x',padx=12,pady=(9,3))
        ttk.Label(title,text='DMS  •  LIVE SWITCHER',font=('TkDefaultFont',14,'bold')).pack(side='left')
        ttk.Label(title,text=VERSION,foreground=MUTED).pack(side='left',padx=(12,0))
        ttk.Button(title,text='Locate apps',command=self.locate).pack(side='right')
        ttk.Button(title,text='ReLoad',command=self.load_dms).pack(side='right',padx=(4,0))
        ttk.Button(title,text='Store',command=self.store_dms).pack(side='right',padx=(4,0))
        ttk.Label(title,text='Pinboard slot:').pack(side='right',padx=(12,3))
        spin=ttk.Spinbox(title,from_=1,to=64,textvariable=self.slot,width=4,command=self.save);spin.pack(side='right')
        spin.bind('<FocusOut>',lambda e:self.save())
        one=ttk.Frame(self.root);one.pack(fill='x',padx=12,pady=(6,0))
        ttk.Label(one,text='PINBOARD PRESETS',font=('TkDefaultFont',10,'bold')).pack(side='left')
        ttk.Button(one,text='+ Add .sboard',command=self.add_board).pack(side='right')
        self.drop_button=ttk.Button(one,text='Drop',command=self.toggle_select)
        self.drop_button.pack(side='right',padx=5)
        self.blank_button=tk.Button(one,text='BLANK',command=self.toggle_blank,background='#d4d7dc',foreground='#181818',width=12)
        self.blank_button.pack(side='left',expand=True)
        self.board_rail=ScrollRail(self.root);self.board_rail.pack(fill='x',padx=12,pady=(2,2))
        two=ttk.Frame(self.root);two.pack(fill='x',padx=12,pady=(6,0))
        ttk.Label(two,text='DECK CARDS',font=('TkDefaultFont',10,'bold')).pack(side='left')
        ttk.Button(two,text='Load .buttstore',command=self.load_deck).pack(side='right',padx=(6,0))
        ttk.Button(two,text='Run Sync',command=self.sync_deck).pack(side='right')
        self.hide_click_button=tk.Button(two,text='Hide Click: OFF',bg='#2466b4',fg='white',command=self.toggle_hide_click)
        self.hide_click_button.pack(side='right',padx=5)
        self.store_tabs=tk.Frame(self.root,background=BG)
        self.store_tabs.pack(fill='x',padx=12,pady=(3,0))
        self.deck_rail=ScrollRail(self.root);self.deck_rail.pack(fill='x',padx=12,pady=(2,4))
        ttk.Label(self.root,textvariable=self.status,foreground=MUTED,wraplength=900).pack(fill='x',padx=12,pady=4)
        self.pres_toggle=ttk.Button(self.root,text='▸ Pre-Show',command=self.toggle_preshow)
        self.pres_toggle.pack(fill='x',padx=12,pady=(3,5))
        self.pres_frame=tk.Frame(self.root,bg=PANEL)
        self.build_preshow()
    def set_status(self,msg):self.status.set(msg)
    def locate(self):
        sbc=filedialog.askdirectory(title='Streamer Board Console repository',initialdir=str(self.sbc or Path.home()))
        if sbc:
            root=discover_sbc(sbc)
            if root:self.sbc=root
            else:messagebox.showerror('Not found','Folder needs pin_board_instance.py and sbc_core/board_registry.py')
        deck=filedialog.askdirectory(title='Deck Card Widget repository',initialdir=str(self.deck or Path.home()))
        if deck:
            root=discover_deck(deck)
            if root:self.deck=root
            else:messagebox.showerror('Not found','Folder needs 3dcp_perspective_console.py')
        self.save();self.set_status('Application directories saved. Restart live applications after applying bridges.')
    def save(self):
        try:slot=max(1,min(64,self.slot.get()))
        except tk.TclError:slot=1
        atomic_json(STATE,{'boards':self.boards,'decks':self.decks,'sbc':str(self.sbc or ''), 'deck':str(self.deck or ''),'slot':slot,'hidden_stores':sorted(self.hidden_stores),'hidden_click':self.hidden_click,'store_order':self.store_order,'blank_requested':self.blank_requested,'tethers':self.tethers,'show_only':sorted(self.show_only),'auto_order':self.auto_order})
    def saves_dir(self):
        # A writable program-owned location, including after system/desktop install.
        target=Path(__file__).resolve().parent/'saves'
        try:
            target.mkdir(parents=True,exist_ok=True)
            probe=target/'.write-check'
            probe.write_text('',encoding='utf-8');probe.unlink()
            return target
        except OSError:
            target=APPDATA/'saves';target.mkdir(parents=True,exist_ok=True)
            return target
    def store_dms(self):
        path=filedialog.asksaveasfilename(title='Store DMS pinboard set',initialdir=str(self.saves_dir()),defaultextension='.dms',filetypes=[('DMS sets','*.dms')])
        if not path:return
        payload={'dms_format':'DMS-SET','version':1,'boards':[{'path':e['path'],'name':e['name']} for e in self.boards],
                 'buttstores':[s for s in self.store_order if any(e['source']==s for e in self.decks)],'tethers':self.tethers,'show_only':sorted(self.show_only),'auto_order':self.auto_order}
        try:
            if Path(path).suffix.lower()!='.dms':raise ValueError('The set must end in .dms')
            atomic_json(Path(path),payload)
        except Exception as exc:messagebox.showerror('Store failed',str(exc));return
        self.set_status(f'Stored {len(self.boards)} pinboards and {len(payload["buttstores"])} ButtStore references.')
    def load_dms(self):
        path=filedialog.askopenfilename(title='ReLoad .dms pinboard set',initialdir=str(self.saves_dir()),filetypes=[('DMS sets','*.dms')])
        if not path:return
        try:
            if Path(path).suffix.lower()!='.dms':raise ValueError('Expected a .dms file')
            data=json.loads(Path(path).read_text('utf-8'))
            if not isinstance(data,dict) or data.get('dms_format')!='DMS-SET':raise ValueError('Not a valid DMS-SET')
            boards=data.get('boards');stores=data.get('buttstores',[]);tethers=normalize_tethers(data.get('tethers',[]),strict=True)
            auto_order=normalize_order(data.get('auto_order'))
            show_only=data.get('show_only',[])
            if not isinstance(show_only,list) or any(not isinstance(x,str) for x in show_only):raise ValueError('Invalid show-only set')
            if not isinstance(boards,list) or not isinstance(stores,list):raise ValueError('Invalid boards or buttstores list')
            # Strict board loading: validate every referenced file BEFORE changing anything.
            replacement=[]
            for e in boards:
                if not isinstance(e,dict):raise ValueError('Invalid board entry')
                board=safe_path(e['path'],'.sboard')
                raw=json.loads(board.read_text('utf-8'))
                if not isinstance(raw,dict) or not isinstance(raw.get('pins'),list):raise ValueError(f'Invalid SBoard: {board.name}')
                replacement.append({'path':str(board),'name':str(e.get('name') or board.stem)[:64]})
            additions=[];missing=[];already=set(self.store_order)
            for raw_store in stores:
                if not isinstance(raw_store,str):raise ValueError('Invalid ButtStore reference')
                source=str(Path(raw_store).expanduser().resolve())
                if source in already:continue
                try:cards=read_buttstore(safe_path(source,'.buttstore'))
                except (ValueError,OSError) as exc:missing.append(Path(source).name);continue
                additions.append((source,cards));already.add(source)
        except Exception as exc:
            messagebox.showerror('ReLoad refused',f'Pinboard set left unchanged: {exc}')
            return
        self.boards=replacement
        self.tethers=tethers
        self.pres_line=min(self.pres_line,len(self.tethers)-1)
        self.pres_board=None;self.pres_deck=None
        self.auto_order=auto_order
        self.cancel_pending()
        for source,cards in additions:
            for c in cards:self.decks.append({'source':source,'id':c['id'],'name':c['label'],'color':c.get('color','#666c78'),'border_type':c.get('border_type',''),'source_type':c.get('source_type','')})
            self.store_order.append(source)
        if 'show_only' in data:self.show_only=set(s for s in show_only if s in self.store_order)
        self.reorder_decks()
        self.save();self.paint();self.render_preshow()
        self.set_status(f'ReLoaded {len(replacement)} pinboards; added {len(additions)} ButtStores.'+(f' Missing ButtStores skipped: {", ".join(missing)}' if missing else ''))
    def toggle_blank(self):
        if self.select_mode:return
        if self.pres_open:
            self.pres_board={'path':BLANK_ID,'name':'BLANK'}
            self.set_selected_pair()
            return
        if not self.blank_requested:self.activate_blank()
        else:
            # The existing empty board remains on screen until another preset is
            # chosen; only the visual toggle state is cleared.
            self.blank_requested=False
            self.save();self.paint()
            self.set_status('BLANK deselected; the current empty board remains until another board loads.')

    def activate_blank(self,from_tether=False):
        if not self.sbc:self.set_status('Streamer Board not found; use Locate apps.');return
        try:
            active=live_board(self.sbc,self.slot.get())
            if not active:raise ValueError('Start a pinboard in this slot before using BLANK')
            existing=active.get('board_path','')
            if not existing or not Path(existing).is_file():
                existing=next((e['path'] for e in self.boards if Path(e['path']).is_file()),'')
            if not existing:raise ValueError('No source .sboard available to construct BLANK')
            model=json.loads(Path(existing).read_text('utf-8'))
            if not isinstance(model,dict) or not isinstance(model.get('pins'),list):raise ValueError('Incompatible .sboard data')
            model['pins']=[]
            target=APPDATA/'blank_pinboard.sboard';atomic_json(target,model)
            command=sbc_userdata(self.sbc)/'board_instances/commands'/f'{active["instance_id"]}.command.json'
            next_command(command,'swap_state',{'path':str(target)})
            self.blank_requested=True
            if from_tether:self.ignore_events['board']=(BLANK_ID,time.monotonic()+12)
            self.save();self.paint()
            self.set_status('BLANK requested for the running pinboard; no saved presets were changed.')
        except Exception as exc:self.set_status(f'BLANK refused: {exc}')
    def board_dir(self):
        # Prefer the user's SBC repository, even if discovery could not validate it.
        candidates=[self.sbc,Path.home()/'Streamer-Board-Console',Path.home()/'streamer-board-console']
        for root in candidates:
            if root and Path(root).is_dir():
                for folder in (Path(root)/'user_data'/'boards',Path(root)/'boards',Path(root)):
                    if folder.is_dir() and any(folder.glob('*.sboard')):return folder
                return Path(root)
        return Path(__file__).resolve().parent
    def add_board(self):
        path=filedialog.askopenfilename(title='Choose an existing .sboard preset',initialdir=str(self.board_dir()),filetypes=[('Streamer Board preset','*.sboard')])
        if path:
            self.boards.append({'path':str(safe_path(path,'.sboard')),'name':Path(path).stem})
            self.save();self.paint()
    def load_deck(self):
        root=self.deck.parent/'user_data/buttstores' if self.deck else Path.home()
        path=filedialog.askopenfilename(title='Load cards from .buttstore',initialdir=str(root),filetypes=[('Deck Card ButtStore','*.buttstore')])
        if not path:return
        try: cards=read_buttstore(safe_path(path,'.buttstore'))
        except Exception as e:messagebox.showerror('Unsupported ButtStore',str(e));return
        self.add_cards(cards,str(Path(path).resolve()))
        self.reorder_decks()
        self.set_status(f'Loaded {len(cards)} deck card references; selecting one asks the running widget to load that store.')
    def add_cards(self,cards,source):
        seen={(c['source'],c['id']) for c in self.decks}
        for c in cards:
            key=(source,c['id'])
            if key not in seen:
                self.decks.append({'source':source,'id':c['id'],'name':c['label'],'color':c.get('color','#666c78'),'border_type':c.get('border_type',''),'source_type':c.get('source_type','')})
                seen.add(key)
        if source not in self.store_order:self.store_order.append(source)
        self.hidden_stores.discard(source)
        self.reorder_decks()
        self.save();self.paint()
    def sync_deck(self):
        if not self.deck:self.set_status('Deck app not found. Use Locate apps.');return
        status=load_json(deck_runtime(self.deck)/'dms_live_status.json',{})
        if not status or not status.get('heartbeat') or __import__('time').time()-status['heartbeat']>5:
            self.set_status('No live Deck bridge heartbeat. Install bridge and restart Deck Card Widget.');return
        source=str(Path(status['store_path']).resolve())
        # Replace the live store's natural order from the widget, preserving DMS aliases.
        old={(e['source'],e['id']):e for e in self.decks}
        # Refresh current store classifications even if the installed bridge
        # predates metadata support. Existing bridge installations still work.
        try: from_file={c['id']:c for c in read_buttstore(Path(source))}
        except (OSError, ValueError, TypeError): from_file={}
        live=[]
        for c in status.get('cards',[]):
            key=(source,str(c.get('id','')))
            if not key[1]:continue
            entry=dict(old.get(key,{'source':source,'id':key[1],'name':c.get('label',key[1])}))
            entry['color']=c.get('color',entry.get('color','#666c78'))
            details=from_file.get(key[1],{})
            for field in ('border_type','source_type'):
                if field in c:entry[field]=c[field]
                elif field in details:entry[field]=details[field]
            live.append(entry)
        self.decks=[e for e in self.decks if e['source']!=source]+live
        if source not in self.store_order:self.store_order.append(source)
        self.reorder_decks(source)
        self.hidden_stores.update(s for s in self.store_order if s!=source)
        self.hidden_stores.discard(source)
        self.show_only.clear()
        self.auto_hidden.clear()
        self.last_active=(source,str(status.get('active_card_id','')))
        self.save();self.paint();self.focus_card(*self.last_active)
        self.set_status(f"Run Sync: showing {Path(source).name}; focused active card. Other stores hidden, not dropped.")
    def reorder_decks(self,source=None):
        # Keep the actual DeckCard Widget / ButtStore natural order intact.
        # The display is recomputed by order_stores() during paint(), per store.
        # Retaining this entry point avoids changing the existing load/sync calls.
        return

    def toggle_select(self):
        if not self.select_mode:
            self.select_mode=True;self.selected.clear()
            self.drop_button.configure(text='Drop Selected')
            self.set_status('Button Select mode: click buttons in either rail, then Drop Selected to remove them. No source files are deleted.')
        else:
            removed=len(self.selected)
            self.boards=[e for e in self.boards if ('board',e.get('path')) not in self.selected]
            self.decks=[e for e in self.decks if ('deck',e.get('source'),e.get('id')) not in self.selected]
            self.store_order=[s for s in self.store_order if any(e['source']==s for e in self.decks)]
            self.hidden_stores.intersection_update(self.store_order)
            self.show_only.intersection_update(self.store_order)
            self.auto_hidden.clear();self.selected.clear();self.select_mode=False
            self.drop_button.configure(text='Drop');self.save()
            self.set_status(f'Dropped {removed} selected DMS buttons; files untouched.')
        self.paint()
    def button_tap(self,group,entry):
        if self.select_mode:
            key=('board',entry['path']) if group=='board' else ('deck',entry['source'],entry['id'])
            if key in self.selected:self.selected.remove(key)
            else:self.selected.add(key)
            self.paint()
        elif self.pres_open:
            if group=='board':self.pres_board={'path':entry['path'],'name':entry['name']}
            else:self.pres_deck={'source':entry['source'],'id':str(entry['id']),'name':entry['name']}
            self.set_selected_pair()
        elif group=='board':self.board_send(entry)
        else:self.deck_send(entry)
    def toggle_hide_click(self):
        self.hidden_click=not self.hidden_click
        if not self.hidden_click:self.auto_hidden.clear()
        self.save();self.paint()
    def focus_card(self,source,card_id):
        for button,entry in getattr(self,'deck_widgets',[]):
            if entry['source']==source and entry['id']==card_id:
                self.deck_rail.canvas.update_idletasks()
                x=button.winfo_x();width=max(1,self.deck_rail.inner.winfo_width())
                self.deck_rail.canvas.xview_moveto(max(0,min(1,x/width)))
                return
    def focus_store(self,source):
        for button,entry in getattr(self,'deck_widgets',[]):
            if entry['source']==source:
                self.deck_rail.canvas.update_idletasks()
                self.deck_rail.canvas.xview_moveto(max(0,button.winfo_x()/max(1,self.deck_rail.inner.winfo_width())))
                return
    def store_menu(self,source,button):
        menu=tk.Menu(button,tearoff=False)
        menu.add_command(label='Show only' if source not in self.show_only else 'Stop show only',command=lambda:self.toggle_show_only(source))
        menu.add_separator()
        menu.add_command(label='Focus',command=lambda:self.focus_store(source))
        menu.add_command(label='Reload',command=lambda:self.reload_store(source))
        menu.add_command(label='Swap',command=lambda:self.swap_store(source))
        menu.add_command(label='Hide',command=lambda:self.set_store_hidden(source,True))
        menu.add_command(label='Show',command=lambda:self.set_store_hidden(source,False))
        menu.add_separator()
        menu.add_command(label='Drop',command=lambda:self.drop_store(source))
        menu.tk_popup(button.winfo_rootx(),button.winfo_rooty()+button.winfo_height())
    def set_store_hidden(self,source,hidden):
        if hidden:self.hidden_stores.add(source)
        else:
            self.hidden_stores.discard(source)
            self.auto_hidden={key for key in self.auto_hidden if key[0]!=source}
            if self.show_only:self.show_only.add(source)
        self.save();self.paint()
    def drop_store(self,source):
        self.decks=[e for e in self.decks if e['source']!=source]
        self.store_order=[s for s in self.store_order if s!=source]
        self.hidden_stores.discard(source)
        self.show_only.discard(source)
        self.auto_hidden={key for key in self.auto_hidden if key[0]!=source}
        self.save();self.paint();self.set_status(f'Dropped {Path(source).name} from DMS memory; disk file and running widget unchanged.')
    def reload_store(self,source):
        try:cards=read_buttstore(safe_path(source,'.buttstore'))
        except Exception as exc:self.set_status(f'Reload failed: {exc}');return
        self.decks=[e for e in self.decks if e['source']!=source]
        self.add_cards(cards,source)
        self.set_status(f'Reloaded {Path(source).name} ({len(cards)} cards).')
    def swap_store(self,source):
        path=filedialog.askopenfilename(title='Swap ButtStore',initialdir=str(Path(source).parent),filetypes=[('Deck ButtStore','*.buttstore')])
        if not path:return
        try:
            new=str(safe_path(path,'.buttstore'));cards=read_buttstore(Path(new))
        except Exception as exc:self.set_status(f'Swap failed: {exc}');return
        if new!=source:self.drop_store(source)
        else:self.decks=[e for e in self.decks if e['source']!=source]
        self.add_cards(cards,new)
    def board_send(self,entry,from_tether=False):
        if entry.get('path')==BLANK_ID:return self.activate_blank(from_tether=from_tether)
        if not self.sbc:self.set_status('Streamer Board not found; use Locate apps.');return
        try:
            path=safe_path(entry['path'],'.sboard')
            active=live_board(self.sbc,self.slot.get())
            if active and active.get('board_path') and Path(active['board_path']).resolve()==path:
                if not from_tether:self.activate_blank()
                return
            if not active:
                self.set_status(f'Pinboard slot {self.slot.get()} not running; open a board in Streamer Board Console first.');return
            instance=active['instance_id']
            commands=sbc_userdata(self.sbc)/'board_instances/commands'/f'{instance}.command.json'
            next_command(commands,'swap_state',{'path':str(path)})
            self.blank_requested=False
            if from_tether:self.ignore_events['board']=(str(path),time.monotonic()+12)
            self.save();self.paint()
            self.set_status(f'Board switch requested: {entry["name"]} → slot {self.slot.get()} (check RED once status confirms).')
        except Exception as e:self.set_status(f'Board switch refused: {e}')
    def deck_send(self,entry,from_tether=False):
        if not self.deck:self.set_status('Deck app not found; use Locate apps.');return
        try:
            status=load_json(deck_runtime(self.deck)/'dms_live_status.json',{})
            import time
            if time.time()-float(status.get('heartbeat',0))>5:
                self.set_status('Deck Card Widget bridge not responding; start the patched app.');return
            source=safe_path(entry['source'],'.buttstore')
            path=deck_runtime(self.deck)/'dms_live_command.json'
            seq=next_command(path,'load_and_select',{'path':str(source),'card_id':entry['id']})
            if from_tether:self.ignore_events['deck']=((str(source),str(entry['id'])),time.monotonic()+12)
            else:
                self.manual_deck_ack=seq
                self.manual_deck_target=(str(source),str(entry['id']))
            self.set_status(f'Deck selection requested: {entry["name"]}')
        except Exception as e:self.set_status(f'Deck switch refused: {e}')
    def _hold_menu(self,group,i,btn):
        if self.pres_open:return
        entry=(self.boards if group=='board' else self.decks)[i]
        menu=tk.Menu(btn,tearoff=False)
        if group=='board':
            menu.add_command(label='Reload',command=lambda:self.board_send(entry))
            menu.add_command(label='Swap',command=lambda:self.swap_board(i))
        else:menu.add_command(label='Reload',command=lambda:self.deck_send(entry))
        menu.add_command(label='Name',command=lambda:self.rename(group,i))
        menu.add_command(label='Drop',command=lambda:self.drop(group,i))
        menu.tk_popup(btn.winfo_rootx()+8,btn.winfo_rooty()+btn.winfo_height())
    def swap_board(self,i):
        path=filedialog.askopenfilename(title='Replace preset in this position',initialdir=str(self.board_dir()),filetypes=[('Streamer Board preset','*.sboard')])
        if path:
            self.boards[i]={'path':str(safe_path(path,'.sboard')),'name':Path(path).stem}
            self.save();self.paint()
    def rename(self,group,i):
        coll=self.boards if group=='board' else self.decks
        new=simpledialog.askstring('Button Name','Alias for this switch button:',initialvalue=coll[i]['name'],parent=self.root)
        if new and new.strip():coll[i]['name']=new.strip()[:64];self.save();self.paint()
    def drop(self,group,i):
        coll=self.boards if group=='board' else self.decks
        name=coll[i]['name']
        coll.pop(i);self.save();self.paint();self.set_status(f'Dropped button {name}; source files untouched.')
    def toggle_show_only(self,source):
        if source in self.show_only:self.show_only.remove(source)
        else:self.show_only.add(source)
        self.save();self.paint()
        self.set_status(f'Show-only filter: {len(self.show_only)} active tab(s). Right-click a tab for ButtStore options.')

    def paint(self):
        self.board_rail.clear();self.deck_rail.clear()
        for child in self.store_tabs.winfo_children():child.destroy()
        self.blank_button.configure(background='#2c9c4c' if self.blank_requested else '#d4d7dc',foreground='white' if self.blank_requested else '#181818')
        self.hide_click_button.configure(text='Hide Click: ON' if self.hidden_click else 'Hide Click: OFF',bg='#ae2733' if self.hidden_click else '#2466b4')
        for source in self.store_order:
            count=sum(1 for e in self.decks if e['source']==source)
            if not count:continue
            label=Path(source).stem+(' [H]' if source in self.hidden_stores else '')
            selected=source in self.show_only
            tab=HoldButton(self.store_tabs,text=label,tap=lambda s=source:self.toggle_show_only(s),
                           hold=lambda w,s=source:self.store_menu(s,w),
                           bg='#29884b' if selected else PANEL,fg='white' if selected else TEXT,relief='sunken' if selected else 'ridge')
            tab.pack(side='left',padx=(0,4))
            tab.bind('<Button-3>',lambda e,s=source,w=tab:self.store_menu(s,w))
        board=live_board(self.sbc,self.slot.get()) if self.sbc else None
        active_path=str(Path(board.get('board_path','')).resolve()) if board and board.get('board_path') else ''
        deckstatus=load_json(deck_runtime(self.deck)/'dms_live_status.json',{}) if self.deck else {}
        self.board_widgets=[];self.deck_widgets=[]
        for i,entry in enumerate(self.boards):
            isactive=bool(active_path and active_path==entry['path'])
            bg='#c89d30' if ('board',entry['path']) in self.selected else board_color(entry['name'],isactive)
            b=HoldButton(self.board_rail.inner,tap=lambda e=entry:self.button_tap('board',e),hold=lambda w,j=i:self._hold_menu('board',j,w),
                text=('● ' if isactive else '')+entry['name'],background=bg,foreground=label_color(bg),activebackground=bg,
                relief='raised',bd=2,width=18,height=2,wraplength=135)
            b.pack(side='left',padx=4,pady=8)
            self.board_widgets.append((b,entry))
        # Category ordering is performed independently for EACH ButtStore; the
        # combined view always preserves tab/load order.
        for entry in order_stores(self.decks,self.store_order,self.auto_order):
            i=self.decks.index(entry)
            key=(entry['source'],entry['id'])
            if entry['source'] in self.hidden_stores or key in self.auto_hidden:continue
            if self.show_only and entry['source'] not in self.show_only:continue
            bg='#c89d30' if ('deck',entry['source'],entry['id']) in self.selected else entry.get('color','#666c78')
            active=(deckstatus.get('store_path')==entry.get('source') and str(deckstatus.get('active_card_id'))==entry['id'])
            b=HoldButton(self.deck_rail.inner,tap=lambda e=entry:self.button_tap('deck',e),hold=lambda w,j=i:self._hold_menu('deck',j,w),
                text=('● ' if active else '')+entry['name'],background=bg,foreground=label_color(bg),activebackground=bg,
                relief='sunken' if active else 'raised',bd=3 if active else 2,width=18,height=2,wraplength=135)
            b.pack(side='left',padx=4,pady=8)
            self.deck_widgets.append((b,entry))
    def refresh_styles(self):
        active=live_board(self.sbc,self.slot.get()) if self.sbc else None
        active_path=str(Path(active.get('board_path','')).resolve()) if active and active.get('board_path') else ''
        deckstatus=load_json(deck_runtime(self.deck)/'dms_live_status.json',{}) if self.deck else {}
        import time
        if time.time()-float(deckstatus.get('heartbeat',0))>5:deckstatus={}
        self.check_tether_events(active_path,deckstatus)
        if active_path==self.blank_path and not self.blank_requested:
            self.blank_requested=True;self.save();self.blank_button.configure(background='#2c9c4c',foreground='white')
        elif active_path and active_path!=self.blank_path and self.blank_requested:
            self.blank_requested=False;self.save();self.blank_button.configure(background='#d4d7dc',foreground='#181818')
        for btn,entry in getattr(self,'board_widgets',[]):
            isactive=bool(active_path and active_path==entry['path'])
            bg=board_color(entry['name'],isactive)
            btn.configure(background=bg,foreground=label_color(bg),activebackground=bg,
                          text=('● ' if isactive else '')+entry['name'])
        current=(deckstatus.get('store_path'),str(deckstatus.get('active_card_id','')))
        if current[0] and current[1]:
            if self.hidden_click and self.last_active and current!=self.last_active:
                self.auto_hidden.add(self.last_active)
                self.last_active=current
                self.paint()
                return
            self.last_active=current
        for btn,entry in getattr(self,'deck_widgets',[]):
            isactive=(deckstatus.get('store_path')==entry.get('source') and deckstatus.get('active_card_id')==entry['id'])
            btn.configure(relief='sunken' if isactive else 'raised',bd=3 if isactive else 2,
                          text=('● ' if isactive else '')+entry['name'])
    def toggle_preshow(self):
        self.pres_open=not self.pres_open
        self.pres_toggle.configure(text=('▾ Pre-Show • EDIT' if self.pres_open else '▸ Pre-Show'))
        if self.pres_open:
            self.cancel_pending()
            # Keep the collapse button ABOVE Pre-Show so it remains reachable
            # when users expand into many tether rows.
            self.pres_frame.pack(fill='x',padx=12,pady=(0,6),after=self.pres_toggle)
            desired_height=min(870,max(600,self.root.winfo_screenheight()-100))
            self.root.geometry(f'{max(self.root.winfo_width(),980)}x{max(self.root.winfo_height(),desired_height)}')
        else:
            self.pres_frame.pack_forget()
            self.pres_board=None;self.pres_deck=None
            self.observed_board=None;self.observed_deck=None
        self.render_preshow()
        self.set_status('Pre-Show EDIT: select a line, then click a Pinboard and a Deck Card; no live switches.' if self.pres_open else 'LIVE mode: button presses switch normally.')

    def build_preshow(self):
        """Exactly three tether entries are visible; the model may contain more."""
        heading=tk.Frame(self.pres_frame,bg=PANEL)
        heading.pack(fill='x',padx=8,pady=(7,2))
        tk.Label(heading,text='PRE-SHOW • TETHER EDITOR',bg=PANEL,fg=TEXT).pack(side='left')
        ttk.Button(heading,text='+ Row',command=self.add_tether_row).pack(side='right')
        self.pres_count_label=tk.Label(heading,text='',bg=PANEL,fg=MUTED)
        self.pres_count_label.pack(side='right',padx=8)

        tk.Label(self.pres_frame,text='Choose a row and its Pinboard + Deck Card. Right-click or hold a row for row actions. Scroll for more.',
                 bg=PANEL,fg=MUTED,anchor='w',justify='left',wraplength=850).pack(fill='x',padx=8,pady=(0,3))
        table_area=tk.Frame(self.pres_frame,bg=PANEL)
        table_area.pack(fill='x',padx=6)
        # A Treeview supplies native, keyboard-accessible vertical scrolling and
        # a fixed viewport of THREE entries, regardless of the number saved.
        style=ttk.Style()
        style.configure('DmsTether.Treeview',background='#27303d',fieldbackground='#27303d',
                        foreground=TEXT,rowheight=31,borderwidth=0)
        style.map('DmsTether.Treeview',background=[('selected','#355785')],
                  foreground=[('selected','#ffffff')])
        style.configure('DmsTether.Treeview.Heading',background='#354155',foreground=TEXT)
        self.pres_rows=ttk.Treeview(table_area,columns=('num','board','deck','rules'),
                                    show='headings',height=3,selectmode='browse',
                                    style='DmsTether.Treeview')
        for key,label,width,minwidth,stretch in (
                ('num','#',42,36,False),('board','SBoard',225,90,True),
                ('deck','Deck Card',225,90,True),('rules','Enabled triggers / delays',330,110,True)):
            self.pres_rows.heading(key,text=label,anchor='w')
            self.pres_rows.column(key,width=width,minwidth=minwidth,stretch=stretch,anchor='w')
        scroll=ttk.Scrollbar(table_area,orient='vertical',command=self.pres_rows.yview)
        self.pres_rows.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        self.pres_rows.pack(side='left',fill='x',expand=True)
        self.pres_rows.bind('<<TreeviewSelect>>',self._on_tether_row_select)
        # A right-click or deliberate 650 ms primary-button hold on any row
        # opens the SAME row context menu. Cancel a hold when scrolling/dragging.
        self._row_hold_job=None
        self._row_hold_origin=None
        self._row_hold_opened=False
        self.pres_rows.bind('<Button-3>',self._on_row_context_click)
        self.pres_rows.bind('<ButtonPress-1>',self._on_row_press)
        self.pres_rows.bind('<B1-Motion>',self._on_row_motion)
        self.pres_rows.bind('<ButtonRelease-1>',self._on_row_release)
        self.pres_rows.bind('<Leave>',self._on_row_release)
        self.pres_modes=tk.Frame(self.pres_frame,bg=PANEL);self.pres_modes.pack(fill='x',padx=6,pady=4)
        self.pres_delays=tk.Frame(self.pres_frame,bg=PANEL);self.pres_delays.pack(fill='x',padx=6,pady=4)
        self.pres_bottom=tk.Frame(self.pres_frame,bg=PANEL);self.pres_bottom.pack(fill='x',padx=6,pady=(0,8))
        tk.Label(self.pres_frame,text='DECKCARD AUTO-ORDER • left-click to number/remove • right-click for Swap Order',bg=PANEL,fg=TEXT).pack(anchor='w',padx=8,pady=(4,1))
        self.order_bar=tk.Frame(self.pres_frame,bg=PANEL);self.order_bar.pack(fill='x',padx=6,pady=(1,8))

    def _on_tether_row_select(self,_event=None):
        selected=self.pres_rows.selection()
        if not selected:return
        try:index=int(selected[0].removeprefix('tether-'))
        except ValueError:return
        if index!=self.pres_line and 0<=index<len(self.tethers):
            self.choose_line(index)

    def _cancel_row_hold(self):
        if self._row_hold_job is not None:
            self.pres_rows.after_cancel(self._row_hold_job)
            self._row_hold_job=None
        self._row_hold_origin=None

    def _on_row_press(self,event):
        self._cancel_row_hold()
        self._row_hold_opened=False
        item=self.pres_rows.identify_row(event.y)
        if not item:return
        self._row_hold_origin=(item,event.x,event.y)
        self._row_hold_job=self.pres_rows.after(
            650,lambda iid=item:self._on_row_hold(iid))

    def _on_row_motion(self,event):
        if self._row_hold_origin is not None:
            _,x,y=self._row_hold_origin
            if abs(event.x-x)>8 or abs(event.y-y)>8:
                self._cancel_row_hold()

    def _on_row_release(self,_event=None):
        was_opened=self._row_hold_opened
        self._cancel_row_hold()
        self._row_hold_opened=False
        if was_opened:return 'break'

    def _on_row_hold(self,item):
        self._row_hold_job=None
        self._row_hold_origin=None
        if item not in self.pres_rows.get_children():return
        self._row_hold_opened=True
        self._show_row_context_menu(item,self.pres_rows.winfo_pointerx(),self.pres_rows.winfo_pointery())

    def _on_row_context_click(self,event):
        self._cancel_row_hold()
        item=self.pres_rows.identify_row(event.y)
        if item:self._show_row_context_menu(item,event.x_root,event.y_root)
        return 'break'

    def _show_row_context_menu(self,item,x,y):
        try:index=int(item.removeprefix('tether-'))
        except ValueError:return
        if not 0<=index<len(self.tethers):return
        if index!=self.pres_line:
            self.choose_line(index)
        else:
            self.pres_rows.selection_set(item)
            self.pres_rows.focus(item)
        menu=tk.Menu(self.pres_rows,tearoff=0,bg=PANEL,fg=TEXT,
                     activebackground='#355785',activeforeground='white')
        menu.add_command(label='Delete Row',command=lambda i=index:self.delete_row(i))
        menu.add_command(label='Remove Triggers & Delays',command=lambda i=index:self.remove_triggers(i))
        menu.add_separator()
        menu.add_command(label='Clear Fields (All Rows)…',command=self.clear_fields)
        try:menu.tk_popup(x,y)
        finally:menu.grab_release()

    def delete_row(self,index):
        self._cancel_row_hold()
        self.tethers=delete_tether_row(self.tethers,index)
        self.pres_line=min(index,len(self.tethers)-1)
        row=self.current_row()
        self.pres_board=dict(row['board']) if row['board'] else None
        self.pres_deck=dict(row['deck']) if row['deck'] else None
        self.cancel_pending()
        self.save();self.render_preshow()
        self.set_status(f'Deleted tether row {index+1}; {len(self.tethers)} rows remain (minimum three visible).')

    def remove_triggers(self,index):
        self._cancel_row_hold()
        self.tethers=remove_row_triggers(self.tethers,index)
        self.pres_line=index
        self.cancel_pending()
        self.save();self.render_preshow()
        self.set_status(f'Removed all triggers and delays from row {index+1}. The paired SBoard and Deck Card remain.')

    def clear_fields(self):
        self._cancel_row_hold()
        if not messagebox.askyesno('Clear Fields',
                'Are you sure you want to clear the fields for all rows?',parent=self.root):
            self.set_status('Clear Fields cancelled. No changes made.')
            return
        self.tethers=clear_all_fields(self.tethers)
        self.pres_board=None;self.pres_deck=None
        self.cancel_pending()
        self.save();self.render_preshow()
        self.set_status('Cleared all tether fields in every row. The row count, pinboard and deck lists, and auto-order are unchanged.')

    def add_tether_row(self):
        from tether_core import empty_row
        self.tethers.append(empty_row())
        self.pres_line=len(self.tethers)-1
        self.pres_board=None;self.pres_deck=None
        self.save();self.render_preshow()
        self.set_status(f'Added tether row {self.pres_line+1}. Select a Pinboard + Deck Card, set triggers, then Set Pair.')

    def current_row(self):return self.tethers[self.pres_line]

    def choose_line(self,i):
        self.pres_line=i
        row=self.current_row()
        self.pres_board=dict(row['board']) if row['board'] else None
        self.pres_deck=dict(row['deck']) if row['deck'] else None
        self.render_preshow()

    def change_page(self,page):
        row=self.current_row(); rule=row['rules'][page]
        if self.pres_page==page:
            rule['enabled']=not rule['enabled']
        else:
            self.pres_page=page
            if not rule['enabled']:rule['enabled']=True
        self.save();self.render_preshow()

    def set_delay(self,seconds):
        row=self.current_row();rule=row['rules'][self.pres_page]
        if not rule['enabled']:return
        delays=rule['delays']
        if seconds in delays:delays.remove(seconds)
        else:delays.append(seconds)
        delays.sort()
        self.save();self.render_preshow()

    def set_selected_pair(self):
        row=self.current_row()
        if self.pres_board:row['board']=dict(self.pres_board)
        if self.pres_deck:row['deck']=dict(self.pres_deck)
        self.save();self.render_preshow()

    def detether(self):
        self.tethers=detach_matching(self.tethers,self.pres_line,False)
        self.pres_line=min(self.pres_line,len(self.tethers)-1);self.pres_board=None;self.pres_deck=None
        self.cancel_pending();self.save();self.render_preshow()

    def detether_all(self):
        row=self.current_row()
        if messagebox.askyesno('De-Tether all','Clear all tether lines matching this row’s Deck Card and/or SBoard?'):
            self.tethers=detach_matching(self.tethers,self.pres_line,True)
            self.pres_line=0;self.pres_board=None;self.pres_deck=None
            self.cancel_pending();self.save();self.render_preshow()

    def render_preshow(self):
        # Treeview is a fixed three-row viewport with its own scrollbar.  Its
        # rows are refreshed from the full model, never a truncated slice.
        self.pres_line=min(self.pres_line,len(self.tethers)-1)
        self.pres_count_label.configure(text=f'{len(self.tethers)} tethers • 3 visible')
        for item in self.pres_rows.get_children():self.pres_rows.delete(item)
        labels_short={'dc_load':'DC Load','sb_load':'SB Load',
                      'dc_change':'DC Change','sb_change':'SB Change',
                      'dc_hide':'DC Hide','sb_hide':'SB Hide'}
        for i,item in enumerate(self.tethers):
            board=item['board'];deck=item['deck'];rules=item['rules']
            summary=', '.join(f'{labels_short[k]} +{delay_seconds(v)}s' if delay_seconds(v) else labels_short[k]
                              for k,v in rules.items() if v['enabled']) or 'None'
            name_b=(self.pres_board or board) if i==self.pres_line else board
            name_d=(self.pres_deck or deck) if i==self.pres_line else deck
            self.pres_rows.insert('', 'end', iid=f'tether-{i}',
                values=(str(i+1), (name_b or {}).get('name','— SBoard —'),
                        (name_d or {}).get('name','— DeckCard —'), summary))
        selected=f'tether-{self.pres_line}'
        self.pres_rows.selection_set(selected)
        self.pres_rows.focus(selected)
        self.pres_rows.see(selected)
        for frame in (self.pres_modes,self.pres_delays,self.pres_bottom):
            for widget in frame.winfo_children():widget.destroy()
        row=self.current_row()
        labels={'dc_load':'DC Load','sb_load':'SB Load','dc_change':'DC Change','sb_change':'SB Change','dc_hide':'DC Hide','sb_hide':'SB Hide'}
        for page,label in labels.items():
            rule=row['rules'][page];selected=(page==self.pres_page)
            tk.Button(self.pres_modes,text=label+(' ✓' if rule['enabled'] else ''),bg=('#337d5a' if selected and rule['enabled'] else '#355785' if selected else '#414958'),fg='white',command=lambda p=page:self.change_page(p)).pack(side='left',padx=3)
        rule=row['rules'][self.pres_page]
        tk.Label(self.pres_delays,text=f'{labels[self.pres_page]} delay: {delay_seconds(rule)} seconds',bg=PANEL,fg=TEXT).pack(side='left',padx=5)
        for delay,label in ((10,'10s after'),(30,'30s after'),(60,'1m after')):
            tk.Button(self.pres_delays,text=label,bg=('#8855a6' if delay in rule['delays'] else '#414958'),fg='white',state='normal' if rule['enabled'] else 'disabled',command=lambda d=delay:self.set_delay(d)).pack(side='left',padx=3)
        ttk.Button(self.pres_bottom,text='Set Pair / Update Line',command=self.set_selected_pair).pack(side='left',padx=3)
        HoldButton(self.pres_bottom,text='De-Tether (hold: all)',tap=self.detether,hold=lambda _w:self.detether_all(),bg='#873e45',fg='white').pack(side='right',padx=3)
        tk.Label(self.pres_bottom,text='Click selected rule again to disable; setup is retained.',bg=PANEL,fg=MUTED).pack(side='left',padx=8)
        self.render_auto_order()

    def set_auto_category(self,category):
        if self.swap_category_pending:
            first=self.swap_category_pending
            self.swap_category_pending=None
            self.auto_order=swap_category(self.auto_order,first,category)
        else:self.auto_order=toggle_category(self.auto_order,category)
        self.reorder_decks()
        self.save();self.paint();self.render_auto_order()

    def auto_category_menu(self,category,button):
        menu=tk.Menu(button,tearoff=False)
        active=category in self.auto_order
        menu.add_command(label='Turn Off' if active else 'Turn On',command=lambda:self.set_auto_category(category))
        menu.add_command(label='Swap Order',state='normal' if active else 'disabled',command=lambda:self.begin_swap_category(category))
        menu.tk_popup(button.winfo_rootx(),button.winfo_rooty()+button.winfo_height())

    def begin_swap_category(self,category):
        self.swap_category_pending=category
        self.render_auto_order()
        self.set_status(f'Auto-order swap: click the category that should exchange numbers with {category}.')

    def render_auto_order(self):
        for child in self.order_bar.winfo_children():child.destroy()
        titles={'partners':'Partners','sponsors':'Sponsors','cud':'Catch Up Deets (1io)',
                'normal':'Normal','ending':'Ending','after':'After','credits':'Credits'}
        for index,category in enumerate(CATEGORIES):
            priority=self.auto_order.index(category)+1 if category in self.auto_order else 0
            is_swap=category==self.swap_category_pending
            bg='#956c24' if is_swap else '#287e51' if priority else '#414958'
            b=tk.Button(self.order_bar,text=f'{"☑" if priority else "☐"} {priority}  {titles[category]}',bg=bg,fg='white',
                        command=lambda c=category:self.set_auto_category(c),padx=5)
            b.grid(row=index//4,column=index%4,sticky='ew',padx=2,pady=2)
            b.bind('<Button-3>',lambda e,c=category,w=b:self.auto_category_menu(c,w))
        for column in range(4):self.order_bar.grid_columnconfigure(column,weight=1)

    def cancel_pending(self):
        for job in self.pending_jobs:
            try:self.root.after_cancel(job)
            except (tk.TclError,ValueError):pass
        self.pending_jobs=[]

    def _ignored(self,domain,target):
        expected=self.ignore_events.get(domain)
        if not expected:return False
        if expected[1]<time.monotonic():
            self.ignore_events.pop(domain,None);return False
        if expected[0]==target:
            self.ignore_events.pop(domain,None);return True
        return False

    def check_tether_events(self,board_path,deckstatus):
        current_board=BLANK_ID if board_path==self.blank_path else board_path
        current_deck=(str(deckstatus.get('store_path') or ''),str(deckstatus.get('active_card_id') or ''))
        if self.observed_board is None:self.observed_board=current_board
        if self.observed_deck is None:self.observed_deck=current_deck
        ack=deckstatus.get('ack_seq')
        if self.last_ack_seq is None:self.last_ack_seq=ack
        ack_changed=ack!=self.last_ack_seq and ack is not None
        self.last_ack_seq=ack
        if self.pres_open:
            self.observed_board=current_board;self.observed_deck=current_deck;return
        old_board=self.observed_board;old_deck=self.observed_deck
        events=[]
        if current_board!=old_board and current_board:
            if not self._ignored('board',current_board):
                # BLANK is a fully eligible sboard endpoint for SB Load.
                events.append(('sb_load',current_board))
                if old_board:
                    events.append(('sb_change',old_board))
                    if old_board!=BLANK_ID and current_board==BLANK_ID:
                        events.append(('sb_hide',old_board))
        if current_deck!=old_deck and all(current_deck):
            if not self._ignored('deck',current_deck):
                events.append(('dc_load',current_deck))
                if all(old_deck):
                    events.append(('dc_change',old_deck))
                    if self.hidden_click and getattr(self,'last_active',old_deck)==old_deck and old_deck not in getattr(self,'auto_hidden',set()):
                        events.append(('dc_hide',old_deck))
        elif ack_changed and self.manual_deck_ack==ack and current_deck==self.manual_deck_target and all(current_deck):
            # Clicking an already-active card still counts as an explicit load.
            if not self._ignored('deck',current_deck):events.append(('dc_load',current_deck))
        if ack_changed and self.manual_deck_ack==ack:
            self.manual_deck_ack=None;self.manual_deck_target=None
        self.observed_board=current_board;self.observed_deck=current_deck
        for kind,key in events:
            for action in matching_actions(self.tethers,kind,key):
                self.schedule_tether(action)

    def schedule_tether(self,action):
        kind=action['target'];delay=action['delay']
        def fire():
            if self.pres_open:return
            if kind=='board':self.board_send(action['entry'],from_tether=True)
            else:self.deck_send(action['entry'],from_tether=True)
        if delay: self.pending_jobs.append(self.root.after(delay*1000,fire))
        else:fire()

    def poll(self):
        # Update styles in place so a held button cannot disappear while the user presses it.
        self.refresh_styles()
        self.root.after(1500,self.poll)
    def close(self):self.cancel_pending();self.save();self.root.destroy()
    def run(self):self.root.mainloop()

if __name__=='__main__':LiveSwitcher().run()
