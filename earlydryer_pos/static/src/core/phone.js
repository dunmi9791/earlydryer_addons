/**
 * Nigerian phone numbers in international form: "0803 123 4567",
 * "2348031234567" and "+234 803 123 4567" all give "+2348031234567".
 * Returns "" when the input cannot be a phone number.
 */
export function normalizeNigerianPhone(value) {
    let digits = (value || "").replace(/[\s\-().]/g, "");
    if (!digits) {
        return "";
    }
    if (digits.startsWith("+")) {
        digits = digits.slice(1);
    } else if (digits.startsWith("00")) {
        digits = digits.slice(2);
    } else if (digits.startsWith("0")) {
        digits = "234" + digits.slice(1);
    } else if (digits.length === 10) {
        // 803 123 4567 without the trunk 0
        digits = "234" + digits;
    }
    if (!/^\d{8,15}$/.test(digits)) {
        return "";
    }
    if (digits.startsWith("234") && digits.length !== 13) {
        return "";
    }
    return "+" + digits;
}

/** Digits only, to compare phones written in different ways. */
export function phoneDigits(value) {
    const normalized = normalizeNigerianPhone(value);
    return (normalized || value || "").replace(/\D/g, "");
}
