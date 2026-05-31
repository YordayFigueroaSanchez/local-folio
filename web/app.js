const NAV_VIEWS = ["dashboard", "accounts", "movements", "staking", "market", "config"];
const VIEWS = [...NAV_VIEWS, "account-detail"];
const TAB_LABELS = { market: "MERCADO" };

function money(value) {
  const number = Number(value || 0);
  return number.toLocaleString("en-US", { minimumFractionDigits: 8, maximumFractionDigits: 8 });
}

function usd(value) {
  const number = Number(value || 0);
  return number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(value) {
  const number = Number(value || 0);
  return number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%";
}

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `toast ${isError ? "error" : "ok"}`;
  setTimeout(() => {
    el.className = "toast hidden";
  }, 3400);
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Error de API");
  }
  return data;
}

function renderTable(tableId, headers, rows, numericCols = []) {
  const table = document.getElementById(tableId);
  const head = `<thead><tr>${headers.map((h, i) => `<th${numericCols.includes(i) ? ' class="col-num"' : ''}>${h}</th>`).join("")}</tr></thead>`;
  const bodyRows = rows.length
    ? rows
        .map((row) => `<tr>${row.map((cell, i) => `<td${numericCols.includes(i) ? ' class="col-num"' : ''}>${cell}</td>`).join("")}</tr>`)
        .join("")
    : `<tr><td colspan="${headers.length}">${t("common.no_data")}</td></tr>`;
  const body = `<tbody>${bodyRows}</tbody>`;
  table.innerHTML = `${head}${body}`;
}

function showView(name) {
  VIEWS.forEach((view) => {
    const section = document.getElementById(`view-${view}`);
    const tab = document.getElementById(`tab-${view}`);
    const active = view === name;
    section.classList.toggle("hidden", !active);
    if (tab) tab.classList.toggle("active", active);
  });
}

const VIEW_LOADERS = {
  dashboard:  () => loadDashboard(),
  accounts:   () => loadAccounts(),
  movements:  () => loadMovements(),
  staking:    () => loadStaking(),
  market:     () => loadMarket(),
  config:     () => loadDbConfig(),
};

async function switchView(name) {
  showView(name);
  const loader = VIEW_LOADERS[name];
  if (loader) {
    try { await loader(); } catch (err) { toast(err.message, true); }
  }
}

// =============================================================================
// Multi-Currency State and Helpers (Steps 15-19)
// =============================================================================

const movementFormState = {
  selectedAccountId: null,
  currencySymbol: null,
  lastEditedField: null, // 'amount' | 'monto_usd' | 'price_usd'
  lockedField: 'price_usd',  // field kept fixed during recalculation
  isCalculating: false,
  pricesLoaded: false,
};

let recentMovements = [];

function getPrecisionForCurrency(symbol) {
  return 8;
}

