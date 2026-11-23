"""The approve-an-invoice-under-500 Logix case expects an Apply Workflow answer with the 500 condition, not a script.

Approving is a status change, and status changes go to an Apply Workflow step.
"""

import frappe

OLD_TITLE = "A rule to approve an invoice under 500 gets a script, not a question back"
TITLE = "A rule to approve an invoice under 500 points to Apply Workflow with the 500 condition"
ASSERTIONS = (
	("regex", "(?i)apply workflow"),
	("regex", "\\b500\\b"),
	("no_tool_call", "write_script, write_agent_tool"),
	(
		"tool_artifact",
		'{"tool": "finalize", "path": "modified_script", "matcher": "equals", "expected": "null"}',
	),
	(
		"tool_artifact",
		'{"tool": "finalize", "path": "response", "matcher": "regex", '
		'"expected": "^(?![\\\\s\\\\S]*unable to generate a safe script)"}',
	),
)


def execute():
	name = frappe.db.get_value("AI Eval Case", {"title": OLD_TITLE}, "name")
	if not name:
		return
	case = frappe.get_doc("AI Eval Case", name)
	expect_apply_workflow(case)
	case.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def expect_apply_workflow(case) -> None:
	"""Give the case the Apply Workflow title and assertions and drop its expected script steps."""
	threshold = case.assertions[0].pass_threshold if case.assertions else 4
	case.title = TITLE
	case.expected_tool_calls = []
	case.assertions = []
	for assertion_type, value in ASSERTIONS:
		case.append(
			"assertions", {"assertion_type": assertion_type, "value": value, "pass_threshold": threshold}
		)
