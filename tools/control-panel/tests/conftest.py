"""The control panel's modules sit in tools/control-panel, which is no package: put it on the path.

The tests import panel_core only, never control_panel or tkinter, so they run on a machine with
no display, no Docker and no network.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