function roundTo(value, decimals) {
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

function formatNumber(value, decimals) {
  return Number(value).toFixed(decimals);
}

function debounce(func, wait) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

async function fetchAndFillMarketPrices(currency) {
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

function calculateConversions({ amount, monto_usd, precio_usd, currency_symbol, source_field }) {
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

function validateCoherence({ amount, monto_usd, precio_usd, source_field, tolerance = 0.01 }) {
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

function showCoherenceWarningModal(errorMessage) {
  return new Promise((resolve) => {
    const existingModal = document.getElementById('coherence-warning-modal');
    if (existingModal) {
      existingModal.remove();
    }

    const modal = document.createElement('div');
    modal.id = 'coherence-warning-modal';
    modal.className = 'modal-overlay';

    const content = document.createElement('div');
    content.className = 'modal-card modal-card-warning';

    const title = document.createElement('h3');
    title.className = 'modal-title modal-title-warning';
    title.textContent = t("coherence.title");

    const errorParagraph = document.createElement("p");
    errorParagraph.className = "modal-message";
    errorParagraph.textContent = errorMessage;

    const hintParagraph = document.createElement("p");
    hintParagraph.className = "modal-hint";
    hintParagraph.textContent = t("coherence.hint");

    const actions = document.createElement('div');
    actions.className = 'modal-actions';

    const noButton = document.createElement('button');
    noButton.id = 'modal-no';
    noButton.type = 'button';
    noButton.className = 'modal-btn modal-btn-secondary';
    noButton.textContent = 'NO';

    const yesButton = document.createElement('button');
    yesButton.id = 'modal-yes';
    yesButton.type = 'button';
    yesButton.className = 'modal-btn modal-btn-primary';
    yesButton.textContent = 'SI';

    actions.appendChild(noButton);
    actions.appendChild(yesButton);
    content.appendChild(title);
    content.appendChild(errorParagraph);
    content.appendChild(hintParagraph);
    content.appendChild(actions);

    modal.appendChild(content);
    document.body.appendChild(modal);

    document.getElementById('modal-yes').onclick = () => {
      modal.remove();
      resolve(true);
    };

    document.getElementById('modal-no').onclick = () => {
      modal.remove();
      resolve(false);
    };
  });
}

function showFormModal({ title, message = "", fields, confirmText = "Confirmar", cancelText = "Cancelar", danger = false, onFieldChange = null, defaultLock = null }) {
  return new Promise((resolve) => {
    const existingModal = document.getElementById("generic-form-modal");
    if (existingModal) {
      existingModal.remove();
    }

    const modal = document.createElement("div");
    modal.id = "generic-form-modal";
    modal.className = "modal-overlay";

    const content = document.createElement("div");
    content.className = "modal-card";

    const escapeHtml = (value) => String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const escapeAttr = (value) => String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    const lockableFieldNames = fields.filter((f) => f.lockable).map((f) => f.name);
    let lockedField = defaultLock || lockableFieldNames[0] || null;

    const controlsHtml = fields
      .map((field) => {
        if (field.type === "select") {
          const optionsHtml = (field.options || [])
            .map((opt) => `<option value="${escapeAttr(opt.value)}"${String(opt.value) === String(field.value) ? " selected" : ""}>${escapeHtml(opt.label)}</option>`)
            .join("");
          return `
            <label class="modal-field">
              <span>${escapeHtml(field.label)}</span>
              <select class="modal-input" id="modal-field-${field.name}">
                ${optionsHtml}
              </select>
            </label>
          `;
        }

        if (field.lockable) {
          const isLocked = lockedField === field.name;
          return `
            <label class="modal-field">
              <span>${escapeHtml(field.label)}</span>
              <div class="modal-input-lockwrap">
                <input
                  class="modal-input"
                  id="modal-field-${field.name}"
                  type="${field.type || "text"}"
                  value="${escapeAttr(field.value)}"
                  placeholder="${escapeAttr(field.placeholder)}"
                  step="${field.step || ""}"
                  min="${field.min ?? ""}"
                />
                <button type="button" class="modal-lock-btn${isLocked ? " is-locked" : ""}" data-lock-field="${escapeAttr(field.name)}" title="${isLocked ? "Campo fijo" : "Fijar este campo"}">${isLocked ? "&#128274;" : "&#128275;"}</button>
              </div>
            </label>
          `;
        }

        return `
          <label class="modal-field">
            <span>${escapeHtml(field.label)}</span>
            <input
              class="modal-input"
              id="modal-field-${field.name}"
              type="${field.type || "text"}"
              value="${escapeAttr(field.value)}"
              placeholder="${escapeAttr(field.placeholder)}"
              step="${field.step || ""}"
              min="${field.min ?? ""}"
            />
          </label>
        `;
      })
      .join("");

    content.innerHTML = `
      <h3 class="modal-title">${escapeHtml(title)}</h3>
      ${message ? `<p class="modal-message">${escapeHtml(message)}</p>` : ""}
      <div class="modal-fields">${controlsHtml}</div>
      <div class="modal-actions">
        <button id="modal-cancel" class="modal-btn modal-btn-secondary" type="button">
          ${cancelText}
        </button>
        <button id="modal-confirm" class="modal-btn ${danger ? "modal-btn-danger" : "modal-btn-primary"}" type="button">
          ${confirmText}
        </button>
      </div>
    `;

    modal.appendChild(content);
    document.body.appendChild(modal);

    // Reactive field change support
    if (onFieldChange) {
      const setValue = (name, val) => {
        const el = document.getElementById(`modal-field-${name}`);
        if (el) el.value = val;
      };
      const getValues = () => {
        const vals = {};
        fields.forEach((f) => {
          const el = document.getElementById(`modal-field-${f.name}`);
          vals[f.name] = el ? el.value : "";
        });
        return vals;
      };
      fields.forEach((field) => {
        const el = document.getElementById(`modal-field-${field.name}`);
        if (el) {
          el.addEventListener("input", () => {
            onFieldChange(field.name, getValues(), setValue, lockedField);
          });
        }
      });
    }

    // Lock button click handlers
    content.querySelectorAll(".modal-lock-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        lockedField = btn.dataset.lockField;
        content.querySelectorAll(".modal-lock-btn").forEach((b) => {
          const isNowLocked = b.dataset.lockField === lockedField;
          b.classList.toggle("is-locked", isNowLocked);
          b.innerHTML = isNowLocked ? "&#128274;" : "&#128275;";
          b.title = isNowLocked ? "Campo fijo" : "Fijar este campo";
        });
      });
    });

    const cleanup = () => modal.remove();

    document.getElementById("modal-cancel").onclick = () => {
      cleanup();
      resolve({ confirmed: false, values: {} });
    };

    document.getElementById("modal-confirm").onclick = () => {
      const values = {};
      fields.forEach((field) => {
        const input = document.getElementById(`modal-field-${field.name}`);
        values[field.name] = input ? input.value : "";
      });
      cleanup();
      resolve({ confirmed: true, values });
    };
  });
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

function handleAccountChange() {
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

function initMovementForm() {
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

// =============================================================================

function buildTabs() {
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = NAV_VIEWS.map((view) => `<button id="tab-${view}" data-view="${view}">${t("tab." + view)}</button>`).join("");
  tabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  showView("dashboard");
}

async function loadDashboard() {
  const data = await apiFetch("/api/dashboard");
  document.getElementById("dash-total-usd").textContent = money(data.total_usd);
  document.getElementById("dash-accounts").textContent = String(data.accounts_count);
  document.getElementById("dash-last-update").textContent = data.last_price_update || t("dashboard.no_snapshot");
}

async function loadCurrenciesIntoSelect() {
  const data = await apiFetch("/api/currencies");
  const select = document.getElementById("select-symbol");
  select.innerHTML =
    `<option value="">${t("accounts.modal.select")}</option>` +
    data.items.map((c) => `<option value="${c.simbolo}">${c.simbolo}</option>`).join("");
}

async function loadMarket() {
  const currData = await apiFetch("/api/currencies");
  const currencyMap = {};
  (currData.items || []).forEach((c) => {
    currencyMap[String(c.simbolo || "").toUpperCase()] = c.nombre || c.simbolo;
  });

  const data = await apiFetch("/api/prices/latest");
  let items = data.items || [];
  const symbolToCoinGeckoId = {
    ONE: "harmony",
    ONT: "ontology",
    BTC: "bitcoin",
    ETH: "ethereum",
  };

  const symbolsInResponse = new Set(items.map((it) => String(it.symbol || "").toUpperCase()));
  const accountsData = await apiFetch("/api/accounts");
  const accounts = accountsData.items || [];

  for (const acc of accounts) {
    const symbol = String(acc.symbol || "").toUpperCase();
    if (!symbol || symbolsInResponse.has(symbol)) {
      continue;
    }
    const coinId = symbolToCoinGeckoId[symbol];
    if (coinId) {
      try {
        const directResponse = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(coinId)}&vs_currencies=usd`);
        if (directResponse.ok) {
          const directData = await directResponse.json();
          const directPrice = Number(directData?.[coinId]?.usd);
          if (Number.isFinite(directPrice) && directPrice > 0) {
            items.push({ symbol, price_usd: directPrice, snapshot_at: "live-direct" });
            symbolsInResponse.add(symbol);
            continue;
          }
        }
      } catch (_err) {
        // Continue with server/API fallbacks below.
      }
    }
    let livePrice = null;
    try {
      const liveData = await apiFetch(`/api/prices?currency=${encodeURIComponent(symbol)}`);
      const liveValue = Number(liveData.precio_usd);
      if (Number.isFinite(liveValue) && liveValue > 0) {
        livePrice = liveValue;
      }
    } catch (_err) {
      livePrice = null;
    }
    if (livePrice !== null) {
      items.push({ symbol, price_usd: livePrice, snapshot_at: "live" });
      symbolsInResponse.add(symbol);
      continue;
    }
    const movementsData = await apiFetch(`/api/movements?account_id=${encodeURIComponent(acc.id)}&limit=100`);
    const movements = movementsData.items || [];
    const latestWithPrice = movements.find((mv) => Number(mv.price_usd || 0) > 0);
    items.push({
      symbol,
      price_usd: latestWithPrice ? Number(latestWithPrice.price_usd) : 0,
      snapshot_at: latestWithPrice ? "fallback" : "sin snapshot",
    });
    symbolsInResponse.add(symbol);
  }

  // Include currencies with no price history yet
  Object.keys(currencyMap).forEach((symbol) => {
    if (!symbolsInResponse.has(symbol)) {
      items.push({ symbol, price_usd: 0, snapshot_at: "sin precio" });
    }
  });

  items = items.sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));

  const table = document.getElementById("table-market");
  const thead = `<thead><tr><th>${t("market.table.symbol")}</th><th>${t("market.table.name")}</th><th class="col-num">${t("market.table.price_usd")}</th><th>${t("market.table.snapshot")}</th><th></th></tr></thead>`;
  const tbody = items.length
    ? items.map((it) => {
        const nombre = currencyMap[String(it.symbol).toUpperCase()] || "-";
        const escapedSymbol = String(it.symbol).replace(/"/g, "&quot;");
        return `<tr><td>${it.symbol}</td><td>${nombre}</td><td class="col-num">${money(it.price_usd)}</td><td>${it.snapshot_at}</td><td><button class="btn-delete-currency" data-simbolo="${escapedSymbol}" type="button">${t("market.btn.delete")}</button></td></tr>`;
      }).join("")
    : `<tr><td colspan="5">${t("common.no_data")}</td></tr>`;
  table.innerHTML = thead + `<tbody>${tbody}</tbody>`;
  table.querySelectorAll(".btn-delete-currency").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await deleteCurrency(btn.dataset.simbolo);
      } catch (err) {
        toast(err.message, true);
      }
    });
  });
}

function openCurrencyFormModal() {
  document.getElementById("currency-form-modal").classList.remove("is-hidden");
}

function closeCurrencyFormModal() {
  document.getElementById("currency-form-modal").classList.add("is-hidden");
  document.getElementById("form-currency").reset();
}

async function submitCurrencyForm(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    simbolo: form.simbolo.value.trim().toUpperCase(),
    nombre: form.nombre.value.trim(),
  };
  await apiFetch("/api/currencies", { method: "POST", body: JSON.stringify(payload) });
  closeCurrencyFormModal();
  await loadMarket();
  await loadCurrenciesIntoSelect();
  toast(t("market.toast.added"));
}

async function deleteCurrency(simbolo) {
  await apiFetch(`/api/currencies/${encodeURIComponent(simbolo)}`, { method: "DELETE" });
  await loadMarket();
  await loadCurrenciesIntoSelect();
  toast(t("market.toast.deleted", simbolo));
}

async function loadAccounts(query = "") {
  const endpoint = query ? `/api/accounts?query=${encodeURIComponent(query)}` : "/api/accounts";

  const [accountsData, reportData] = await Promise.all([
    apiFetch(endpoint),
    apiFetch("/api/reports/consolidated").catch(() => ({ ok: true, rows: [], total_usd: 0 })),
  ]);

  const accounts = accountsData.items || [];
  let reportRows = reportData.rows || [];
  let totalUsd = Number(reportData.total_usd || 0);

  // Compatibility fallback: derive financial data from movements if backend omits it
  const needsDerivedUsd = reportRows.some((it) => it.usd_used === undefined || it.usd_current === undefined);
  if (needsDerivedUsd) {
    const derivedRows = await Promise.all(
      accounts.map(async (acc) => {
        const movementsData = await apiFetch(`/api/movements?account_id=${encodeURIComponent(acc.id)}&limit=100`);
        const movements = movementsData.items || [];
        let balance = 0, usdUsed = 0, latestPriceUsd = 0;
        movements.forEach((mv, index) => {
          const sign = mv.type === "retiro" ? -1 : 1;
          const amount = Number(mv.amount || 0);
          const rawAmountUsd = Number(mv.monto_usd || 0);
          const priceUsd = Number(mv.price_usd || 0);
          const amountUsd = rawAmountUsd > 0 ? rawAmountUsd : (amount * priceUsd);
          balance += sign * amount;
          usdUsed += sign * amountUsd;
          if (index === 0 && priceUsd > 0) latestPriceUsd = priceUsd;
        });
        return {
          account_id: acc.id,
          balance,
          usd_used: usdUsed,
          usd_current: balance * latestPriceUsd,
          usd_source: latestPriceUsd > 0 ? "fallback" : "missing",
        };
      })
    );
    reportRows = derivedRows;
    totalUsd = derivedRows.reduce((sum, it) => sum + Number(it.usd_current || 0), 0);
  }

  const reportById = {};
  reportRows.forEach((r) => { reportById[r.account_id] = r; });

  document.getElementById("report-total-usd").textContent = usd(totalUsd);

  const sourceLabel = (source) => {
    if (source === "snapshot") return "snapshot";
    if (source === "fallback") return "fallback";
    return t("reports.source.no_price");
  };

  renderTable(
    "table-accounts",
    [
      t("accounts.table.name"), t("accounts.table.currency"), t("common.stake"),
      t("accounts.table.target"), t("reports.table.balance"),
      t("reports.table.usd_used"), t("reports.table.usd_current"), t("reports.table.retorno"),
    ],
    accounts.map((it) => {
      const rep = reportById[it.id] || {};
      const retornoCell = (() => {
        if (rep.usd_used === undefined || rep.usd_current === undefined) return "-";
        const used = Number(rep.usd_used || 0);
        const current = Number(rep.usd_current || 0);
        if (used === 0) return "-";
        const ratio = (current / used) * 100;
        const cls = ratio >= 100 ? "retorno-gain" : "retorno-loss";
        return `<span class="${cls}">${pct(ratio)}</span>`;
      })();
      return [
        `<button class="btn-account-link" data-account-id="${it.id}">${it.name}</button>`,
        it.symbol,
        it.allows_stake ? "SI" : "NO",
        usd(it.stake_target),
        rep.balance !== undefined ? money(rep.balance) : "-",
        rep.usd_used !== undefined ? usd(rep.usd_used) : "-",
        rep.usd_current !== undefined ? usd(rep.usd_current) : "-",
        retornoCell,
      ];
    }),
    [3, 4, 5, 6, 7]
  );

  const accountOptions = accounts
    .map((it) => `<option value="${it.id}" data-symbol="${String(it.symbol || '').toUpperCase()}">${it.id} - ${it.name} (${it.symbol})</option>`)
    .join("");
  document.getElementById("movement-account").innerHTML = accountOptions;

  if (accounts.length > 0) {
    handleAccountChange();
  }
}

async function openAccountFormModal() {
  await loadCurrenciesIntoSelect();
  document.getElementById("account-form-modal").classList.remove("is-hidden");
}

function closeAccountFormModal() {
  document.getElementById("account-form-modal").classList.add("is-hidden");
  const form = document.getElementById("form-account");
  form.reset();
  form.stake_target.value = "0";
}

async function submitAccountForm(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    name: form.name.value.trim(),
    symbol: form.symbol.value.trim().toUpperCase(),
    allows_stake: form.allows_stake.value === "true",
    stake_target: Number(form.stake_target.value || 0),
  };

  const confirmation = await showFormModal({
    title: t("accounts.confirm.title"),
    message: t("accounts.confirm.msg", payload.name, payload.symbol),
    fields: [],
    confirmText: t("accounts.modal.create"),
  });
  if (!confirmation.confirmed) {
    return;
  }

  await apiFetch("/api/accounts", { method: "POST", body: JSON.stringify(payload) });
  closeAccountFormModal();
  await loadAccounts();
  await loadDashboard();
  toast(t("accounts.toast.created"));
}

function openMovementFormModal() {
  document.getElementById("movement-form-modal").classList.remove("is-hidden");
  // Pre-fill fecha with today's date as default.
  const fechaInput = document.getElementById("movement-fecha");
  if (fechaInput && !fechaInput.value) {
    fechaInput.value = new Date().toISOString().slice(0, 10);
  }
}

function closeMovementFormModal() {
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

async function submitMovementForm(event) {
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
    if (currentDetailAccountId !== null) {
      await showAccountDetail(currentDetailAccountId);
    } else {
      await loadMovements();
    }
    toast(t("movements.toast.registered"));
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadMovements() {
  const data = await apiFetch("/api/movements/recent?limit=10");
  recentMovements = data.items || [];
  renderTable(
    "table-movements",
    [t("movements.table.account"), t("movements.table.currency"), t("movements.table.date"), t("movements.table.type"), t("movements.table.amount"), t("movements.table.price_usd"), t("common.usd"), t("movements.table.description"), t("movements.table.last_modified"), t("movements.table.actions")],
    data.items.map((it) => [
      it.account_name || "-",
      it.symbol || "-",
      it.date,
      it.type,
      money(it.amount),
      money(it.price_usd),
      usd(it.monto_usd || 0),
      it.description || "-",
      it.last_modified || "-",
      `<button class="btn-row-edit" data-id="${it.id}" title="Editar">&#9998;</button>`
      + `<button class="btn-row-dup" data-id="${it.id}" title="Duplicar">&#128203;</button>`
      + `<button class="btn-row-delete" data-id="${it.id}" title="Eliminar">&#128465;</button>`,
    ]),
    [4, 5, 6]
  );
}

async function duplicateMovement(id) {
  const src = recentMovements.find((it) => Number(it.id) === id)
    || currentDetailTransactions.find((it) => Number(it.id) === id);
  if (!src) {
    toast("Movimiento no encontrado", true);
    return;
  }

  const res = await apiFetch("/api/movements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account_id: src.account_id ?? currentDetailAccountId,
      type: src.type,
      amount: src.amount,
      price_usd: src.price_usd,
      monto_usd: src.monto_usd,
      description: src.description || "",
      fecha: src.date,
    }),
  });

  if (!res.ok) {
    toast("Error al duplicar movimiento", true);
    return;
  }

  const newId = res.movement_id;
  toast("Movimiento duplicado. Abriendo editor...");

  // Refresh detail or movements list so the new row is in currentDetailTransactions
  if (currentDetailAccountId !== null) {
    await showAccountDetail(currentDetailAccountId);
  } else {
    await loadMovements();
  }

  await editMovement(newId);
}

