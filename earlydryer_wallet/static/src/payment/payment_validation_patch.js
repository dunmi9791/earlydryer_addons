import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatCurrency } from "@web/core/currency";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(OrderPaymentValidation.prototype, {
    async askBeforeValidation() {
        if ((await super.askBeforeValidation(...arguments)) === false) {
            return false;
        }
        const pos = this.pos;
        if (!pos.edWalletEnabled) {
            return true;
        }
        const order = this.order;
        const partner = order.getPartner();
        const realCustomer = Boolean(partner && !pos.edIsWalkIn(partner));
        const walletPaid = order.payment_ids
            .filter((p) => pos.edIsWalletMethod(p.payment_method_id))
            .reduce((total, p) => total + p.amount, 0);
        const topups = order.lines.filter((line) => pos.edIsTopupLine(line));
        const alert = (body) => {
            pos.dialog.add(AlertDialog, { title: _t("Wallet"), body });
            return false;
        };
        if ((walletPaid || topups.length) && !realCustomer) {
            return alert(_t("Wallet payments and top-ups need the customer's account."));
        }
        if (topups.some((line) => line.getDiscount())) {
            return alert(_t("A wallet top-up cannot be discounted."));
        }
        if (walletPaid > 0) {
            const available = pos.edWalletAvailable(partner);
            if (order.currency.round(walletPaid - available) > 0) {
                return alert(
                    _t(
                        "%(name)s has %(available)s in the wallet on this till, less than %(paid)s.",
                        {
                            name: partner.name,
                            available: formatCurrency(available, order.currency.id),
                            paid: formatCurrency(walletPaid, order.currency.id),
                        }
                    )
                );
            }
        }
        return true;
    },

    async finalizeValidation() {
        const pos = this.pos;
        const order = this.order;
        const partner = order.getPartner();
        if (pos.edWalletEnabled && partner && !pos.edIsWalkIn(partner)) {
            const walletPaid = order.payment_ids
                .filter((p) => pos.edIsWalletMethod(p.payment_method_id))
                .reduce((total, p) => total + p.amount, 0);
            const topup = order.lines
                .filter((line) => pos.edIsTopupLine(line))
                .reduce((total, line) => total + line.priceIncl, 0);
            const known = pos.edWalletKnown(partner.id).balance !== 0;
            if (walletPaid || topup || known) {
                // as at the time of sale, before this order is recorded
                order.earlydryer_wallet_balance_after = order.currency.round(
                    pos.edWalletAvailable(partner) - walletPaid + topup
                );
            }
            // before printing and syncing: the cap stays right offline
            pos.edWalletRecord(order);
        }
        return super.finalizeValidation(...arguments);
    },
});
