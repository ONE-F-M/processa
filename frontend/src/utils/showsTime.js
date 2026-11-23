// Copyright (c) 2026, one-fm and contributors
// Transcript times: when a piece shows its time, how a time is stamped and shown, and restored history.

import { dayjs } from "@/dayjs";

// True when the transcript item at index shows its time; format is how a time is shown.
export function showsTime(items, index, format) {
	const item = items[index];
	const next = items[index + 1];
	if (!item.ts) return false;
	return !next || item.kind === "user" || next.kind === "user" || format(next.ts) !== format(item.ts);
}

export function stampNow() {
	return new Date();
}

export function formatTime(ts) {
	const t = dayjs(ts);
	return t.isValid() ? t.short() : "";
}

export function restoredItems(history, isNewestPage) {
	const out = [];
	history.forEach((m, index) => {
		if (m.role === "user") {
			out.push({ kind: "user", text: m.content, ts: m.timestamp });
			return;
		}
		// a stored rate-limit refusal carries role "system" —
		// restore it as a system notice, same as when it first streamed.
		if (m.role === "system") {
			if (m.content) out.push({ kind: "system", text: m.content, ts: m.timestamp });
			return;
		}
		for (const note of m.notes || []) {
			out.push({ kind: "narration", text: note, ts: m.timestamp });
		}
		if (m.content) {
			out.push({ kind: "agent", text: m.content, message: m.message || "", ts: m.timestamp });
		}
		const isLastOfPage = index === history.length - 1;
		for (const event of m.events || []) {
			const value = event.value || {};
			if (event.name === "onefm.choice") {
				out.push({
					kind: "choice",
					value,
					// What the user said next, when it was one of the options —
					// so a reopened conversation shows which way it went.
					answered: answeredWith(history, index, value.options || []),
					restored: !(isNewestPage && isLastOfPage),
					ts: m.timestamp,
				});
			} else {
				out.push({
					kind: "custom",
					name: event.name,
					value,
					doneAction: "restored",
					restored: true,
					ts: m.timestamp,
				});
			}
		}
	});
	return out;
}

function answeredWith(history, index, options) {
	const next = history[index + 1];
	if (!next || next.role !== "user") return "";
	const said = (next.content || "").trim();
	return options.find((opt) => opt === said) || "";
}
