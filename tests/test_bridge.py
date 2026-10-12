import tempfile, unittest
from pathlib import Path
from switch_core import atomic_json
from dms_live_deck_bridge import _switch, border_color

class Var:
    def __init__(self): self.v=None
    def set(self, x):self.v=x
    def get(self):return self.v
    def configure(self,**kw):pass

class Store:
    def __init__(self,path,card):
        self.path=Path(path)
        self.data={'under_header':{},'header':{'resource_profile':'low','active_card_id':card},'body':{'cards':[{'id':card,'label':'Other'}]}}
    @classmethod
    def load_or_create(cls,p):return cls(p,'new-card')
    def active_card(self):return self.data['body']['cards'][0]

class App:
    def __init__(self,path):
        self.store=Store(path,'old-card')
        self.scan_loop_var=Var();self.output_visible_var=Var();self.resource_profile_var=Var()
        self.scan_speed_var=Var();self.scanner_color_var=Var();self.speed_scale=Var()
        self.speed_label=Var();self.status_var=Var();self.calls=[]
    def save_now(self):self.calls.append('save-old')
    def refresh_deck_buttons(self):self.calls.append('refresh-buttons')
    def load_active_card_into_editor(self):self.calls.append('reset-editor')
    def select_card(self,id):
        self.calls.append('select-new')
        if self.calls.index('reset-editor')>self.calls.index('select-new'):
            raise AssertionError('old editor content would overwrite fresh store')
        self.store.data['header']['active_card_id']=id

class BridgeTests(unittest.TestCase):
    def test_native_deck_border_palette(self):
        self.assertEqual(border_color({'deck_border_type':'PARTNER'}),'#2f78ff')
        self.assertEqual(border_color({'deck_border_type':'FAN'}),'#38b86b')
        self.assertEqual(border_color({'deck_border_type':'NONE'}),'#666c78')
    def test_new_store_preloads_editor_before_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'old.buttstore';new=Path(tmp)/'new.buttstore'
            old.write_text('{}')
            atomic_json(new,{'buttstore_format':'3DCP-BUTTSTORE',
                             'body':{'cards':[{'id':'new-card','label':'Test'}]}})
            app=App(old)
            _switch(app,{'path':str(new),'card_id':'new-card'})
            self.assertEqual(app.calls,['save-old','refresh-buttons','reset-editor','select-new'])
            self.assertEqual(app.store.path,new)
    def test_nonexistent_card_is_rejected_without_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'old.buttstore';new=Path(tmp)/'new.buttstore'
            old.write_text('{}');atomic_json(new,{'buttstore_format':'3DCP-BUTTSTORE',
                                         'body':{'cards':[{'id':'a'}]}})
            app=App(old)
            with self.assertRaises(ValueError):_switch(app,{'path':str(new),'card_id':'b'})
            self.assertEqual(app.calls,[])

if __name__=='__main__':unittest.main()
