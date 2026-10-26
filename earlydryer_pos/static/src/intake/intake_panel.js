import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { formatCurrency } from "@web/core/currency";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";

/** Laundry counter: customer, garment grid, services, order options. */
export class EdIntakePanel extends Component {
    static template = "earlydryer_pos.EdIntakePanel";
    static props = {};

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.state = useState({ categoryId: false });
    }

    get order() {
        return this.pos.getOrder();
    }
    get categories() {
        return this.pos.edCategories();
    }
    get category() {
        return this.categories.find((c) => c.id === this.state.categoryId) || false;
    }
    get services() {
        return this.category ? this.pos.edServicesFor(this.category) : [];
    }
    priceOf(product) {
        return formatCurrency(
            this.pos.edPrice(product, this.order),
            this.pos.config.currency_id.id
        );
    }
    get selectedGarment() {
        const line = this.order?.getSelectedOrderline();
        return line?.edIsGarment ? line : line?.edParentLine || false;
    }

    async addService(product) {
        await this.pos.edAddGarment(product, this.order);
        this.state.categoryId = false;
    }

    async orderDiscount() {
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Discount on the whole order (%)"),
            startingValue: 0,
        });
        if (value !== undefined && value !== null && value !== "") {
            await this.pos.edSetOrderDiscount(
                this.order,
                Math.min(Math.max(parseFloat(value) || 0, 0), 100)
            );
        }
    }

    async editNote() {
        const note = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Customer instructions"),
            startingValue: this.order.earlydryer_customer_note || "",
            placeholder: _t('e.g. "no starch"'),
            rows: 3,
        });
        if (note !== undefined) {
            this.order.earlydryer_customer_note = note;
        }
    }
}