async function editMovement(id) {
  const current = recentMovements.find((it) => Number(it.id) === id)
    || currentDetailTransactions.find((it) => Number(it.id) === id);
  if (!current) {
    toast(t("movements.toast.not_found"), true);
    return;
  }

  const editStep = await showFormModal({
    title: t("movements.edit.title", id),
    fields: [
      {
        name: "type",
        label: t("movements.edit.type"),
        type: "select",
        value: current.type,
        options: [
          { value: "ingreso", label: t("movements.edit.ingreso") },
          { value: "retiro", label: t("movements.edit.retiro") },
          { value: "reward", label: t("movements.modal.type.reward") },
        ],
      },
      { name: "fecha", label: t("movements.modal.fecha"), type: "date", value: (current.date || "").slice(0, 10) },
      { name: "amount", label: t("movements.edit.amount"), type: "number", min: 0, step: "0.00000001", value: current.amount ?? 0, lockable: true },
      { name: "price_usd", label: t("movements.edit.price_usd"), type: "number", min: 0, step: "0.00000001", value: current.price_usd ?? 0, lockable: true },
      { name: "monto_usd", label: t("movements.modal.amount_usd"), type: "number", min: 0, step: "0.00000001", value: formatNumber(current.monto_usd ?? ((current.amount ?? 0) * (current.price_usd ?? 0)), 8), lockable: true },
      { name: "description", label: t("movements.edit.description"), type: "text", value: current.description || "" },
    ],
    confirmText: t("movements.edit.save"),
    onFieldChange: (name, values, setValue, lockedField) => {
      const amount   = parseFloat(values.amount)    || 0;
      const price    = parseFloat(values.price_usd) || 0;
      const montoUsd = parseFloat(values.monto_usd) || 0;

      if (name === lockedField) return;

      if (lockedField === "price_usd") {
        if (name === "amount"    && price > 0) setValue("monto_usd", formatNumber(amount * price, 8));
        if (name === "monto_usd" && price > 0) setValue("amount",    formatNumber(montoUsd / price, 8));
      } else if (lockedField === "amount") {
        if (name === "price_usd" && amount > 0) setValue("monto_usd", formatNumber(amount * price, 8));
        if (name === "monto_usd" && amount > 0) setValue("price_usd", formatNumber(montoUsd / amount, 8));
      } else if (lockedField === "monto_usd") {
        if (name === "amount"    && amount > 0) setValue("price_usd", formatNumber(montoUsd / amount, 8));
        if (name === "price_usd" && price  > 0) setValue("amount",    formatNumber(montoUsd / price, 8));
      }
    },
    defaultLock: "price_usd",
  });

  if (!editStep.confirmed) {
    return;
  }

  const type = String(editStep.values.type || "ingreso").trim().toLowerCase();
  const fecha = String(editStep.values.fecha || "").trim();
  const amount = Number(editStep.values.amount || 0);
  const priceUsd = Number(editStep.values.price_usd || 0);
  const montoUsd = Number(editStep.values.monto_usd || 0);
  const description = String(editStep.values.description || "").trim();

  if (amount <= 0 || priceUsd <= 0) {
    toast(t("movements.toast.amount_price_zero"), true);
    return;
  }

  await apiFetch(`/api/movements/${id}`, {
    method: "PUT",
    body: JSON.stringify({ type, amount, price_usd: priceUsd, monto_usd: montoUsd, description, fecha }),
  });
  if (currentDetailAccountId !== null) {
    await showAccountDetail(currentDetailAccountId);
  } else {
    await loadMovements();
  }
  await loadDashboard();
  toast(t("movements.toast.edited"));
}

