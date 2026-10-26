import { describe, expect, test } from "@odoo/hoot";
import {
    formatPrinted,
    isValidPreprinted,
    isValidPrinted,
    luhnCheckDigit,
    luhnIsValid,
    parsePrinted,
} from "@earlydryer_pos/core/tag_code";
import { normalizeNigerianPhone } from "@earlydryer_pos/core/phone";

// Same vectors as tests/test_tag_code_vectors.py (the server helper)
const VECTORS = [
    ["P1", 1, true, "P100000018"],
    ["TP1", 1234567, true, "TP112345674"],
    ["P1", 42, false, "P10000042"],
    ["ED2", 9999999, true, "ED299999997"],
    ["P2", 500, true, "P200005009"],
];

describe.current.tags("headless");

describe("earlydryer tag codes", () => {
    test("luhn", () => {
        expect(luhnCheckDigit("7992739871")).toBe(3);
        expect(luhnIsValid("79927398713")).toBe(true);
        expect(luhnIsValid("79927398710")).toBe(false);
    });

    test("vectors shared with the server", () => {
        for (const [prefix, number, checkDigit, code] of VECTORS) {
            expect(formatPrinted(prefix, number, checkDigit)).toBe(code);
            expect(parsePrinted(code, prefix, checkDigit)).toEqual([number, true]);
        }
        expect(parsePrinted("P10000001X", "P1")).toBe(null);
        expect(parsePrinted("P100000017", "P1")).toEqual([1, false]);
        expect(isValidPrinted("p100000018", "P1")).toBe(true);
        expect(isValidPreprinted("ED200001", "^ED2[0-9]{5}$")).toBe(true);
        expect(isValidPreprinted("XX1", "^ED2[0-9]{5}$")).toBe(false);
    });

    test("nigerian phones", () => {
        expect(normalizeNigerianPhone("0803 123 4567")).toBe("+2348031234567");
        expect(normalizeNigerianPhone("+234 803-123-4567")).toBe("+2348031234567");
        expect(normalizeNigerianPhone("12")).toBe("");
    });
});
