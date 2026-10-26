import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

patch(PaymentScreen.prototype, {
    /** Wallet: a real customer, and the amount capped at the balance. */
    async addNewPaymentLine(paymentMethod) {
        const pos = this.pos;
        if (!pos.edWalletEnabled || !pos.edIsWalletMethod(paymentMethod)) {
            return super.addNewPaymentLine(...arguments);
        }
        const order = this.currentOrder;
        const partner = order.getPartner();
        if (!partner || pos.edIsWalkIn(partner)) {
            this.dialog.add(AlertDialog, {
                title: _t("Customer required"),
                body: _t("Choose the customer before paying from the wallet."),
            });
            return false;
        }
        await pos.edWalletRefresh(partner.id);
        const available = pos.edWalletAvailable(partner) - this.edWalletOnOrder(order);
        if (available <= 0) {
            this.dialog.add(AlertDialog, {
                title: _t("No wallet balance"),
                body: _t("%s has nothing left to spend in the wallet.", partner.name),
            });
            return false;
        }
        const res = await super.addNewPaymentLine(...arguments);
        const line = order.getSelectedPaymentline();
        if (res && line && pos.edIsWalletMethod(line.payment_method_id)) {
            const amount = Math.min(line.amount, available);
            line.setAmount(amount);
            this.numberBuffer.set(amount.toString());
        }
        return res;
    },

    edWalletOnOrder(order, except = null) {
        return order.payment_ids
            .filter((p) => p !== except && this.pos.edIsWalletMethod(p.payment_method_id))
            .reduce((total, p) => total + p.amount, 0);
    },
});
