const { DateTime } = luxon;

/**
 * Datetime fields of the 19 POS models are luxon DateTimes once loaded, but
 * plain "YYYY-MM-DD HH:MM:SS" UTC strings in the payloads of this module.
 */
export function toDateTime(value) {
    if (!value) {
        return null;
    }
    if (value instanceof DateTime) {
        return value;
    }
    const parsed = DateTime.fromSQL(String(value), { zone: "utc" });
    return parsed.isValid ? parsed : null;
}

export function formatLocal(value, format) {
    const date = toDateTime(value);
    return date ? date.setZone("local").toFormat(format) : "";
}
