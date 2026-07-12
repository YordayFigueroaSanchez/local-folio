import datetime as dt
import json
import os
import sqlite3
from urllib import error, parse, request

DB_FILENAME = "mi_portafolio.db"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
HTTP_TIMEOUT = 12.0

_SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
_ACTIVE_DB_CONFIG: str = os.path.join(_SCRIPT_DIR, "active_db.txt")
_DEFAULT_DB_PATH: str = os.path.join(_SCRIPT_DIR, DB_FILENAME)


def _load_active_db_path() -> str:
    """Read persisted active DB path from config file; fall back to default.

    Relative paths are resolved against _SCRIPT_DIR so the config remains
    valid when the project is copied or moved to a new location.
    If the resolved path does not exist the config is ignored and the
    default local DB is used.
    """
    if os.path.isfile(_ACTIVE_DB_CONFIG):
        try:
            raw = open(_ACTIVE_DB_CONFIG, encoding="utf-8").read().strip()
            if raw:
                path = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(_SCRIPT_DIR, raw))
                if os.path.isfile(path):
                    return path
                # Stored path no longer exists (project moved/copied) — reset
                _save_active_db_path(_DEFAULT_DB_PATH)
        except OSError:
            pass
    return _DEFAULT_DB_PATH


def _save_active_db_path(path: str) -> None:
    """Persist the active DB path to config file.

    Paths inside _SCRIPT_DIR are stored as relative paths so the config
    stays portable when the project directory is copied to another location.
    Paths on a different drive or outside the project are stored absolute.
    """
    try:
        try:
            rel = os.path.relpath(path, _SCRIPT_DIR)
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

SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "ADA": "cardano",
    "SOL": "solana",
    "XRP": "ripple",
    "DOT": "polkadot",
    "DOGE": "dogecoin",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "AVAX": "avalanche-2",
    "TRX": "tron",
    "LINK": "chainlink",
    "ATOM": "cosmos",
    "NEAR": "near",
    "XLM": "stellar",
    "ONT": "ontology",
    "ONE": "harmony",
    "NYM": "nym",
}


def get_db_path() -> str:
    """Return the active database path (can be overridden at runtime via set_active_db_path)."""
    return _ACTIVE_DB_PATH


def set_active_db_path(path: str) -> None:
    """Override the active database path and persist the choice across restarts."""
    global _ACTIVE_DB_PATH
    _ACTIVE_DB_PATH = path
    _save_active_db_path(path)


def get_connection() -> sqlite3.Connection:
    """Create a SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(get_db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Database backup and selection helpers
# ---------------------------------------------------------------------------

def _backups_dir() -> str:
    """Return the path to the backups subdirectory (created on demand)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backups_dir = os.path.join(script_dir, "backups")
    os.makedirs(backups_dir, exist_ok=True)
    return backups_dir


def create_db_backup(db_path: str | None = None) -> str:
    """Copy the active database to scripts/backups/ using SQLite backup API.

    Returns the absolute path of the created backup file.
    """
    source_path = db_path or get_db_path()
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"mi_portafolio_{timestamp}.db"
    backup_path = os.path.join(_backups_dir(), backup_name)

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
    backups_dir = _backups_dir()

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

    if os.path.isdir(backups_dir):
        for entry in sorted(os.scandir(backups_dir), key=lambda e: e.stat().st_mtime, reverse=True):
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


def now_iso() -> str:
    """Return current local datetime in ISO-like format without timezone."""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_json(url: str) -> dict:
    """Fetch and decode a JSON payload from a URL."""
    with request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Unexpected JSON payload shape")
    return data