async function editMovementById() {
  const idStep = await showFormModal({
    title: t("movements.edit_by_id.title"),
    fields: [
      { name: "id", label: t("movements.edit_by_id.id_label"), type: "number", min: 1, step: "1", placeholder: t("movements.edit_by_id.id_ph") },
    ],
    confirmText: t("common.continue"),
  });
  if (!idStep.confirmed) return;
  const id = Number(idStep.values.id || 0);
  if (!id) { toast(t("movements.toast.invalid_id"), true); return; }
  await editMovement(id);
}

async function deleteMovement(id) {
  const confirmDelete = await showFormModal({
    title: t("movements.delete.title", id),
    fields: [],
    confirmText: t("movements.delete.confirm"),
    cancelText: t("common.cancel"),
    danger: true,
  });

  if (!confirmDelete.confirmed) {
    return;
  }

  await apiFetch(`/api/movements/${id}`, { method: "DELETE" });
  if (currentDetailAccountId !== null) {
    await showAccountDetail(currentDetailAccountId);
  } else {
    await loadMovements();
  }
  await loadDashboard();
  toast(t("movements.toast.deleted"));
}

async function deleteMovementById() {
  const step = await showFormModal({
    title: t("movements.del_by_id.title"),
    fields: [
      { name: "id", label: t("movements.edit_by_id.id_label"), type: "number", min: 1, step: "1", placeholder: t("movements.edit_by_id.id_ph") },
    ],
    confirmText: t("common.continue"),
    danger: true,
  });
  if (!step.confirmed) return;
  const id = Number(step.values.id || 0);
  if (!id) { toast(t("movements.toast.invalid_id"), true); return; }
  await deleteMovement(id);
}



