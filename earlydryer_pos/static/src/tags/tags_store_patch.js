import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { labelsHtml, orderLabels, printHtml } from "@earlydryer_pos/tags/tag_print";

patch(PosStore.prototype, {
    /**
     * Printed mode: give every piece needing a tag its code from the till's
     * ranges, before printing. Without enough numbers the pieces stay blank,
     * "to tag at the counter".
     */
    edAssignTagCodes(order) {
        if (this.edBranch.tag_mode !== "printed") {
            return true;
        }
        let missing = false;
        for (const line of order.edGarmentLines.filter((l) => l.edNeedsTags)) {
            const have = line.edTagCodes;
            const needed = line.edPieceCount - have.length;
            if (needed <= 0) {
                continue;
            }
            const codes = this.edTakeTagCodes(needed);
            if (!codes) {
                missing = true;
                continue;
            }
            line.earlydryer_tag_codes = [...have, ...codes].join(",");
        }
        if (missing) {
            this.notification.add(
                _t("No tag numbers left on this till: tag these garments at the counter."),
                { type: "warning", sticky: true }
            );
        }
        return !missing;
    },

    async edPrintTags(order) {
        const labels = orderLabels(this, order);
        if (!labels.length) {
            return false;
        }
        const html = labelsHtml(
            labels,
            this.config.earlydryer_label_width_mm,
            this.config.earlydryer_label_height_mm
        );
        return printHtml(html);
    },
});