def get_active_symbols(conn: sqlite3.Connection) -> list[str]:
    """Return distinct currency symbols from accounts and the currencies table."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT UPPER(moneda) FROM cuentas "
        "UNION "
        "SELECT DISTINCT UPPER(simbolo) FROM monedas"
    )
    return [row[0] for row in cursor.fetchall() if row[0]]


def fetch_crypto_prices_usd(symbols: list[str]) -> dict[str, float]:
    """Fetch crypto prices in USD from CoinGecko for supported symbols."""
    symbol_to_price: dict[str, float] = {}
    coingecko_ids: list[str] = []
    id_to_symbol: dict[str, str] = {}

    for symbol in symbols:
        if symbol == "USD":
            symbol_to_price[symbol] = 1.0
            continue

        coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol)
        if coin_id is None:
            print(f"Aviso: símbolo sin mapeo en CoinGecko: {symbol}")
            continue

        coingecko_ids.append(coin_id)
        id_to_symbol[coin_id] = symbol

    if coingecko_ids:
        query_params = parse.urlencode({"ids": ",".join(coingecko_ids), "vs_currencies": "usd"})
        url = f"{COINGECKO_API_URL}?{query_params}"
        data = fetch_json(url)

        for coin_id in coingecko_ids:
            symbol = id_to_symbol[coin_id]
            try:
                symbol_to_price[symbol] = float(data[coin_id]["usd"])
            except (KeyError, TypeError, ValueError):
                print(f"Aviso: no se pudo obtener precio USD para {symbol} ({coin_id})")

    return symbol_to_price


def save_price_snapshots(
    conn: sqlite3.Connection, symbol_to_price_usd: dict[str, float]
) -> None:
    """Store one price snapshot row per currency symbol."""
    if not symbol_to_price_usd:
        return

    cursor = conn.cursor()
    timestamp = now_iso()
    rows = [
        (timestamp, symbol, float(price_usd))
        for symbol, price_usd in symbol_to_price_usd.items()
    ]
    cursor.executemany(
        """
        INSERT INTO historial_precios (fecha_calculo, moneda, precio_usd)
        VALUES (?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def update_prices_from_internet(conn: sqlite3.Connection) -> None:
    """Fetch USD prices and persist them in price history."""
    symbols = get_active_symbols(conn)
    if not symbols:
        print("No hay cuentas creadas; primero cree una cuenta.")
        return

    symbol_to_price = fetch_crypto_prices_usd(symbols)

    # Fiat handling for direct valuation in reports.
    if "USD" in symbols:
        symbol_to_price["USD"] = 1.0
    save_price_snapshots(conn, symbol_to_price)
    print(
        "Precios actualizados correctamente "
        f"({len(symbol_to_price)} moneda/s guardada/s, referencia USD-only)."
    )


def create_account(conn: sqlite3.Connection) -> None:
    """Create a new account with staking settings."""
    print("\n=== Crear Nueva Cuenta ===")
    nombre = input("Nombre de la cuenta: ").strip()
    moneda = input("Moneda (ej: ETH, USD, BTC): ").strip().upper()

    if not nombre or not moneda:
        print("Error: nombre y moneda son obligatorios.")
        return

    permite_stake_input = input("¿Permite staking? (s/n): ").strip().lower()
    permite_stake = 1 if permite_stake_input == "s" else 0

    objetivo = 0.0
    if permite_stake == 1:
        objetivo_raw = input("Meta de rewards esperados en 30 días (USD): ").strip()
        try:
            objetivo = float(objetivo_raw)
            if objetivo < 0:
                raise ValueError
        except ValueError:
            print("Error: meta inválida.")
            return

    try:
        conn.execute(
            """
            INSERT INTO cuentas (nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
            VALUES (?, ?, ?, ?)
            """,
            (nombre, moneda, permite_stake, objetivo),
        )
        conn.commit()
        print("Cuenta creada correctamente.")
    except sqlite3.Error as exc:
        print(f"Error de base de datos al crear cuenta: {exc}")


def list_currencies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all registered currencies ordered by simbolo."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT simbolo, nombre FROM monedas ORDER BY simbolo")
    return cursor.fetchall()


def add_currency(conn: sqlite3.Connection, simbolo: str, nombre: str) -> None:
    """Insert a new currency. Raises ValueError if it already exists."""
    simbolo = simbolo.strip().upper()
    nombre = nombre.strip()
    if not simbolo:
        raise ValueError("El simbolo es requerido")
    if not nombre:
        raise ValueError("El nombre es requerido")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO monedas (simbolo, nombre) VALUES (?, ?)", (simbolo, nombre))
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"La moneda '{simbolo}' ya existe")


def delete_currency(conn: sqlite3.Connection, simbolo: str) -> None:
    """Delete a currency. Raises ValueError if any account uses it."""
    simbolo = simbolo.strip().upper()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cuentas WHERE moneda = ?", (simbolo,))
    count = cursor.fetchone()[0]
    if count > 0:
        raise ValueError(f"No se puede eliminar '{simbolo}': esta en uso por {count} cuenta(s)")
    cursor.execute("DELETE FROM monedas WHERE simbolo = ?", (simbolo,))
    conn.commit()


def list_accounts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all accounts ordered by id."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual
        FROM cuentas
        ORDER BY id
        """
    )
    return cursor.fetchall()


def search_accounts(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    """Search accounts by partial name or currency symbol."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    pattern = f"%{query.strip()}%"
    cursor.execute(
        """
        SELECT id, nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual
        FROM cuentas
        WHERE nombre_cuenta LIKE ? COLLATE NOCASE OR moneda LIKE ? COLLATE NOCASE
        ORDER BY id
        """,
        (pattern, pattern),
    )
    return cursor.fetchall()


def show_account_search(conn: sqlite3.Connection) -> None:
    """Display account search results by name or symbol."""
    print("\n=== Buscar Cuentas ===")
    query = input("Buscar por nombre o moneda: ").strip()
    if not query:
        print("Error: criterio vacio. Sugerencia: ingrese al menos 1 caracter.")
        return

    rows = search_accounts(conn, query)
    if not rows:
        print("No se encontraron cuentas. Sugerencia: pruebe otro filtro.")
        return

    for row in rows:
        print(
            f"[{row['id']}] {row['nombre_cuenta']} ({row['moneda']}) | "
            f"Stake: {'SI' if int(row['permite_stake']) == 1 else 'NO'} | "
            f"Meta: {float(row['objetivo_stake_mensual']):.8f}"
        )


