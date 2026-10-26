/* global JsBarcode */

/**
 * Code128 barcode as an SVG data URL, rendered in the browser (offline) by
 * the bundled JsBarcode (static/lib/jsbarcode, MIT).
 */
export function code128DataUrl(value, { height = 60, width = 2, margin = 0 } = {}) {
    if (!value || typeof JsBarcode === "undefined") {
        return "";
    }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    try {
        JsBarcode(svg, value, {
            format: "CODE128",
            displayValue: false,
            height,
            width,
            margin,
        });
    } catch {
        return "";
    }
    const xml = new XMLSerializer().serializeToString(svg);
    return "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(xml)));
}
