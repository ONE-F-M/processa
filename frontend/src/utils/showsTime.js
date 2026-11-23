// Copyright (c) 2026, one-fm and contributors
// Transcript times: when a piece shows its time, how a time is stamped and shown, and restored history.

import { dayjs } from "@/dayjs";

// True when the transcript item at index shows its time: the last piece of a reply in that minute.
export function showsTime(items, index) {
	const item = items[index];
	const next = items[index + 1];
	if (!item.ts) return false;
	if (!next?.ts || item.kind === "user" || next.kind === "user") return true;
	return formatTime(next.ts) !== formatTime(item.ts);
}

// Live entries take the client clock; restored entries keep the stored creation time as-is.
export function stampNow() {
	return new Date();
}

export function formatTime(ts) {
	const t = dayjs(ts);
	return t.isValid() ? t.short() : "";
}

// Stored turns as transcript items; restored cards are concluded, the newest reply's options stay live.
export function restoredItems(history, isNewestPage) {
	const out = [];
	history.forEach((m, index) => {
		if (m.role === "user") {
			out.push({ kind: "user", text: m.content, ts: m.timestamp });
			return;
		}
		// A stored rate-limit refusal carries role "system"; restore it as a system notice.
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
					// What the user said next when it was one of the options, so a reopened chat shows the answer.
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
