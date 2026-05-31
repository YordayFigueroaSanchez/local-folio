import sqlite3

from gestor_portafolio import get_connection, initialize_database, now_iso

# ---------------------------------------------------------------------------
# Test dataset definitions
# Each entry in ACCOUNTS is a dict with:
#   name          : str
#   symbol        : str
#   allows_stake  : bool
#   stake_target  : float   (native units; 0 if allows_stake=False)
#   snapshot_price: float   (USD per unit for historial_precios)
#   expected_tx   : int     (used for post-insert validation)
#   transactions  : list of (tipo, monto, precio_usd, fecha_iso, descripcion)
# ---------------------------------------------------------------------------

ACCOUNTS = [
    {
        "name": "ONT Test",
        "symbol": "ONT",
        "allows_stake": False,
        "stake_target": 0.0,
        "snapshot_price": 0.24,
        "expected_tx": 2,
        # Expected: balance = 5000+8000 = 13000 ONT
        # USD_usado = (5000*0.15)+(8000*0.20) = 750 + 1600 = 2350.00 USD
        # USD_actual = 13000 * 0.24 = 3120.00 USD
        "transactions": [
            ("ingreso", 5000.0, 0.15, "2024-11-01 00:00:00", "Compra inicial ONT Test"),
            ("ingreso", 8000.0, 0.20, "2025-02-15 00:00:00", "Segunda compra ONT Test"),
        ],
    },
    {
        "name": "ONT Staking Principal",
        "symbol": "ONT",
        "allows_stake": True,
        "stake_target": 30000.0,
        "snapshot_price": 0.24,
        "expected_tx": 7,
        # Expected: balance=14500, progress=48.33%, USD_usado=2800, USD_actual=3480
        "transactions": [
            ("ingreso", 10000.0, 0.18, "2026-05-01 00:00:00", "Compra inicial"),
            ("reward",   1000.0, 0.19, "2026-05-02 00:00:00", "Reward enero"),
            ("reward",   1000.0, 0.21, "2026-05-03 00:00:00", "Reward febrero"),
            ("reward",   1000.0, 0.22, "2026-05-04 00:00:00", "Reward marzo"),
            ("retiro",    500.0, 0.20, "2026-05-05 00:00:00", "Retiro parcial"),
            ("reward",   1000.0, 0.23, "2026-05-06 00:00:00", "Reward abril"),
            ("reward",   1000.0, 0.25, "2026-05-07 00:00:00", "Reward mayo"),
        ],
    },
    {
        "name": "BTC Test",
        "symbol": "BTC",
        "allows_stake": False,
        "stake_target": 0.0,
        "snapshot_price": 100000.0,
        "expected_tx": 2,
        # Expected: balance=0.0005, USD_usado=36.00, USD_actual=50.00
        "transactions": [
            ("ingreso", 0.0002, 75000.0, "2025-05-01 00:00:00", "Compra BTC mayo 2025"),
            ("ingreso", 0.0003, 70000.0, "2026-05-26 00:00:00", "Compra BTC mayo 2026"),
        ],
    },
    {
        "name": "ONE Test",
        "symbol": "ONE",
        "allows_stake": True,
        "stake_target": 10000.0,
        "snapshot_price": 0.035,
        "expected_tx": 7,
        # Expected: balance = 2000+3000+500+600+700+800+900 = 8500 ONE
        # USD_usado (ingresos) = (2000*0.025)+(3000*0.030) = 50 + 90 = 140.00 USD
        # USD_actual = 8500 * 0.035 = 297.50 USD
        # progress = 8500 / 10000 * 100 = 85.00 %
        "transactions": [
            ("ingreso", 2000.0, 0.025, "2025-01-10 00:00:00", "Compra inicial ONE"),
            ("ingreso", 3000.0, 0.030, "2025-03-15 00:00:00", "Segunda compra ONE"),
            ("reward",   500.0, 0.028, "2025-04-01 00:00:00", "Reward mes 1"),
            ("reward",   600.0, 0.029, "2025-05-01 00:00:00", "Reward mes 2"),
            ("reward",   700.0, 0.030, "2025-06-01 00:00:00", "Reward mes 3"),
            ("reward",   800.0, 0.031, "2025-07-01 00:00:00", "Reward mes 4"),
            ("reward",   900.0, 0.032, "2025-08-01 00:00:00", "Reward mes 5"),
        ],
    },
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _upsert_account(conn: sqlite3.Connection, cfg: dict) -> int:
    """Insert account if missing, otherwise update its stake settings."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id FROM cuentas
        WHERE nombre_cuenta = ? AND UPPER(moneda) = ?
        LIMIT 1
        """,
        (cfg["name"], cfg["symbol"]),
    )
    row = cursor.fetchone()

    if row:
        account_id = int(row[0])
        cursor.execute(
            """
            UPDATE cuentas
            SET permite_stake = ?,
                objetivo_stake_mensual = ?
            WHERE id = ?
            """,
            (1 if cfg["allows_stake"] else 0, cfg["stake_target"], account_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO cuentas (nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
            VALUES (?, ?, ?, ?)
            """,
            (cfg["name"], cfg["symbol"], 1 if cfg["allows_stake"] else 0, cfg["stake_target"]),
        )
        account_id = int(cursor.lastrowid)

    conn.commit()
    return account_id


def _reset_transactions(conn: sqlite3.Connection, account_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM transacciones WHERE id_cuenta = ?", (account_id,))
    conn.commit()


def _insert_transactions(conn: sqlite3.Connection, account_id: int, transactions: list) -> None:
    cursor = conn.cursor()
    rows = []
    for tx_type, amount, price_usd, fecha, description in transactions:
        amount_usd = round(amount * price_usd, 8)
        rows.append((account_id, fecha, amount, tx_type, description, price_usd, amount_usd))

    cursor.executemany(
        """
        INSERT INTO transacciones (
            id_cuenta, fecha, monto, tipo, descripcion, precio_usd, monto_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def _insert_price_snapshot(conn: sqlite3.Connection, symbol: str, price_usd: float) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO historial_precios (fecha_calculo, moneda, precio_usd) VALUES (?, ?, ?)",
        (now_iso(), symbol, price_usd),
    )
    conn.commit()


def _tx_count(conn: sqlite3.Connection, account_id: int) -> int:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transacciones WHERE id_cuenta = ?", (account_id,))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def _rename_account(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    """Rename account if old_name exists and new_name does not."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM cuentas WHERE nombre_cuenta = ?", (old_name,))
    if not cursor.fetchone():
        return
    cursor.execute("SELECT id FROM cuentas WHERE nombre_cuenta = ?", (new_name,))
    if cursor.fetchone():
        return
    cursor.execute("UPDATE cuentas SET nombre_cuenta = ? WHERE nombre_cuenta = ?", (new_name, old_name))
    conn.commit()
    print(f"  Renamed account '{old_name}' -> '{new_name}'")


def setup_account(conn: sqlite3.Connection, cfg: dict) -> bool:
    """Set up a single test account. Returns True on success."""
    account_id = _upsert_account(conn, cfg)
    _reset_transactions(conn, account_id)
    _insert_transactions(conn, account_id, cfg["transactions"])
    _insert_price_snapshot(conn, cfg["symbol"], cfg["snapshot_price"])

    count = _tx_count(conn, account_id)
    expected = cfg["expected_tx"]
    if count != expected:
        print(f"ERROR [{cfg['name']}]: expected {expected} transactions, found {count}.")
        return False

    print(f"  [{cfg['name']}] account_id={account_id}, tx={count}, snapshot={cfg['symbol']}=${cfg['snapshot_price']:.2f}")
    return True


def main() -> int:
    conn = get_connection()
    try:
        initialize_database(conn)
        _rename_account(conn, "ONT Real", "ONT Test")
        print("Setting up test accounts...")
        ok = True
        for cfg in ACCOUNTS:
            ok = setup_account(conn, cfg) and ok
        if ok:
            print("All test accounts set up successfully.")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
