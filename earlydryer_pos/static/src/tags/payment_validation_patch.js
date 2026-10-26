import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { serializeDateTime } from "@web/core/l10n/dates";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { uuidv4 } from "@point_of_sale/utils";

patch(OrderPaymentValidation.prototype, {
    get edPos() {
        return this.pos.edEnabled ? this.pos : false;
    },

    async askBeforeValidation() {
        if ((await super.askBeforeValidation(...arguments)) === false) {
            return false;
        }
        const pos = this.edPos;
        if (!pos) {
            return true;
        }
        const order = this.order;
        const onAccount = order.payment_ids.some(
            (payment) => payment.payment_method_id.type === "pay_later" && payment.amount
        );
        if ((order.edIsLaundry || onAccount) && !pos.edHasRealCustomer(order)) {
            pos.dialog.add(AlertDialog, {
                title: _t("Customer required"),
                body: order.edIsLaundry
                    ? _t("A laundry intake needs a real customer (name and phone).")
                    : _t("A balance on account needs an identified customer, not the walk-in."),
            });
            return false;
        }
        if (order.edIsLaundry && pos.edBranch.tag_mode === "preprinted") {
            const untagged = order.edGarmentLines
                .filter((line) => line.edNeedsTags)
                .reduce(
                    (n, line) => n + Math.max(line.edPieceCount - line.edTagCodes.length, 0),
                    0
                );
            if (untagged) {
                const confirmed = await ask(pos.dialog, {
                    title: _t("Pieces without tag"),
                    body: _t(
                        "%s piece(s) have no tag scanned. Validate and tag them at the counter later?",
                        untagged
                    ),
                });
                if (!confirmed) {
                    return false;
                }
            }
        }
        return true;
    },

    async _askForCustomerIfRequired() {
        // a customer created offline is attached when the order syncs
        if (this.edPos && this.order.earlydryer_new_partner_phone) {
            return true;
        }
        return super._askForCustomerIfRequired(...arguments);
    },

    async finalizeValidation() {
        const pos = this.edPos;
        const order = this.order;
        if (pos && order.edIsLaundry) {
            pos.edAssignTagCodes(order);
            const promise = order.edPromiseEstimate(pos.edPayload.calendar);
            order.earlydryer_promised_estimate = promise ? serializeDateTime(promise) : false;
        }
        return super.finalizeValidation(...arguments);
    },

    async afterOrderValidation() {
        const res = await super.afterOrderValidation(...arguments);
        const pos = this.edPos;
        if (pos) {
            // balance paid at collection: the job is released with this order
            for (const line of this.order.lines.filter((l) => l.earlydryer_settlement_job_ref)) {
                const jobId = parseInt(line.earlydryer_settlement_job_ref, 10);
                if (pos.edState.collectedJobIds.includes(jobId)) {
                    continue;
                }
                const cashier = pos.getCashier();
                await pos.edQueueCollection({
                    uuid: uuidv4(),
                    job_id: jobId,
                    employee_id: pos.config.module_pos_hr && cashier?.id ? cashier.id : false,
                    mode: "settlement",
                    approver_employee_id: false,
                    amount_due: line.price_unit,
                    collected_on: serializeDateTime(luxon.DateTime.now()),
                    settlement_order_uuid: this.order.uuid,
                });
            }
        }
        if (pos && this.order.edIsLaundry && pos.config.earlydryer_print_tags_auto) {
            pos.edPrintTags(this.order);
        }
        return res;
    },
});
