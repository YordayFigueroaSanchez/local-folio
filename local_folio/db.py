"""Conexión SQLite, esquema, migraciones y backups de la base de datos."""

import datetime as dt
import os
import sqlite3

DB_FILENAME = "mi_portafolio.db"

_PACKAGE_DIR: str = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT: str = os.path.dirname(_PACKAGE_DIR)
# Los datos (DB, backups, active_db.txt) viven historicamente en scripts/.
# Moverlos a un directorio data/ propio es un cambio pendiente separado,
# para no invalidar instalaciones existentes.
DATA_DIR: str = os.path.join(PROJECT_ROOT, "scripts")

_ACTIVE_DB_CONFIG: str = os.path.join(DATA_DIR, "active_db.txt")
_DEFAULT_DB_PATH: str = os.path.join(DATA_DIR, DB_FILENAME)


def _load_active_db_path() -> str:
    """Read persisted active DB path from config file; fall back to default.

    Relative paths are resolved against DATA_DIR so the config remains
    valid when the project is copied or moved to a new location.
    If the resolved path does not exist the config is ignored and the
    default local DB is used.
    """
    if os.path.isfile(_ACTIVE_DB_CONFIG):
        try:
            raw = open(_ACTIVE_DB_CONFIG, encoding="utf-8").read().strip()
            if raw:
                path = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(DATA_DIR, raw))
                if os.path.isfile(path):
                    return path
                # Stored path no longer exists (project moved/copied) — reset
                _save_active_db_path(_DEFAULT_DB_PATH)
        except OSError:
            pass
    return _DEFAULT_DB_PATH


def _save_active_db_path(path: str) -> None:
    """Persist the active DB path to config file.

    Paths inside DATA_DIR are stored as relative paths so the config
    stays portable when the project directory is copied to another location.
    Paths on a different drive or outside the project are stored absolute.
    """
    try:
        try:
            rel = os.path.relpath(path, DATA_DIR)
            path_to_store = path if rel.startswith("..") else rel
        except ValueError:
            # relpath raises ValueError on Windows for cross-drive paths
            path_to_store = path
        with open(_ACTIVE_DB_CONFIG, "w", encoding="utf-8") as f:
            f.write(path_to_store)
    except OSError:
        pass


# Active database path — loaded from config file on startup
_ACTIVE_DB_PATH: str = _load_active_db_path()


def get_db_path() -> str:
    """Return the active database path (can be overridden at runtime via set_active_db_path)."""
    return _ACTIVE_DB_PATH


def set_active_db_path(path: str) -> None:
    """Override the active database path and persist the choice across restarts."""
    global _ACTIVE_DB_PATH
    _ACTIVE_DB_PATH = path
    _save_active_db_path(path)


