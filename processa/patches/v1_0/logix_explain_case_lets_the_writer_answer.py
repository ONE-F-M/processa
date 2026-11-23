"""The explain-the-script Logix case lets the writer answer in words, as every question is answered.

Only the writer sees the linked script, so it answers a question in prose; the case still forbids code and a diff.
"""

import frappe

CASE_TITLE = "Explain the script is answered in words with no code"
CALLS = ("classify_intent", "write_script", "finalize")
ASSERTIONS = (
	("regex", "\\S"),
	("tool_calls", "IN_ORDER"),
	("no_tool_call", "write_agent_tool, clarify"),
	(
		"tool_artifact",
		'{"tool": "finalize", "path": "response", "matcher": "regex", "expected": "^(?![\\\\s\\\\S]*```python)"}',
	),
	("tool_artifact", '{"tool": "finalize", "path": "diff", "matcher": "equals", "expected": "null"}'),
	(
		"tool_artifact",
		'{"tool": "finalize", "path": "response", "matcher": "regex", '
		'"expected": "^(?![\\\\s\\\\S]*unable to generate a safe script)"}',
	),
)


def execute():
	name = frappe.db.get_value("AI Eval Case", {"title": CASE_TITLE}, "name")
	if not name:
		return
	case = frappe.get_doc("AI Eval Case", name)
	if [d.tool_name for d in case.expected_tool_calls] == list(CALLS):
		return
	let_the_writer_answer(case)
	case.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def let_the_writer_answer(case) -> None:
	"""Expect classify, write and finalize, and check the reply has no code and no diff."""
	threshold = case.assertions[0].pass_threshold if case.assertions else 4
	case.expected_tool_calls = []
	for order, tool in enumerate(CALLS, start=1):
		case.append("expected_tool_calls", {"call_order": order, "tool_name": tool})
	case.assertions = []
	for assertion_type, value in ASSERTIONS:
		case.append(
			"assertions", {"assertion_type": assertion_type, "value": value, "pass_threshold": threshold}
		)
