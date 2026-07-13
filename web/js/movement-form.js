// Logica del formulario de registro de movimientos: estado multi-moneda,
// conversion y validacion de coherencia entre monto nativo / USD / precio,
// y el recalculo tri-direccional con "candado" de campo fijo.

import { apiFetch } from "./api.js";
import { formatNumber, getPrecisionForCurrency, roundTo } from "./format.js";
import { debounce, showFormModal, showCoherenceWarningModal, toast } from "./ui.js";
import { appState } from "./state.js";
import { loadDashboard } from "./views/dashboard.js";
import { showAccountDetail } from "./views/account-detail.js";
import { loadMovements } from "./views/movements.js";

const movementFormState = {
  selectedAccountId: null,
  currencySymbol: null,
  lastEditedField: null, // 'amount' | 'monto_usd' | 'price_usd'
  lockedField: 'price_usd',  // field kept fixed during recalculation
  isCalculating: false,
  pricesLoaded: false,
};

export async function fetchAndFillMarketPrices(currency) {
  const spinner = document.getElementById('prices-loading-spinner');
  spinner.classList.remove('is-hidden');

  try {
    const data = await apiFetch(`/api/prices?currency=${encodeURIComponent(currency)}`);
    const priceUsdInput = document.getElementById('movement-price-usd');
    if (data.precio_usd !== null) {
      priceUsdInput.value = formatNumber(data.precio_usd, 8);
      movementFormState.pricesLoaded = true;
    } else {
      // No prices available, clear fields
      movementFormState.pricesLoaded = false;
    }
  } catch (err) {
    console.error('Error fetching prices:', err);
    movementFormState.pricesLoaded = false;
  } finally {
    spinner.classList.add('is-hidden');
  }
}

export function calculateConversions({ amount, monto_usd, precio_usd, currency_symbol, source_field }) {
  const precision = getPrecisionForCurrency(currency_symbol);

  if (!precio_usd || precio_usd <= 0) {
    throw new Error('Precio USD inválido para cálculo');
  }

  if (source_field === 'amount') {
    // From native amount
    const calculatedUsd = roundTo(amount * precio_usd, 8);
    return {
      amount: roundTo(amount, precision),
      monto_usd: calculatedUsd,
    };
  } else if (source_field === 'monto_usd') {
    // From USD amount
    const calculatedAmount = roundTo(monto_usd / precio_usd, precision);
    return {
      amount: calculatedAmount,
      monto_usd: roundTo(monto_usd, 8),
    };
  }

  throw new Error('Invalid source_field');
}

export function validateCoherence({ amount, monto_usd, precio_usd, source_field, tolerance = 0.01 }) {
  if (source_field === 'amount') {
    const expectedUsd = amount * precio_usd;
    const diff = Math.abs(monto_usd - expectedUsd);
    if (diff > tolerance) {
      return { isValid: false, error: `Incoherencia: monto USD esperado ${expectedUsd.toFixed(8)}, recibido ${monto_usd.toFixed(8)}` };
    }
  } else if (source_field === 'monto_usd') {
    const expectedAmount = monto_usd / precio_usd;
    const diff = Math.abs(amount - expectedAmount);
    if (diff > tolerance) {
      return { isValid: false, error: `Incoherencia: monto nativo esperado ${expectedAmount.toFixed(8)}, recibido ${amount.toFixed(8)}` };
    }
  }
  return { isValid: true };
}

