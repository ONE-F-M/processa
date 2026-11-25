import { beforeEach, describe, expect, it, vi } from "vitest";

const frappeRequest = vi.fn();

// The banner text is what the tests read, so the Button stub renders only its default slot.
vi.mock("frappe-ui", async () => {
	const { h } = await import("vue");
	return {
		Button: {
			setup:
				(_, { slots }) =>
				() =>
					h("button", slots.default?.()),
		},
		frappeRequest: (...args) => frappeRequest(...args),
	};
});
vi.mock("@iconify/vue", () => ({ Icon: { render: () => null } }));
vi.mock("@/composables/useCurrentUser", () => ({
	useCurrentUser: () => ({ currentRoles: globalThis.__roles }),
}));

const { createSSRApp, ref } = await import("vue");
const { renderToString } = await import("vue/server-renderer");
const Banner = (
	await import("../../src/components/Instances/InstancePausedAgentBanner/InstancePausedAgentBanner.vue")
).default;
const { useInstanceControl } = await import("../../src/composables/useInstanceControl.js");

const SANDBOX_WAIT = {
	agent_run: "run1",
	waits_on: "agent_sandbox",
	wait_label: "checkout_pr_head for processa@version-15 (session)",
	suspended_at: "2026-11-25 13:27:08.287175",
	answered_at: "2026-11-25 13:27:07.140807",
	stuck: true,
};

async function render(agents) {
	return renderToString(createSSRApp(Banner, { instanceName: "inst1", agents }));
}

describe("the paused agent banner", () => {
	beforeEach(() => {
		globalThis.__roles = ref(["Process Owner"]);
	});

	it("says what the agent waits for and since when", async () => {
		const html = await render([{ ...SANDBOX_WAIT, stuck: false, answered_at: null }]);
		expect(html).toContain("AI agent paused");
		expect(html).toContain("checkout_pr_head for processa@version-15 (session)");
		expect(html).toContain("since 13:27");
		expect(html).not.toContain("Resume agent");
	});

	it("offers Resume agent when the answer arrived and the agent was not woken", async () => {
		const html = await render([SANDBOX_WAIT]);
		expect(html).toContain("The answer arrived at 13:27 but the agent was not woken.");
		expect(html).toContain("Resume agent");
	});

	it("names a delegation as another agent", async () => {
		const html = await render([{ ...SANDBOX_WAIT, waits_on: "a2a", wait_label: "Ask the Dev Agent" }]);
		expect(html).toContain("another agent (Ask the Dev Agent)");
	});

	it("hides Resume agent from a user without a recovery role", async () => {
		globalThis.__roles = ref(["Employee"]);
		const html = await render([SANDBOX_WAIT]);
		expect(html).toContain("The answer arrived at 13:27");
		expect(html).not.toContain("Resume agent");
	});
});

describe("useInstanceControl", () => {
	it("sends the extra parameters a control needs", async () => {
		frappeRequest.mockResolvedValueOnce({ resumed_with: "sb1" });
		const { runControl } = useInstanceControl();
		await runControl("resume_suspended_agent", "inst1", "", { agent_run: "run1" });
		expect(frappeRequest).toHaveBeenCalledWith({
			url: "/api/method/processa.api.instances.resume_suspended_agent",
			method: "POST",
			params: { instance_name: "inst1", reason: "", agent_run: "run1" },
		});
	});
});
