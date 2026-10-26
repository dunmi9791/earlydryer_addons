/** @odoo-module **/
import { registry } from "@web/core/registry";
registry.category("web_tour.tours").add("earlydryer_reporting_dashboard", {
  steps: () => [
    { trigger: ".er-dashboard [data-kpi='orders_count']", run: "click" },
    { trigger: ".o_list_view .o_list_renderer", run() {} },
  ],
});
