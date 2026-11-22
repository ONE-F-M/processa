// Copyright (c) 2026, one-fm and contributors
// The pieces of one reply share a time, so it shows once, under the last piece.

/**
 * True when the transcript item at index shows its time.
 *
 * @param {Array<{kind: string, ts?: *}>} items  the transcript
 * @param {number} index
 * @param {(ts: *) => string} format  how a time is shown
 */
export function showsTime(items, index, format) {
	const item = items[index];
	const next = items[index + 1];
	if (!item.ts) return false;
	return !next || item.kind === "user" || next.kind === "user" || format(next.ts) !== format(item.ts);
}