def get_precision_for_currency(symbol: str) -> int:
    """
    Return the number of decimal places for a given currency symbol.

    Args:
        symbol: Currency symbol (e.g., 'BTC', 'USD', 'USDT')

    Returns:
        int: 8 for all currencies

    Examples:
        >>> get_precision_for_currency('BTC')
        8
        >>> get_precision_for_currency('USD')
        8
        >>> get_precision_for_currency('USDT')
        8
    """
    # Unified precision policy: always 8 decimals.
    return 8


def calculate_conversions(
    *,
    amount: float | None = None,
    monto_usd: float | None = None,
    precio_usd: float,
    currency_symbol: str,
    source_field: str
) -> dict[str, float]:
    """Calculate bidirectional conversions between native currency and USD."""
    if precio_usd <= 0:
        raise ValueError("precio_usd debe ser mayor que 0")
    if source_field not in {'amount', 'monto_usd'}:
        raise ValueError(f"source_field inválido: {source_field}")

    precision = get_precision_for_currency(currency_symbol)

    if source_field == 'amount':
        amount_value = amount
        monto_usd_value = round(amount_value * precio_usd, 8)
    else:
        monto_usd_value = monto_usd
        amount_value = round(monto_usd_value / precio_usd, precision)

    return {
        'amount': amount_value,
        'monto_usd': monto_usd_value,
    }


def validate_coherence(
    *,
    amount: float,
    monto_usd: float,
    precio_usd: float,
    source_field: str,
    tolerance: float = 0.01
) -> tuple[bool, str | None]:
    """
    Validate mathematical coherence between entered value and calculated values.

    Only validates the relevant pair based on which field the user entered.

    Args:
        amount: Amount in native currency
        monto_usd: Amount in USD
        precio_usd: Price USD of the currency
        source_field: Field that user entered
        tolerance: Acceptable error margin (default 0.01)

    Returns:
        (is_valid, error_message)
        - is_valid: True if coherent, False if not
        - error_message: None if valid, description of error if invalid

    Examples:
        >>> validate_coherence(
        ...     amount=0.01,
        ...     monto_usd=950.0,
        ...     precio_usd=95000.0,
        ...     source_field='amount'
        ... )
        (True, None)
    """
    # Validate only the relevant pair based on source field
    if source_field == 'amount':
        # User entered native → validate native * precio_usd ≈ monto_usd
        expected_usd = amount * precio_usd
        difference = abs(expected_usd - monto_usd)
        
        if difference > tolerance:
            return (
                False,
                f"Incoherencia: monto nativo ({amount}) * precio_usd ({precio_usd}) "
                f"= {expected_usd:.8f}, pero monto_usd registrado = {monto_usd:.8f}. "
                f"Diferencia: {difference:.8f}"
            )
    
    elif source_field == 'monto_usd':
        # User entered USD → validate monto_usd / precio_usd ≈ amount
        expected_amount = monto_usd / precio_usd
        difference = abs(expected_amount - amount)
        
        if difference > tolerance:
            return (
                False,
                f"Incoherencia: monto_usd ({monto_usd}) / precio_usd ({precio_usd}) "
                f"= {expected_amount:.8f}, pero monto nativo registrado = {amount:.8f}. "
                f"Diferencia: {difference:.8f}"
            )
    
    else:
        return (False, f"source_field no soportado en flujo USD-only: {source_field}")
    
    # If we reach here, validation passed
    return (True, None)


def fetch_market_prices(currency_symbol: str) -> float | None:
    """
    Fetch the USD market price for a specific currency.

    Queries CoinGecko for COIN/USD price.

    Args:
        currency_symbol: Currency symbol (e.g., 'BTC', 'ETH', 'USD')

    Returns:
        precio_usd if successful
        None if fails (timeout, network error, unsupported currency)

    Timeout: 12 seconds per API request

    Examples:
        >>> precio_usd = fetch_market_prices('BTC')
        >>> if precio_usd:
        ...     print(f"BTC: ${precio_usd}")
    """
    try:
        # Special case: USD account
        if currency_symbol.upper() == 'USD':
            return 1.0

        # Crypto: query CoinGecko
        symbol_upper = currency_symbol.upper()
        coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol_upper)
        if coin_id is None:
            # Unsupported currency
            return None

        # Fetch crypto price in USD directly from CoinGecko id
        query_params = parse.urlencode({"ids": coin_id, "vs_currencies": "usd"})
        url = f"{COINGECKO_API_URL}?{query_params}"
        data = fetch_json(url)
        precio_usd = float(data[coin_id]["usd"])

        if precio_usd <= 0:
            # Failed to get price
            return None

        return precio_usd

    except (error.URLError, TimeoutError, ValueError, KeyError):
        # Any error → return None (fallback to manual entry)
        return None


