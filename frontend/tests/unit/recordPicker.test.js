import { test, vi } from "vitest";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import {
	canCreateRecord,
	isMissing,
	joinValues,
	splitValues,
	toOptions,
	valuesOf,
} from "@/utils/recordPicker.js";

vi.mock("frappe-ui", () => ({
	createResource: () => ({ fetch: async () => [] }),
	// Stands in for the Headless UI combobox: the test replays what it emits.
	Autocomplete: {
		setup(_, { emit }) {
			globalThis.__autocompleteEmit = emit;
			return () => null;
		},
	},
	Button: { render: () => null },
	FeatherIcon: { render: () => null },
}));
vi.mock("vue-router", () => ({ onBeforeRouteLeave: () => {} }));

const SRC = path.resolve(import.meta.dirname, "../../src");

function sourceFiles(dir) {
	return readdirSync(dir).flatMap((name) => {
		const full = path.join(dir, name);
		return statSync(full).isDirectory() ? sourceFiles(full) : [full];
	});
}

test("toOptions: maps rows by valueField and drops rows without a value", () => {
	const rows = [{ name: "A", title: "Alpha" }, { name: "" }, { id: "x", name: "B" }];
	assert.deepEqual(
		toOptions(rows, "name", (r) => r.title || r.name).map((o) => [o.value, o.label]),
		[
			["A", "Alpha"],
			["B", "B"],
		],
	);
});

test("multiple values round-trip through the comma-separated attribute", () => {
	assert.deepEqual(splitValues("a, b,,c"), ["a", "b", "c"]);
	assert.deepEqual(splitValues(""), []);
	assert.equal(joinValues(["a", "b"]), "a,b");
});

test("valuesOf: accepts options, plain values and empty selections", () => {
	assert.deepEqual(valuesOf([{ value: "a" }, "b"]), ["a", "b"]);
	assert.deepEqual(valuesOf({ value: "a" }), ["a"]);
	assert.deepEqual(valuesOf(null), []);
});

test("canCreateRecord: only a non-empty name that matches no option", () => {
	const options = [{ value: "Draft" }];
	assert.equal(canCreateRecord("draft", options), false);
	assert.equal(canCreateRecord("  ", options), false);
	assert.equal(canCreateRecord("Review", options), true);
});

test("isMissing: flags a value absent from a loaded list", () => {
	assert.equal(isMissing("Gone", [{ value: "Draft" }]), true);
	assert.equal(isMissing("Draft", [{ value: "Draft" }]), false);
	assert.equal(isMissing("Gone", []), false);
});

test("the three old pickers are gone and nothing imports them", () => {
	for (const name of ["FrappeAutocomplete", "FrappeMultiSelect", "RecordCombobox"]) {
		assert.equal(existsSync(path.join(SRC, "bpmn/shared", `${name}.js`)), false);
		for (const file of sourceFiles(SRC)) {
			assert.equal(
				readFileSync(file, "utf8").includes(name),
				false,
				`${file} still mentions ${name}`,
			);
		}
	}
});

test("a server-searched single picker keeps typed text until it closes, not on every keystroke", async () => {
	const { RecordPickerField } = await import("@/bpmn/shared/RecordPickerField.js");
	const freeText = (props) =>
		RecordPickerField.prototype.pickerProps.call({ props: { onChange() {}, ...props } }).allowFreeText;
	const search = async () => [];
	assert.equal(freeText({ fetchApi: search }), "blur");
	assert.equal(freeText({ fetchApi: search, multiple: true }), "");
	assert.equal(freeText({ loadOptions: search, keepTyped: true }), "blur");
	assert.equal(freeText({ loadOptions: search }), "");
});

async function mountPicker(props) {
	const { createRenderer } = await import("vue");
	const RecordPicker = (await import("@/components/Controls/RecordPicker/RecordPicker.vue")).default;
	const node = (tag) => ({ tag, children: [], addEventListener() {}, removeEventListener() {} });
	const { createApp } = createRenderer({
		createElement: node,
		createText: (text) => ({ text }),
		createComment: (text) => ({ comment: text }),
		setText() {},
		setElementText() {},
		insert: (child, parent) => (child.parent = parent),
		remove() {},
		parentNode: (child) => child.parent || null,
		nextSibling: () => null,
		patchProp() {},
	});
	const saved = [];
	createApp(RecordPicker, { ...props, "onUpdate:modelValue": (value) => saved.push(value) }).mount({});
	return { saved, emit: globalThis.__autocompleteEmit };
}

test("closing a picker by moving focus away keeps the typed text, not the highlighted option", async () => {
	vi.useFakeTimers();
	const listeners = {};
	vi.stubGlobal("document", {
		addEventListener: (type, handler) => (listeners[type] = handler),
		removeEventListener() {},
		querySelector: () => null,
	});
	try {
		const { saved, emit } = await mountPicker({ modelValue: "Sales Order", allowFreeText: "blur" });
		emit("update:query", "Stock Entr");
		// Headless UI on blur: it picks the highlighted option, then empties its search text.
		listeners.blur({ target: { closest: () => ({}) } });
		emit("update:modelValue", { label: "Stock Entry", value: "Stock Entry" });
		emit("update:query", "");
		await vi.advanceTimersByTimeAsync(200);
		assert.deepEqual(saved, ["Stock Entr"]);

		emit("update:modelValue", { label: "Sales Invoice", value: "Sales Invoice" });
		assert.deepEqual(saved, ["Stock Entr", "Sales Invoice"]);
	} finally {
		vi.unstubAllGlobals();
		vi.useRealTimers();
	}
});

test("auto-save waits while the person types in a picker's search box", async () => {
	const { useProcessSave } = await import("@/composables/Process/useProcessSave.js");
	const pc = {};
	useProcessSave(pc);
	const focusedIn = (classes) => ({
		tagName: "INPUT",
		closest: (selector) => selector.split(",").some((s) => classes.includes(s.trim().slice(1))),
	});
	try {
		vi.stubGlobal("document", { activeElement: focusedIn(["record-picker-body"]) });
		assert.equal(pc.isEditingShapeProperties(), true);
		vi.stubGlobal("document", { activeElement: focusedIn(["canvas"]) });
		assert.equal(pc.isEditingShapeProperties(), false);
	} finally {
		vi.unstubAllGlobals();
	}
});
