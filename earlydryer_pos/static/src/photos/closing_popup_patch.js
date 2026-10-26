import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(ClosePosPopup.prototype, {
    async confirm() {
        if (this.pos.edEnabled) {
            await this.pos.edBackground(false);
            const photos = this.pos.edState.photosPending;
            const collections = this.pos.edState.collectionQueue.length;
            if (photos || collections) {
                const confirmed = await ask(this.dialog, {
                    title: _t("Not everything is uploaded"),
                    body: _t(
                        "%(photos)s photo(s) and %(collections)s collection(s) are still on this device. " +
                            "They upload when the till is online again; do not clear this browser. Close anyway?",
                        { photos, collections }
                    ),
                    confirmLabel: _t("Close anyway"),
                });
                if (!confirmed) {
                    return;
                }
            }
        }
        return super.confirm(...arguments);
    },
});
