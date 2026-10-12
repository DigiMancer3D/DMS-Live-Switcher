#!/usr/bin/env python3
"""Two-row in-process SBC/Deck switch controller for KDE/OBS (Tkinter)."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from pathlib import Path
from switch_core import (APPDATA, STATE, load_json, atomic_json, next_command,
    board_color, card_color, label_color, discover_sbc, discover_deck,
    sbc_userdata, deck_runtime, live_board, safe_path, read_buttstore)

BG='#15191f'; PANEL='#212630'; TEXT='#e8ecf2'; MUTED='#aeb7c3'

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
        self.decks=self.data.get('decks',[])
        self.sbc=discover_sbc(self.data.get('sbc',''))
        self.deck=discover_deck(self.data.get('deck',''))
        self.root=tk.Tk(className='Dmsliveswitcher');self.root.title('DMS Live Switcher — Pinboards + Deck Cards')
        # Match KDE's StartupWMClass and provide a real taskbar/window icon.
        try:
            self.root.iconphoto(True, tk.PhotoImage(file=str(Path(__file__).resolve().parent/'assets/dms-live-switcher-128.png')))
        except (tk.TclError, OSError):
            pass
        self.slot=tk.IntVar(value=int(self.data.get('slot',1)))
        self.root.geometry('980x342');self.root.minsize(650,300)
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
        ttk.Button(title,text='Locate apps',command=self.locate).pack(side='right')
        ttk.Label(title,text='Pinboard slot:').pack(side='right',padx=(12,3))
        spin=ttk.Spinbox(title,from_=1,to=64,textvariable=self.slot,width=4,command=self.save);spin.pack(side='right')
        spin.bind('<FocusOut>',lambda e:self.save())
        one=ttk.Frame(self.root);one.pack(fill='x',padx=12,pady=(6,0))
        ttk.Label(one,text='PINBOARD PRESETS',font=('TkDefaultFont',10,'bold')).pack(side='left')
        ttk.Button(one,text='+ Add .sboard',command=self.add_board).pack(side='right')
        self.board_rail=ScrollRail(self.root);self.board_rail.pack(fill='x',padx=12,pady=(2,2))
        two=ttk.Frame(self.root);two.pack(fill='x',padx=12,pady=(6,0))
        ttk.Label(two,text='DECK CARDS',font=('TkDefaultFont',10,'bold')).pack(side='left')
        ttk.Button(two,text='Load .buttstore',command=self.load_deck).pack(side='right',padx=(6,0))
        ttk.Button(two,text='Sync running',command=self.sync_deck).pack(side='right')
        self.deck_rail=ScrollRail(self.root);self.deck_rail.pack(fill='x',padx=12,pady=(2,4))
        ttk.Label(self.root,textvariable=self.status,foreground=MUTED,wraplength=900).pack(fill='x',padx=12,pady=4)
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
        atomic_json(STATE,{'boards':self.boards,'decks':self.decks,'sbc':str(self.sbc or ''), 'deck':str(self.deck or ''),'slot':slot})
    def board_dir(self):
        if self.sbc:return sbc_userdata(self.sbc)/'boards'
        return Path.home()/'streamer-board-console'
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
        self.set_status(f'Loaded {len(cards)} deck card references; selecting one asks the running widget to load that store.')
    def add_cards(self,cards,source):
        seen={(c['source'],c['id']) for c in self.decks}
        for c in cards:
            key=(source,c['id'])
            if key not in seen:
                self.decks.append({'source':source,'id':c['id'],'name':c['label'],'color':c.get('color','#666c78')})
                seen.add(key)
        self.save();self.paint()
    def sync_deck(self):
        if not self.deck:self.set_status('Deck app not found. Use Locate apps.');return
        status=load_json(deck_runtime(self.deck)/'dms_live_status.json',{})
        if not status or not status.get('heartbeat') or __import__('time').time()-status['heartbeat']>5:
            self.set_status('No live Deck bridge heartbeat. Install bridge and restart Deck Card Widget.');return
        source=status['store_path'];self.add_cards(status.get('cards',[]),source)
        self.set_status(f"Synced {len(status.get('cards',[]))} cards from running Deck Card Widget.")
    def board_send(self,entry):
        if not self.sbc:self.set_status('Streamer Board not found; use Locate apps.');return
        try:
            path=safe_path(entry['path'],'.sboard')
            active=live_board(self.sbc,self.slot.get())
            if not active:
                self.set_status(f'Pinboard slot {self.slot.get()} not running; open a board in Streamer Board Console first.');return
            instance=active['instance_id']
            commands=sbc_userdata(self.sbc)/'board_instances/commands'/f'{instance}.command.json'
            next_command(commands,'swap_state',{'path':str(path)})
            self.set_status(f'Board switch requested: {entry["name"]} → slot {self.slot.get()} (check RED once status confirms).')
        except Exception as e:self.set_status(f'Board switch refused: {e}')
    def deck_send(self,entry):
        if not self.deck:self.set_status('Deck app not found; use Locate apps.');return
        try:
            status=load_json(deck_runtime(self.deck)/'dms_live_status.json',{})
            import time
            if time.time()-float(status.get('heartbeat',0))>5:
                self.set_status('Deck Card Widget bridge not responding; start the patched app.');return
            source=safe_path(entry['source'],'.buttstore')
            path=deck_runtime(self.deck)/'dms_live_command.json'
            next_command(path,'load_and_select',{'path':str(source),'card_id':entry['id']})
            self.set_status(f'Deck selection requested: {entry["name"]}')
        except Exception as e:self.set_status(f'Deck switch refused: {e}')
    def _hold_menu(self,group,i,btn):
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
    def paint(self):
        self.board_rail.clear();self.deck_rail.clear()
        board=live_board(self.sbc,self.slot.get()) if self.sbc else None
        active_path=str(Path(board.get('board_path','')).resolve()) if board and board.get('board_path') else ''
        deckstatus=load_json(deck_runtime(self.deck)/'dms_live_status.json',{}) if self.deck else {}
        self.board_widgets=[];self.deck_widgets=[]
        for i,entry in enumerate(self.boards):
            isactive=bool(active_path and active_path==entry['path'])
            bg=board_color(entry['name'],isactive)
            b=HoldButton(self.board_rail.inner,tap=lambda e=entry:self.board_send(e),hold=lambda w,j=i:self._hold_menu('board',j,w),
                text=('● ' if isactive else '')+entry['name'],background=bg,foreground=label_color(bg),activebackground=bg,
                relief='raised',bd=2,width=18,height=2,wraplength=135)
            b.pack(side='left',padx=4,pady=8)
            self.board_widgets.append((b,entry))
        for i,entry in enumerate(self.decks):
            # Grey default; only an explicit per-card border color overrides it.
            bg=entry.get('color','#666c78')
            active=(deckstatus.get('store_path')==entry.get('source') and deckstatus.get('active_card_id')==entry['id'])
            b=HoldButton(self.deck_rail.inner,tap=lambda e=entry:self.deck_send(e),hold=lambda w,j=i:self._hold_menu('deck',j,w),
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
        for btn,entry in getattr(self,'board_widgets',[]):
            isactive=bool(active_path and active_path==entry['path'])
            bg=board_color(entry['name'],isactive)
            btn.configure(background=bg,foreground=label_color(bg),activebackground=bg,
                          text=('● ' if isactive else '')+entry['name'])
        for btn,entry in getattr(self,'deck_widgets',[]):
            isactive=(deckstatus.get('store_path')==entry.get('source') and deckstatus.get('active_card_id')==entry['id'])
            btn.configure(relief='sunken' if isactive else 'raised',bd=3 if isactive else 2,
                          text=('● ' if isactive else '')+entry['name'])
    def poll(self):
        # Update styles in place so a held button cannot disappear while the user presses it.
        self.refresh_styles()
        self.root.after(1500,self.poll)
    def close(self):self.save();self.root.destroy()
    def run(self):self.root.mainloop()

if __name__=='__main__':LiveSwitcher().run()
