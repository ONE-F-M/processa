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
});
