import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { EdCustomerDialog } from "@earlydryer_pos/intake/customer_dialog";
import { EdLineDetailsDialog } from "@earlydryer_pos/line_details/line_details_dialog";

patch(PosStore.prototype, {
    setup() {
        // laundry mode of the product screen: garments or retail products
        this.edIntakeTab = "laundry";
        return super.setup(...arguments);
    },

    /** Customer button of the laundry counter. */
    async edSelectCustomer(order = this.getOrder()) {
        const payload = await makeAwaitable(this.dialog, EdCustomerDialog, {});
        if (!payload) {
            return false;
        }
        if (payload.partner) {
            order.earlydryer_new_partner_name = false;
            order.earlydryer_new_partner_phone = false;
            this.setPartnerToCurrentOrder(payload.partner);
        } else {
            // created (or matched by phone) on the server when the order syncs
            this.setPartnerToCurrentOrder(false);
            order.earlydryer_new_partner_name = payload.newName;
            order.earlydryer_new_partner_phone = payload.newPhone;
        }
        return true;
    },

    edCustomerLabel(order = this.getOrder()) {
        if (order?.earlydryer_new_partner_name) {
            return `${order.earlydryer_new_partner_name} (${_t("new")})`;
        }
        const partner = order?.getPartner();
        if (!partner || this.edIsWalkIn(partner)) {
            return "";
        }
        return partner.name;
    },

    /** Ask for a real customer before the first laundry line. */
    async edEnsureCustomer(order = this.getOrder()) {
        if (this.edHasRealCustomer(order)) {
            return true;
        }
        await this.edSelectCustomer(order);
        if (this.edHasRealCustomer(order)) {
            return true;
        }
        this.dialog.add(AlertDialog, {
            title: _t("Customer required"),
            body: _t(
                "A laundry intake needs a real customer with a name and a phone number, " +
                    "never the walk-in customer."
            ),
        });
        return false;
    },

    async addLineToOrder(vals, order, opts = {}) {
        if (this.edEnabled && !opts.edInternal) {
            const template =
                typeof vals.product_tmpl_id === "number"
                    ? this.models["product.template"].get(vals.product_tmpl_id)
                    : vals.product_tmpl_id || vals.product_id?.product_tmpl_id;
            const kind = template?.earlydryer_kind;
            if (["surcharge", "express", "settlement"].includes(kind)) {
                this.dialog.add(AlertDialog, {
                    title: _t("Not sold on its own"),
                    body: _t(
                        "Surcharges and express are added from the garment details; " +
                            "balances are paid from the Collect screen."
                    ),
                });
                return;
            }
            if (kind === "laundry") {
                return this.edAddGarment(template.product_variant_ids[0], order, vals.qty);
            }
        }
        return super.addLineToOrder(...arguments);
    },

    /** Add a garment × service line, then open its details. */
    async edAddGarment(product, order = this.getOrder(), qty = 1) {
        order = order || this.addNewOrder();
        if (!(await this.edEnsureCustomer(order))) {
            return;
        }
        const line = await super.addLineToOrder(
            { product_tmpl_id: product.product_tmpl_id, product_id: product, qty: qty || 1 },
            order,
            { merge: false },
            false
        );
        if (!line) {
            return;
        }
        order.edApplyExpress(this.edExpressProduct);
        order.selectOrderline(line);
        await this.edOpenLineDetails(line);
        return line;
    },

    async edOpenLineDetails(line) {
        if (!line?.edIsGarment) {
            return;
        }
        await makeAwaitable(this.dialog, EdLineDetailsDialog, { line });
        line.order_id?.selectOrderline(line);
    },

    async edSetExpress(order, express) {
        order.earlydryer_express = Boolean(express);
        order.edApplyExpress(this.edExpressProduct);
    },

    edPromiseLabel(order = this.getOrder()) {
        const promise = order?.edPromiseEstimate(this.edPayload.calendar);
        return promise ? promise.setZone("local").toFormat("ccc dd LLL, HH:mm") : "";
    },
});
