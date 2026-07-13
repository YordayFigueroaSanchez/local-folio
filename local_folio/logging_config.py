"""Configuración centralizada de logging para el paquete local_folio.

Los mensajes puramente interactivos de la CLI (menús, prompts, resúmenes
de movimientos) siguen usando print(): son la interfaz de usuario de la
aplicación, no diagnóstico. Este módulo cubre los mensajes operativos y
de advertencia (arranque/apagado del servidor, avisos de precios, fallas
de coherencia) que antes eran print() sueltos sin nivel ni timestamp.
"""

import logging
import os

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_LEVEL = "INFO"

_configured = False


def configure_logging(level: str | int | None = None) -> None:
    """Configure the 'local_folio' logger with a single console handler.

    Idempotent: subsequent calls are no-ops so both entrypoints (CLI and
    server) can call it unconditionally without duplicating handlers.
    The level can be overridden via the LOCAL_FOLIO_LOG_LEVEL environment
    variable (e.g. DEBUG, INFO, WARNING); defaults to INFO.
    """
    global _configured
    if _configured:
        return

    resolved_level = level if level is not None else os.environ.get("LOCAL_FOLIO_LOG_LEVEL", _DEFAULT_LEVEL)

    logger = logging.getLogger("local_folio")
    logger.setLevel(resolved_level)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False

    _configured = True
