"""Shim de compatibilidad: la lógica vive en el paquete local_folio.

Se mantiene este archivo para que los scripts que hacen
`from gestor_portafolio import ...` (p. ej. setup_test_ont.py) y el
lanzamiento directo de la CLI sigan funcionando.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from local_folio import *  # noqa: E402,F401,F403
from local_folio.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
