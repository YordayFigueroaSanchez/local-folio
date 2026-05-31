import json
import mimetypes
import os
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, parse

import gestor_portafolio as gp

HOST = "127.0.0.1"
PORT = 8765

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
WEB_DIR = os.path.join(PROJECT_ROOT, "web")


def _db_connection() -> sqlite3.Connection:
    conn = gp.get_connection()
    conn.row_factory = sqlite3.Row
    return conn


def _safe_int(value: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if maximum is not None and parsed > maximum:
        return maximum
    return parsed


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length_raw = handler.headers.get("Content-Length", "0").strip()
    try:
        length = int(length_raw)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc

    raw = handler.rfile.read(max(0, length)) if length > 0 else b"{}"
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON body") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _response(handler: BaseHTTPRequestHandler, payload: dict, status: int = HTTPStatus.OK) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(encoded)


def _error(handler: BaseHTTPRequestHandler, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
    _response(handler, {"ok": False, "error": message}, status=status)


def _serialize_accounts(rows: list[sqlite3.Row]) -> list[dict]:
    return [
        {
            "id": int(row["id"]),
            "name": str(row["nombre_cuenta"]),
            "symbol": str(row["moneda"]).upper(),
            "allows_stake": int(row["permite_stake"]) == 1,
            "stake_target": float(row["objetivo_stake_mensual"]),
        }
        for row in rows
    ]


def _serialize_movements(rows: list[sqlite3.Row]) -> list[dict]:
    serialized: list[dict] = []
    for row in rows:
        row_keys = set(row.keys())
        serialized.append(
            {
                "id": int(row["id"]),
                "account_id": int(row["id_cuenta"]) if "id_cuenta" in row_keys else None,
                "date": str(row["fecha"]),
                "type": str(row["tipo"]),
                "amount": float(row["monto"]),
                "price_usd": float(row["precio_usd"]),
                "monto_usd": float(row["monto_usd"]) if "monto_usd" in row_keys else 0.0,
                "description": str(row["descripcion"] or ""),
                "account_name": str(row["account_name"]) if "account_name" in row_keys else None,
                "symbol": str(row["symbol"]) if "symbol" in row_keys else None,
                "last_modified": str(row["fecha_ultima_modificacion"]) if "fecha_ultima_modificacion" in row_keys and row["fecha_ultima_modificacion"] else None,
            }
        )
    return serialized


def _consolidated_report(conn: sqlite3.Connection) -> dict:
    balances = gp.get_account_balances(conn)
    prices = gp.get_latest_prices(conn)

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id_cuenta,
            COALESCE(
                SUM(
                    CASE
                        WHEN tipo IN ('ingreso', 'reward') THEN
                            CASE
                                WHEN monto_usd > 0 THEN monto_usd
                                ELSE (monto * precio_usd)
                            END
                        ELSE 0
                    END
                ),
                0
            ) -
            COALESCE(
                SUM(
                    CASE
                        WHEN tipo = 'retiro' THEN
                            CASE
                                WHEN monto_usd > 0 THEN monto_usd
                                ELSE (monto * precio_usd)
                            END
                        ELSE 0
                    END
                ),
                0
            ) AS usd_used
        FROM transacciones
        GROUP BY id_cuenta
        """
    )
    usd_used_by_account = {
        int(row["id_cuenta"]): float(row["usd_used"])
        for row in cursor.fetchall()
    }

    cursor.execute(
        """
        SELECT hp.moneda, hp.precio_usd, hp.fecha_calculo
        FROM historial_precios hp
        INNER JOIN (
            SELECT moneda, MAX(fecha_calculo) AS max_fecha
            FROM historial_precios
            GROUP BY moneda
        ) latest
            ON hp.moneda = latest.moneda
           AND hp.fecha_calculo = latest.max_fecha
        """
    )
    snapshot_meta_by_symbol = {
        str(row["moneda"]).upper(): {
            "price_usd": float(row["precio_usd"]),
            "snapshot_at": str(row["fecha_calculo"]),
        }
        for row in cursor.fetchall()
    }

    # Fallback for environments without price snapshots yet:
    # use the latest transaction price per symbol as last known USD value.
    cursor.execute(
        """
        SELECT UPPER(c.moneda) AS symbol, t.precio_usd
        FROM transacciones t
        INNER JOIN cuentas c ON c.id = t.id_cuenta
        WHERE t.precio_usd > 0
        ORDER BY t.fecha DESC, t.id DESC
        """
    )
    fallback_price_by_symbol: dict[str, float] = {}
    for row in cursor.fetchall():
        symbol = str(row["symbol"]).upper()
        if symbol not in fallback_price_by_symbol:
            fallback_price_by_symbol[symbol] = float(row["precio_usd"])

    rows: list[dict] = []
    total_usd = 0.0

    for row in balances:
        account_id = int(row["id"])
        symbol = str(row["moneda"]).upper()
        balance = float(row["saldo"])
        price_usd, _ = prices.get(symbol, (0.0, 0.0))
        usd_source = "snapshot"
        snapshot_at = None
        if symbol in snapshot_meta_by_symbol:
            snapshot_at = snapshot_meta_by_symbol[symbol]["snapshot_at"]
            price_usd = snapshot_meta_by_symbol[symbol]["price_usd"]
        elif price_usd <= 0:
            fallback_price = fallback_price_by_symbol.get(symbol, 0.0)
            if fallback_price > 0:
                price_usd = fallback_price
                usd_source = "fallback"
            else:
                usd_source = "missing"

        usd_current = balance * float(price_usd)
        usd_used = usd_used_by_account.get(account_id, 0.0)
        total_usd += usd_current

        rows.append(
            {
                "account_id": account_id,
                "account_name": str(row["nombre_cuenta"]),
                "symbol": symbol,
                "balance": balance,
                "usd_used": usd_used,
                "usd_current": usd_current,
                "value_usd": usd_current,
                "price_usd": float(price_usd),
                "usd_source": usd_source,
                "snapshot_at": snapshot_at,
            }
        )

    return {
        "rows": rows,
        "total_usd": total_usd,
    }


def _staking_progress(conn: sqlite3.Connection) -> list[dict]:
    prices = gp.get_latest_prices(conn)
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
                AND t.fecha >= DATE('now', '-30 days')
                THEN t.monto ELSE 0 END), 0) AS rewards_30d_native
        FROM cuentas c
        LEFT JOIN transacciones t ON c.id = t.id_cuenta
        WHERE c.permite_stake = 1
        GROUP BY c.id, c.nombre_cuenta, c.moneda, c.objetivo_stake_mensual
        ORDER BY c.id
        """
    )

    rows = []
    for row in cursor.fetchall():
        target = float(row["objetivo_stake_mensual"])
        current = float(row["stake_acumulado"])
        rewards_native = float(row["rewards_30d_native"])
        symbol = str(row["moneda"]).upper()

        current_price, _ = prices.get(symbol, (0.0, 1.0))
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


def _last_price_update(conn: sqlite3.Connection) -> str | None:
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(fecha_calculo) FROM historial_precios")
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0])


