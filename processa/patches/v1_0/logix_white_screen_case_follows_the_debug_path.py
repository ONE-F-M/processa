"""The white-screen Logix case expects the debug path: classify_intent then debug_script, and checks the reply itself.

A debug answer is given by debug_script, so the case no longer waits for finalize or reads its artifact.
"""

import frappe

CASE_TITLE = "A white screen and a failed transaction are debugged, not refused"
NO_REFUSAL = "^(?![\\s\\S]*(unable to generate a safe script|could not publish this script))"


def execute():
	name = frappe.db.get_value("AI Eval Case", {"title": CASE_TITLE}, "name")
	if not name:
		return
	case = frappe.get_doc("AI Eval Case", name)
	if follow_debug_path(case):
		case.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def follow_debug_path(case) -> bool:
	"""Drop the expected finalize call and check the reply with a regex; False when already done."""
	changed = False
	calls = [d for d in case.expected_tool_calls if d.tool_name != "finalize"]
	if len(calls) != len(case.expected_tool_calls):
		case.expected_tool_calls = calls
		changed = True
	for d in case.assertions:
		if d.assertion_type == "tool_artifact" and '"tool": "finalize"' in (d.value or ""):
			d.assertion_type = "regex"
			d.value = NO_REFUSAL
			changed = True
	return changed
