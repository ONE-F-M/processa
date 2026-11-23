import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("frappe-ui", () => ({ frappeRequest: vi.fn() }));
// Refocus and scroll run on the next tick, which needs a DOM this suite does not have.
vi.mock("vue", async (original) => ({ ...(await original()), nextTick: vi.fn() }));

import { frappeRequest } from "frappe-ui";
import { useEditorTimeline } from "@/composables/Editor/useEditorTimeline";
import { useEditorInlineComment } from "@/composables/Editor/useEditorInlineComment";

const USERS = [
	{ name: "ann@example.com", full_name: "Ann Lee" },
	{ name: "anna@example.com", full_name: "Anna Cole" },
];

function editor() {
	const refs = [
		"comments", "timelineText", "timelineFilterMode", "timelineTaskFilter", "timelineAssignedFilter",
		"activeCommentElement", "commentFormData", "users", "showInlineCommentPopover",
		"inlineCommentPopoverEl", "inlineCommentFormData", "inlineMentionedUsers", "inlineCommentElement",
		"inlineCommentOverlayTarget", "timelineAssignedTo", "timelineIsTask", "timelineMentionedUsers",
		"userSearchQuery", "showUserDropdown", "showMentionDropdown", "activeMentionContext",
		"mentionSearchQuery", "mentionStartIndex", "activeMentionIndex", "commentError", "selectedElements",
	];
	const ed = Object.fromEntries(refs.map((name) => [name, ref(null)]));
	ed.users.value = USERS;
	ed.comments.value = [];
	ed.selectedElements.value = [];
	ed.timelineText.value = "";
	ed.timelineAssignedTo.value = "";
	ed.timelineMentionedUsers.value = [];
	ed.commentFormData.value = { text: "", assigned_to: "", is_task: false };
	ed.inlineCommentFormData.value = { text: "", assigned_to: "", is_task: false };
	ed.inlineMentionedUsers.value = [];
	ed.inlineCommentElement.value = { id: "Task_1" };
	ed.activeMentionIndex.value = 0;
	ed.commentError.value = "";
	ed.props = { modelName: "Map 1", commentsAllowed: true };
	ed.modeler = { get: () => ({ remove: vi.fn(), add: vi.fn(), select: vi.fn() }) };
	ed.onReady = vi.fn();
	ed.fetchComments = vi.fn();
	useEditorTimeline(ed);
	useEditorInlineComment(ed);
	return ed;
}

function key(name) {
	return { key: name, preventDefault: vi.fn(), stopPropagation: vi.fn() };
}

beforeEach(() => frappeRequest.mockReset());

describe("mention keyboard selection", () => {
	it("ArrowDown then Enter commits the second suggestion", () => {
		const ed = editor();
		ed.timelineText.value = "Hi @ann";
		ed.mentionSearchQuery.value = "ann";
		ed.mentionStartIndex.value = 3;
		ed.activeMentionContext.value = "timeline";
		ed.showMentionDropdown.value = true;

		ed.onMentionKeydown(key("ArrowDown"));
		ed.onMentionKeydown(key("Enter"));

		expect(ed.timelineText.value).toBe("Hi @Anna Cole ");
		expect(ed.timelineAssignedTo.value).toBe("anna@example.com");
		expect(ed.showMentionDropdown.value).toBe(false);
	});

	it("leaves Cmd+Enter to submit and Escape closes the list", () => {
		const ed = editor();
		ed.timelineText.value = "Hi @ann";
		ed.mentionSearchQuery.value = "ann";
		ed.activeMentionContext.value = "timeline";
		ed.showMentionDropdown.value = true;

		ed.onMentionKeydown({ ...key("Enter"), metaKey: true });
		expect(ed.timelineText.value).toBe("Hi @ann");

		ed.onMentionKeydown(key("Escape"));
		expect(ed.showMentionDropdown.value).toBe(false);
	});
});

describe("task comment assignee", () => {
	it("refuses an inline task with no assignee and no typed mention", async () => {
		const ed = editor();
		ed.inlineCommentFormData.value = { text: "Please fix", assigned_to: "", is_task: true };

		await ed.submitInlineComment();

		expect(frappeRequest).not.toHaveBeenCalled();
		expect(ed.commentError.value).toMatch(/needs an assignee/);
	});

	it("refuses a timeline task with no assignee", async () => {
		const ed = editor();
		ed.timelineText.value = "Please fix";
		ed.timelineIsTask.value = true;

		await ed.submitTimelineComment();

		expect(frappeRequest).not.toHaveBeenCalled();
		expect(ed.commentError.value).toMatch(/needs an assignee/);
	});

	it("resolves a typed @Full Name to the user and sends it", async () => {
		const ed = editor();
		expect(ed.resolveTypedMention("ping @Anna Cole please")).toBe("anna@example.com");

		ed.inlineCommentFormData.value = { text: "ping @Ann Lee", assigned_to: "", is_task: true };
		await ed.submitInlineComment();

		expect(frappeRequest).toHaveBeenCalledOnce();
		expect(frappeRequest.mock.calls[0][0].params.assigned_to).toBe("ann@example.com");
		expect(ed.commentError.value).toBe("");
	});
});
