// Vista Dashboard.

import { apiFetch } from "../api.js";
import { money } from "../format.js";

export async function loadDashboard() {
  const data = await apiFetch("/api/dashboard");
  document.getElementById("dash-total-usd").textContent = money(data.total_usd);
  document.getElementById("dash-accounts").textContent = String(data.accounts_count);
  document.getElementById("dash-last-update").textContent = data.last_price_update || t("dashboard.no_snapshot");
}
