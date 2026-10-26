import { registry } from "@web/core/registry";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as NumberPopup from "@point_of_sale/../tests/generic_helpers/number_popup_util";
import * as OfflineUtil from "@point_of_sale/../tests/generic_helpers/offline_util";
import * as PosHr from "@pos_hr/../tests/tours/utils/pos_hr_helpers";
import { refresh } from "@point_of_sale/../tests/generic_helpers/utils";

const click = (trigger, content) => ({
    content: content || `click ${trigger}`,
    trigger,
    run: "click",
});
const fill = (trigger, value) => ({
    content: `fill ${trigger}`,
    trigger,
    run: `edit ${value}`,
});
const see = (trigger, content) => ({ content: content || `check ${trigger}`, trigger });

function open(cashier = "T Front Desk", pin = "1234") {
    return [PosHr.login(cashier, pin), Dialog.confirm("Open Register")].flat();
}

function chooseCustomer(name) {
    return [
        click(".ed-customer-button"),
        fill(".ed-customer-query", name),
        click(`.ed-customer-results button:contains("${name}")`),
        see(`.ed-customer-button:contains("${name}")`),
    ];
}

function addGarment(categoryCode, serviceCode) {
    return [
        click(`.ed-garment[data-code="${categoryCode}"]`),
        click(`.ed-service[data-code="${serviceCode}"]`),
        see(".ed-line-details"),
    ];
}

registry.category("web_tour.tours").add("earlydryer_pos_intake", {
    steps: () =>
        [
            open(),
            chooseCustomer("T Customer"),
            addGarment("TSUIT", "TDC"),
            click('.ed-surcharge-chip[data-code="TBEAD"]'),
            fill(".ed-colour", "Navy"),
            click('.ed-condition-chip:contains("stain")'),
            click(".ed-details-apply"),
            click(".ed-express-toggle"),
            see('.orderline:contains("Express")'),
            see('.orderline:contains("T Beads")'),
            click(".pay-order-button"),
            PaymentScreen.clickPaymentMethod("T Cash"),
            PaymentScreen.enterPaymentLineAmount("T Cash", "1000"),
            PaymentScreen.clickPaymentMethod("T Customer Account"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.receiptIsThere(),
            see(".ed-receipt-customer:contains('T Customer')"),
            see(".ed-tags"),
            see(".ed-balance-due"),
            see(".ed-receipt-promise"),
        ].flat(),
});

registry.category("web_tour.tours").add("earlydryer_pos_walk_in_refused", {
    steps: () =>
        [
            open(),
            click('.ed-garment[data-code="TSHIRT"]'),
            click('.ed-service[data-code="TWI"]'),
            // the customer dialog opens first; cancelling refuses the line
            see(".ed-customer-query"),
            click(".modal-footer .btn-secondary:contains('Cancel')"),
            see(".modal:contains('Customer required')"),
            Dialog.confirm(),
            see(".product-screen:not(:has(.orderline))"),
        ].flat(),
});

registry.category("web_tour.tours").add("earlydryer_pos_discount_pin", {
    steps: () =>
        [
            open(),
            chooseCustomer("T Customer"),
            addGarment("TSHIRT", "TWI"),
            click(".ed-details-apply"),
            click(".ed-order-discount"),
            NumberPopup.enterValue("15"),
            Dialog.confirm(),
            see(".modal:contains('needs approval')"),
            NumberPopup.enterValue("9876"),
            Dialog.confirm(),
            see(".orderline:contains('15%')"),
        ].flat(),
});

registry.category("web_tour.tours").add("earlydryer_pos_collection", {
    steps: () =>
        [
            open(),
            click(".ed-collect-button"),
            fill(".ed-collect-query", "T Customer"),
            click(".ed-collect-search"),
            see(".ed-shelf:contains('A-01')"),
            click(".ed-release"),
            see(".ed-collect-query"),
        ].flat(),
});

registry.category("web_tour.tours").add("earlydryer_pos_offline_intake", {
    steps: () =>
        [
            open(),
            OfflineUtil.setOfflineMode(),
            refresh(),
            Dialog.confirm("Continue with limited functionality"),
            chooseCustomer("T Customer"),
            addGarment("TSHIRT", "TWI"),
            click(".ed-details-apply"),
            click(".pay-order-button"),
            PaymentScreen.clickPaymentMethod("T Cash"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.receiptIsThere(),
            see(".ed-tags"),
            OfflineUtil.setOnlineMode(),
            ReceiptScreen.clickNextOrder(),
        ].flat(),
});