async function loadStaking() {
  const data = await apiFetch("/api/staking/progress");
  renderTable(
    "table-staking",
    [t("staking.table.account"), t("staking.table.currency"), t("staking.table.current_stake"), t("staking.table.rewards_30d"), t("staking.table.target"), t("staking.table.progress")],
    data.items.map((it) => [
      `<button class="btn-account-link" data-account-id="${it.account_id}">${it.account_name}</button>`,
      it.symbol,
      money(it.current_stake),
      it.current_price_usd > 0 ? usd(it.rewards_30d_usd) : "—",
      usd(it.target_rewards_usd),
      pct(it.progress_pct),
    ]),
    [2, 3, 4, 5]
  );
}



async function loadDbConfig() {
  const data = await apiFetch("/api/db/list");
  const activeName = data.active ? data.active.split(/[\\/]/).pop() : "-";
  document.getElementById("db-active-name").textContent = activeName;

  const tbody = document.getElementById("db-files-list");
  tbody.innerHTML = (data.files || []).map((f) => {
    const isActive = f.path === data.active;
    return `<tr class="${isActive ? "db-row-active" : ""}">
      <td>${f.name}${isActive ? ` <span class="db-active-badge">${t("config.db.active_badge")}</span>` : ""}</td>
      <td class="col-num">${f.size_kb} KB</td>
      <td>${f.modified_at}</td>
      <td>${isActive ? "" : `<button class="btn-db-switch" data-path="${f.path}" data-name="${f.name}">${t("config.db.btn_use")}</button> <button class="btn-db-delete" data-name="${f.name}">${t("config.db.btn_delete")}</button>`}</td>
    </tr>`;
  }).join("");
}

