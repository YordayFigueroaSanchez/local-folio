// Punto de entrada: arma las pestanas, conecta los event listeners de toda
// la aplicacion y dispara la carga inicial de datos. Importa la logica de
// cada vista desde js/.

import { apiFetch } from "./js/api.js";
import { toast, showFormModal } from "./js/ui.js";
import { appState } from "./js/state.js";
import { NAV_VIEWS, showView } from "./js/router.js";
import { loadDashboard } from "./js/views/dashboard.js";
import { loadAccounts, openAccountFormModal, closeAccountFormModal, submitAccountForm } from "./js/views/accounts.js";
import { loadMovements, editMovement, duplicateMovement, deleteMovement } from "./js/views/movements.js";
import { loadStaking } from "./js/views/staking.js";
import { loadMarket, openCurrencyFormModal, closeCurrencyFormModal, submitCurrencyForm, updatePrices } from "./js/views/market.js";
import { loadDbConfig } from "./js/views/config.js";
import { showAccountDetail } from "./js/views/account-detail.js";
import {
  initMovementForm,
  openMovementFormModal,
  closeMovementFormModal,
  submitMovementForm,
  openMovementFromDetail,
} from "./js/movement-form.js";

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

function buildTabs() {
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = NAV_VIEWS.map((view) => `<button id="tab-${view}" data-view="${view}">${t("tab." + view)}</button>`).join("");
  tabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  showView("dashboard");
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
    appState.currentDetailAccountId = null;
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
    appState.currentDetailAccountId = null;
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
