// Vista Cuentas: listado consolidado y alta de cuentas nuevas.

import { apiFetch } from "../api.js";
import { money, usd, pct } from "../format.js";
import { renderTable, showFormModal, toast } from "../ui.js";
import { loadDashboard } from "./dashboard.js";
import { handleAccountChange } from "../movement-form.js";

export async function loadCurrenciesIntoSelect() {
  const data = await apiFetch("/api/currencies");
  const select = document.getElementById("select-symbol");
  select.innerHTML =
    `<option value="">${t("accounts.modal.select")}</option>` +
    data.items.map((c) => `<option value="${c.simbolo}">${c.simbolo}</option>`).join("");
}

export async function loadAccounts(query = "") {
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

export async function openAccountFormModal() {
  await loadCurrenciesIntoSelect();
  document.getElementById("account-form-modal").classList.remove("is-hidden");
}

export function closeAccountFormModal() {
  document.getElementById("account-form-modal").classList.add("is-hidden");
  const form = document.getElementById("form-account");
  form.reset();
  form.stake_target.value = "0";
}

export async function submitAccountForm(event) {
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
