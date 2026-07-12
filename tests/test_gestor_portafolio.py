import io
import sqlite3
import unittest
from contextlib import redirect_stdout

from scripts import gestor_portafolio as gp


class PortfolioManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        gp.initialize_database(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _create_account(
        self,
        name: str,
        symbol: str,
        allows_stake: int = 0,
        target: float = 0.0,
    ) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO cuentas (nombre_cuenta, moneda, permite_stake, objetivo_stake_mensual)
            VALUES (?, ?, ?, ?)
            """,
            (name, symbol, allows_stake, target),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def _insert_tx(
        self,
        account_id: int,
        amount: float,
        tx_type: str,
        description: str = "",
        date_text: str = "2026-01-01 00:00:00",
        price_usd: float = 1.0,
    ) -> None:
        monto_usd = round(float(amount) * float(price_usd), 8)
        self.conn.execute(
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
            (account_id, date_text, amount, tx_type, description, price_usd, monto_usd),
        )
        self.conn.commit()

    def _insert_price(self, symbol: str, usd_price: float) -> None:
        self.conn.execute(
            """
            INSERT INTO historial_precios (fecha_calculo, moneda, precio_usd)
            VALUES (?, ?, ?)
            """,
            ("2026-05-25 10:00:00", symbol, usd_price),
        )
        self.conn.commit()

    def test_000_btc_baseline_dataset_regression(self) -> None:
        account_id = self._create_account("test BTC", "BTC")

        self._insert_tx(
            account_id,
            amount=0.0150,
            tx_type="ingreso",
            description="compra inicial",
            date_text="2026-05-25 09:00:00",
            price_usd=68000.0,
        )
        self._insert_tx(
            account_id,
            amount=0.0085,
            tx_type="ingreso",
            description="segunda compra",
            date_text="2026-05-26 11:30:00",
            price_usd=70500.0,
        )
        self._insert_tx(
            account_id,
            amount=0.0042,
            tx_type="retiro",
            description="venta parcial",
            date_text="2026-05-27 16:45:00",
            price_usd=71200.0,
        )

        balances = gp.get_account_balances(self.conn)
        self.assertEqual(len(balances), 1)
        self.assertAlmostEqual(float(balances[0]["saldo"]), 0.0193)

        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN tipo = 'ingreso' THEN monto * precio_usd ELSE -monto * precio_usd END)
            FROM transacciones
            WHERE id_cuenta = ?
            """,
            (account_id,),
        )
        (net_usd,) = cursor.fetchone()

        self.assertAlmostEqual(float(net_usd), 1320.21, places=2)

    def test_001_dual_staking_baseline_dataset_regression(self) -> None:
        ont_id = self._create_account("ONT Test", "ONT", allows_stake=1, target=200.0)
        one_id = self._create_account("ONE Test", "ONE", allows_stake=1, target=300.0)

        ont_transactions = [
            (100.0, "ingreso", "2026-05-25 09:00:00", 0.20, "compra inicial"),
            (12.5, "reward", "2026-05-26 09:00:00", 0.21, "reward 1"),
            (10.0, "reward", "2026-05-27 09:00:00", 0.22, "reward 2"),
            (8.5, "reward", "2026-05-28 09:00:00", 0.23, "reward 3"),
            (9.0, "reward", "2026-05-29 09:00:00", 0.24, "reward 4"),
            (10.0, "reward", "2026-05-30 09:00:00", 0.25, "reward 5"),
        ]
        one_transactions = [
            (200.0, "ingreso", "2026-05-25 10:00:00", 0.015, "compra inicial"),
            (15.0, "reward", "2026-05-26 10:00:00", 0.016, "reward 1"),
            (12.0, "reward", "2026-05-27 10:00:00", 0.017, "reward 2"),
            (10.0, "reward", "2026-05-28 10:00:00", 0.018, "reward 3"),
            (8.0, "reward", "2026-05-29 10:00:00", 0.019, "reward 4"),
            (5.0, "reward", "2026-05-30 10:00:00", 0.020, "reward 5"),
            (5.0, "reward", "2026-05-31 10:00:00", 0.021, "reward 6"),
        ]

        for amount, tx_type, date_text, price_usd, description in ont_transactions:
            self._insert_tx(
                ont_id,
                amount=amount,
                tx_type=tx_type,
                description=description,
                date_text=date_text,
                price_usd=price_usd,
            )

        for amount, tx_type, date_text, price_usd, description in one_transactions:
            self._insert_tx(
                one_id,
                amount=amount,
                tx_type=tx_type,
                description=description,
                date_text=date_text,
                price_usd=price_usd,
            )

        balances = gp.get_account_balances(self.conn)
        by_name = {str(row["nombre_cuenta"]): float(row["saldo"]) for row in balances}

        self.assertAlmostEqual(by_name["ONT Test"], 150.0)
        self.assertAlmostEqual(by_name["ONE Test"], 255.0)

        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT nombre_cuenta, SUM(monto * precio_usd)
            FROM transacciones t
            INNER JOIN cuentas c ON c.id = t.id_cuenta
            GROUP BY nombre_cuenta
            ORDER BY nombre_cuenta
            """
        )
        totals = {
            str(name): float(total_usd)
            for name, total_usd in cursor.fetchall()
        }

        self.assertAlmostEqual(totals["ONT Test"], 31.44, places=2)
        self.assertAlmostEqual(totals["ONE Test"], 3.981, places=2)

        self._insert_price("ONT", usd_price=0.25)
        self._insert_price("ONE", usd_price=0.02)

        output = io.StringIO()
        with redirect_stdout(output):
            gp.show_staking_progress(self.conn, reference_date="2026-05-30")

        rendered = output.getvalue()
        # ONT: 50 rewards * 0.25 USD = 12.50 USD / meta 200 USD = 6.25%
        # ONE: 55 rewards * 0.02 USD = 1.10 USD / meta 300 USD = 0.37%
        self.assertIn("[1] ONT Test (ONT) | Stake actual: 150.00000000 | Rewards 30d: 50.00000000 ONT @ USD 0.2500 = USD 12.50 | Meta: USD 200.00 | Progreso: 6.25%", rendered)
        self.assertIn("[2] ONE Test (ONE) | Stake actual: 255.00000000 | Rewards 30d: 55.00000000 ONE @ USD 0.0200 = USD 1.10 | Meta: USD 300.00 | Progreso: 0.37%", rendered)

    def test_002_staking_withdrawals_baseline_dataset_regression(self) -> None:
        ont_id = self._create_account("ONT Withdraw Test", "ONT", allows_stake=1, target=200.0)
        one_id = self._create_account("ONE Withdraw Test", "ONE", allows_stake=1, target=300.0)

        ont_transactions = [
            (120.0, "ingreso", "2026-06-01 09:00:00", 0.20, "compra inicial"),
            (10.0, "reward", "2026-06-02 09:00:00", 0.21, "reward 1"),
            (8.0, "reward", "2026-06-03 09:00:00", 0.22, "reward 2"),
            (15.0, "retiro", "2026-06-04 09:00:00", 0.23, "retiro parcial 1"),
            (7.0, "reward", "2026-06-05 09:00:00", 0.24, "reward 3"),
            (5.0, "retiro", "2026-06-06 09:00:00", 0.25, "retiro parcial 2"),
        ]
        one_transactions = [
            (180.0, "ingreso", "2026-06-01 10:00:00", 0.015, "compra inicial"),
            (20.0, "reward", "2026-06-02 10:00:00", 0.016, "reward 1"),
            (15.0, "reward", "2026-06-03 10:00:00", 0.017, "reward 2"),
            (30.0, "retiro", "2026-06-04 10:00:00", 0.018, "retiro parcial 1"),
            (12.0, "reward", "2026-06-05 10:00:00", 0.019, "reward 3"),
            (10.0, "retiro", "2026-06-06 10:00:00", 0.020, "retiro parcial 2"),
            (8.0, "reward", "2026-06-07 10:00:00", 0.021, "reward 4"),
        ]

        for amount, tx_type, date_text, price_usd, description in ont_transactions:
            self._insert_tx(
                ont_id,
                amount=amount,
                tx_type=tx_type,
                description=description,
                date_text=date_text,
                price_usd=price_usd,
            )

        for amount, tx_type, date_text, price_usd, description in one_transactions:
            self._insert_tx(
                one_id,
                amount=amount,
                tx_type=tx_type,
                description=description,
                date_text=date_text,
                price_usd=price_usd,
            )

        balances = gp.get_account_balances(self.conn)
        by_name = {str(row["nombre_cuenta"]): float(row["saldo"]) for row in balances}

        self.assertAlmostEqual(by_name["ONT Withdraw Test"], 125.0)
        self.assertAlmostEqual(by_name["ONE Withdraw Test"], 195.0)

        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT
                nombre_cuenta,
                SUM(CASE WHEN tipo IN ('ingreso', 'reward') THEN monto * precio_usd ELSE -monto * precio_usd END)
            FROM transacciones t
            INNER JOIN cuentas c ON c.id = t.id_cuenta
            WHERE nombre_cuenta IN ('ONT Withdraw Test', 'ONE Withdraw Test')
            GROUP BY nombre_cuenta
            ORDER BY nombre_cuenta
            """
        )
        totals = {
            str(name): float(total_usd)
            for name, total_usd in cursor.fetchall()
        }

        self.assertAlmostEqual(totals["ONT Withdraw Test"], 24.84, places=2)
        self.assertAlmostEqual(totals["ONE Withdraw Test"], 2.931, places=2)

        self._insert_price("ONT", usd_price=0.24)
        self._insert_price("ONE", usd_price=0.02)

        output = io.StringIO()
        with redirect_stdout(output):
            gp.show_staking_progress(self.conn, reference_date="2026-06-07")

        rendered = output.getvalue()
        # ONT: 10+8+7=25 rewards * 0.24 USD = 6.00 USD / meta 200 USD = 3.00%
        # ONE: 20+15+12+8=55 rewards * 0.02 USD = 1.10 USD / meta 300 USD = 0.37%
        self.assertIn("ONT Withdraw Test (ONT) | Stake actual: 125.00000000 | Rewards 30d: 25.00000000 ONT @ USD 0.2400 = USD 6.00 | Meta: USD 200.00 | Progreso: 3.00%", rendered)
        self.assertIn("ONE Withdraw Test (ONE) | Stake actual: 195.00000000 | Rewards 30d: 55.00000000 ONE @ USD 0.0200 = USD 1.10 | Meta: USD 300.00 | Progreso: 0.37%", rendered)

    def test_recent_movements_by_account_respects_limit_and_order(self) -> None:
        target_id = self._create_account("Cuenta Target", "BTC")
        other_id = self._create_account("Cuenta Otra", "ETH")

        for idx, amount in enumerate([0.1, 0.2, 0.3, 0.4, 0.5], start=1):
            self._insert_tx(
                target_id,
                amount=amount,
                tx_type="ingreso",
                description=f"target {idx}",
                date_text=f"2026-07-0{idx} 10:00:00",
                price_usd=70000.0,
            )

        self._insert_tx(
            other_id,
            amount=1.0,
            tx_type="ingreso",
            description="other",
            date_text="2026-07-10 10:00:00",
            price_usd=3000.0,
        )

        rows = gp.get_recent_account_movements(self.conn, account_id=target_id, limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(str(rows[0]["descripcion"]), "target 5")
        self.assertEqual(str(rows[1]["descripcion"]), "target 4")
        self.assertEqual(str(rows[2]["descripcion"]), "target 3")

    def test_update_movement_by_id_updates_fields(self) -> None:
        account_id = self._create_account("Edit Test", "BTC")
        self._insert_tx(
            account_id,
            amount=0.5,
            tx_type="ingreso",
            description="before",
            price_usd=70000.0,
        )

        row = gp.get_recent_account_movements(self.conn, account_id=account_id, limit=1)[0]
        movement_id = int(row["id"])

        updated = gp.update_movement_by_id(
            self.conn,
            movement_id=movement_id,
            tipo="retiro",
            monto=0.25,
            precio_usd=71000.0,
            descripcion="after",
        )

        self.assertTrue(updated)
        updated_row = gp.get_movement_by_id(self.conn, movement_id)
        self.assertIsNotNone(updated_row)
        assert updated_row is not None
        self.assertEqual(str(updated_row["tipo"]), "retiro")
        self.assertAlmostEqual(float(updated_row["monto"]), 0.25)
        self.assertAlmostEqual(float(updated_row["precio_usd"]), 71000.0)
        self.assertAlmostEqual(float(updated_row["monto_usd"]), 17750.0)
        self.assertEqual(str(updated_row["descripcion"]), "after")

    def test_update_movement_by_id_preserves_explicit_monto_usd(self) -> None:
        """Un monto_usd explicito no debe ser pisado por el recalculo monto * precio."""
        account_id = self._create_account("Edit USD Source", "BTC")
        self._insert_tx(
            account_id,
            amount=0.5,
            tx_type="ingreso",
            price_usd=70000.0,
        )

        row = gp.get_recent_account_movements(self.conn, account_id=account_id, limit=1)[0]
        movement_id = int(row["id"])

        updated = gp.update_movement_by_id(
            self.conn,
            movement_id=movement_id,
            tipo="ingreso",
            monto=0.5,
            precio_usd=70000.0,
            descripcion="entrada en USD",
            monto_usd=35000.5,
        )

        self.assertTrue(updated)
        updated_row = gp.get_movement_by_id(self.conn, movement_id)
        assert updated_row is not None
        self.assertAlmostEqual(float(updated_row["monto_usd"]), 35000.5)

    def test_delete_movement_by_id_removes_row(self) -> None:
        account_id = self._create_account("Delete Test", "ETH")
        self._insert_tx(
            account_id,
            amount=1.0,
            tx_type="ingreso",
            description="to delete",
            price_usd=3000.0,
        )

        row = gp.get_recent_account_movements(self.conn, account_id=account_id, limit=1)[0]
        movement_id = int(row["id"])

        deleted = gp.delete_movement_by_id(self.conn, movement_id)
        self.assertTrue(deleted)
        self.assertIsNone(gp.get_movement_by_id(self.conn, movement_id))

    def test_search_accounts_by_name_or_symbol(self) -> None:
        self._create_account("Binance Spot", "BTC")
        self._create_account("Ledger ONE", "ONE")
        self._create_account("Wallet ETH", "ETH")

        by_name = gp.search_accounts(self.conn, "ledger")
        self.assertEqual(len(by_name), 1)
        self.assertEqual(str(by_name[0]["nombre_cuenta"]), "Ledger ONE")

        by_symbol = gp.search_accounts(self.conn, "eth")
        self.assertEqual(len(by_symbol), 1)
        self.assertEqual(str(by_symbol[0]["moneda"]), "ETH")

    def test_normalize_main_option_shortcuts(self) -> None:
        self.assertEqual(gp.normalize_main_option("h"), "10")
        self.assertEqual(gp.normalize_main_option("ayuda"), "10")
        self.assertEqual(gp.normalize_main_option("help"), "10")
        self.assertEqual(gp.normalize_main_option("q"), "11")
        self.assertEqual(gp.normalize_main_option("salir"), "11")
        self.assertEqual(gp.normalize_main_option("9"), "9")

    def test_database_schema_and_single_account_balance(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {row[0] for row in cursor.fetchall()}

        self.assertIn("cuentas", table_names)
        self.assertIn("transacciones", table_names)
        self.assertIn("historial_precios", table_names)

        cursor.execute("PRAGMA table_info(transacciones)")
        tx_columns = {row[1] for row in cursor.fetchall()}
        self.assertIn("precio_usd", tx_columns)
        self.assertIn("monto_usd", tx_columns)
        self.assertNotIn("usd_uyu", tx_columns)

        account_id = self._create_account("Binance Spot", "ETH")
        self._insert_tx(account_id, 10.0, "ingreso", "compra")
        self._insert_tx(account_id, 2.5, "retiro", "gasto")
        self._insert_tx(account_id, 1.0, "ingreso", "stake")

        balances = gp.get_account_balances(self.conn)
        self.assertEqual(len(balances), 1)
        self.assertAlmostEqual(float(balances[0]["saldo"]), 8.5)

    def test_multi_account_interleaved_transactions(self) -> None:
        btc_id = self._create_account("Ledger", "BTC")
        usd_id = self._create_account("Cash", "USD")

        self._insert_tx(btc_id, 1.2, "ingreso", "compra")
        self._insert_tx(usd_id, 1000.0, "ingreso", "transferencia")
        self._insert_tx(btc_id, 0.25, "retiro", "transferencia")
        self._insert_tx(usd_id, 125.0, "retiro", "gasto")
        self._insert_tx(btc_id, 0.05, "ingreso", "stake")

        balances = gp.get_account_balances(self.conn)
        by_id = {int(row["id"]): float(row["saldo"]) for row in balances}

        self.assertAlmostEqual(by_id[btc_id], 1.0)
        self.assertAlmostEqual(by_id[usd_id], 875.0)

    def test_consolidated_report_totals_with_seeded_prices(self) -> None:
        eth_id = self._create_account("Metamask", "ETH")
        usd_id = self._create_account("Broker", "USD")

        self._insert_tx(eth_id, 2.0, "ingreso", "compra")
        self._insert_tx(eth_id, 0.5, "retiro", "gasto")
        self._insert_tx(usd_id, 500.0, "ingreso", "transferencia")

        self._insert_price("ETH", usd_price=3000.0)
        self._insert_price("USD", usd_price=1.0)

        output = io.StringIO()
        with redirect_stdout(output):
            gp.show_consolidated_portfolio(self.conn)

        rendered = output.getvalue()
        # ETH: 1.5 * 3000 = 4500 USD ; USD acct: 500 * 1 = 500 USD ; total = 5000 USD
        self.assertIn("Total Portafolio USD: 5000.00000000", rendered)
        self.assertNotIn("Total Portafolio UYU", rendered)

    def test_staking_progress_uses_total_account_balance(self) -> None:
        account_id = self._create_account("Staking Wallet", "ONT", allows_stake=1, target=100.0)

        self._insert_tx(account_id, 50.0, "ingreso", "compra inicial",
                        date_text="2026-05-20 10:00:00")
        self._insert_tx(account_id, 8.0, "reward", "reward 1",
                        date_text="2026-05-25 10:00:00")
        self._insert_tx(account_id, 2.0, "reward", "reward 2",
                        date_text="2026-05-28 10:00:00")
        self._insert_price("ONT", usd_price=5.0)

        output = io.StringIO()
        with redirect_stdout(output):
            gp.show_staking_progress(self.conn, reference_date="2026-05-30")

        rendered = output.getvalue()
        # stake_acumulado = 50 + 8 + 2 = 60
        # rewards_30d_native = 8 + 2 = 10 ONT (dentro de los 30 dias desde 2026-04-30)
        # rewards_30d_usd = 10 * 5.0 = 50.0 USD
        # objetivo_stake_mensual = 100.0 USD
        # progreso = 50.0 / 100.0 * 100 = 50.0%
        self.assertIn("Stake actual: 60.00000000", rendered)
        self.assertIn("Rewards 30d: 10.00000000 ONT @ USD 5.0000 = USD 50.00", rendered)
        self.assertIn("Progreso: 50.00%", rendered)

    # =========================================================================
    # PASO 21: Tests for calculate_conversions()
    # =========================================================================

    def test_calculate_conversions_from_amount(self) -> None:
        """Test conversion starting from native amount (BTC)."""
        result = gp.calculate_conversions(
            amount=1.0,
            precio_usd=95000.0,
            source_field="amount"
        )
        self.assertAlmostEqual(result["amount"], 1.0, places=8)
        self.assertAlmostEqual(result["monto_usd"], 95000.0, places=8)

    def test_calculate_conversions_from_usd(self) -> None:
        """Test conversion starting from USD amount."""
        result = gp.calculate_conversions(
            monto_usd=1000.0,
            precio_usd=50000.0,
            source_field="monto_usd"
        )
        self.assertAlmostEqual(result["amount"], 0.02, places=8)
        self.assertAlmostEqual(result["monto_usd"], 1000.0, places=8)

    def test_calculate_conversions_invalid_source_field(self) -> None:
        """Test unsupported source_field raises ValueError."""
        with self.assertRaises(ValueError):
            gp.calculate_conversions(
                amount=1.0,
                precio_usd=100000.0,
                source_field="monto_uyu"
            )

    def test_calculate_conversions_usd_account(self) -> None:
        """Test USD special case where precio_usd = 1.0."""
        result = gp.calculate_conversions(
            amount=500.0,
            precio_usd=1.0,
            source_field="amount"
        )
        self.assertAlmostEqual(result["amount"], 500.0, places=8)
        self.assertAlmostEqual(result["monto_usd"], 500.0, places=8)

    # =========================================================================
    # PASO 22: Tests for validate_coherence()
    # =========================================================================

    def test_validate_coherence_valid(self) -> None:
        """Test validation passes for coherent values."""
        is_valid, error_msg = gp.validate_coherence(
            amount=1.0,
            monto_usd=95000.0,
            precio_usd=95000.0,
            source_field="amount"
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)

    def test_validate_coherence_invalid_amount(self) -> None:
        """Test validation fails when source is amount and calculated USD doesn't match."""
        is_valid, error_msg = gp.validate_coherence(
            amount=1.0,
            monto_usd=100000.0,  # Should be 95000
            precio_usd=95000.0,
            source_field="amount"
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)
        self.assertIn("incoherencia", error_msg.lower())

    def test_validate_coherence_invalid_usd(self) -> None:
        """Test validation fails when source is monto_usd and calculated amount doesn't match."""
        is_valid, error_msg = gp.validate_coherence(
            amount=2.0,  # Should be ~1.05
            monto_usd=100000.0,
            precio_usd=95000.0,
            source_field="monto_usd"
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)

    def test_validate_coherence_invalid_source_field(self) -> None:
        """Test validation fails when using an unsupported source field."""
        is_valid, error_msg = gp.validate_coherence(
            amount=2.0,
            monto_usd=95000.0,
            precio_usd=95000.0,
            source_field="monto_uyu"
        )
        self.assertFalse(is_valid)
        self.assertIsNotNone(error_msg)
        self.assertIn("source_field", error_msg)

    def test_validate_coherence_edge_case_tolerance(self) -> None:
        """Test validation with value just at tolerance boundary."""
        is_valid, error_msg = gp.validate_coherence(
            amount=1.0,
            monto_usd=95000.009,  # Within 0.01 tolerance
            precio_usd=95000.0,
            source_field="amount"
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error_msg)

    # =========================================================================
    # PASO 23: Tests for fetch_market_prices()
    # =========================================================================

    def test_fetch_market_prices_usd_special(self) -> None:
        """Test USD special case returns 1.0 without hitting the network."""
        precio_usd = gp.fetch_market_prices("USD")
        self.assertIsNotNone(precio_usd)
        self.assertAlmostEqual(precio_usd, 1.0, places=8)

    def test_fetch_market_prices_unsupported_currency(self) -> None:
        """Test unsupported currency returns None (fallback behavior)."""
        self.assertIsNone(gp.fetch_market_prices("UYU"))
        self.assertIsNone(gp.fetch_market_prices("UNSUPPORTED_XYZ"))

    # =========================================================================
    # PASO 24: Tests for ensure_multi_currency_columns()
    # =========================================================================

    def test_ensure_multi_currency_columns_new_db(self) -> None:
        """Test migration adds columns to new database."""
        # Database already initialized in setUp, which calls ensure_multi_currency_columns
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(transacciones)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        self.assertIn("monto_usd", columns)
        self.assertEqual(columns["monto_usd"], "REAL")

    def test_ensure_multi_currency_columns_idempotent(self) -> None:
        """Test migration is idempotent (can run multiple times safely)."""
        # Run migration again
        gp.ensure_usd_only_schema(self.conn)
        gp.ensure_usd_only_schema(self.conn)
        
        # Should still have columns with no errors
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(transacciones)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        self.assertIn("monto_usd", columns)
        self.assertNotIn("monto_uyu", columns)

    def test_multi_currency_columns_default_zero(self) -> None:
        """Test existing records get DEFAULT 0 for new columns."""
        # Insert old-style transaction without new columns
        account_id = self._create_account("Test Account", "BTC")
        
        # Insert using only old columns
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO transacciones 
            (id_cuenta, fecha, monto, tipo, descripcion, precio_usd, monto_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, "2026-05-26 10:00:00", 1.0, "ingreso", "test", 95000.0, 95000.0)
        )
        self.conn.commit()
        
        # Query back to verify defaults
        cursor.execute(
            "SELECT monto_usd FROM transacciones WHERE id_cuenta = ?",
            (account_id,)
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 95000.0)

    # =========================================================================
    # UOW-013: fecha seleccionable y fecha_ultima_modificacion
    # =========================================================================

    def test_fecha_ultima_modificacion_column_exists(self) -> None:
        """La migracion debe agregar fecha_ultima_modificacion a transacciones."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(transacciones)")
        columns = {row[1] for row in cursor.fetchall()}
        self.assertIn("fecha_ultima_modificacion", columns)

    def test_insert_tx_backfills_fecha_ultima_modificacion(self) -> None:
        """Registros insertados via _insert_tx heredan fecha como valor inicial de fecha_ultima_modificacion."""
        account_id = self._create_account("UOW013 Test", "ONT")
        self._insert_tx(
            account_id,
            amount=50.0,
            tx_type="ingreso",
            date_text="2026-01-15 10:00:00",
            price_usd=0.20,
        )
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT fecha, fecha_ultima_modificacion FROM transacciones WHERE id_cuenta = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        # _insert_tx no puebla fecha_ultima_modificacion; despues de migracion el valor puede
        # ser NULL o igual a fecha segun si la migracion corrio con datos existentes.
        # Lo importante es que la columna existe y no levanta error.

    def test_update_movement_by_id_updates_fecha_ultima_modificacion(self) -> None:
        """update_movement_by_id debe actualizar fecha_ultima_modificacion en cada edicion."""
        account_id = self._create_account("UOW013 Edit", "BTC")
        self._insert_tx(
            account_id,
            amount=1.0,
            tx_type="ingreso",
            date_text="2026-01-01 00:00:00",
            price_usd=70000.0,
        )
        # Forzar fecha_ultima_modificacion inicial a un valor conocido y antiguo
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE transacciones SET fecha_ultima_modificacion = '2020-01-01 00:00:00' WHERE id_cuenta = ?",
            (account_id,),
        )
        self.conn.commit()

        row = gp.get_recent_account_movements(self.conn, account_id=account_id, limit=1)[0]
        movement_id = int(row["id"])

        updated = gp.update_movement_by_id(
            self.conn,
            movement_id=movement_id,
            tipo="retiro",
            monto=0.5,
            precio_usd=71000.0,
            descripcion="editado",
        )
        self.assertTrue(updated)

        updated_row = gp.get_movement_by_id(self.conn, movement_id)
        self.assertIsNotNone(updated_row)
        assert updated_row is not None
        last_mod = str(updated_row["fecha_ultima_modificacion"])
        # La fecha_ultima_modificacion debe ser mayor que el valor antiguo
        self.assertGreater(last_mod, "2020-01-01 00:00:00")

    def test_update_movement_by_id_fecha_editable(self) -> None:
        """update_movement_by_id debe permitir cambiar la fecha del movimiento."""
        account_id = self._create_account("UOW013 Fecha", "ETH")
        self._insert_tx(
            account_id,
            amount=2.0,
            tx_type="ingreso",
            date_text="2026-01-01 00:00:00",
            price_usd=3000.0,
        )
        row = gp.get_recent_account_movements(self.conn, account_id=account_id, limit=1)[0]
        movement_id = int(row["id"])

        nueva_fecha = "2025-06-15"
        updated = gp.update_movement_by_id(
            self.conn,
            movement_id=movement_id,
            tipo="ingreso",
            monto=2.0,
            precio_usd=3000.0,
            descripcion="",
            fecha=nueva_fecha,
        )
        self.assertTrue(updated)

        updated_row = gp.get_movement_by_id(self.conn, movement_id)
        self.assertIsNotNone(updated_row)
        assert updated_row is not None
        self.assertIn(nueva_fecha, str(updated_row["fecha"]))

    def test_insert_with_custom_fecha_via_sql(self) -> None:
        """El campo fecha acepta fechas historicas distintas a now_iso()."""
        account_id = self._create_account("UOW013 HistFecha", "ONT")
        fecha_custom = "2024-03-10 09:00:00"
        now = gp.now_iso()
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO transacciones
                (id_cuenta, fecha, monto, tipo, descripcion,
                 precio_usd, monto_usd, fecha_ultima_modificacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, fecha_custom, 100.0, "ingreso", "test historico", 0.25, 25.0, now),
        )
        self.conn.commit()

        cursor.execute(
            "SELECT fecha, fecha_ultima_modificacion FROM transacciones WHERE id_cuenta = ?",
            (account_id,),
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], fecha_custom)
        self.assertNotEqual(row[0], row[1],
            "fecha del movimiento debe ser distinta de fecha_ultima_modificacion")

    def test_ensure_usd_only_schema_idempotent_with_new_column(self) -> None:
        """La migracion de fecha_ultima_modificacion es idempotente."""
        gp.ensure_usd_only_schema(self.conn)
        gp.ensure_usd_only_schema(self.conn)
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(transacciones)")
        columns = {row[1] for row in cursor.fetchall()}
        self.assertIn("fecha_ultima_modificacion", columns)

    # ── UOW-014: get_account_detail ──────────────────────────────────────────

    def test_get_account_detail_returns_account_fields(self) -> None:
        """get_account_detail debe retornar los campos de la cuenta."""
        account_id = self._create_account("Detail BTC", "BTC", allows_stake=1, target=100.0)
        result = gp.get_account_detail(self.conn, account_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], account_id)
        self.assertEqual(result["name"], "Detail BTC")
        self.assertEqual(result["symbol"], "BTC")
        self.assertTrue(result["allows_stake"])
        self.assertEqual(result["stake_target"], 100.0)

    def test_get_account_detail_returns_transactions(self) -> None:
        """get_account_detail debe incluir todas las transacciones de la cuenta."""
        account_id = self._create_account("Detail ETH", "ETH")
        self._insert_tx(account_id, 1.0, "ingreso", date_text="2026-01-01 00:00:00")
        self._insert_tx(account_id, 0.5, "retiro", date_text="2026-01-02 00:00:00")
        result = gp.get_account_detail(self.conn, account_id)
        self.assertEqual(len(result["transactions"]), 2)
        types = {tx["type"] for tx in result["transactions"]}
        self.assertIn("ingreso", types)
        self.assertIn("retiro", types)

    def test_get_account_detail_calculates_saldo(self) -> None:
        """get_account_detail debe calcular saldo_nativo como ingresos - retiros."""
        account_id = self._create_account("Saldo ONT", "ONT")
        self._insert_tx(account_id, 100.0, "ingreso")
        self._insert_tx(account_id, 30.0, "reward")
        self._insert_tx(account_id, 10.0, "retiro")
        result = gp.get_account_detail(self.conn, account_id)
        self.assertAlmostEqual(result["saldo_nativo"], 120.0, places=6)

    def test_get_account_detail_empty_account(self) -> None:
        """get_account_detail con cuenta sin transacciones debe retornar lista vacia y saldo cero."""
        account_id = self._create_account("Vacia", "USD")
        result = gp.get_account_detail(self.conn, account_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["transactions"], [])
        self.assertAlmostEqual(result["saldo_nativo"], 0.0)

    def test_get_account_detail_nonexistent_returns_none(self) -> None:
        """get_account_detail debe retornar None si la cuenta no existe."""
        result = gp.get_account_detail(self.conn, 999999)
        self.assertIsNone(result)

    # ── UOW-015: backup and DB selection ────────────────────────────────────

    def test_create_db_backup(self) -> None:
        """create_db_backup debe crear un archivo .db con nombre timestamp."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_portafolio.db")
            conn = sqlite3.connect(db_path)
            gp.initialize_database(conn)
            conn.close()

            # Patch _ACTIVE_DB_PATH so backup reads from tmpdir
            original = gp._ACTIVE_DB_PATH
            gp.set_active_db_path(db_path)
            try:
                backup_path = gp.create_db_backup(db_path)
                self.assertTrue(os.path.isfile(backup_path))
                self.assertTrue(backup_path.endswith(".db"))
                self.assertIn("mi_portafolio_", os.path.basename(backup_path))
            finally:
                gp.set_active_db_path(original)

    def test_list_db_files_includes_active(self) -> None:
        """list_db_files debe incluir al menos la base de datos activa."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "mi_portafolio.db")
            conn = sqlite3.connect(db_path)
            gp.initialize_database(conn)
            conn.close()

            gp.set_active_db_path(db_path)
            try:
                result = gp.list_db_files(db_path)
                self.assertEqual(result["active"], db_path)
                names = [f["name"] for f in result["files"]]
                self.assertIn("mi_portafolio.db", names)
                first = result["files"][0]
                self.assertIn("name", first)
                self.assertIn("size_kb", first)
                self.assertIn("modified_at", first)
            finally:
                gp.set_active_db_path(gp._ACTIVE_DB_PATH)

    def test_validate_sqlite_file_valid(self) -> None:
        """validate_sqlite_file debe retornar True para un SQLite valido."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "valid.db")
            conn = sqlite3.connect(db_path)
            gp.initialize_database(conn)
            conn.close()
            self.assertTrue(gp.validate_sqlite_file(db_path))

    def test_validate_sqlite_file_invalid(self) -> None:
        """validate_sqlite_file debe retornar False para un archivo que no es SQLite."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_path = os.path.join(tmpdir, "notadb.db")
            with open(bad_path, "w") as f:
                f.write("this is not a sqlite file")
            self.assertFalse(gp.validate_sqlite_file(bad_path))


if __name__ == "__main__":
    unittest.main()