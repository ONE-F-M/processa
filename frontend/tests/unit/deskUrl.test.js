import { test } from "vitest"
import assert from "node:assert/strict"

import { deskUrl } from "@/utils/deskUrl.js"

test("lower-cases the doctype and hyphenates spaces", () => {
	assert.equal(deskUrl("Work Item", "WI-000001"), "/app/work-item/WI-000001")
})

test("URL-encodes the record name", () => {
	assert.equal(
		deskUrl("BPMN Process Model", "My Map / v2"),
		"/app/bpmn-process-model/My%20Map%20%2F%20v2",
	)
})

test("a missing doctype yields an empty slug", () => {
	assert.equal(deskUrl(undefined, "X"), "/app//X")
})