def _latest_prices(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT hp.moneda, hp.precio_usd, hp.fecha_calculo
        FROM historial_precios hp
        INNER JOIN (
            SELECT moneda, MAX(fecha_calculo) AS max_fecha
            FROM historial_precios
            GROUP BY moneda
        ) latest
            ON hp.moneda = latest.moneda
           AND hp.fecha_calculo = latest.max_fecha
        ORDER BY hp.moneda
        """
    )
    latest_by_symbol = {
        str(row["moneda"]).upper(): {
            "symbol": str(row["moneda"]).upper(),
            "price_usd": float(row["precio_usd"]),
            "snapshot_at": str(row["fecha_calculo"]),
        }
        for row in cursor.fetchall()
    }

    cursor.execute("SELECT DISTINCT UPPER(moneda) AS symbol FROM cuentas ORDER BY symbol")
    account_symbols = [str(row["symbol"]).upper() for row in cursor.fetchall()]

    for symbol in account_symbols:
        if symbol in latest_by_symbol:
            continue

        cursor.execute(
            """
            SELECT t.precio_usd
            FROM transacciones t
            INNER JOIN cuentas c ON c.id = t.id_cuenta
            WHERE UPPER(c.moneda) = ? AND t.precio_usd > 0
            ORDER BY t.fecha DESC, t.id DESC
            LIMIT 1
            """,
            (symbol,),
        )
        row = cursor.fetchone()
        if row is None:
            latest_by_symbol[symbol] = {
                "symbol": symbol,
                "price_usd": 0.0,
                "snapshot_at": "sin snapshot",
            }
        else:
            latest_by_symbol[symbol] = {
                "symbol": symbol,
                "price_usd": float(row["precio_usd"]),
                "snapshot_at": "fallback",
            }

    return [latest_by_symbol[symbol] for symbol in sorted(latest_by_symbol.keys())]


def _serve_static(handler: BaseHTTPRequestHandler, route_path: str) -> bool:
    requested = route_path.split("?", 1)[0]
    relative = requested.lstrip("/")
    if not relative:
        relative = "index.html"

    full_path = os.path.normpath(os.path.join(WEB_DIR, relative))
    if not full_path.startswith(WEB_DIR):
        _error(handler, "Invalid static path", status=HTTPStatus.FORBIDDEN)
        return True

    if not os.path.isfile(full_path):
        return False

    mime_type, _ = mimetypes.guess_type(full_path)
    content_type = mime_type or "application/octet-stream"

    with open(full_path, "rb") as f:
        content = f.read()

    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", f"{content_type}; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)
    return True


class PortfolioRequestHandler(BaseHTTPRequestHandler):
    server_version = "PortfolioWebUI/1.0"

    def log_message(self, fmt: str, *args) -> None:
        # Keep server output concise for local use.
        return

    def do_GET(self) -> None:
        parsed = parse.urlparse(self.path)
        route = parsed.path

        if route == "/api/dashboard":
            self._handle_dashboard()
            return
        if route == "/api/accounts":
            self._handle_list_accounts(parsed)
            return
        if route == "/api/currencies":
            self._handle_list_currencies()
            return
        if route == "/api/movements/recent":
            self._handle_list_recent_movements(parsed)
            return
        if route == "/api/movements":
            self._handle_list_movements(parsed)
            return
        if route == "/api/reports/consolidated":
            self._handle_consolidated_report()
            return
        if route == "/api/staking/progress":
            self._handle_staking_progress()
            return
        if route == "/api/prices/latest":
            self._handle_latest_prices()
            return
        if route == "/api/prices":
            self._handle_market_prices(parsed)
            return
        if route == "/api/db/list":
            self._handle_db_list()
            return

        account_detail_prefix = "/api/accounts/"
        if route.startswith(account_detail_prefix) and route.endswith("/detail"):
            account_id_raw = route[len(account_detail_prefix):-len("/detail")]
            self._handle_account_detail(account_id_raw)
            return

        if route == "/":
            served = _serve_static(self, "/index.html")
        else:
            served = _serve_static(self, route)

        if not served:
            _error(self, "Route not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = parse.urlparse(self.path)
        route = parsed.path

        if route == "/api/accounts":
            self._handle_create_account()
            return
        if route == "/api/currencies":
            self._handle_add_currency()
            return
        if route == "/api/movements":
            self._handle_create_movement()
            return
        if route == "/api/prices/update":
            self._handle_update_prices()
            return
        if route == "/api/db/backup":
            self._handle_db_backup()
            return
        if route == "/api/db/switch":
            self._handle_db_switch()
            return

        _error(self, "Route not found", status=HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        parsed = parse.urlparse(self.path)
        route = parsed.path

        prefix = "/api/movements/"
        if route.startswith(prefix):
            movement_id_raw = route[len(prefix) :]
            self._handle_update_movement(movement_id_raw)
            return

        _error(self, "Route not found", status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = parse.urlparse(self.path)
        route = parsed.path

        currencies_prefix = "/api/currencies/"
        if route.startswith(currencies_prefix):
            simbolo_raw = route[len(currencies_prefix):]
            self._handle_delete_currency(simbolo_raw)
            return

        prefix = "/api/movements/"
        if route.startswith(prefix):
            movement_id_raw = route[len(prefix) :]
            self._handle_delete_movement(movement_id_raw)
            return

        backup_prefix = "/api/db/backup/"
        if route.startswith(backup_prefix):
            filename_raw = route[len(backup_prefix):]
            self._handle_delete_backup(filename_raw)
            return

        _error(self, "Route not found", status=HTTPStatus.NOT_FOUND)

    def _handle_dashboard(self) -> None:
        try:
            with _db_connection() as conn:
                report = _consolidated_report(conn)
                payload = {
                    "ok": True,
                    "accounts_count": len(report["rows"]),
                    "total_usd": report["total_usd"],
                    "last_price_update": _last_price_update(conn),
                }
            _response(self, payload)
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_accounts(self, parsed: parse.ParseResult) -> None:
        query_map = parse.parse_qs(parsed.query)
        raw_query = (query_map.get("query") or [""])[0].strip()

        try:
            with _db_connection() as conn:
                rows = gp.search_accounts(conn, raw_query) if raw_query else gp.list_accounts(conn)
            _response(self, {"ok": True, "items": _serialize_accounts(rows)})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_account_detail(self, account_id_raw: str) -> None:
        try:
            account_id = int(account_id_raw)
        except ValueError:
            _error(self, "account_id must be an integer")
            return
        try:
            with _db_connection() as conn:
                detail = gp.get_account_detail(conn, account_id)
            if detail is None:
                _error(self, "Account not found", status=HTTPStatus.NOT_FOUND)
                return
            _response(self, {"ok": True, **detail})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_currencies(self) -> None:
        try:
            with _db_connection() as conn:
                rows = gp.list_currencies(conn)
            _response(self, {"ok": True, "items": [{"simbolo": r["simbolo"], "nombre": r["nombre"]} for r in rows]})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_add_currency(self) -> None:
        try:
            body = _json_body(self)
            simbolo = str(body.get("simbolo", "")).strip().upper()
            nombre = str(body.get("nombre", "")).strip()
            with _db_connection() as conn:
                gp.add_currency(conn, simbolo, nombre)
            _response(self, {"ok": True})
        except ValueError as exc:
            _error(self, str(exc))
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_delete_currency(self, simbolo_raw: str) -> None:
        simbolo = simbolo_raw.strip().upper()
        if not simbolo:
            _error(self, "Simbolo requerido")
            return
        try:
            with _db_connection() as conn:
                gp.delete_currency(conn, simbolo)
            _response(self, {"ok": True})
        except ValueError as exc:
            _error(self, str(exc))
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_market_prices(self, parsed: parse.ParseResult) -> None:
        """Handle GET /api/prices?currency=<SYMBOL> in USD-only mode."""
        query_map = parse.parse_qs(parsed.query)
        currency_raw = (query_map.get("currency") or [""])[0].strip()

        if not currency_raw:
            _error(self, "currency query parameter is required")
            return

        try:
            symbol = currency_raw.upper()
            prices = gp.fetch_market_prices(symbol)

            # Fallback path: if main fetch fails, try direct CoinGecko lookup for known symbols.
            if prices is None:
                try:
                    if symbol == "USD":
                        prices = (1.0, 1.0)
                    elif symbol == "UYU":
                        prices = None
                    else:
                        coin_id = gp.SYMBOL_TO_COINGECKO_ID.get(symbol)
                        if coin_id is None and symbol == "ONT":
                            coin_id = "ontology"

                        if coin_id:
                            query_params = parse.urlencode({"ids": coin_id, "vs_currencies": "usd"})
                            url = f"{gp.COINGECKO_API_URL}?{query_params}"
                            data = gp.fetch_json(url)
                            precio_usd = float(data[coin_id]["usd"])
                            if precio_usd > 0:
                                prices = (precio_usd, 1.0)
                except Exception:
                    prices = None

            if prices is None:
                # API failed or unsupported currency → return null
                _response(self, {"ok": True, "precio_usd": None, "usd_uyu": None})
            else:
                precio_usd, _ = prices
                _response(self, {"ok": True, "precio_usd": precio_usd, "usd_uyu": 1.0})
        except Exception as exc:
            # Catch any unexpected errors
            _error(self, f"Error fetching prices: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_create_account(self) -> None:
        try:
            body = _json_body(self)
            name = str(body.get("name", "")).strip()
            symbol = str(body.get("symbol", "")).strip().upper()
            allows_stake = bool(body.get("allows_stake", False))
            target_raw = body.get("stake_target", 0)

            if not name:
                raise ValueError("Account name is required")
            if not symbol:
                raise ValueError("Account symbol is required")

            target = float(target_raw)
            if allows_stake and target <= 0:
                raise ValueError("Stake target must be greater than 0 when staking is enabled")
            if not allows_stake:
                target = 0.0

            with _db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO cuentas (nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, symbol, 1 if allows_stake else 0, target),
                )
                conn.commit()
                account_id = int(cur.lastrowid)

            _response(self, {"ok": True, "account_id": account_id}, status=HTTPStatus.CREATED)
        except ValueError as exc:
            _error(self, str(exc), status=HTTPStatus.BAD_REQUEST)
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_recent_movements(self, parsed: parse.ParseResult) -> None:
        query_map = parse.parse_qs(parsed.query)
        limit_raw = (query_map.get("limit") or ["10"])[0].strip()
        try:
            limit = _safe_int(limit_raw, default=10, minimum=1, maximum=100)
            with _db_connection() as conn:
                rows = gp.get_recent_movements_all(conn, limit=limit)
            _response(self, {"ok": True, "items": _serialize_movements(rows)})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_list_movements(self, parsed: parse.ParseResult) -> None:
        query_map = parse.parse_qs(parsed.query)
        account_id_raw = (query_map.get("account_id") or [""])[0].strip()
        limit_raw = (query_map.get("limit") or ["10"])[0].strip()

        if not account_id_raw:
            _error(self, "account_id query parameter is required")
            return

        try:
            account_id = int(account_id_raw)
            limit = _safe_int(limit_raw, default=10, minimum=1, maximum=100)
            with _db_connection() as conn:
                rows = gp.get_recent_account_movements(conn, account_id=account_id, limit=limit)
            _response(self, {"ok": True, "items": _serialize_movements(rows)})
        except ValueError:
            _error(self, "account_id must be an integer")
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_create_movement(self) -> None:
        try:
            body = _json_body(self)
            account_id = int(body.get("account_id"))
            tx_type = str(body.get("type", "")).strip().lower()
            amount = float(body.get("amount", 0))
            price_usd = float(body.get("price_usd", 0))
            monto_usd = float(body.get("monto_usd", 0))
            description = str(body.get("description", "")).strip()
            fecha_raw = str(body.get("fecha", "")).strip()
            # Accept ISO date (YYYY-MM-DD) or datetime string; fallback to now.
            fecha = fecha_raw if fecha_raw else gp.now_iso()

            # Basic validation
            if tx_type not in {"ingreso", "retiro", "reward"}:
                raise ValueError("type must be 'ingreso', 'retiro' or 'reward'")
            if amount <= 0:
                raise ValueError("amount must be greater than 0")
            if price_usd <= 0:
                raise ValueError("price_usd must be greater than 0")
            if monto_usd < 0:
                raise ValueError("monto_usd must be non-negative")

            source_field = body.get("source_field", "amount")
            if source_field not in {"amount", "monto_usd"}:
                source_field = "amount"
            
            is_valid, error_msg = gp.validate_coherence(
                amount=amount,
                monto_usd=monto_usd,
                monto_uyu=0.0,
                precio_usd=price_usd,
                usd_uyu=1.0,
                source_field=source_field
            )
            
            if not is_valid:
                print(f"WARNING: Coherence validation failed: {error_msg}")

            with _db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM cuentas WHERE id = ?", (account_id,))
                if cur.fetchone() is None:
                    raise ValueError("account_id does not exist")

                now = gp.now_iso()
                cur.execute(
                    """
                    INSERT INTO transacciones (
                        id_cuenta, fecha, monto, tipo, descripcion,
                        precio_usd, monto_usd, fecha_ultima_modificacion
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_id,
                        fecha,
                        amount,
                        tx_type,
                        description,
                        price_usd,
                        monto_usd,
                        now,
                    ),
                )
                conn.commit()
                movement_id = int(cur.lastrowid)

            _response(self, {"ok": True, "movement_id": movement_id}, status=HTTPStatus.CREATED)
        except ValueError as exc:
            _error(self, str(exc), status=HTTPStatus.BAD_REQUEST)
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_update_movement(self, movement_id_raw: str) -> None:
        try:
            movement_id = int(movement_id_raw)
            body = _json_body(self)

            tx_type = str(body.get("type", "")).strip().lower()
            amount = float(body.get("amount", 0))
            price_usd = float(body.get("price_usd", 0))
            description = str(body.get("description", "")).strip()
            fecha_raw = str(body.get("fecha", "")).strip()
            fecha = fecha_raw if fecha_raw else None

            if tx_type not in {"ingreso", "retiro", "reward"}:
                raise ValueError("type must be 'ingreso', 'retiro' or 'reward'")
            if amount <= 0 or price_usd <= 0:
                raise ValueError("amount and price_usd must be greater than 0")

            with _db_connection() as conn:
                current = gp.get_movement_by_id(conn, movement_id)
                if current is None:
                    _error(self, "Movement not found", status=HTTPStatus.NOT_FOUND)
                    return

                updated = gp.update_movement_by_id(
                    conn,
                    movement_id=movement_id,
                    tipo=tx_type,
                    monto=amount,
                    precio_usd=price_usd,
                    descripcion=description,
                    fecha=fecha,
                )

            if not updated:
                _error(self, "Movement not found", status=HTTPStatus.NOT_FOUND)
                return
            _response(self, {"ok": True, "updated": True})
        except ValueError as exc:
            _error(self, str(exc), status=HTTPStatus.BAD_REQUEST)
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_delete_movement(self, movement_id_raw: str) -> None:
        try:
            movement_id = int(movement_id_raw)
            with _db_connection() as conn:
                deleted = gp.delete_movement_by_id(conn, movement_id=movement_id)
            if not deleted:
                _error(self, "Movement not found", status=HTTPStatus.NOT_FOUND)
                return
            _response(self, {"ok": True, "deleted": True})
        except ValueError:
            _error(self, "movement id must be an integer")
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_consolidated_report(self) -> None:
        try:
            with _db_connection() as conn:
                report = _consolidated_report(conn)
            _response(self, {"ok": True, **report})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_staking_progress(self) -> None:
        try:
            with _db_connection() as conn:
                rows = _staking_progress(conn)
            _response(self, {"ok": True, "items": rows})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_update_prices(self) -> None:
        try:
            with _db_connection() as conn:
                gp.update_prices_from_internet(conn)
            _response(self, {"ok": True, "updated": True})
        except (error.URLError, TimeoutError, ValueError) as exc:
            _error(self, f"Price update failed: {exc}", status=HTTPStatus.BAD_GATEWAY)
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_latest_prices(self) -> None:
        try:
            with _db_connection() as conn:
                prices = _latest_prices(conn)
            _response(self, {"ok": True, "items": prices})
        except sqlite3.Error as exc:
            _error(self, f"Database error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    # ------------------------------------------------------------------
    # Database backup and selection
    # ------------------------------------------------------------------

    def _handle_db_list(self) -> None:
        info = gp.list_db_files()
        _response(self, {"ok": True, **info})

    def _handle_db_backup(self) -> None:
        try:
            backup_path = gp.create_db_backup()
            info = gp.list_db_files()
            _response(self, {"ok": True, "backup_name": os.path.basename(backup_path), "files": info["files"]})
        except OSError as exc:
            _error(self, f"Backup error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_delete_backup(self, filename_raw: str) -> None:
        import urllib.parse
        filename = urllib.parse.unquote(filename_raw).strip()
        # Only allow deleting files inside scripts/backups/ — never the active DB
        script_dir = os.path.dirname(os.path.abspath(__file__))
        backups_dir = os.path.join(script_dir, "backups")
        target_path = os.path.normpath(os.path.join(backups_dir, filename))
        # Prevent path traversal: resolved path must stay inside backups_dir
        if not target_path.startswith(os.path.normpath(backups_dir) + os.sep):
            _error(self, "Invalid filename", status=HTTPStatus.BAD_REQUEST)
            return
        if not os.path.isfile(target_path):
            _error(self, f"File not found: {filename}", status=HTTPStatus.NOT_FOUND)
            return
        # Refuse to delete the currently active database
        if os.path.normpath(target_path) == os.path.normpath(gp.get_db_path()):
            _error(self, "Cannot delete the active database", status=HTTPStatus.CONFLICT)
            return
        try:
            os.remove(target_path)
        except OSError as exc:
            _error(self, f"Delete error: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        info = gp.list_db_files()
        _response(self, {"ok": True, **info})

    def _handle_db_switch(self) -> None:
        try:
            body = _json_body(self)
        except ValueError as exc:
            _error(self, str(exc), status=HTTPStatus.BAD_REQUEST)
            return

        filename = body.get("filename", "").strip()
        if not filename:
            _error(self, "filename is required", status=HTTPStatus.BAD_REQUEST)
            return

        # Resolve against scripts/ or scripts/backups/
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(script_dir, filename),
            os.path.join(script_dir, "backups", filename),
        ]
        target_path = next((p for p in candidates if os.path.isfile(p)), None)
        if target_path is None:
            _error(self, f"File not found: {filename}", status=HTTPStatus.NOT_FOUND)
            return

        if not gp.validate_sqlite_file(target_path):
            _error(self, "Not a valid SQLite database", status=HTTPStatus.BAD_REQUEST)
            return

        gp.set_active_db_path(target_path)
        # Ensure the new DB has the expected schema
        with _db_connection() as conn:
            gp.initialize_database(conn)

        _response(self, {"ok": True, "active": target_path, "active_name": os.path.basename(target_path)})


def run_server() -> None:
    with _db_connection() as conn:
        gp.initialize_database(conn)

    server = ThreadingHTTPServer((HOST, PORT), PortfolioRequestHandler)
    print(f"Web UI server running at http://{HOST}:{PORT}")
    active = gp.get_db_path()
    label = "(default)" if active == gp._DEFAULT_DB_PATH else "(custom — persisted)"
    print(f"Database path: {active}  {label}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Web UI server stopped.")


if __name__ == "__main__":
    run_server()
