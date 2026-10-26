/**
 * Port of earlydryer_tagging/models/earlydryer_tag_code.py: printed garment
 * tags are <prefix><7-digit number><Luhn check digit>. Keep both in step: the
 * JS unit test and tests/test_tag_code_vectors.py share the same vectors.
 */

export const NUMBER_DIGITS = 7;
export const MAX_NUMBER = 10 ** NUMBER_DIGITS - 1;
export const DEFAULT_PREPRINTED_PATTERN = "^[A-Z0-9]{4,16}$";

export function luhnCheckDigit(digits) {
    let total = 0;
    const reversed = String(digits).split("").reverse();
    reversed.forEach((char, position) => {
        let value = parseInt(char, 10);
        if (position % 2 === 0) {
            value *= 2;
            if (value > 9) {
                value -= 9;
            }
        }
        total += value;
    });
    return (10 - (total % 10)) % 10;
}

export function luhnIsValid(digits) {
    if (digits.length < 2 || !/^\d+$/.test(digits)) {
        return false;
    }
    return luhnCheckDigit(digits.slice(0, -1)) === parseInt(digits.slice(-1), 10);
}

export function normalizeCode(code) {
    return (code || "").trim().toUpperCase();
}

export function formatPrinted(prefix, number, checkDigit = true) {
    const body = String(number).padStart(NUMBER_DIGITS, "0");
    return checkDigit ? `${prefix}${body}${luhnCheckDigit(body)}` : `${prefix}${body}`;
}

/** [number, valid] of a printed code of ``prefix``, or null. */
export function parsePrinted(code, prefix, checkDigit = true) {
    code = normalizeCode(code);
    const tail = code.slice(prefix.length);
    const length = NUMBER_DIGITS + (checkDigit ? 1 : 0);
    if (!code.startsWith(prefix) || tail.length !== length || !/^\d+$/.test(tail)) {
        return null;
    }
    const valid = checkDigit ? luhnIsValid(tail) : true;
    return [parseInt(tail.slice(0, NUMBER_DIGITS), 10), valid];
}

export function isValidPrinted(code, prefix, checkDigit = true) {
    const parsed = parsePrinted(code, prefix || "", checkDigit);
    return Boolean(parsed && prefix && parsed[1]);
}

export function isValidPreprinted(code, pattern) {
    try {
        return new RegExp(pattern || DEFAULT_PREPRINTED_PATTERN).test(normalizeCode(code));
    } catch {
        return false;
    }
}