function recalculateAmounts() {
  if (movementFormState.isCalculating) return;
  movementFormState.isCalculating = true;

  try {
    const amountInput   = document.getElementById('movement-amount');
    const usdInput      = document.getElementById('movement-amount-usd');
    const priceUsdInput = document.getElementById('movement-price-usd');

    const amount   = parseFloat(amountInput.value)   || 0;
    const montoUsd = parseFloat(usdInput.value)      || 0;
    const price    = parseFloat(priceUsdInput.value) || 0;

    const edited = movementFormState.lastEditedField;
    const locked = movementFormState.lockedField;

    if (!edited || !locked) return;
    if (edited === locked) return;  // editing the locked field — nothing to derive

    // Tri-directional: locked stays fixed, the field NOT edited and NOT locked is derived
    if (locked === 'price_usd') {
      if (price <= 0) return;
      if (edited === 'amount')    usdInput.value      = formatNumber(amount * price, 8);
      if (edited === 'monto_usd') amountInput.value   = formatNumber(montoUsd / price, 8);
    } else if (locked === 'amount') {
      if (amount <= 0) return;
      if (edited === 'price_usd') usdInput.value      = formatNumber(amount * price, 8);
      if (edited === 'monto_usd') priceUsdInput.value = formatNumber(montoUsd / amount, 8);
    } else if (locked === 'monto_usd') {
      if (montoUsd <= 0) return;
      if (edited === 'amount')    priceUsdInput.value = formatNumber(montoUsd / amount, 8);
      if (edited === 'price_usd') amountInput.value   = formatNumber(montoUsd / price, 8);
    }
  } catch (err) {
    console.error('Error in recalculation:', err);
  } finally {
    movementFormState.isCalculating = false;
  }
}

const debouncedRecalculate = debounce(recalculateAmounts, 300);

export function handleAccountChange() {
  const accountSelect = document.getElementById('movement-account');
  const selectedOption = accountSelect.options[accountSelect.selectedIndex];

  if (!selectedOption) return;

  // Prefer explicit symbol metadata and keep text parsing as fallback.
  const optionSymbol = (selectedOption.dataset.symbol || '').trim().toUpperCase();
  const text = selectedOption.text;
  const match = text.match(/\(([A-Z]+)\)/);
  const symbol = optionSymbol || (match ? match[1] : '');

  if (symbol) {
    movementFormState.currencySymbol = symbol;
    movementFormState.selectedAccountId = Number(accountSelect.value);

    // Update labels
    document.getElementById('amount-currency-label').textContent = movementFormState.currencySymbol;
    document.getElementById('price-currency-label').textContent = movementFormState.currencySymbol;

    // Adjust step for amount input based on precision
    const precision = getPrecisionForCurrency(movementFormState.currencySymbol);
    const step = '0.00000001';
    document.getElementById('movement-amount').setAttribute('step', step);

    // Fetch and fill market prices
    fetchAndFillMarketPrices(movementFormState.currencySymbol);
  }
}

export function initMovementForm() {
  const accountSelect = document.getElementById('movement-account');
  const amountInput   = document.getElementById('movement-amount');
  const usdInput      = document.getElementById('movement-amount-usd');
  const priceUsdInput = document.getElementById('movement-price-usd');

  // Account change event
  accountSelect.addEventListener('change', handleAccountChange);

  // Field input events — track which field was last edited
  amountInput.addEventListener('input', () => {
    movementFormState.lastEditedField = 'amount';
    debouncedRecalculate();
  });
  usdInput.addEventListener('input', () => {
    movementFormState.lastEditedField = 'monto_usd';
    debouncedRecalculate();
  });
  priceUsdInput.addEventListener('input', () => {
    movementFormState.lastEditedField = 'price_usd';
    debouncedRecalculate();
  });

  // Lock button click handlers
  document.querySelectorAll('#movement-form-modal .modal-lock-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      movementFormState.lockedField = btn.dataset.lockField;
      document.querySelectorAll('#movement-form-modal .modal-lock-btn').forEach((b) => {
        const isNowLocked = b.dataset.lockField === movementFormState.lockedField;
        b.classList.toggle('is-locked', isNowLocked);
        b.innerHTML = isNowLocked ? '&#128274;' : '&#128275;';
        b.title = isNowLocked ? 'Campo fijo' : 'Fijar este campo';
      });
    });
  });
}

