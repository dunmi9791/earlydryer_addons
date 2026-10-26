/** @odoo-module **/
import {
  Component,
  onWillStart,
  onWillUnmount,
  onPatched,
  onMounted,
  useRef,
  useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
const { DateTime } = luxon;

export class ReportingHeader extends Component {
  static template = "earlydryer_reporting.Header";
  static props = ["state", "refresh", "periodChanged", "branches"];
}
export class ReportingTile extends Component {
  static template = "earlydryer_reporting.Tile";
  static props = ["code", "kpi", "open"];
  get formatted() {
    const value = Number(this.props.kpi.value || 0);
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 2,
      ...(this.props.kpi.unit === "currency"
        ? { style: "currency", currency: this.props.kpi.currency || "NGN" }
        : {}),
    }).format(value);
  }
  get direction() {
    const lower = [
      "turnaround_avg_h",
      "turnaround_p90_h",
      "overdue_count",
      "unpaid_balance",
      "unpaid_releases",
      "discount_pct",
      "discount_value",
      "expenses",
      "ready_uncollected_count",
      "uncollected_count",
      "cost_per_kg",
      "rework_rate",
      "missing_items",
    ].includes(this.props.code);
    const delta = this.props.kpi.delta_pct;
    return delta === null || !delta
      ? "text-muted"
      : delta > 0 !== lower
        ? "text-success"
        : "text-danger";
  }
}
export class ReportingChart extends Component {
  static template = "earlydryer_reporting.Chart";
  static props = ["rows", "type", "title"];
  setup() {
    this.canvas = useRef("canvas");
    onWillStart(() => loadBundle("web.chartjs_lib"));
    onMounted(() => this.draw());
    onPatched(() => this.draw());
    onWillUnmount(() => this.chart?.destroy());
  }
  draw() {
    this.chart?.destroy();
    if (!this.canvas.el) return;
    const daily = this.props.type === "line";
    const rowLabel = (row) =>
      `${typeof row.name === "object" ? Object.values(row.name)[0] : row.name} · ${row.express ? _t("Express") : _t("Standard")}`;
    const labels = [
      ...new Set(this.props.rows.map((r) => (daily ? r.date : rowLabel(r)))),
    ];
    const branches = daily
      ? [...new Set(this.props.rows.map((r) => r.earlydryer_branch_id))]
      : [null];
    this.chart = new Chart(this.canvas.el, {
      type: daily ? "line" : "bar",
      data: {
        labels,
        datasets: branches.map((branch, index) => ({
          label: daily
            ? this.props.rows.find((row) => row.earlydryer_branch_id === branch)
                ?.branch_name || `${_t("Plant")} ${branch}`
            : _t("Hours"),
          data: labels.map((label) => {
            const row = this.props.rows.find((r) =>
              daily
                ? r.date === label && r.earlydryer_branch_id === branch
                : rowLabel(r) === label,
            );
            return Number(row?.[daily ? "value" : "hours"] || 0);
          }),
          borderColor: ["#6f42c1", "#159c90", "#eea63a"][index % 3],
          backgroundColor: ["#6f42c1", "#159c90", "#eea63a"][index % 3],
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: daily } },
      },
    });
  }
}
export class ReportingSection extends Component {
  static template = "earlydryer_reporting.Section";
  static components = { ReportingTile };
  static props = ["title", "codes", "data", "open"];
}
export class EarlydryerDashboard extends Component {
  static template = "earlydryer_reporting.Dashboard";
  static components = { ReportingHeader, ReportingSection, ReportingChart };
  setup() {
    this.orm = useService("orm");
    this.action = useService("action");
    this.state = useState({
      period: "month",
      compare: "previous",
      branch: "",
      start: "",
      end: "",
      data: {},
      branches: [],
      loading: false,
      error: "",
      updated: "",
    });
    this.sections = [
      {
        title: _t("Sales"),
        codes: [
          "orders_count",
          "orders_value",
          "revenue_posted",
          "avg_order_value",
          "retail_sales",
          "discount_value",
          "discount_pct",
        ],
      },
      {
        title: _t("Operations"),
        codes: [
          "items_count",
          "turnaround_avg_h",
          "turnaround_p90_h",
          "on_time_pct",
          "overdue_count",
          "ready_uncollected_count",
          "uncollected_count",
          "rework_rate",
          "missing_items",
        ],
      },
      {
        title: _t("Customers"),
        codes: [
          "new_customers",
          "repeat_customers",
          "repeat_rate",
          "wallet_topups",
          "wallet_balance",
        ],
      },
      {
        title: _t("Money"),
        codes: ["unpaid_balance", "unpaid_releases", "expenses", "cost_per_kg"],
      },
    ];
    this.choosePeriod();
    onWillStart(() => this.refresh());
  }
  choosePeriod() {
    const now = DateTime.now().setZone("Africa/Lagos");
    const periods = {
      today: [now, now],
      yesterday: [now.minus({ days: 1 }), now.minus({ days: 1 })],
      week: [now.startOf("week"), now],
      last_week: [
        now.minus({ weeks: 1 }).startOf("week"),
        now.minus({ weeks: 1 }).endOf("week"),
      ],
      month: [now.startOf("month"), now],
      last_month: [
        now.minus({ months: 1 }).startOf("month"),
        now.minus({ months: 1 }).endOf("month"),
      ],
      year: [now.startOf("year"), now],
    };
    if (periods[this.state.period])
      [this.state.start, this.state.end] = periods[this.state.period].map((d) =>
        d.toISODate(),
      );
  }
  async periodChanged() {
    this.choosePeriod();
    await this.refresh();
  }
  async refresh() {
    const sequence = (this.sequence = (this.sequence || 0) + 1);
    this.state.loading = true;
    this.state.error = "";
    try {
      const branches = this.state.branch ? [Number(this.state.branch)] : [];
      const data = await this.orm.call(
        "earlydryer.kpi",
        "compute",
        [[], branches, this.state.start, this.state.end, this.state.compare],
        { dashboard: true },
      );
      if (sequence !== this.sequence) return;
      this.state.data = data;
      // Keep the initial allowed options when filtering to one plant.
      if (!this.state.branch) this.state.branches = data._meta?.branches || [];
      this.state.updated = DateTime.now().toLocaleString(
        DateTime.TIME_WITH_SECONDS,
      );
    } catch (error) {
      if (sequence === this.sequence)
        this.state.error =
          error.data?.message || _t("Unable to load performance indicators.");
    } finally {
      if (sequence === this.sequence) this.state.loading = false;
    }
  }
  open(kpi) {
    const drill = kpi.drill;
    this.action.doAction({
      type: "ir.actions.act_window",
      name: kpi.label,
      res_model: drill.model,
      views: [
        [false, "list"],
        [false, "form"],
      ],
      domain: drill.domain,
      context: drill.context,
    });
  }
}
registry
  .category("actions")
  .add("earlydryer_reporting.dashboard", EarlydryerDashboard);
