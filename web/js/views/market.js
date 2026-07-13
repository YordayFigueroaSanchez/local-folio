// Vista Mercado: precios de referencia y gestion de monedas registradas.

import { apiFetch } from "../api.js";
import { money } from "../format.js";
import { showFormModal, toast } from "../ui.js";
import { loadDashboard } from "./dashboard.js";
import { loadCurrenciesIntoSelect } from "./accounts.js";

export async function loadMarket() {
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

export function openCurrencyFormModal() {
  document.getElementById("currency-form-modal").classList.remove("is-hidden");
}

export function closeCurrencyFormModal() {
  document.getElementById("currency-form-modal").classList.add("is-hidden");
  document.getElementById("form-currency").reset();
}

export async function submitCurrencyForm(event) {
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

export async function deleteCurrency(simbolo) {
  await apiFetch(`/api/currencies/${encodeURIComponent(simbolo)}`, { method: "DELETE" });
  await loadMarket();
  await loadCurrenciesIntoSelect();
  toast(t("market.toast.deleted", simbolo));
}

export async function updatePrices() {
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
