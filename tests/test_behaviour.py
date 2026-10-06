"""Eye, lip, earphone and voice detectors of the interview page, on synthetic signals:  python -m tests.test_behaviour"""
import subprocess
import sys
from pathlib import Path

r = subprocess.run(["node", "--experimental-transform-types", "--no-warnings", str(Path(__file__).with_name("behaviour_checks.mts"))],
                   capture_output=True, text=True)
print(r.stdout + r.stderr)
sys.exit(r.returncode)
