"""Cliente de precios de mercado (CoinGecko) y snapshots de cotizaciones."""

import json
import logging
import os
import sqlite3
import threading
import time
from urllib import error, parse, request

from .core import now_iso

# Nombre explicito (no __name__): mismo motivo que en server.py, para
# que este logger siempre cuelgue de la jerarquia "local_folio.*" sin
# importar como se invoque el modulo que lo importa.
logger = logging.getLogger("local_folio.prices")

COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
HTTP_TIMEOUT = 12.0

# Caché en memoria para fetch_market_prices() (consultas de un solo
# simbolo, tipicamente disparadas por la UI al abrir el formulario de
# movimiento o la vista de Mercado). fetch_crypto_prices_usd()/
# update_prices_from_internet() NO usan este cache: representan un
# refresco explicito pedido por el usuario y siempre deben ir a la red.
PRICE_CACHE_TTL_SECONDS = float(os.environ.get("LOCAL_FOLIO_PRICE_CACHE_TTL", "30"))

_price_cache: dict[str, tuple[float, float]] = {}
_price_cache_lock = threading.Lock()


def _cache_now() -> float:
    return time.monotonic()


def clear_price_cache() -> None:
    """Clear the in-memory price cache. Mainly useful for tests."""
    with _price_cache_lock:
        _price_cache.clear()


def _get_cached_price(symbol: str) -> float | None:
    with _price_cache_lock:
        entry = _price_cache.get(symbol)
        if entry is None:
            return None
        price, expires_at = entry
        if _cache_now() >= expires_at:
            del _price_cache[symbol]
            return None
        return price


def _set_cached_price(symbol: str, price: float) -> None:
    with _price_cache_lock:
        _price_cache[symbol] = (price, _cache_now() + PRICE_CACHE_TTL_SECONDS)

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
            logger.warning("Símbolo sin mapeo en CoinGecko: %s", symbol)
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
                logger.warning("No se pudo obtener precio USD para %s (%s)", symbol, coin_id)

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


def update_prices_from_internet(conn: sqlite3.Connection) -> int:
    """Fetch USD prices and persist them in price history.

    Returns the number of currencies saved (0 when there are no symbols).
    """
    symbols = get_active_symbols(conn)
    if not symbols:
        return 0

    symbol_to_price = fetch_crypto_prices_usd(symbols)

    # Fiat handling for direct valuation in reports.
    if "USD" in symbols:
        symbol_to_price["USD"] = 1.0
    save_price_snapshots(conn, symbol_to_price)
    return len(symbol_to_price)


def fetch_market_prices(currency_symbol: str) -> float | None:
    """
    Fetch the USD market price for a specific currency.

    Queries CoinGecko for COIN/USD price, using an in-memory cache
    (PRICE_CACHE_TTL_SECONDS) to avoid hitting CoinGecko's rate limit
    when the same symbol is requested repeatedly in a short window.
    Only successful lookups are cached; a failure is retried on the
    next call instead of being remembered for the TTL window.

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
    # Special case: USD account (no network, no need to cache)
    symbol_upper = currency_symbol.upper()
    if symbol_upper == 'USD':
        return 1.0

    cached = _get_cached_price(symbol_upper)
    if cached is not None:
        return cached

    try:
        # Crypto: query CoinGecko
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

        _set_cached_price(symbol_upper, precio_usd)
        return precio_usd

    except (error.URLError, TimeoutError, ValueError, KeyError):
        # Any error → return None (fallback to manual entry)
        return None