export function openMovementFormModal() {
  document.getElementById("movement-form-modal").classList.remove("is-hidden");
  // Pre-fill fecha with today's date as default.
  const fechaInput = document.getElementById("movement-fecha");
  if (fechaInput && !fechaInput.value) {
    fechaInput.value = new Date().toISOString().slice(0, 10);
  }
}

export function closeMovementFormModal() {
  document.getElementById("movement-form-modal").classList.add("is-hidden");
  document.getElementById("form-movement").reset();
  movementFormState.lastEditedField = null;
  movementFormState.lockedField = 'price_usd';
  movementFormState.isCalculating = false;
  movementFormState.currencySymbol = "";
  movementFormState.selectedAccountId = null;
  // Reset lock buttons to default state (price_usd locked)
  document.querySelectorAll('#movement-form-modal .modal-lock-btn').forEach((btn) => {
    const isLocked = btn.dataset.lockField === 'price_usd';
    btn.classList.toggle('is-locked', isLocked);
    btn.innerHTML = isLocked ? '&#128274;' : '&#128275;';
    btn.title = isLocked ? 'Campo fijo' : 'Fijar este campo';
  });
}

export async function submitMovementForm(event) {
  event.preventDefault();
  const form = event.target;

  // Read form values
  const account_id = Number(form.account_id.value);
  const type = form.type.value;
  const amount = Number(form.amount.value) || 0;
  const monto_usd = Number(form.monto_usd.value) || 0;
  const price_usd = Number(form.price_usd.value) || 0;
  const description = form.description.value.trim();
  const fecha = form.fecha.value.trim() || new Date().toISOString().slice(0, 10);

  // Basic validation
  if (!account_id || account_id <= 0) {
    toast(t("movements.toast.no_account"), true);
    return;
  }

  if (amount <= 0) {
    toast(t("movements.toast.amount_zero"), true);
    return;
  }

  if (price_usd <= 0) {
    toast(t("movements.toast.price_zero"), true);
    return;
  }

  // Coherence validation (normalize source_field: price_usd edits → treat as amount anchor)
  if (movementFormState.lastEditedField) {
    const normalizedSource = movementFormState.lastEditedField === 'price_usd' ? 'amount' : movementFormState.lastEditedField;
    const validation = validateCoherence({
      amount,
      monto_usd,
      precio_usd: price_usd,
      source_field: normalizedSource,
    });

    if (!validation.isValid) {
      // Show modal and wait for user decision
      const userConfirmed = await showCoherenceWarningModal(validation.error);
      if (!userConfirmed) {
        // User chose NO, cancel submission
        return;
      }
      // User chose SI, continue with submission
    }
  }

  // Prepare payload
  const payload = {
    account_id,
    type,
    amount,
    price_usd,
    monto_usd,
    description,
    fecha,
    source_field: movementFormState.lastEditedField || 'amount',
  };

  const saveConfirmation = await showFormModal({
    title: t("movements.confirm.title"),
    message: t("movements.confirm.msg", type, amount, movementFormState.currencySymbol || "NAT", price_usd),
    fields: [],
    confirmText: t("movements.confirm.save"),
  });
  if (!saveConfirmation.confirmed) {
    return;
  }

  try {
    await apiFetch("/api/movements", { method: "POST", body: JSON.stringify(payload) });
    closeMovementFormModal();
    await loadDashboard();
    if (appState.currentDetailAccountId !== null) {
      await showAccountDetail(appState.currentDetailAccountId);
    } else {
      await loadMovements();
    }
    toast(t("movements.toast.registered"));
  } catch (err) {
    toast(err.message, true);
  }
}

export function openMovementFromDetail() {
  const accountSelect = document.getElementById("movement-account");
  // Pre-select the account
  accountSelect.value = String(appState.currentDetailAccountId);
  handleAccountChange();
  openMovementFormModal();
}
