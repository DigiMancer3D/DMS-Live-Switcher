import json, os, tempfile, time, unittest
from pathlib import Path
from switch_core import board_color, card_color, label_color, atomic_json, load_json, next_command, read_buttstore, live_board
from scripts.install_bridges import edited_pin, edited_deck

class CoreTests(unittest.TestCase):
    def test_episode_pattern_case_insensitive(self):
        for s in ('EP94','ep 1','eP-093','Ep: 10'):
            self.assertEqual(board_color(s),'#7139ba')
        self.assertEqual(board_color('Introduction'),'#23734f')
        self.assertEqual(board_color('EP94',True),'#b52a38')
        self.assertEqual(board_color('prep'),'#23734f')
        self.assertEqual(board_color('STEP12'),'#23734f')
    def test_card_color_default_and_explicit(self):
        self.assertEqual(card_color({'id':'a'}),'#666c78')
        self.assertEqual(card_color({'deck_border_type':'SPONSOR'}),'#ff2424')
        self.assertEqual(card_color({'deck_border_type':'OBS'}),'#ff00ff')
        self.assertEqual(card_color({'special_border_color':'#aB12cD'}),'#aB12cD')
        self.assertEqual(card_color({'style':{'special_border_color':'#123456'}}),'#123456')
        self.assertEqual(card_color({'border':{'enabled':True,'color':'#abcdef'}}),'#abcdef')
        self.assertEqual(card_color({'border':{'enabled':False,'color':'#abcdef'}}),'#666c78')
        self.assertEqual(label_color('#ffffff'),'#121212')
    def test_command_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'commands/c.json'
            first=next_command(path,'load_board',{'path':'/tmp/example.sboard'})
            second=next_command(path,'load_board',{'path':'/tmp/example.sboard'})
            self.assertGreater(second,first)
            self.assertEqual(load_json(path)['command'],'load_board')
    def test_buttstore_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'good.buttstore'
            atomic_json(path,{'buttstore_format':'3DCP-BUTTSTORE','body':{'cards':[{'id':'x','label':'Example'}]}})
            self.assertEqual(read_buttstore(path)[0]['label'],'Example')
            atomic_json(path,{'format':'not-buttstore'})
            with self.assertRaises(ValueError):read_buttstore(path)
    def test_patches_idempotent_and_compile(self):
        pin='''from pathlib import Path\nclass PinBoardApp:\n    def load_board(self,p):\n        pass\n    def apply_command(self,command,payload):\n        if command == "rise_output":\n            pass\n        elif command == "close":\n            pass\n'''
        deck='''RUNTIME_DIR = 1\nclass PerspectiveConsoleApp:\n    def __init__(self):\n        self.root.after(1200, self.archive_duplicate_buttstores_after_load)\n'''
        self.assertEqual(edited_pin(pin.replace('        elif command == "close":', '        elif command == "swap_state":\n            pass\n        elif command == "close":')) , pin.replace('        elif command == "close":', '        elif command == "swap_state":\n            pass\n        elif command == "close":'))
        for src,fn in ((pin,edited_pin),(deck,edited_deck)):
            new=fn(src);compile(new,'<test>','exec')
            self.assertEqual(fn(new),new)
    def test_fresh_board_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'user_data/board_instances'
            folder.mkdir(parents=True)
            atomic_json(folder/'ok.status.json',{'slot':1,'instance_id':'hello',
                'heartbeat':time.time(),'pid':os.getpid(),'board_path':'/tmp/x.sboard'})
            self.assertEqual(live_board(root,1)['instance_id'],'hello')
            self.assertIsNone(live_board(root,2))

if __name__=='__main__':unittest.main()
