import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { serializeDateTime } from "@web/core/l10n/dates";
import { ConnectionLostError } from "@web/core/network/rpc";
import { formatCurrency } from "@web/core/currency";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { uuidv4 } from "@point_of_sale/utils";
import {
    approversOf,
    askManagerPin,
    matchRule,
} from "@earlydryer_pos/discount_approval/manager_pin";

const { DateTime } = luxon;
const NOT_READY = ["received", "tagged", "sorted", "washed", "dried", "ironed", "qc"];

/** Collection: scan the receipt or a tag, see the shelf, release when paid. */
export class EdCollectionScreen extends Component {
    static template = "earlydryer_pos.EdCollectionScreen";
    static props = {};

    setup() {
        this.pos = usePos();
        this.inputRef = useRef("input");
        this.state = useState({
            query: "",
            jobs: [],
            job: false,
            searching: false,
            message: "",
        });
        onMounted(() => this.inputRef.el?.focus());
    }

    formatCurrency(amount) {
        return formatCurrency(amount, this.pos.config.currency_id.id);
    }
    formatDate(value) {
        return value
            ? DateTime.fromSQL(value, { zone: "utc" })
                  .setZone("local")
                  .toFormat("ccc dd LLL, HH:mm")
            : "";
    }

    async lookup() {
        const code = this.state.query.trim();
        if (!code) {
            return;
        }
        this.state.searching = true;
        this.state.message = "";
        let jobs = null;
        if (this.pos.edOnline) {
            try {
                const result = await this.pos.data.call("laundry.job", "earlydryer_pos_lookup", [
                    code,
                    this.pos.config.id,
                ]);
                const collected = new Set(this.pos.edState.collectedJobIds);
                jobs = result.jobs.filter((job) => !collected.has(job.id));
            } catch (error) {
                if (!(error instanceof ConnectionLostError)) {
                    console.warn(error);
                }
            }
        }
        if (jobs === null) {
            jobs = this.pos.edLookupOffline(code);
            if (!jobs.length) {
                this.state.message = _t(
                    "Offline: only jobs ready on this till's cache can be found."
                );
            }
        }
        this.state.searching = false;
        this.state.jobs = jobs;
        this.state.job = jobs.length === 1 ? jobs[0] : false;
        if (!jobs.length && !this.state.message) {
            this.state.message = _t("No job found for %s.", code);
        }
    }

    open(job) {
        this.state.job = job;
    }

    get job() {
        return this.state.job;
    }
    get isNotReady() {
        return this.job && NOT_READY.includes(this.job.state);
    }
    get isClosed() {
        return this.job && ["collected", "delivered", "cancelled"].includes(this.job.state);
    }
    get isPaid() {
        return this.job && (this.job.amount_due <= 0.0001 || this.job.credit_approved);
    }

    get cashierEmployee() {
        const cashier = this.pos.getCashier();
        return this.pos.config.module_pos_hr && cashier?.id ? cashier : false;
    }

    async _record(mode, extra = {}) {
        const job = this.job;
        await this.pos.edQueueCollection({
            uuid: uuidv4(),
            job_id: job.id,
            employee_id: this.cashierEmployee?.id || false,
            mode,
            approver_employee_id: false,
            amount_due: job.amount_due,
            collected_on: serializeDateTime(DateTime.now()),
            settlement_order_uuid: false,
            ...extra,
        });
        this.pos.notification.add(
            _t("%(job)s released from shelf %(shelf)s.", {
                job: job.name,
                shelf: job.shelf || "-",
            }),
            { type: "success" }
        );
        this.reset();
    }

    async release() {
        await this._record("paid");
    }

    async creditRelease() {
        const job = this.job;
        const rule = matchRule(this.pos, "laundry.job", "credit", job.amount_due);
        const approvers = approversOf(
            this.pos,
            rule,
            this.pos.edPayload.credit_fallback_employee_ids || []
        );
        const approver = await askManagerPin(this.pos, approvers, {
            title: _t("Release %s on credit", this.formatCurrency(job.amount_due)),
        });
        if (approver) {
            await this._record("credit", { approver_employee_id: approver.id });
        }
    }

    async takePayment() {
        const job = this.job;
        const pos = this.pos;
        let partner = pos.models["res.partner"].get(job.partner_id);
        if (!partner && pos.edOnline) {
            [partner] = await pos.data.read("res.partner", [job.partner_id]);
        }
        if (!partner) {
            pos.notification.add(
                _t("This customer is not on the till offline: release on manager credit instead."),
                { type: "warning" }
            );
            return;
        }
        let order = pos.getOrder();
        if (!order || order.lines.length || order.finalized) {
            order = pos.addNewOrder();
        }
        pos.setPartnerToCurrentOrder(partner);
        const product = pos.edSettlementProduct;
        const line = await pos.addLineToOrder(
            {
                product_tmpl_id: product.product_tmpl_id,
                product_id: product,
                price_unit: job.amount_due,
                qty: 1,
                earlydryer_settlement_job_ref: String(job.id),
                full_product_name: _t("Balance %s", job.name),
            },
            order,
            { merge: false, edInternal: true },
            false
        );
        if (line) {
            // released when the payment is validated (see payment validation)
            pos.pay();
        }
    }

    reset() {
        this.state.query = "";
        this.state.jobs = [];
        this.state.job = false;
        this.state.message = "";
        this.inputRef.el?.focus();
    }

    back() {
        this.pos.navigate("ProductScreen", { orderUuid: this.pos.getOrder()?.uuid });
    }
}

registry.category("pos_pages").add("EdCollectionScreen", {
    name: "EdCollectionScreen",
    component: EdCollectionScreen,
    route: `/pos/ui/${odoo.pos_config_id}/earlydryer-collect`,
    params: {},
});
