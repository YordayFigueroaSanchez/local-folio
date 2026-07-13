"""Tests de integración para la API REST de local_folio.server.

Levanta un ThreadingHTTPServer real en un puerto efímero y ejercita los
endpoints via http.client. La base de datos activa se redirige a un
archivo temporal dentro de db.DATA_DIR durante toda la clase (es la
única ubicación donde /api/db/switch busca archivos), y se restaura al
finalizar para no tocar los datos reales del usuario.
"""

import gc
import http.client
import json
import os
import sqlite3
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from local_folio import db
from local_folio.server import PortfolioRequestHandler


def _remove_file_with_retry(path: str, attempts: int = 10, delay: float = 0.2) -> None:
    """Remove a file, retrying briefly.

    Each HTTP request opens its own sqlite3.Connection that is never
    explicitly closed (only committed via the `with` context manager);
    on Windows the underlying file lock can outlive the request by a
    few milliseconds until the connection object is garbage collected.
    """
    for _ in range(attempts - 1):
        try:
            os.remove(path)
            return
        except (PermissionError, OSError):
            gc.collect()
            time.sleep(delay)
    os.remove(path)


class ServerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original_db_path = db.get_db_path()

        cls.tmp_db_path = os.path.join(db.DATA_DIR, "_test_server_api_tmp.db")
        if os.path.exists(cls.tmp_db_path):
            os.remove(cls.tmp_db_path)
        conn = sqlite3.connect(cls.tmp_db_path)
        db.initialize_database(conn)
        conn.close()
        db.set_active_db_path(cls.tmp_db_path)

        backups_path = db.backups_dir()
        cls._backups_before = set(os.listdir(backups_path)) if os.path.isdir(backups_path) else set()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PortfolioRequestHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

        db.set_active_db_path(cls.original_db_path)
        if os.path.exists(cls.tmp_db_path):
            _remove_file_with_retry(cls.tmp_db_path)

        # Red de seguridad: si algun test dejo un backup huerfano por un
        # fallo a mitad de camino, se limpia sin tocar los backups reales.
        backups_path = db.backups_dir()
        if os.path.isdir(backups_path):
            after = set(os.listdir(backups_path))
            for name in after - cls._backups_before:
                try:
                    os.remove(os.path.join(backups_path, name))
                except OSError:
                    pass

    def setUp(self) -> None:
        conn = db.get_connection()
        conn.execute("DELETE FROM transacciones")
        conn.execute("DELETE FROM cuentas")
        conn.execute("DELETE FROM monedas")
        conn.execute("DELETE FROM historial_precios")
        conn.commit()
        conn.close()

    def _request(self, method: str, path: str, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        payload = json.loads(raw) if raw else None
        return resp.status, payload

    def _create_account(
        self,
        name: str = "Cuenta Test",
        symbol: str = "USD",
        allows_stake: bool = False,
        stake_target: float = 0,
    ) -> int:
        status, payload = self._request(
            "POST",
            "/api/accounts",
            {
                "name": name,
                "symbol": symbol,
                "allows_stake": allows_stake,
                "stake_target": stake_target,
            },
        )
        self.assertEqual(status, 201, payload)
        return payload["account_id"]

    # ------------------------------------------------------------------
    # Static files and routing
    # ------------------------------------------------------------------

    def test_static_index_served(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"<html", body.lower())

    def test_unknown_route_returns_404(self) -> None:
        status, payload = self._request("GET", "/api/does-not-exist")
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_static_path_traversal_rejected(self) -> None:
        status, _ = self._request("GET", "/../local_folio/db.py")
        self.assertEqual(status, 403)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    def test_create_and_list_account(self) -> None:
        self._create_account(name="Binance", symbol="BTC")
        status, payload = self._request("GET", "/api/accounts")
        self.assertEqual(status, 200)
        self.assertIn("Binance", [a["name"] for a in payload["items"]])

    def test_create_account_missing_name_returns_400(self) -> None:
        status, payload = self._request("POST", "/api/accounts", {"symbol": "USD"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_create_account_stake_without_target_returns_400(self) -> None:
        status, payload = self._request(
            "POST",
            "/api/accounts",
            {"name": "Stake", "symbol": "ONT", "allows_stake": True, "stake_target": 0},
        )
        self.assertEqual(status, 400)

    def test_search_accounts_by_query(self) -> None:
        self._create_account(name="Ledger Cold", symbol="BTC")
        self._create_account(name="Hot Wallet", symbol="ETH")
        status, payload = self._request("GET", "/api/accounts?query=ledger")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["name"], "Ledger Cold")

    def test_account_detail_not_found(self) -> None:
        status, _ = self._request("GET", "/api/accounts/999999/detail")
        self.assertEqual(status, 404)

    # ------------------------------------------------------------------
    # Currencies
    # ------------------------------------------------------------------

    def test_add_and_delete_currency(self) -> None:
        status, payload = self._request("POST", "/api/currencies", {"simbolo": "xrp", "nombre": "Ripple"})
        self.assertEqual(status, 200, payload)

        status, payload = self._request("GET", "/api/currencies")
        self.assertIn("XRP", [c["simbolo"] for c in payload["items"]])

        status, _ = self._request("DELETE", "/api/currencies/XRP")
        self.assertEqual(status, 200)

    def test_add_duplicate_currency_returns_400(self) -> None:
        self._request("POST", "/api/currencies", {"simbolo": "ADA", "nombre": "Cardano"})
        status, payload = self._request("POST", "/api/currencies", {"simbolo": "ADA", "nombre": "Cardano"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_delete_currency_in_use_returns_400(self) -> None:
        self._create_account(name="Cardano acc", symbol="ADA")
        status, payload = self._request("DELETE", "/api/currencies/ADA")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------

    def test_create_movement_and_fetch(self) -> None:
        account_id = self._create_account(symbol="BTC")
        status, payload = self._request(
            "POST",
            "/api/movements",
            {
                "account_id": account_id,
                "type": "ingreso",
                "amount": 0.5,
                "price_usd": 70000,
                "monto_usd": 35000,
                "source_field": "amount",
            },
        )
        self.assertEqual(status, 201, payload)
        movement_id = payload["movement_id"]

        status, payload = self._request("GET", f"/api/movements?account_id={account_id}")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], movement_id)

    def test_create_movement_missing_account_id_returns_400(self) -> None:
        status, payload = self._request(
            "POST", "/api/movements", {"type": "ingreso", "amount": 1, "price_usd": 1}
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_create_movement_invalid_account_returns_400(self) -> None:
        status, payload = self._request(
            "POST",
            "/api/movements",
            {"account_id": 999999, "type": "ingreso", "amount": 1, "price_usd": 1},
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_create_movement_invalid_type_returns_400(self) -> None:
        account_id = self._create_account(symbol="BTC")
        status, payload = self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "deposito", "amount": 1, "price_usd": 1},
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_update_movement_preserves_explicit_monto_usd(self) -> None:
        """Regresion de la mejora 4: el PUT no debe pisar monto_usd con monto*precio."""
        account_id = self._create_account(symbol="BTC")
        _, payload = self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "ingreso", "amount": 0.5, "price_usd": 70000},
        )
        movement_id = payload["movement_id"]

        status, payload = self._request(
            "PUT",
            f"/api/movements/{movement_id}",
            {
                "type": "ingreso",
                "amount": 0.5,
                "price_usd": 70000,
                "monto_usd": 34999.5,
                "description": "entrada en usd",
            },
        )
        self.assertEqual(status, 200, payload)

        status, payload = self._request("GET", f"/api/accounts/{account_id}/detail")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(payload["transactions"][0]["monto_usd"], 34999.5)

    def test_update_nonexistent_movement_returns_404(self) -> None:
        status, payload = self._request(
            "PUT",
            "/api/movements/999999",
            {"type": "ingreso", "amount": 1, "price_usd": 1, "description": ""},
        )
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_delete_movement(self) -> None:
        account_id = self._create_account(symbol="ETH")
        _, payload = self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "ingreso", "amount": 1, "price_usd": 3000},
        )
        movement_id = payload["movement_id"]

        status, _ = self._request("DELETE", f"/api/movements/{movement_id}")
        self.assertEqual(status, 200)

        status, payload = self._request("DELETE", f"/api/movements/{movement_id}")
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_recent_movements_endpoint(self) -> None:
        account_id = self._create_account(symbol="BTC")
        self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "ingreso", "amount": 1, "price_usd": 100},
        )
        status, payload = self._request("GET", "/api/movements/recent?limit=5")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload["items"]), 1)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def test_dashboard_and_consolidated_report(self) -> None:
        account_id = self._create_account(symbol="USD")
        self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "ingreso", "amount": 500, "price_usd": 1, "monto_usd": 500},
        )

        status, payload = self._request("GET", "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(payload["accounts_count"], 1)
        self.assertAlmostEqual(payload["total_usd"], 500.0)

        status, payload = self._request("GET", "/api/reports/consolidated")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(payload["total_usd"], 500.0)

    def test_staking_progress(self) -> None:
        # rewards_30d_usd se calcula con el ultimo snapshot de historial_precios,
        # no con el monto_usd del movimiento; se usa USD (precio fijo, sin red)
        # para poder generar ese snapshot via /api/prices/update.
        account_id = self._create_account(name="Staking", symbol="USD", allows_stake=True, stake_target=100)
        self._request(
            "POST",
            "/api/movements",
            {"account_id": account_id, "type": "reward", "amount": 50, "price_usd": 1, "monto_usd": 50},
        )
        self._request("POST", "/api/prices/update")

        status, payload = self._request("GET", "/api/staking/progress")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertAlmostEqual(payload["items"][0]["rewards_30d_usd"], 50.0)
        self.assertAlmostEqual(payload["items"][0]["progress_pct"], 50.0)

    # ------------------------------------------------------------------
    # Prices (sin red: solo el caso USD, que no llama a CoinGecko)
    # ------------------------------------------------------------------

    def test_prices_latest_empty_by_default(self) -> None:
        status, payload = self._request("GET", "/api/prices/latest")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])

    def test_prices_usd_is_always_one(self) -> None:
        status, payload = self._request("GET", "/api/prices?currency=USD")
        self.assertEqual(status, 200)
        self.assertEqual(payload["precio_usd"], 1.0)

    def test_prices_missing_currency_param_returns_400(self) -> None:
        status, payload = self._request("GET", "/api/prices")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_update_prices_usd_only_no_network(self) -> None:
        self._create_account(symbol="USD")
        status, payload = self._request("POST", "/api/prices/update")
        self.assertEqual(status, 200, payload)

        status, payload = self._request("GET", "/api/prices/latest")
        self.assertIn("USD", [p["symbol"] for p in payload["items"]])

    # ------------------------------------------------------------------
    # Database management
    # ------------------------------------------------------------------

    def test_db_list_includes_active(self) -> None:
        status, payload = self._request("GET", "/api/db/list")
        self.assertEqual(status, 200)
        self.assertEqual(os.path.normpath(payload["active"]), os.path.normpath(self.tmp_db_path))

    def test_db_backup_and_delete(self) -> None:
        status, payload = self._request("POST", "/api/db/backup")
        self.assertEqual(status, 200, payload)
        backup_name = payload["backup_name"]

        status, payload = self._request("GET", "/api/db/list")
        self.assertIn(backup_name, [f["name"] for f in payload["files"]])

        status, _ = self._request("DELETE", f"/api/db/backup/{backup_name}")
        self.assertEqual(status, 200)

    def test_db_delete_backup_nonexistent_returns_404(self) -> None:
        status, payload = self._request("DELETE", "/api/db/backup/no-existe.db")
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_db_switch_nonexistent_file_returns_404(self) -> None:
        status, payload = self._request("POST", "/api/db/switch", {"filename": "no-existe-xyz.db"})
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])

    def test_db_switch_invalid_sqlite_returns_400(self) -> None:
        bogus_path = os.path.join(db.backups_dir(), "_test_bogus_not_sqlite.db")
        with open(bogus_path, "w", encoding="utf-8") as f:
            f.write("not a sqlite file")
        try:
            status, payload = self._request(
                "POST", "/api/db/switch", {"filename": "_test_bogus_not_sqlite.db"}
            )
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])
        finally:
            os.remove(bogus_path)

    def test_db_switch_success_and_restore(self) -> None:
        secondary_path = os.path.join(db.backups_dir(), "_test_server_secondary.db")
        conn = sqlite3.connect(secondary_path)
        db.initialize_database(conn)
        conn.close()
        try:
            status, payload = self._request(
                "POST", "/api/db/switch", {"filename": "_test_server_secondary.db"}
            )
            self.assertEqual(status, 200, payload)
            self.assertEqual(os.path.normpath(payload["active"]), os.path.normpath(secondary_path))
        finally:
            # El endpoint solo busca en DATA_DIR/backups, asi que restaurar
            # el puntero al DB temporal de esta clase se hace directo.
            db.set_active_db_path(self.tmp_db_path)
            _remove_file_with_retry(secondary_path)


if __name__ == "__main__":
    unittest.main()
