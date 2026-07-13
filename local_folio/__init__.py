"""local-folio: seguimiento local de portafolio (crypto y fiat).

Fachada del paquete: re-exporta la API pública de los módulos internos
(db, core, prices, cli) para consumo programático y compatibilidad con
los scripts de scripts/.
"""

from .cli import (
    main,
    normalize_main_option,
    print_menu,
    show_consolidated_portfolio,
    show_quick_help,
    show_staking_progress,
)
from .core import (
    AMOUNT_PRECISION,
    add_currency,
    calculate_conversions,
    create_account,
    delete_currency,
    delete_movement_by_id,
    get_account_balances,
    get_account_currency,
    get_account_detail,
    get_latest_prices,
    get_movement_by_id,
    get_recent_account_movements,
    get_recent_movements_all,
    get_staking_progress,
    insert_movement,
    list_accounts,
    list_currencies,
    now_iso,
    search_accounts,
    update_movement_by_id,
    validate_coherence,
)
from .db import (
    DATA_DIR,
    DB_FILENAME,
    PROJECT_ROOT,
    backups_dir,
    create_db_backup,
    ensure_usd_only_schema,
    get_connection,
    get_db_path,
    initialize_database,
    list_db_files,
    set_active_db_path,
    validate_sqlite_file,
)
from .logging_config import configure_logging
from .prices import (
    COINGECKO_API_URL,
    HTTP_TIMEOUT,
    SYMBOL_TO_COINGECKO_ID,
    fetch_crypto_prices_usd,
    fetch_json,
    fetch_market_prices,
    get_active_symbols,
    save_price_snapshots,
    update_prices_from_internet,
)

__all__ = [
    # db
    "DATA_DIR",
    "DB_FILENAME",
    "PROJECT_ROOT",
    "backups_dir",
    "create_db_backup",
    "ensure_usd_only_schema",
    "get_connection",
    "get_db_path",
    "initialize_database",
    "list_db_files",
    "set_active_db_path",
    "validate_sqlite_file",
    # logging
    "configure_logging",
    # core
    "AMOUNT_PRECISION",
    "add_currency",
    "calculate_conversions",
    "create_account",
    "delete_currency",
    "delete_movement_by_id",
    "get_account_balances",
    "get_account_currency",
    "get_account_detail",
    "get_latest_prices",
    "get_movement_by_id",
    "get_recent_account_movements",
    "get_recent_movements_all",
    "get_staking_progress",
    "insert_movement",
    "list_accounts",
    "list_currencies",
    "now_iso",
    "search_accounts",
    "update_movement_by_id",
    "validate_coherence",
    # prices
    "COINGECKO_API_URL",
    "HTTP_TIMEOUT",
    "SYMBOL_TO_COINGECKO_ID",
    "fetch_crypto_prices_usd",
    "fetch_json",
    "fetch_market_prices",
    "get_active_symbols",
    "save_price_snapshots",
    "update_prices_from_internet",
    # cli
    "main",
    "normalize_main_option",
    "print_menu",
    "show_consolidated_portfolio",
    "show_quick_help",
    "show_staking_progress",
]
