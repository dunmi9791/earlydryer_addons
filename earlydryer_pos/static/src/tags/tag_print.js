import { _t } from "@web/core/l10n/translation";
import { escape } from "@web/core/utils/strings";
import { code128DataUrl } from "@earlydryer_pos/receipt/barcode";
import { formatLocal } from "@earlydryer_pos/core/dates";

/** "Adaeze O." like the tagging module's labels (never the phone). */
export function customerShortName(name) {
    name = (name || "").trim();
    const parts = name.split(/\s+/);
    if (parts.length <= 1) {
        return name.slice(0, 20);
    }
    return `${parts[0].slice(0, 16)} ${parts.at(-1)[0].toUpperCase()}.`;
}

/** One label per piece of the order's garments (tagging module layout). */
export function orderLabels(pos, order) {
    const customer = order.earlydryer_new_partner_name || order.getPartner()?.name || "";
    const promise = formatLocal(order.earlydryer_promised_estimate, "dd/MM HH:mm");
    const labels = [];
    for (const line of order.edGarmentLines) {
        if (!line.edNeedsTags) {
            continue;
        }
        const pieces = line.edCategory?.piece_count || 1;
        const codes = line.edTagCodes;
        let index = 0;
        for (let unit = 0; unit < Math.round(line.qty); unit++) {
            for (let piece = 1; piece <= pieces; piece++) {
                labels.push({
                    code: codes[index] || "",
                    job: order.pos_reference || order.name || "",
                    customer: customerShortName(customer),
                    garment: line.edCategory?.name || "",
                    service: line.edService?.code || "",
                    piece: pieces > 1 ? `${piece}/${pieces}` : "",
                    express: order.earlydryer_express ? _t("EXPRESS") : "",
                    promised: promise,
                });
                index++;
            }
        }
    }
    return labels;
}

export function labelsHtml(labels, widthMm, heightMm) {
    const w = widthMm || 50;
    const h = (heightMm || 25) - 0.5;
    const body = labels
        .map((label) => {
            const barcode = label.code ? code128DataUrl(label.code, { height: 50, width: 2 }) : "";
            return `<div class="ed-label">
                <div class="row"><b>${escape(label.job)}</b> ${escape(label.piece)}
                    ${label.express ? `<span class="badge">${escape(label.express)}</span>` : ""}</div>
                ${barcode ? `<img class="bc" src="${barcode}"/>` : `<div class="notag">${escape(_t("TO TAG AT THE COUNTER"))}</div>`}
                <div class="row code">${escape(label.code)}</div>
                <div class="row small">${escape(label.garment)} · <b>${escape(label.service)}</b> · ${escape(label.customer)}</div>
                ${label.promised ? `<div class="row tiny">${escape(_t("Due"))} ${escape(label.promised)}</div>` : ""}
            </div>`;
        })
        .join("");
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/><style>
        @page { size: ${w}mm ${h + 0.5}mm; margin: 0; }
        html, body { margin: 0; padding: 0; }
        .ed-label { box-sizing: border-box; width: ${w}mm; height: ${h}mm; padding: 1mm 2mm;
            overflow: hidden; page-break-after: always; font-family: Arial, sans-serif; color: #000; line-height: 1.1; }
        .ed-label:last-child { page-break-after: auto; }
        .row { white-space: nowrap; overflow: hidden; font-size: 7pt; }
        .code { font-family: "Courier New", monospace; font-weight: bold; font-size: 10pt; text-align: center; }
        .small { font-size: 6.5pt; } .tiny { font-size: 6pt; }
        .badge { float: right; background: #000; color: #fff; font-weight: bold; padding: 0 0.8mm; }
        .bc { display: block; width: ${w - 4}mm; height: ${Math.round(h * 0.36 * 10) / 10}mm; margin-top: 0.5mm; }
        .notag { font-weight: bold; text-align: center; padding: 2mm 0; font-size: 8pt; }
    </style></head><body>${body}</body></html>`;
}

/** Print through the browser (the PC's label printer driver), offline too. */
export function printHtml(html) {
    return new Promise((resolve) => {
        const iframe = document.createElement("iframe");
        iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
        document.body.appendChild(iframe);
        const doc = iframe.contentWindow.document;
        doc.open();
        doc.write(html);
        doc.close();
        const done = () => {
            setTimeout(() => iframe.remove(), 1000);
            resolve(true);
        };
        const images = [...doc.images];
        Promise.all(
            images.map((img) =>
                img.complete
                    ? null
                    : new Promise((r) => {
                          img.onload = r;
                          img.onerror = r;
                      })
            )
        ).then(() => {
            iframe.contentWindow.focus();
            iframe.contentWindow.print();
            done();
        });
    });
}
