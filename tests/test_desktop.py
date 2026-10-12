"""Checks for KDE installation and safe upgrade behavior without touching real user HOME."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/desktop_setup.py'


class DesktopSetupTests(unittest.TestCase):
    def run_action(self, home, action, success=True):
        env = dict(os.environ, HOME=str(home))
        result = subprocess.run([sys.executable, str(SCRIPT), action], env=env,
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
        return result

    def test_install_creates_launcher_icon_and_stable_app(self):
        with tempfile.TemporaryDirectory(prefix='dms-desktop-unit-') as tmp:
            home=Path(tmp)
            self.run_action(home,'install')
            root=home/'Applications/DMS_Live_Switcher'
            desktop=home/'.local/share/applications/dms-live-switcher.desktop'
            icon=home/'.local/share/icons/hicolor/256x256/apps/dms-live-switcher.png'
            self.assertTrue((root/'run.sh').is_file())
            self.assertTrue((root/'scripts/install_bridges.py').is_file())
            self.assertTrue(icon.is_file())
            value=desktop.read_text()
            self.assertIn('StartupWMClass=Dmsliveswitcher',value)
            self.assertIn('Icon=dms-live-switcher',value)
            self.assertIn('Terminal=false',value)
            self.assertIn(str(root/'run.sh'),value)
            self.assertIn('Categories=Utility;',value)
            self.assertNotIn('Categories=Office;Utility;',value)

    def test_conflict_backup_and_safe_remove(self):
        with tempfile.TemporaryDirectory(prefix='dms-desktop-unit-') as tmp:
            home=Path(tmp)
            self.run_action(home,'install')
            root=home/'Applications/DMS_Live_Switcher'
            (root/'user-custom-file.txt').write_text('KEEP ORIGINAL')
            self.run_action(home,'install',success=False)
            self.assertTrue((root/'user-custom-file.txt').is_file())
            self.run_action(home,'upgrade')
            self.assertFalse((root/'user-custom-file.txt').exists())
            backups=list((home/'.local/share/dms-live-switcher/desktop-backups').glob('DMS_Live_Switcher-*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'user-custom-file.txt').read_text(),'KEEP ORIGINAL')
            self.run_action(home,'remove')
            self.assertTrue((root/'run.sh').is_file())
            self.assertFalse((home/'.local/share/applications/dms-live-switcher.desktop').exists())
            self.assertTrue(backups[0].exists())


if __name__=='__main__': unittest.main()
