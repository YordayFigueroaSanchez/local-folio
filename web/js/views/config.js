// Vista Configuracion (gestion de base de datos).

import { apiFetch } from "../api.js";

export async function loadDbConfig() {
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
