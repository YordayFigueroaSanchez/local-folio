"""Shim de compatibilidad: el servidor vive en local_folio/server.py.

Se mantiene este archivo para que los launchers existentes
(run_web_ui.ps1, stop_web_ui.ps1, .vscode/tasks.json) sigan funcionando.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_folio.server import main  # noqa: E402

if __name__ == "__main__":
    main()
