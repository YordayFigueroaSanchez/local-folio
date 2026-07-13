// Cambio de vista (mostrar/ocultar secciones y pestanas). Sin dependencias
// de otros modulos: solo manipula el DOM.

export const NAV_VIEWS = ["dashboard", "accounts", "movements", "staking", "market", "config"];
export const VIEWS = [...NAV_VIEWS, "account-detail"];

export function showView(name) {
  VIEWS.forEach((view) => {
    const section = document.getElementById(`view-${view}`);
    const tab = document.getElementById(`tab-${view}`);
    const active = view === name;
    section.classList.toggle("hidden", !active);
    if (tab) tab.classList.toggle("active", active);
  });
}
