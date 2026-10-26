/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { EdCustomerDialog } from "@earlydryer_pos/intake/customer_dialog";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { normalizeNigerianPhone, phoneDigits } from "@earlydryer_pos/core/phone";

patch(EdCustomerDialog.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.notifyConsent = true;
    },
    async create() {
        const name = this.state.name.trim();
        const phone = normalizeNigerianPhone(this.state.phone);
        if (!name || !phone) {
            this.state.error = _t("Enter a name and a valid phone number.");
            return;
        }
        const existing = this.pos.models["res.partner"].find(
            (partner) => phoneDigits(partner.phone || "") === phoneDigits(phone)
        );
        if (existing) {
            this.state.error = _t("A customer already has this phone number. Select them from search.");
            return;
        }
        if (this.pos.edOnline) {
            try {
                const [partner] = await this.pos.data.create("res.partner", [{
                    name, phone, earlydryer_notify_opt_in: this.state.notifyConsent,
                }], false);
                if (partner) {
                    this.props.getPayload({ partner });
                    this.props.close();
                    return;
                }
            } catch {
                // Keep consent with the offline order until its customer is created.
            }
        }
        this.props.getPayload({ newName: name, newPhone: phone, notifyConsent: this.state.notifyConsent });
        this.props.close();
    },
});
patch(PosStore.prototype, {
    async edSelectCustomer(order = this.getOrder()) {
        const payload = await makeAwaitable(this.dialog, EdCustomerDialog, {});
        if (!payload) return false;
        order.earlydryer_notify_consent_recorded = false;
        if (payload.partner) {
            order.earlydryer_new_partner_name = false;
            order.earlydryer_new_partner_phone = false;
            this.setPartnerToCurrentOrder(payload.partner);
        } else {
            this.setPartnerToCurrentOrder(false);
            order.earlydryer_new_partner_name = payload.newName;
            order.earlydryer_new_partner_phone = payload.newPhone;
            order.earlydryer_notify_consent = payload.notifyConsent;
            order.earlydryer_notify_consent_recorded = true;
        }
        return true;
    },
});
