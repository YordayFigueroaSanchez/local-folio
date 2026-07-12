"""Lógica de negocio pura: cuentas, movimientos, monedas y reportes.

Este módulo no hace I/O de consola ni llamadas de red; solo consultas
SQLite y cálculos. La CLI y el servidor web consumen estas funciones.
"""

import datetime as dt
import sqlite3

# Unified precision policy: all amounts use 8 decimals regardless of currency.
AMOUNT_PRECISION = 8


def now_iso() -> str:
    """Return current local datetime in ISO-like format without timezone."""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Conversions and validation
# ---------------------------------------------------------------------------

def calculate_conversions(
    *,
    amount: float | None = None,
    monto_usd: float | None = None,
    precio_usd: float,
    source_field: str
) -> dict[str, float]:
    """Calculate bidirectional conversions between native currency and USD."""
    if precio_usd <= 0:
        raise ValueError("precio_usd debe ser mayor que 0")
    if source_field not in {'amount', 'monto_usd'}:
        raise ValueError(f"source_field inválido: {source_field}")

    if source_field == 'amount':
        amount_value = amount
        monto_usd_value = round(amount_value * precio_usd, AMOUNT_PRECISION)
    else:
        monto_usd_value = monto_usd
        amount_value = round(monto_usd_value / precio_usd, AMOUNT_PRECISION)

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


# ---------------------------------------------------------------------------
# Currencies
# ---------------------------------------------------------------------------

def list_currencies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all registered currencies ordered by simbolo."""
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


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def create_account(
    conn: sqlite3.Connection,
    *,
    name: str,
    symbol: str,
    allows_stake: bool,
    stake_target: float,
) -> int:
    """Insert a new account and return its id. Raises ValueError on bad input."""
    name = name.strip()
    symbol = symbol.strip().upper()
    if not name:
        raise ValueError("Account name is required")
    if not symbol:
        raise ValueError("Account symbol is required")

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cuentas (nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
        VALUES (?, ?, ?, ?)
        """,
        (name, symbol, 1 if allows_stake else 0, float(stake_target)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def list_accounts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all accounts ordered by id."""
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


def get_account_currency(conn: sqlite3.Connection, account_id: int) -> str | None:
    """Return account currency symbol for the given account id."""
    cursor = conn.cursor()
    cursor.execute("SELECT UPPER(moneda) FROM cuentas WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] else None


def get_account_balances(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return account balances using ingresos - retiros."""
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


# ---------------------------------------------------------------------------
# Movements
# ---------------------------------------------------------------------------

def insert_movement(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    fecha: str,
    monto: float,
    tipo: str,
    descripcion: str,
    precio_usd: float,
    monto_usd: float,
) -> int:
    """Insert a movement and return its id. Raises ValueError on bad input."""
    if tipo not in {"ingreso", "retiro", "reward"}:
        raise ValueError("type must be 'ingreso', 'retiro' or 'reward'")
    if monto <= 0:
        raise ValueError("amount must be greater than 0")
    if precio_usd <= 0:
        raise ValueError("price_usd must be greater than 0")
    if monto_usd < 0:
        raise ValueError("monto_usd must be non-negative")

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO transacciones (
            id_cuenta, fecha, monto, tipo, descripcion,
            precio_usd, monto_usd, fecha_ultima_modificacion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            fecha,
            float(monto),
            tipo,
            descripcion,
            float(precio_usd),
            float(monto_usd),
            now_iso(),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_recent_account_movements(
    conn: sqlite3.Connection, account_id: int, limit: int = 10
) -> list[sqlite3.Row]:
    """Return recent movements for one account ordered by id desc."""
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


def get_movement_by_id(conn: sqlite3.Connection, movement_id: int) -> sqlite3.Row | None:
    """Return one movement row by id or None if not found."""
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
    monto_usd: float | None = None,
) -> bool:
    """Update one movement safely and return True when a row was changed.

    When monto_usd is not provided it is recomputed as monto * precio_usd;
    passing it explicitly preserves a USD amount entered by the user.
    """
    if tipo not in {"ingreso", "retiro", "reward"}:
        raise ValueError("Tipo invalido")
    if monto <= 0 or precio_usd <= 0:
        raise ValueError("Valores numericos invalidos")

    if monto_usd is None or monto_usd <= 0:
        monto_usd = round(float(monto) * float(precio_usd), 8)

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
                tipo, float(monto), float(precio_usd), float(monto_usd),
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
                tipo, float(monto), float(precio_usd), float(monto_usd),
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


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def get_latest_prices(conn: sqlite3.Connection) -> dict[str, float]:
    """Get latest price_usd per currency from history."""
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


def get_staking_progress(
    conn: sqlite3.Connection, reference_date: str | None = None
) -> list[dict]:
    """Return staking rewards progress (last 30 days, valued in USD) per account."""
    prices = get_latest_prices(conn)
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

    rows = []
    for row in cursor.fetchall():
        target = float(row["objetivo_stake_mensual"])
        current = float(row["stake_acumulado"])
        rewards_native = float(row["rewards_30d_native"])
        symbol = str(row["moneda"]).upper()

        current_price = prices.get(symbol, 0.0)
        rewards_usd = rewards_native * current_price
        progress = (rewards_usd / target * 100.0) if target > 0 else 0.0

        rows.append(
            {
                "account_id": int(row["id"]),
                "account_name": str(row["nombre_cuenta"]),
                "symbol": symbol,
                "current_stake": current,
                "rewards_30d_native": rewards_native,
                "rewards_30d_usd": rewards_usd,
                "current_price_usd": current_price,
                "target_rewards_usd": target,
                "progress_pct": progress,
            }
        )
    return rows


def get_account_detail(conn: sqlite3.Connection, account_id: int) -> dict | None:
    """Return full account detail: fields, transactions, and calculated balances.

    Returns None if the account does not exist.
    """
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
