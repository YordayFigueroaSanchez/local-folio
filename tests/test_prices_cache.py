"""Tests del caché en memoria de fetch_market_prices (local_folio.prices).

Usa mocks sobre fetch_json para no depender de la red real ni de
CoinGecko en CI. Cada test limpia el caché en setUp/tearDown para no
interferir con otros tests del proceso.
"""

import unittest
from unittest import mock

from local_folio import prices


class PriceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        prices.clear_price_cache()

    def tearDown(self) -> None:
        prices.clear_price_cache()

    def test_second_call_within_ttl_uses_cache_not_network(self) -> None:
        call_count = {"n": 0}

        def fake_fetch_json(url: str) -> dict:
            call_count["n"] += 1
            return {"bitcoin": {"usd": 65000.0}}

        with mock.patch("local_folio.prices.fetch_json", side_effect=fake_fetch_json):
            first = prices.fetch_market_prices("BTC")
            second = prices.fetch_market_prices("BTC")

        self.assertEqual(first, 65000.0)
        self.assertEqual(second, 65000.0)
        self.assertEqual(call_count["n"], 1, "la segunda llamada debio usar el cache, no la red")

    def test_refetches_after_ttl_expires(self) -> None:
        call_count = {"n": 0}

        def fake_fetch_json(url: str) -> dict:
            call_count["n"] += 1
            return {"bitcoin": {"usd": 100.0 + call_count["n"]}}

        fake_clock = {"t": 0.0}

        def fake_now() -> float:
            return fake_clock["t"]

        with mock.patch("local_folio.prices.fetch_json", side_effect=fake_fetch_json), \
                mock.patch("local_folio.prices._cache_now", side_effect=fake_now):
            first = prices.fetch_market_prices("BTC")
            fake_clock["t"] += prices.PRICE_CACHE_TTL_SECONDS + 1
            second = prices.fetch_market_prices("BTC")

        self.assertEqual(call_count["n"], 2, "tras vencer el TTL debe volver a consultar la red")
        self.assertNotEqual(first, second)

    def test_failed_lookup_is_not_cached(self) -> None:
        call_count = {"n": 0}

        def failing_fetch_json(url: str) -> dict:
            call_count["n"] += 1
            raise ValueError("simulated network failure")

        with mock.patch("local_folio.prices.fetch_json", side_effect=failing_fetch_json):
            first = prices.fetch_market_prices("BTC")
            second = prices.fetch_market_prices("BTC")

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(call_count["n"], 2, "un fallo no debe quedar cacheado: cada llamada reintenta")

    def test_cache_is_scoped_per_symbol(self) -> None:
        def fake_fetch_json(url: str) -> dict:
            if "bitcoin" in url:
                return {"bitcoin": {"usd": 65000.0}}
            return {"ethereum": {"usd": 3000.0}}

        with mock.patch("local_folio.prices.fetch_json", side_effect=fake_fetch_json):
            btc = prices.fetch_market_prices("BTC")
            eth = prices.fetch_market_prices("ETH")

        self.assertEqual(btc, 65000.0)
        self.assertEqual(eth, 3000.0)

    def test_usd_never_touches_cache_or_network(self) -> None:
        with mock.patch("local_folio.prices.fetch_json") as fake_fetch_json:
            result = prices.fetch_market_prices("USD")

        self.assertEqual(result, 1.0)
        fake_fetch_json.assert_not_called()

    def test_clear_price_cache_forces_refetch(self) -> None:
        call_count = {"n": 0}

        def fake_fetch_json(url: str) -> dict:
            call_count["n"] += 1
            return {"bitcoin": {"usd": 65000.0}}

        with mock.patch("local_folio.prices.fetch_json", side_effect=fake_fetch_json):
            prices.fetch_market_prices("BTC")
            prices.clear_price_cache()
            prices.fetch_market_prices("BTC")

        self.assertEqual(call_count["n"], 2)


if __name__ == "__main__":
    unittest.main()