def choose_account(conn: sqlite3.Connection) -> int | None:
    """Prompt the user to select an account id."""
    accounts = list_accounts(conn)
    if not accounts:
        print("No hay cuentas disponibles. Cree una cuenta primero.")
        return None

    print("\nCuentas disponibles:")
    for account in accounts:
        print(f"{account['id']}. {account['nombre_cuenta']} ({account['moneda']})")

    selected = input("Seleccione el ID de la cuenta: ").strip()
    try:
        account_id = int(selected)
    except ValueError:
        print("ID inválido.")
        return None

    if not any(account["id"] == account_id for account in accounts):
        print("ID de cuenta inexistente.")
        return None

    return account_id


def get_account_currency(conn: sqlite3.Connection, account_id: int) -> str | None:
    """Return account currency symbol for the given account id."""
    cursor = conn.cursor()
    cursor.execute("SELECT UPPER(moneda) FROM cuentas WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] else None


def register_transaction(conn: sqlite3.Connection) -> None:
    """Create an income or withdrawal transaction for a selected account with multi-currency input."""
    print("\n=== Registrar Movimiento ===")
    
    # Step 1: Choose account
    account_id = choose_account(conn)
    if account_id is None:
        return

    currency = get_account_currency(conn, account_id)
    if not currency:
        print("No se pudo obtener la moneda de la cuenta seleccionada.")
        return

    # Step 2: Fetch market prices
    print("Obteniendo precios...")
    suggested_price_usd = fetch_market_prices(currency)

    if suggested_price_usd is None:
        print("No se pudieron obtener precios automáticamente. Por favor ingrese manualmente.")
    
    # Step 3: Get basic data
    tipo = input("Tipo (ingreso/retiro/reward): ").strip().lower()
    if tipo not in {"ingreso", "retiro", "reward"}:
        print("Tipo inválido. Debe ser 'ingreso', 'retiro' o 'reward'.")
        return

    descripcion = input("Descripción (opcional): ").strip()

    # Step 4: Input prices with suggestions
    if suggested_price_usd is not None:
        precio_usd_prompt = f"Precio USD por {currency} [{suggested_price_usd:.8f}]: "
    else:
        precio_usd_prompt = f"Precio USD por {currency} (> 0): "
    
    precio_usd_raw = input(precio_usd_prompt).strip()
    if not precio_usd_raw and suggested_price_usd is not None:
        # User accepted suggestion (pressed Enter)
        precio_usd = suggested_price_usd
    else:
        try:
            precio_usd = float(precio_usd_raw)
            if precio_usd <= 0:
                raise ValueError
        except ValueError:
            print(f"Precio USD por {currency} inválido.")
            return
    
    # Step 5: Currency selection
    print(f"\n¿En qué moneda desea ingresar el monto?")
    print(f"  N: {currency}")
    print(f"  U: USD")
    
    currency_choice = input("Selección (N/U): ").strip().upper()
    if currency_choice not in {'N', 'U'}:
        print("Selección inválida. Debe ser N o U.")
        return
    
    # Map choice to source_field
    source_field_map = {'N': 'amount', 'U': 'monto_usd'}
    source_field = source_field_map[currency_choice]
    
    # Step 6: Input amount based on selection
    while True:  # Loop for retry on validation failure
        if currency_choice == 'N':
            monto_prompt = f"Monto ({currency}): "
        elif currency_choice == 'U':
            monto_prompt = "Monto (USD): "
        
        monto_raw = input(monto_prompt).strip()
        try:
            monto_entered = float(monto_raw)
            if monto_entered <= 0:
                raise ValueError
        except ValueError:
            print("Monto inválido. Debe ser mayor que 0.")
            return
        
        # Step 7: Calculate conversions
        try:
            if source_field == 'amount':
                result = calculate_conversions(
                    amount=monto_entered,
                    precio_usd=precio_usd,
                    currency_symbol=currency,
                    source_field='amount'
                )
            elif source_field == 'monto_usd':
                result = calculate_conversions(
                    monto_usd=monto_entered,
                    precio_usd=precio_usd,
                    currency_symbol=currency,
                    source_field='monto_usd'
                )
            
            monto = result['amount']
            monto_usd = result['monto_usd']
        except ValueError as e:
            print(f"Error en cálculo: {e}")
            return
        
        # Step 8: Show summary
        precision = get_precision_for_currency(currency)
        print("\nResumen del movimiento:")
        print(f"  Monto {currency}: {monto:.{precision}f}")
        print(f"  Monto USD: {monto_usd:.8f}")
        
        # Step 9: Validate coherence
        is_valid, error_msg = validate_coherence(
            amount=monto,
            monto_usd=monto_usd,
            precio_usd=precio_usd,
            source_field=source_field
        )
        
        if not is_valid:
            print(f"\n⚠️  ADVERTENCIA: {error_msg}")
            continue_choice = input("¿Desea continuar de todos modos? (SI/NO): ").strip().upper()
            if continue_choice != 'SI':
                print("Volviendo a ingresar monto...")
                continue  # Go back to amount input
        
        # Validation passed or user accepted warning
        break
    
    # Step 10: Confirm registration
    confirm = input("\n¿Confirmar registro? (SI/NO): ").strip().upper()
    if confirm != 'SI':
        print("Registro cancelado.")
        return
    
    # Step 11: Persist to database
    fecha = now_iso()
    try:
        conn.execute(
            """
            INSERT INTO transacciones (
                id_cuenta,
                fecha,
                monto,
                tipo,
                descripcion,
                precio_usd,
                monto_usd
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, fecha, monto, tipo, descripcion, precio_usd, monto_usd),
        )
        conn.commit()
        print("Movimiento registrado correctamente.")
    except sqlite3.Error as exc:
        print(f"Error de base de datos al registrar movimiento: {exc}")


def get_recent_account_movements(
    conn: sqlite3.Connection, account_id: int, limit: int = 10
) -> list[sqlite3.Row]:
    """Return recent movements for one account ordered by id desc."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    safe_limit = max(1, min(int(limit), 100))
    cursor.execute(
        """
        SELECT
            id,
            fecha,
            tipo,
            monto,
            precio_usd,
            monto_usd,
            descripcion,
            fecha_ultima_modificacion
        FROM transacciones
        WHERE id_cuenta = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (account_id, safe_limit),
    )
    return cursor.fetchall()


def get_recent_movements_all(
    conn: sqlite3.Connection, limit: int = 10
) -> list[sqlite3.Row]:
    """Return recent movements across all accounts ordered by id desc."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    safe_limit = max(1, min(int(limit), 100))
    cursor.execute(
        """
        SELECT
            t.id,
            t.id_cuenta,
            t.fecha,
            t.tipo,
            t.monto,
            t.precio_usd,
            t.monto_usd,
            t.descripcion,
            t.fecha_ultima_modificacion,
            c.nombre_cuenta  AS account_name,
            c.moneda         AS symbol
        FROM transacciones t
        JOIN cuentas c ON c.id = t.id_cuenta
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (safe_limit,),
    )
    return cursor.fetchall()


def show_recent_movements_by_account(conn: sqlite3.Connection) -> None:
    """Display recent movements for a selected account."""
    print("\n=== Ultimos Movimientos Por Cuenta ===")
    account_id = choose_account(conn)
    if account_id is None:
        return

    limit_input = input("Cantidad de movimientos a mostrar (default 10, max 100): ").strip()
    if not limit_input:
        limit = 10
    else:
        try:
            limit = int(limit_input)
            if limit <= 0:
                raise ValueError
        except ValueError:
            print("Error: limite invalido. Use un entero mayor que 0.")
            return

    rows = get_recent_account_movements(conn, account_id=account_id, limit=limit)
    if not rows:
        print("No hay movimientos para la cuenta seleccionada.")
        return

    for row in rows:
        print(
            f"[{row['id']}] {row['fecha']} | {row['tipo']} | "
            f"Monto: {float(row['monto']):.8f} | Precio USD: {float(row['precio_usd']):.8f} | "
            f"Desc: {row['descripcion'] or '-'}"
        )


def get_movement_by_id(conn: sqlite3.Connection, movement_id: int) -> sqlite3.Row | None:
    """Return one movement row by id or None if not found."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            t.id,
            t.id_cuenta,
            c.moneda,
            t.fecha,
            t.tipo,
            t.monto,
            t.precio_usd,
            t.monto_usd,
            t.descripcion,
            t.fecha_ultima_modificacion
        FROM transacciones t
        INNER JOIN cuentas c ON c.id = t.id_cuenta
        WHERE t.id = ?
        """,
        (movement_id,),
    )
    return cursor.fetchone()


def update_movement_by_id(
    conn: sqlite3.Connection,
    movement_id: int,
    tipo: str,
    monto: float,
    precio_usd: float,
    descripcion: str,
    fecha: str | None = None,
) -> bool:
    """Update one movement safely and return True when a row was changed."""
    if tipo not in {"ingreso", "retiro", "reward"}:
        raise ValueError("Tipo invalido")
    if monto <= 0 or precio_usd <= 0:
        raise ValueError("Valores numericos invalidos")

    fecha_mov = fecha if fecha else None
    cursor = conn.cursor()
    if fecha_mov:
        cursor.execute(
            """
            UPDATE transacciones
            SET tipo = ?, monto = ?, precio_usd = ?, monto_usd = ?,
                descripcion = ?, fecha = ?, fecha_ultima_modificacion = ?
            WHERE id = ?
            """,
            (
                tipo, float(monto), float(precio_usd),
                round(float(monto) * float(precio_usd), 8),
                descripcion, fecha_mov, now_iso(), movement_id,
            ),
        )
    else:
        cursor.execute(
            """
            UPDATE transacciones
            SET tipo = ?, monto = ?, precio_usd = ?, monto_usd = ?,
                descripcion = ?, fecha_ultima_modificacion = ?
            WHERE id = ?
            """,
            (
                tipo, float(monto), float(precio_usd),
                round(float(monto) * float(precio_usd), 8),
                descripcion, now_iso(), movement_id,
            ),
        )
    conn.commit()
    return cursor.rowcount > 0


def delete_movement_by_id(conn: sqlite3.Connection, movement_id: int) -> bool:
    """Delete one movement by id and return True when a row was removed."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transacciones WHERE id = ?", (movement_id,))
    conn.commit()
    return cursor.rowcount > 0


def edit_movement(conn: sqlite3.Connection) -> None:
    """Edit one movement with explicit SI/NO confirmation."""
    print("\n=== Editar Movimiento ===")
    movement_id_raw = input("ID del movimiento a editar: ").strip()
    try:
        movement_id = int(movement_id_raw)
        if movement_id <= 0:
            raise ValueError
    except ValueError:
        print("Error: ID invalido. Sugerencia: use un entero mayor que 0.")
        return

    row = get_movement_by_id(conn, movement_id)
    if row is None:
        print("Error: movimiento inexistente. Sugerencia: use la opcion de listar movimientos.")
        return

    print(
        f"Actual: [{row['id']}] {row['fecha']} | {row['tipo']} | "
        f"Monto: {float(row['monto']):.8f} | Precio USD: {float(row['precio_usd']):.8f} | "
        f"Desc: {row['descripcion'] or '-'}"
    )

    tipo = input(f"Tipo (ingreso/retiro) [{row['tipo']}]: ").strip().lower() or str(row["tipo"])
    if tipo not in {"ingreso", "retiro", "reward"}:
        print("Error: tipo invalido. Sugerencia: use ingreso, retiro o reward.")
        return

    monto_raw = input(f"Monto (> 0) [{float(row['monto'])}]: ").strip()
    precio_usd_raw = input(f"Precio USD por {row['moneda']} (> 0) [{float(row['precio_usd'])}]: ").strip()
    descripcion = input(f"Descripcion [{row['descripcion'] or ''}]: ").strip() or str(row["descripcion"] or "")

    try:
        monto = float(monto_raw) if monto_raw else float(row["monto"])
        precio_usd = float(precio_usd_raw) if precio_usd_raw else float(row["precio_usd"])
        if monto <= 0 or precio_usd <= 0:
            raise ValueError
    except ValueError:
        print("Error: valores numericos invalidos. Sugerencia: use valores mayores que 0.")
        return

    confirm = input("Confirmar edicion (SI/NO): ").strip().upper()
    if confirm != "SI":
        print("Operacion cancelada.")
        return

    try:
        updated = update_movement_by_id(
            conn,
            movement_id=movement_id,
            tipo=tipo,
            monto=monto,
            precio_usd=precio_usd,
            descripcion=descripcion,
        )
        if updated:
            print("OK: movimiento actualizado correctamente.")
        else:
            print("Error: no se pudo actualizar el movimiento.")
    except (sqlite3.Error, ValueError) as exc:
        print(f"Error al editar movimiento: {exc}")


def delete_movement(conn: sqlite3.Connection) -> None:
    """Delete one movement with explicit SI/NO confirmation."""
    print("\n=== Eliminar Movimiento ===")
    movement_id_raw = input("ID del movimiento a eliminar: ").strip()
    try:
        movement_id = int(movement_id_raw)
        if movement_id <= 0:
            raise ValueError
    except ValueError:
        print("Error: ID invalido. Sugerencia: use un entero mayor que 0.")
        return

    row = get_movement_by_id(conn, movement_id)
    if row is None:
        print("Error: movimiento inexistente. Sugerencia: use la opcion de listar movimientos.")
        return

    print(
        f"A eliminar: [{row['id']}] {row['fecha']} | {row['tipo']} | "
        f"Monto: {float(row['monto']):.8f} | Desc: {row['descripcion'] or '-'}"
    )
    confirm = input("Confirmar eliminacion (SI/NO): ").strip().upper()
    if confirm != "SI":
        print("Operacion cancelada.")
        return

    try:
        deleted = delete_movement_by_id(conn, movement_id)
        if deleted:
            print("OK: movimiento eliminado correctamente.")
        else:
            print("Error: no se pudo eliminar el movimiento.")
    except sqlite3.Error as exc:
        print(f"Error al eliminar movimiento: {exc}")


def show_quick_help() -> None:
    """Print quick usage guidance and menu shortcuts."""
    print("\n=== Ayuda Rapida ===")
    print("Flujo recomendado: crear cuenta -> registrar movimientos -> actualizar precios -> revisar portafolio.")
    print("Atajos en menu principal:")
    print("- h / ayuda / help: abrir ayuda rapida")
    print("- q / salir: salir del sistema")
    print("Reglas clave:")
    print("- Monto y precio USD deben ser mayores que 0.")
    print("- Edicion y eliminacion requieren confirmacion SI/NO.")


def normalize_main_option(raw_option: str) -> str:
    """Normalize main menu shortcuts to concrete option numbers."""
    option = raw_option.strip().lower()
    shortcuts = {
        "h": "10",
        "help": "10",
        "ayuda": "10",
        "q": "11",
        "salir": "11",
    }
    return shortcuts.get(option, option)


def get_account_balances(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return account balances using ingresos - retiros."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            c.id,
            c.nombre_cuenta,
            c.moneda,
            c.permite_stake,
            c.objetivo_stake_mensual,
            COALESCE(SUM(CASE WHEN t.tipo IN ('ingreso', 'reward') THEN t.monto ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN t.tipo = 'retiro' THEN t.monto ELSE 0 END), 0) AS saldo
        FROM cuentas c
        LEFT JOIN transacciones t ON c.id = t.id_cuenta
        GROUP BY c.id, c.nombre_cuenta, c.moneda, c.permite_stake, c.objetivo_stake_mensual
        ORDER BY c.id
        """
    )
    return cursor.fetchall()


def get_latest_prices(conn: sqlite3.Connection) -> dict[str, float]:
    """Get latest price_usd per currency from history."""
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT hp.moneda, hp.precio_usd
        FROM historial_precios hp
        INNER JOIN (
            SELECT moneda, MAX(fecha_calculo) AS max_fecha
            FROM historial_precios
            GROUP BY moneda
        ) latest
        ON hp.moneda = latest.moneda AND hp.fecha_calculo = latest.max_fecha
        """
    )
    return {row["moneda"]: float(row["precio_usd"]) for row in cursor.fetchall()}


def show_consolidated_portfolio(conn: sqlite3.Connection) -> None:
    """Print balances in native currency and USD with USD total."""
    print("\n=== Portafolio Consolidado ===")

    balances = get_account_balances(conn)
    if not balances:
        print("No hay cuentas registradas.")
        return

    prices = get_latest_prices(conn)
    if not prices:
        print("No hay historial de precios. Use la opción 5 para actualizar precios.")

    total_usd = 0.0

    for row in balances:
        moneda = row["moneda"].upper()
        saldo = float(row["saldo"])

        precio_usd = prices.get(moneda, 0.0)

        valor_usd = saldo * precio_usd

        total_usd += valor_usd

        print(
            f"[{row['id']}] {row['nombre_cuenta']} ({moneda}) | "
            f"Saldo: {saldo:.8f} {moneda} | "
            f"USD: {valor_usd:.8f}"
        )

    print("-" * 90)
    print(f"Total Portafolio USD: {total_usd:.8f}")


def show_staking_progress(conn: sqlite3.Connection, reference_date: str | None = None) -> None:
    """Display staking rewards progress for the last 30 days, valued in USD."""
    print("\n=== Progreso de Metas de Staking (Rewards últimos 30 días) ===")

    prices = get_latest_prices(conn)

    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            c.id,
            c.nombre_cuenta,
            c.moneda,
            c.objetivo_stake_mensual,
            COALESCE(SUM(CASE WHEN t.tipo IN ('ingreso', 'reward') THEN t.monto ELSE 0 END), 0) -
            COALESCE(SUM(CASE WHEN t.tipo = 'retiro' THEN t.monto ELSE 0 END), 0) AS stake_acumulado,
            COALESCE(SUM(CASE WHEN t.tipo = 'reward'
                AND t.fecha >= COALESCE(DATE(?, '-30 days'), DATE('now', '-30 days'))
                THEN t.monto ELSE 0 END), 0) AS rewards_30d_native
        FROM cuentas c
        LEFT JOIN transacciones t ON c.id = t.id_cuenta
        WHERE c.permite_stake = 1
        GROUP BY c.id, c.nombre_cuenta, c.moneda, c.objetivo_stake_mensual
        ORDER BY c.id
        """,
        (reference_date,),
    )
    rows = cursor.fetchall()

    if not rows:
        print("No hay cuentas con staking habilitado.")
        return

    for row in rows:
        objetivo = float(row["objetivo_stake_mensual"])
        stake = float(row["stake_acumulado"])
        rewards_native = float(row["rewards_30d_native"])
        moneda = str(row["moneda"]).upper()

        current_price = prices.get(moneda, 0.0)
        rewards_usd = rewards_native * current_price
        progreso = (rewards_usd * 100.0 / objetivo) if objetivo > 0 else 0.0

        if current_price > 0:
            price_str = f"@ USD {current_price:.4f} = USD {rewards_usd:.2f}"
        else:
            price_str = "(sin precio actualizado)"

        print(
            f"[{row['id']}] {row['nombre_cuenta']} ({moneda}) | "
            f"Stake actual: {stake:.8f} | "
            f"Rewards 30d: {rewards_native:.8f} {moneda} {price_str} | "
            f"Meta: USD {objetivo:.2f} | "
            f"Progreso: {progreso:.2f}%"
        )


def print_menu() -> None:
    """Display main menu options."""
    print("\n=== Sistema de Gestión de Portafolio ===")
    print("1. Ver Portafolio Consolidado")
    print("2. Registrar Movimiento")
    print("3. Crear Nueva Cuenta")
    print("4. Ver Progreso de Metas de Staking")
    print("5. Actualizar Precios desde Internet")
    print("6. Ver Ultimos Movimientos Por Cuenta")
    print("7. Editar Movimiento")
    print("8. Eliminar Movimiento")
    print("9. Buscar Cuentas")
    print("10. Ayuda Rapida")
    print("11. Salir")


def get_account_detail(conn: sqlite3.Connection, account_id: int) -> dict | None:
    """Return full account detail: fields, transactions, and calculated balances.

    Returns None if the account does not exist.
    """
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual
        FROM cuentas
        WHERE id = ?
        """,
        (account_id,),
    )
    account_row = cursor.fetchone()
    if account_row is None:
        return None

    cursor.execute(
        """
        SELECT
            id,
            fecha,
            tipo,
            monto,
            precio_usd,
            monto_usd,
            descripcion,
            fecha_ultima_modificacion
        FROM transacciones
        WHERE id_cuenta = ?
        ORDER BY fecha DESC, id DESC
        """,
        (account_id,),
    )
    tx_rows = cursor.fetchall()

    ingresos = sum(
        float(r["monto"])
        for r in tx_rows
        if str(r["tipo"]) in ("ingreso", "reward")
    )
    retiros = sum(float(r["monto"]) for r in tx_rows if str(r["tipo"]) == "retiro")
    saldo_nativo = ingresos - retiros

    # Rewards earned in the last 30 days (same metric used in staking progress view)
    cursor.execute(
        """
        SELECT COALESCE(SUM(monto), 0)
        FROM transacciones
        WHERE id_cuenta = ? AND tipo = 'reward' AND fecha >= DATE('now', '-30 days')
        """,
        (account_id,),
    )
    rewards_30d_native = float(cursor.fetchone()[0])

    prices = get_latest_prices(conn)
    symbol = str(account_row["moneda"]).upper()
    price_usd = prices.get(symbol, 0.0)

    # Fallback: last transaction price.
    if price_usd <= 0 and tx_rows:
        for r in tx_rows:
            if float(r["precio_usd"]) > 0:
                price_usd = float(r["precio_usd"])
                break

    saldo_usd = saldo_nativo * price_usd
    target = float(account_row["objetivo_stake_mensual"])
    rewards_30d_usd = rewards_30d_native * price_usd
    pct_meta = (rewards_30d_usd / target * 100.0) if target > 0 else 0.0

    transactions = [
        {
            "id": int(r["id"]),
            "date": str(r["fecha"]),
            "type": str(r["tipo"]),
            "amount": float(r["monto"]),
            "price_usd": float(r["precio_usd"]),
            "monto_usd": float(r["monto_usd"]),
            "description": str(r["descripcion"] or ""),
            "last_modified": str(r["fecha_ultima_modificacion"]) if r["fecha_ultima_modificacion"] else None,
        }
        for r in tx_rows
    ]

    return {
        "id": int(account_row["id"]),
        "name": str(account_row["nombre_cuenta"]),
        "symbol": symbol,
        "allows_stake": int(account_row["permite_stake"]) == 1,
        "stake_target": target,
        "saldo_nativo": saldo_nativo,
        "saldo_usd": saldo_usd,
        "rewards_30d_native": rewards_30d_native,
        "rewards_30d_usd": rewards_30d_usd,
        "pct_meta": pct_meta,
        "price_usd": price_usd,
        "transactions": transactions,
    }


def main() -> None:
    """Application entrypoint."""
    try:
        conn = get_connection()
        initialize_database(conn)
    except sqlite3.Error as exc:
        print(f"No se pudo inicializar la base de datos: {exc}")
        return

    print(f"Base de datos activa: {get_db_path()}")

    try:
        while True:
            print_menu()
            option = normalize_main_option(input("Seleccione una opción: "))

            if option == "1":
                show_consolidated_portfolio(conn)
            elif option == "2":
                register_transaction(conn)
            elif option == "3":
                create_account(conn)
            elif option == "4":
                show_staking_progress(conn)
            elif option == "5":
                try:
                    update_prices_from_internet(conn)
                except (error.URLError, TimeoutError, ValueError) as exc:
                    print(f"Error al actualizar precios desde internet: {exc}")
            elif option == "6":
                show_recent_movements_by_account(conn)
            elif option == "7":
                edit_movement(conn)
            elif option == "8":
                delete_movement(conn)
            elif option == "9":
                show_account_search(conn)
            elif option == "10":
                show_quick_help()
            elif option == "11":
                print("Saliendo del sistema. ¡Hasta luego!")
                break
            else:
                print("Opción inválida. Intente nuevamente.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
