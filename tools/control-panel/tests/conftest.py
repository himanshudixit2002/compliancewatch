"""The control app's modules sit in tools/control-panel, which is no package: put it on the path,
and this folder too for the tests' own helper (serverkit).

The tests import panel_core, panel_catalog, panel_server and panel_demo, so they run on a machine
with no display, no Docker and no network. The helper they start listens on 127.0.0.1 only.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
