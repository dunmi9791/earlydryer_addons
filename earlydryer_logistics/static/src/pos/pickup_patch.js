import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";

/**
 * "Price in POS" of a pickup opens the till with ?earlydryer_pickup_stop=<id>:
 * a new order is started for the customer, linked to the pickup
 * (earlydryer_pickup_stop_id, synced with the order) and the pickup's fee
 * is added when it was not charged yet. The laundry job created when the
 * order syncs links back to the pickup on the server.
 */
patch(PosStore.prototype, {
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        const params = new URLSearchParams(window.location.search);
        const stopId = Number(params.get("earlydryer_pickup_stop"));
        if (stopId) {
            params.delete("earlydryer_pickup_stop");
            const query = params.toString();
            window.history.replaceState(
                {},
                "",
                window.location.pathname + (query ? `?${query}` : "")
            );
            try {
                await this.edStartPickupOrder(stopId);
            } catch (error) {
                console.warn("Pickup intake not started", error);
                this.notification.add(_t("The pickup could not be loaded."), { type: "danger" });
            }
        }
    },

    async edStartPickupOrder(stopId) {
        const info = await this.data.call("earlydryer.logistics.stop", "earlydryer_pos_pickup_info", [
            stopId,
            this.config.id,
        ]);
        if (!info.ok) {
            this.notification.add(info.message, { type: "warning" });
            return;
        }
        let partner = this.models["res.partner"].get(info.partner_id);
        if (!partner) {
            [partner] = await this.data.read("res.partner", [info.partner_id]);
        }
        const order = this.addNewOrder();
        if (partner) {
            this.setPartnerToCurrentOrder(partner);
        }
        order.earlydryer_pickup_stop_id = info.stop_id;
        order.earlydryer_fulfilment = info.fulfilment;
        if (info.customer_note) {
            order.earlydryer_customer_note = info.customer_note;
        }
        for (const fee of info.fee_lines) {
            const product = this.models["product.product"].get(fee.product_id);
            if (!product) {
                this.notification.add(_t("Fee product not on this till: add the fee by hand."), {
                    type: "warning",
                });
                continue;
            }
            await this.addLineToOrder(
                {
                    product_tmpl_id: product.product_tmpl_id,
                    product_id: product,
                    price_unit: fee.amount,
                    qty: 1,
                    full_product_name: fee.label,
                },
                order,
                { merge: false, edInternal: true },
                false
            );
        }
        this.notification.add(
            _t("Pickup %s: %s bag(s). Count and price the garments.", info.stop_name, info.bag_count),
            { type: "info" }
        );
    },
});
