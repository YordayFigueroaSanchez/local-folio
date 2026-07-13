"""Interfaz de línea de comandos interactiva (menú, prompts y salida)."""

import sqlite3
from urllib import error

from . import core, db, prices
from .logging_config import configure_logging


def create_account(conn: sqlite3.Connection) -> None:
    """Create a new account with staking settings."""
    print("\n=== Crear Nueva Cuenta ===")
    nombre = input("Nombre de la cuenta: ").strip()
    moneda = input("Moneda (ej: ETH, USD, BTC): ").strip().upper()

    if not nombre or not moneda:
        print("Error: nombre y moneda son obligatorios.")
        return

    permite_stake_input = input("¿Permite staking? (s/n): ").strip().lower()
    permite_stake = permite_stake_input == "s"

    objetivo = 0.0
    if permite_stake:
        objetivo_raw = input("Meta de rewards esperados en 30 días (USD): ").strip()
        try:
            objetivo = float(objetivo_raw)
            if objetivo < 0:
                raise ValueError
        except ValueError:
            print("Error: meta inválida.")
            return

    try:
        core.create_account(
            conn,
            name=nombre,
            symbol=moneda,
            allows_stake=permite_stake,
            stake_target=objetivo,
        )
        print("Cuenta creada correctamente.")
    except sqlite3.Error as exc:
        print(f"Error de base de datos al crear cuenta: {exc}")


def show_account_search(conn: sqlite3.Connection) -> None:
    """Display account search results by name or symbol."""
    print("\n=== Buscar Cuentas ===")
    query = input("Buscar por nombre o moneda: ").strip()
    if not query:
        print("Error: criterio vacio. Sugerencia: ingrese al menos 1 caracter.")
        return

    rows = core.search_accounts(conn, query)
    if not rows:
        print("No se encontraron cuentas. Sugerencia: pruebe otro filtro.")
        return

    for row in rows:
        print(
            f"[{row['id']}] {row['nombre_cuenta']} ({row['moneda']}) | "
            f"Stake: {'SI' if int(row['permite_stake']) == 1 else 'NO'} | "
            f"Meta: {float(row['objetivo_stake_mensual']):.8f}"
        )


def choose_account(conn: sqlite3.Connection) -> int | None:
    """Prompt the user to select an account id."""
    accounts = core.list_accounts(conn)
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


def register_transaction(conn: sqlite3.Connection) -> None:
    """Create an income or withdrawal transaction for a selected account with multi-currency input."""
    print("\n=== Registrar Movimiento ===")

    # Step 1: Choose account
    account_id = choose_account(conn)
    if account_id is None:
        return

    currency = core.get_account_currency(conn, account_id)
    if not currency:
        print("No se pudo obtener la moneda de la cuenta seleccionada.")
        return

    # Step 2: Fetch market prices
    print("Obteniendo precios...")
    suggested_price_usd = prices.fetch_market_prices(currency)

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
    print("\n¿En qué moneda desea ingresar el monto?")
    print(f"  N: {currency}")
    print("  U: USD")

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
        else:
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
                result = core.calculate_conversions(
                    amount=monto_entered,
                    precio_usd=precio_usd,
                    source_field='amount'
                )
            else:
                result = core.calculate_conversions(
                    monto_usd=monto_entered,
                    precio_usd=precio_usd,
                    source_field='monto_usd'
                )

            monto = result['amount']
            monto_usd = result['monto_usd']
        except ValueError as e:
            print(f"Error en cálculo: {e}")
            return

        # Step 8: Show summary
        print("\nResumen del movimiento:")
        print(f"  Monto {currency}: {monto:.{core.AMOUNT_PRECISION}f}")
        print(f"  Monto USD: {monto_usd:.8f}")

        # Step 9: Validate coherence
        is_valid, error_msg = core.validate_coherence(
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
    try:
        core.insert_movement(
            conn,
            account_id=account_id,
            fecha=core.now_iso(),
            monto=monto,
            tipo=tipo,
            descripcion=descripcion,
            precio_usd=precio_usd,
            monto_usd=monto_usd,
        )
        print("Movimiento registrado correctamente.")
    except sqlite3.Error as exc:
        print(f"Error de base de datos al registrar movimiento: {exc}")


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

    rows = core.get_recent_account_movements(conn, account_id=account_id, limit=limit)
    if not rows:
        print("No hay movimientos para la cuenta seleccionada.")
        return

    for row in rows:
        print(
            f"[{row['id']}] {row['fecha']} | {row['tipo']} | "
            f"Monto: {float(row['monto']):.8f} | Precio USD: {float(row['precio_usd']):.8f} | "
            f"Desc: {row['descripcion'] or '-'}"
        )


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

    row = core.get_movement_by_id(conn, movement_id)
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
        updated = core.update_movement_by_id(
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

    row = core.get_movement_by_id(conn, movement_id)
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
        deleted = core.delete_movement_by_id(conn, movement_id)
        if deleted:
            print("OK: movimiento eliminado correctamente.")
        else:
            print("Error: no se pudo eliminar el movimiento.")
    except sqlite3.Error as exc:
        print(f"Error al eliminar movimiento: {exc}")


def show_consolidated_portfolio(conn: sqlite3.Connection) -> None:
    """Print balances in native currency and USD with USD total."""
    print("\n=== Portafolio Consolidado ===")

    balances = core.get_account_balances(conn)
    if not balances:
        print("No hay cuentas registradas.")
        return

    latest_prices = core.get_latest_prices(conn)
    if not latest_prices:
        print("No hay historial de precios. Use la opción 5 para actualizar precios.")

    total_usd = 0.0

    for row in balances:
        moneda = row["moneda"].upper()
        saldo = float(row["saldo"])

        precio_usd = latest_prices.get(moneda, 0.0)

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

    rows = core.get_staking_progress(conn, reference_date=reference_date)

    if not rows:
        print("No hay cuentas con staking habilitado.")
        return

    for row in rows:
        current_price = row["current_price_usd"]
        if current_price > 0:
            price_str = f"@ USD {current_price:.4f} = USD {row['rewards_30d_usd']:.2f}"
        else:
            price_str = "(sin precio actualizado)"

        print(
            f"[{row['account_id']}] {row['account_name']} ({row['symbol']}) | "
            f"Stake actual: {row['current_stake']:.8f} | "
            f"Rewards 30d: {row['rewards_30d_native']:.8f} {row['symbol']} {price_str} | "
            f"Meta: USD {row['target_rewards_usd']:.2f} | "
            f"Progreso: {row['progress_pct']:.2f}%"
        )


def update_prices(conn: sqlite3.Connection) -> None:
    """Fetch prices from the internet and report the outcome."""
    symbols = prices.get_active_symbols(conn)
    if not symbols:
        print("No hay cuentas creadas; primero cree una cuenta.")
        return

    saved = prices.update_prices_from_internet(conn)
    print(
        "Precios actualizados correctamente "
        f"({saved} moneda/s guardada/s, referencia USD-only)."
    )


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


def main() -> None:
    """Application entrypoint."""
    configure_logging()
    try:
        conn = db.get_connection()
        db.initialize_database(conn)
    except sqlite3.Error as exc:
        print(f"No se pudo inicializar la base de datos: {exc}")
        return

    print(f"Base de datos activa: {db.get_db_path()}")

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
                    update_prices(conn)
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
