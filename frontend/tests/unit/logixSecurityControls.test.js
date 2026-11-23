import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = new URL("../../src/components/Logix/", import.meta.url);
const read = (path) => readFileSync(new URL(path, src), "utf8");
const template = (sfc) => sfc.slice(sfc.indexOf("<template>"), sfc.indexOf("<script"));

describe("Logix script security controls", () => {
	it("opens the Security panel from a frappe-ui Button", () => {
		const canvas = template(read("LogixCanvas/LogixCanvas.vue"));
		const security = canvas.slice(canvas.lastIndexOf("<", canvas.indexOf('label="Security"')));
		expect(security.startsWith("<Button")).toBe(true);
		expect(canvas).not.toMatch(/<button[^>]*title="Security"/);
	});

	it("draws the panel's marks and close icon with Lucide, not hand-styled boxes or Feather", () => {
		const panel = template(read("LogixSecurityPanel/LogixSecurityPanel.vue"));
		expect(panel).not.toMatch(/<span class="lsp-check/);
		expect(panel).not.toMatch(/FeatherIcon|icon="x"/);
		expect(panel).toMatch(/<Icon icon="lucide:square-check" class="lsp-check lsp-check--on" \/>/);
		expect(panel).toMatch(/icon="lucide:x"/);
	});

	it("says an item is in the open request only when the request lists it", () => {
		const script = read("LogixSecurityPanel/LogixSecurityPanel.vue");
		expect(script).toMatch(/item\.in_open_request\s*\?/);
		expect(script).toMatch(/Not in \$\{open\}/);
		expect(script).not.toMatch(/\$\{props\.lint\.open_request\} is open/);
	});

	it("offers Update request for an open request still in review", () => {
		const panel = read("LogixSecurityPanel/LogixSecurityPanel.vue");
		expect(panel).toMatch(/v-if="updatable"[\s\S]*?label="Update request"/);
		expect(panel).toMatch(/latestRequest\.value\?\.can_update/);
		const composable = readFileSync(
			new URL("../../src/composables/Logix/useLogixScriptSecurity.js", import.meta.url),
			"utf8",
		);
		expect(composable).toMatch(/updating \? UPDATE_URL : REQUEST_URL/);
	});

	it("tells the author what to use instead in a full sentence", () => {
		const canvas = read("LogixCanvas/LogixCanvas.vue");
		expect(canvas).not.toMatch(/Instead: \$\{/);
		expect(canvas).toMatch(/Use \$\{alt\.charAt\(0\)\.toLowerCase\(\)\}/);
		expect(canvas).toMatch(/To keep \$\{name\}, request approval in Security\./);
	});
});
