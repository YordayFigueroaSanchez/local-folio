// Vista Movimientos: listado reciente y acciones CRUD (editar, duplicar,
// eliminar), tambien reutilizadas desde la vista de detalle de cuenta.

import { apiFetch } from "../api.js";
import { money, usd, formatNumber } from "../format.js";
import { renderTable, showFormModal, toast } from "../ui.js";
import { appState } from "../state.js";
import { loadDashboard } from "./dashboard.js";
import { showAccountDetail } from "./account-detail.js";

let recentMovements = [];

export async function loadMovements() {
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

export async function duplicateMovement(id) {
  const src = recentMovements.find((it) => Number(it.id) === id)
    || appState.currentDetailTransactions.find((it) => Number(it.id) === id);
  if (!src) {
    toast("Movimiento no encontrado", true);
    return;
  }

  const res = await apiFetch("/api/movements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account_id: src.account_id ?? appState.currentDetailAccountId,
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
  if (appState.currentDetailAccountId !== null) {
    await showAccountDetail(appState.currentDetailAccountId);
  } else {
    await loadMovements();
  }

  await editMovement(newId);
}

export async function editMovement(id) {
  const current = recentMovements.find((it) => Number(it.id) === id)
    || appState.currentDetailTransactions.find((it) => Number(it.id) === id);
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
  if (appState.currentDetailAccountId !== null) {
    await showAccountDetail(appState.currentDetailAccountId);
  } else {
    await loadMovements();
  }
  await loadDashboard();
  toast(t("movements.toast.edited"));
}

export async function editMovementById() {
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

export async function deleteMovement(id) {
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
  if (appState.currentDetailAccountId !== null) {
    await showAccountDetail(appState.currentDetailAccountId);
  } else {
    await loadMovements();
  }
  await loadDashboard();
  toast(t("movements.toast.deleted"));
}

export async function deleteMovementById() {
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