def get_connection() -> sqlite3.Connection:
    """Create a SQLite connection with foreign keys enabled and named-row access."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Database backup and selection helpers
# ---------------------------------------------------------------------------

def backups_dir() -> str:
    """Return the path to the backups subdirectory (created on demand)."""
    path = os.path.join(DATA_DIR, "backups")
    os.makedirs(path, exist_ok=True)
    return path


def create_db_backup(db_path: str | None = None) -> str:
    """Copy the active database to the backups directory using SQLite backup API.

    Returns the absolute path of the created backup file.
    """
    source_path = db_path or get_db_path()
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"mi_portafolio_{timestamp}.db"
    backup_path = os.path.join(backups_dir(), backup_name)

    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(backup_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    return backup_path


def list_db_files(db_path: str | None = None) -> dict:
    """Return info about the active database and all backup files.

    Returns a dict:
      { "active": <abs_path>, "files": [{"name", "path", "size_kb", "modified_at"}, ...] }
    The active DB is always the first entry.
    """
    active = db_path or get_db_path()
    backups_path = backups_dir()

    def _file_info(path: str) -> dict:
        stat = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": path,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified_at": dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

    seen: set[str] = set()
    files = []

    def _add(path: str) -> None:
        norm = os.path.normpath(path)
        if norm not in seen and os.path.exists(path):
            seen.add(norm)
            files.append(_file_info(path))

    _add(active)

    if os.path.isdir(backups_path):
        for entry in sorted(os.scandir(backups_path), key=lambda e: e.stat().st_mtime, reverse=True):
            if entry.name.endswith(".db"):
                _add(entry.path)

    return {"active": active, "files": files}


def validate_sqlite_file(path: str) -> bool:
    """Return True if the file exists and passes SQLite PRAGMA integrity_check."""
    if not os.path.isfile(path):
        return False
    conn = None
    try:
        conn = sqlite3.connect(path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        return result is not None and result[0] == "ok"
    except sqlite3.Error:
        return False
    finally:
        if conn is not None:
            conn.close()


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create required tables when they do not exist."""
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cuentas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_cuenta TEXT NOT NULL,
            moneda TEXT NOT NULL,
            permite_stake INTEGER NOT NULL CHECK(permite_stake IN (0, 1)),
            objetivo_stake_mensual REAL NOT NULL DEFAULT 0
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transacciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cuenta INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL CHECK(monto > 0),
            tipo TEXT NOT NULL CHECK(tipo IN ('ingreso', 'retiro')),
            descripcion TEXT,
            precio_usd REAL NOT NULL DEFAULT 0,
            monto_usd REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(id_cuenta) REFERENCES cuentas(id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS historial_precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_calculo TEXT NOT NULL,
            moneda TEXT NOT NULL,
            precio_usd REAL NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monedas (
            simbolo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL
        )
        """
    )

    conn.commit()

    # Seed currencies from existing accounts (idempotent).
    cursor.execute(
        "INSERT OR IGNORE INTO monedas (simbolo, nombre) SELECT DISTINCT moneda, moneda FROM cuentas"
    )
    conn.commit()

    ensure_usd_only_schema(conn)


def ensure_usd_only_schema(conn: sqlite3.Connection) -> None:
    """Migrate existing databases to the USD-only schema."""
    cursor = conn.cursor()

    # Detect current CHECK constraint on tipo to determine if 'reward' migration is needed.
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='transacciones'")
    tx_sql_row = cursor.fetchone()
    tx_sql = tx_sql_row[0] if tx_sql_row else ""

    # Migrate transacciones -> keep only USD-only columns AND add 'reward' tipo.
    cursor.execute("PRAGMA table_info(transacciones)")
    tx_columns = {row[1] for row in cursor.fetchall()}
    needs_tx_migration = (
        "monto_usd" not in tx_columns
        or "usd_uyu" in tx_columns
        or "monto_uyu" in tx_columns
        or "'reward'" not in tx_sql
        or "categoria" in tx_columns
    )

    if needs_tx_migration:
        monto_usd_expr = "COALESCE(monto_usd, ROUND(monto * precio_usd, 8))" if "monto_usd" in tx_columns else "ROUND(monto * precio_usd, 8)"

        cursor.execute(
            """
            CREATE TABLE transacciones_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_cuenta INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                monto REAL NOT NULL CHECK(monto > 0),
                tipo TEXT NOT NULL CHECK(tipo IN ('ingreso', 'retiro', 'reward')),
                descripcion TEXT,
                precio_usd REAL NOT NULL DEFAULT 0,
                monto_usd REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(id_cuenta) REFERENCES cuentas(id)
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO transacciones_new (
                id, id_cuenta, fecha, monto, tipo, descripcion, precio_usd, monto_usd
            )
            SELECT
                id,
                id_cuenta,
                fecha,
                monto,
                tipo,
                descripcion,
                COALESCE(precio_usd, 0),
                {monto_usd_expr}
            FROM transacciones
            """
        )
        cursor.execute("DROP TABLE transacciones")
        cursor.execute("ALTER TABLE transacciones_new RENAME TO transacciones")

    # Migrate historial_precios -> keep only USD price snapshots.
    cursor.execute("PRAGMA table_info(historial_precios)")
    price_columns = {row[1] for row in cursor.fetchall()}
    needs_price_migration = "uyu_por_usd" in price_columns
    if needs_price_migration:
        cursor.execute(
            """
            CREATE TABLE historial_precios_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_calculo TEXT NOT NULL,
                moneda TEXT NOT NULL,
                precio_usd REAL NOT NULL
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO historial_precios_new (id, fecha_calculo, moneda, precio_usd)
            SELECT id, fecha_calculo, moneda, precio_usd
            FROM historial_precios
            """
        )
        cursor.execute("DROP TABLE historial_precios")
        cursor.execute("ALTER TABLE historial_precios_new RENAME TO historial_precios")

    # Migrate cuentas -> rename objetivo_stake_anual to objetivo_stake_mensual.
    cursor.execute("PRAGMA table_info(cuentas)")
    cuenta_columns = {row[1] for row in cursor.fetchall()}
    if "objetivo_stake_anual" in cuenta_columns:
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("DROP TABLE IF EXISTS cuentas_new")
        cursor.execute(
            """
            CREATE TABLE cuentas_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_cuenta TEXT NOT NULL,
                moneda TEXT NOT NULL,
                permite_stake INTEGER NOT NULL CHECK(permite_stake IN (0, 1)),
                objetivo_stake_mensual REAL NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO cuentas_new (id, nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
            SELECT id, nombre_cuenta, moneda, permite_stake, objetivo_stake_anual
            FROM cuentas
            """
        )
        cursor.execute("DROP TABLE cuentas")
        cursor.execute("ALTER TABLE cuentas_new RENAME TO cuentas")
        cursor.execute("PRAGMA foreign_keys = ON")

    # Add fecha_ultima_modificacion if missing (aditiva, no destructiva).
    cursor.execute("PRAGMA table_info(transacciones)")
    tx_cols_now = {row[1] for row in cursor.fetchall()}
    if "fecha_ultima_modificacion" not in tx_cols_now:
        cursor.execute(
            "ALTER TABLE transacciones ADD COLUMN fecha_ultima_modificacion TEXT"
        )
        # Backfill existing rows using fecha as initial value.
        cursor.execute(
            "UPDATE transacciones SET fecha_ultima_modificacion = fecha "
            "WHERE fecha_ultima_modificacion IS NULL"
        )

    conn.commit()
