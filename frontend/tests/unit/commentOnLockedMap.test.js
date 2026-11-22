import { ref } from "vue";
import { describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));
// The popover is positioned on the next tick, which needs a DOM this suite does not have.
vi.mock("vue", async (original) => ({ ...(await original()), nextTick: vi.fn() }));

import { useEditorInlineComment } from "@/composables/Editor/useEditorInlineComment";

function editor(props) {
	const refs = [
		"timelineText", "activeCommentElement", "commentFormData", "showInlineCommentPopover",
		"inlineCommentPopoverEl", "inlineCommentFormData", "inlineMentionedUsers", "inlineCommentElement",
		"inlineCommentOverlayTarget", "timelineAssignedTo", "timelineIsTask", "timelineMentionedUsers",
		"userSearchQuery", "showUserDropdown", "showMentionDropdown", "activeMentionContext",
		"mentionSearchQuery", "mentionStartIndex",
	];
	const ed = Object.fromEntries(refs.map((name) => [name, ref(null)]));
	ed.showInlineCommentPopover.value = false;
	ed.props = props;
	ed.modeler = { get: () => ({ remove: vi.fn(), add: vi.fn() }) };
	ed.onReady = vi.fn();
	return ed;
}

describe("commenting on a locked map", () => {
	it("opens the inline comment on a read-only map when commenting is allowed", () => {
		const ed = editor({ readonly: true, commentsAllowed: true });
		useEditorInlineComment(ed);
		ed.openInlineComment({ id: "Task_1" });
		expect(ed.showInlineCommentPopover.value).toBe(true);
	});

	it("keeps it shut while a historical version is shown", () => {
		const ed = editor({ readonly: true, commentsAllowed: false });
		useEditorInlineComment(ed);
		ed.openInlineComment({ id: "Task_1" });
		expect(ed.showInlineCommentPopover.value).toBe(false);
	});
});