async function updatePrices() {
  const confirmation = await showFormModal({
    title: t("market.update.title"),
    message: t("market.update.msg"),
    fields: [],
    confirmText: t("market.update.confirm"),
  });
  if (!confirmation.confirmed) {
    return;
  }

  await apiFetch("/api/prices/update", { method: "POST", body: "{}" });
  await loadMarket();
  await loadDashboard();
  toast(t("market.toast.updated"));
}

// ── Account Detail View ──────────────────────────────────────────────────────

let currentDetailAccountId = null;
let currentDetailTransactions = [];

async function showAccountDetail(accountId) {
  currentDetailAccountId = accountId;
  const data = await apiFetch(`/api/accounts/${accountId}/detail`);
  currentDetailTransactions = data.transactions || [];
  renderAccountDetail(data);
  showView("account-detail");
}

function openMovementFromDetail() {
  const accountSelect = document.getElementById("movement-account");
  // Pre-select the account
  accountSelect.value = String(currentDetailAccountId);
  handleAccountChange();
  openMovementFormModal();
}

function renderAccountDetail(data) {
  document.getElementById("acct-detail-name").textContent = data.name;
  document.getElementById("acct-detail-symbol").textContent = data.symbol;

  const summaryEl = document.getElementById("acct-detail-summary");
  const stakeLabel = data.allows_stake ? "SI" : "NO";
  const pctMeta = data.pct_meta > 0 ? data.pct_meta.toFixed(2) + "%" : "-";
  const showStaking = data.allows_stake;

  summaryEl.innerHTML = `
    <div class="summary-card"><div class="lbl">${t("accounts.detail.lbl_saldo")}</div><div class="val">${money(data.saldo_nativo)} ${data.symbol}</div></div>
    <div class="summary-card"><div class="lbl">${t("accounts.detail.lbl_usd")}</div><div class="val">$ ${usd(data.saldo_usd)}</div></div>
    ${showStaking ? `
    <div class="summary-card"><div class="lbl">${t("accounts.detail.lbl_rewards30d")}</div><div class="val">$ ${usd(data.rewards_30d_usd)}</div></div>
    <div class="summary-card"><div class="lbl">${t("accounts.detail.lbl_meta")}</div><div class="val">$ ${usd(data.stake_target)}</div></div>
    <div class="summary-card"><div class="lbl">${t("accounts.detail.lbl_pct_meta")}</div><div class="val">${pctMeta}</div></div>
    ` : ""}
  `;

  const table = document.getElementById("table-account-detail");
  if (!data.transactions || data.transactions.length === 0) {
    table.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--muted)">${t("accounts.detail.no_transactions")}</td></tr>`;
    return;
  }

  const headers = [
    { label: t("accounts.detail.col_fecha"),      numeric: false },
    { label: t("accounts.detail.col_tipo"),        numeric: false },
    { label: t("accounts.detail.col_cantidad"),    numeric: true  },
    { label: t("accounts.detail.col_precio_usd"), numeric: true  },
    { label: t("accounts.detail.col_total_usd"),  numeric: true  },
    { label: t("accounts.detail.col_ult_mod"),     numeric: false },
    { label: t("common.actions"),                  numeric: false },
  ];
  const thead = `<thead><tr>${headers.map((h) => `<th${h.numeric ? ' class="col-num"' : ""}>${h.label}</th>`).join("")}</tr></thead>`;
  const rows = data.transactions.map((tx) =>
    `<tr>
      <td>${tx.date}</td>
      <td>${tx.type}</td>
      <td class="col-num">${money(tx.amount)}</td>
      <td class="col-num">${money(tx.price_usd)}</td>
      <td class="col-num">${usd(tx.monto_usd)}</td>
      <td>${tx.last_modified || "-"}</td>
      <td><button class="btn-row-edit" data-id="${tx.id}" title="Editar">&#9998;</button><button class="btn-row-dup" data-id="${tx.id}" title="Duplicar">&#128203;</button><button class="btn-row-delete" data-id="${tx.id}" title="Eliminar">&#128465;</button></td>
    </tr>`
  ).join("");
  table.innerHTML = `${thead}<tbody>${rows}</tbody>`;
}

