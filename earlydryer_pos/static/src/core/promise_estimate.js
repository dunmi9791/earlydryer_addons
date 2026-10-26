/**
 * Offline estimate of the promised ready time: the turnaround counted in the
 * plant's working hours (resource calendar attendances, minus public
 * holidays), like earlydryer.catalog.promised_datetime on the server. The
 * server recomputes the real promise when the order syncs.
 */

const { DateTime } = luxon;

function attendancesOf(calendar, day) {
    // luxon weekday 1 = Monday; Odoo dayofweek 0 = Monday
    const dayofweek = day.weekday - 1;
    let attendances = calendar.attendances.filter((a) => a.dayofweek === dayofweek);
    if (calendar.two_weeks) {
        // Odoo: week_type 0/1 alternates on the ISO week number parity
        const weekType = String(Math.floor(day.weekNumber % 2));
        attendances = attendances.filter((a) => !a.week_type || a.week_type === weekType);
    }
    return attendances.sort((a, b) => a.hour_from - b.hour_from);
}

function leaveIntervals(calendar) {
    return (calendar.leaves || []).map(([from, to]) => [
        DateTime.fromSQL(from, { zone: "utc" }),
        DateTime.fromSQL(to, { zone: "utc" }),
    ]);
}

/** Working intervals of ``day`` (plant time zone) minus the leaves. */
function workIntervals(calendar, day, leaves) {
    const intervals = [];
    for (const attendance of attendancesOf(calendar, day)) {
        let start = day.startOf("day").plus({ minutes: Math.round(attendance.hour_from * 60) });
        const end = day.startOf("day").plus({ minutes: Math.round(attendance.hour_to * 60) });
        let pieces = [[start, end]];
        for (const [leaveFrom, leaveTo] of leaves) {
            const next = [];
            for (const [from, to] of pieces) {
                if (leaveTo <= from || leaveFrom >= to) {
                    next.push([from, to]);
                    continue;
                }
                if (leaveFrom > from) {
                    next.push([from, leaveFrom]);
                }
                if (leaveTo < to) {
                    next.push([leaveTo, to]);
                }
            }
            pieces = next;
        }
        intervals.push(...pieces);
        start = end;
    }
    return intervals;
}

/**
 * @param {Object|false} calendar payload of pos.config._earlydryer_calendar_data
 * @param {DateTime} start luxon DateTime
 * @param {number} hours working hours to add
 * @returns {DateTime} (UTC)
 */
export function addWorkingHours(calendar, start, hours) {
    if (!calendar || !calendar.attendances?.length) {
        return start.plus({ hours });
    }
    const leaves = leaveIntervals(calendar);
    let current = start.setZone(calendar.tz || "UTC");
    let remaining = hours * 60;
    if (remaining <= 0) {
        return current.toUTC();
    }
    // 3 years of days at most: a calendar always has working days
    for (let i = 0; i < 1100; i++) {
        const day = current.startOf("day");
        for (const [from, to] of workIntervals(calendar, day, leaves)) {
            const begin = from < current ? current : from;
            if (to <= begin) {
                continue;
            }
            const available = to.diff(begin, "minutes").minutes;
            if (available >= remaining) {
                return begin.plus({ minutes: remaining }).toUTC();
            }
            remaining -= available;
        }
        current = day.plus({ days: 1 });
    }
    return start.plus({ hours });
}

/** Latest promise among ``hoursList`` from ``start``. */
export function estimatePromise(calendar, start, hoursList) {
    let latest = null;
    for (const hours of new Set(hoursList)) {
        const end = addWorkingHours(calendar, start, hours);
        if (!latest || end > latest) {
            latest = end;
        }
    }
    return latest;
}
