"""Historical entry point; replacement uses behavioral rollback tests."""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parent
raise SystemExit(subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', str(root/'tests'), '-p', 'test_release.py'], cwd=root))
