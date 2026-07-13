// Vista Staking.

import { apiFetch } from "../api.js";
import { money, usd, pct } from "../format.js";
import { renderTable } from "../ui.js";

export async function loadStaking() {
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
