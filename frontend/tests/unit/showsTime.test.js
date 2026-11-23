import { test } from "vitest"
import assert from "node:assert/strict"
import { formatTime, restoredItems, showsTime } from "@/utils/showsTime.js"

test("one reply shows its time once, under its last piece, and every message of yours keeps its own", () => {
	const items = [
		{ kind: "user", ts: "2026-11-23 11:38:05" },
		{ kind: "agent", ts: "2026-11-23 11:38:05" },
		{ kind: "choice", ts: "2026-11-23 11:38:05" },
		{ kind: "user", ts: "2026-11-23 11:40:00" },
		{ kind: "agent", ts: "2026-11-23 11:41:00" },
		{ kind: "routed" },
	]
	const shown = items.map((_item, i) => showsTime(items, i))
	assert.deepEqual(shown, [true, false, true, true, true, false])
})

test("a reply that runs into the next minute shows the time of each minute", () => {
	const items = [
		{ kind: "agent", ts: "2026-11-23 11:38:05" },
		{ kind: "custom", ts: "2026-11-23 11:39:10" },
	]
	assert.deepEqual(items.map((_item, i) => showsTime(items, i)), [true, true])
})

test("formatTime shows a valid time and nothing for a missing one", () => {
	assert.equal(formatTime("2026-11-23 11:38:00"), "Nov 23, 11:38 AM")
	assert.equal(formatTime("not a time"), "")
})

test("restored history keeps one timestamp per message so its pieces share a time", () => {
	const history = [
		{ role: "user", content: "hi", timestamp: "t1" },
		{
			role: "assistant", content: "Pick one", message: "m1", timestamp: "t2", notes: ["Looking"],
			events: [{ name: "onefm.choice", value: { options: ["Yes", "No"] } }],
		},
		{ role: "user", content: "Yes", timestamp: "t3" },
	]
	const items = restoredItems(history, true)

	assert.deepEqual(items.map((item) => [item.kind, item.ts]), [
		["user", "t1"], ["narration", "t2"], ["agent", "t2"], ["choice", "t2"], ["user", "t3"],
	])
	assert.equal(items[3].answered, "Yes")
	assert.equal(items[3].restored, true)
})
