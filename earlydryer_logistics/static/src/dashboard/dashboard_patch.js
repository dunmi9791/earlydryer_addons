import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { EarlydryerDashboard } from "@earlydryer_reporting/dashboard";

// "Logistics" section of the owner dashboard. The server only returns these
// KPIs to Operations Managers and above; tiles without data are not shown.
patch(EarlydryerDashboard.prototype, {
    setup() {
        super.setup(...arguments);
        this.sections.push({
            title: _t("Logistics"),
            codes: [
                "logistics_pickups_done",
                "logistics_deliveries_done",
                "logistics_on_slot_pct",
                "logistics_failed_pct",
                "logistics_stops_per_trip",
                "logistics_fee_revenue",
                "logistics_cod_collected",
                "logistics_cash_difference",
                "logistics_carrier_cost",
            ],
        });
    },
});
