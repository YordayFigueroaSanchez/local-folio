// Vista de detalle de cuenta.

import { apiFetch } from "../api.js";
import { money, usd } from "../format.js";
import { appState } from "../state.js";
import { showView } from "../router.js";

export async function showAccountDetail(accountId) {
  appState.currentDetailAccountId = accountId;
  const data = await apiFetch(`/api/accounts/${accountId}/detail`);
  appState.currentDetailTransactions = data.transactions || [];
  renderAccountDetail(data);
  showView("account-detail");
}

export function renderAccountDetail(data) {
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