function bindEvents() {
  document.getElementById("btn-new-account").addEventListener("click", openAccountFormModal);

  // Account detail: delegate clicks on account name buttons in the accounts table
  ["table-accounts", "table-staking"].forEach((tableId) => {
    document.getElementById(tableId).addEventListener("click", (event) => {
      const btn = event.target.closest("[data-account-id]");
      if (btn) {
        const accountId = parseInt(btn.dataset.accountId, 10);
        showAccountDetail(accountId).catch((err) => toast(err.message, true));
      }
    });
  });

  document.getElementById("btn-back-accounts").addEventListener("click", () => {
    currentDetailAccountId = null;
    showView("accounts");
  });

  document.getElementById("btn-add-movement-detail").addEventListener("click", openMovementFromDetail);

  document.getElementById("table-account-detail").addEventListener("click", async (e) => {
    try {
      const editBtn = e.target.closest(".btn-row-edit");
      const dupBtn  = e.target.closest(".btn-row-dup");
      const delBtn  = e.target.closest(".btn-row-delete");
      if (editBtn) {
        await editMovement(Number(editBtn.dataset.id));
      } else if (dupBtn) {
        await duplicateMovement(Number(dupBtn.dataset.id));
      } else if (delBtn) {
        await deleteMovement(Number(delBtn.dataset.id));
      }
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-cancel-account-form").addEventListener("click", closeAccountFormModal);

  document.getElementById("form-account").addEventListener("submit", async (event) => {
    try {
      await submitAccountForm(event);
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-new-movement").addEventListener("click", () => {
    currentDetailAccountId = null;
    openMovementFormModal();
  });

  document.getElementById("btn-cancel-movement-form").addEventListener("click", closeMovementFormModal);

  document.getElementById("form-movement").addEventListener("submit", async (event) => {
    try {
      await submitMovementForm(event);
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-search-accounts").addEventListener("click", async () => {
    try {
      await loadAccounts(document.getElementById("accounts-query").value.trim());
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-refresh-accounts").addEventListener("click", async () => {
    try {
      await loadAccounts();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-load-movements").addEventListener("click", async () => {
    try {
      await loadMovements();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("table-movements").addEventListener("click", async (e) => {
    try {
      const editBtn = e.target.closest(".btn-row-edit");
      const dupBtn  = e.target.closest(".btn-row-dup");
      const delBtn  = e.target.closest(".btn-row-delete");
      if (editBtn) {
        await editMovement(Number(editBtn.dataset.id));
      } else if (dupBtn) {
        await duplicateMovement(Number(dupBtn.dataset.id));
      } else if (delBtn) {
        await deleteMovement(Number(delBtn.dataset.id));
      }
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-load-staking").addEventListener("click", async () => {
    try {
      await loadStaking();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-load-prices").addEventListener("click", async () => {
    try {
      await loadMarket();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-update-prices").addEventListener("click", async () => {
    try {
      await updatePrices();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-new-currency").addEventListener("click", openCurrencyFormModal);

  document.getElementById("btn-cancel-currency-form").addEventListener("click", closeCurrencyFormModal);

  document.getElementById("form-currency").addEventListener("submit", async (event) => {
    try {
      await submitCurrencyForm(event);
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("btn-db-backup").addEventListener("click", async () => {
    try {
      await apiFetch("/api/db/backup", { method: "POST" });
      toast(t("config.db.toast_backup_ok"));
      await loadDbConfig();
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.getElementById("db-files-list").addEventListener("click", async (e) => {
    const delBtn = e.target.closest(".btn-db-delete");
    if (delBtn) {
      const name = delBtn.dataset.name;
      const confirmed = await showFormModal({
        title: t("config.db.delete_title"),
        message: t("config.db.delete_msg", name),
        fields: [],
        confirmText: t("config.db.btn_delete"),
      });
      if (!confirmed.confirmed) return;
      try {
        await apiFetch(`/api/db/backup/${encodeURIComponent(name)}`, { method: "DELETE" });
        toast(t("config.db.toast_delete_ok", name));
        await loadDbConfig();
      } catch (err) { toast(err.message, true); }
      return;
    }
    const btn = e.target.closest(".btn-db-switch");
    if (!btn) return;
    const name = btn.dataset.name;
    const confirmed = await showFormModal({
      title: t("config.db.switch_title"),
      message: t("config.db.switch_msg", name),
      fields: [],
      confirmText: t("config.db.btn_use"),
    });
    if (!confirmed.confirmed) return;
    try {
      await apiFetch("/api/db/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: name }),
      });
      toast(t("config.db.toast_switch_ok", name));
      await loadDbConfig();
      await loadDashboard();
    } catch (err) {
      toast(err.message, true);
    }
  });
}

async function bootstrap() {
  applyTranslations();
  buildTabs();
  bindEvents();
  initMovementForm(); // Initialize multi-currency form logic
  try {
    await loadAccounts();
    await loadDashboard();
    await loadMovements();
    await loadStaking();
    await loadMarket();
    await loadDbConfig();
  } catch (err) {
    toast(err.message, true);
  }
}

bootstrap();
