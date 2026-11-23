"""Seeds ProsAlly Baseline cases: one per route (explain, targeted edit, create) and one per request constraint.

The edits run on a small Leave Request map with no gateway and no script task. Idempotent by suite and title.
"""

import json
from pathlib import Path

import frappe

from processa.patches.v1_0.seed_prosally_baseline_suite import AGENT_ID, BASE_ASSERTIONS, SHAPE, SUITE_TITLE

MAP_XML = json.loads((Path(__file__).parent / "data" / "prosally_leave_request_map.json").read_text())["current_xml"]
OLD_STEPS = ("Submit leave request", "Review request", "Record leave", "Notify employee")


def _edit(title, request, *checks):
	return {
		"title": title,
		"prompt": "Yes, proceed",
		"context": _confirmed(request, "MODIFY_EXISTING"),
		"calls": _calls("classify_intent", "modify_process"),
		"assertions": [
			*BASE_ASSERTIONS,
			{"assertion_type": "no_tool_call", "value": "generate_process"},
			*checks,
		],
	}


def _calls(*tools):
	return [
		{"call_order": order, "tool_name": tool, "argument": "", "matcher": "", "expected_value": ""}
		for order, tool in enumerate(tools, start=1)
	]


def _drawn(tool, pattern):
	"""The XML the tool recorded matches pattern."""
	return {
		"assertion_type": "tool_artifact",
		"value": json.dumps({"tool": tool, "path": "bpmn_xml", "matcher": "regex", "expected": pattern}),
	}


def _keeps(*names):
	"""A pattern that holds only when every name is still on the map."""
	return "(?s)^" + "".join(f"(?=.*{name})" for name in names)


def _confirmed(request, action):
	"""The request, ProsAlly's confirmation card for it, and the map when there is one."""
	context = {
		"conversation_messages": [
			{"message_type": "User", "text": request},
			{
				"message_type": "Bot",
				"text": "Here is what I understood. Shall I go ahead?",
				"metadata": {"intent": "CONFIRM", "agent_result": {"action_intent": action}},
			},
		]
	}
	if action == "MODIFY_EXISTING":
		context["current_xml"] = MAP_XML
	return context


CASES = [
	{
		"title": "A question about the map is answered in text, with nothing drawn",
		"prompt": "What does this process do, step by step? Give me text, not a drawing.",
		"context": {"current_xml": MAP_XML},
		"calls": _calls("classify_intent"),
		"assertions": [
			*BASE_ASSERTIONS,
			{"assertion_type": "no_tool_call", "value": "generate_process, modify_process, confirm"},
			{"assertion_type": "regex", "value": "(?i)review request"},
		],
	},
	_edit(
		"A targeted edit renames one step and keeps the others",
		'Rename "Record leave" to "Record leave in the HR system".',
		_drawn("modify_process", _keeps("Record leave in the HR system", *OLD_STEPS[:2], OLD_STEPS[3])),
	),
	{
		"title": "A new process is drawn by the create route",
		"prompt": "Yes, proceed",
		"context": _confirmed(
			"Create a non-executable expense claim process: the Employee submits the claim, the Line Manager "
			"approves it and Finance pays it.",
			"GENERATE_NEW",
		),
		"calls": _calls("classify_intent", "generate_process"),
		"assertions": [*BASE_ASSERTIONS, {"assertion_type": "no_tool_call", "value": "modify_process"}],
	},
	_edit(
		'"Do not change anything else" adds the one step and keeps every other',
		'Add a step "Check leave balance" after "Review request". Do not change anything else.',
		_drawn("modify_process", _keeps("Check leave balance", *OLD_STEPS)),
	),
	_edit(
		'"No script tasks" adds the email step without a script task',
		'After "Record leave", add a step that emails the employee the approved dates. No script tasks.',
		_drawn("modify_process", r"(?s)^(?!.*scriptTask)(?=.*(?i:mail))"),
	),
	_edit(
		"Adding one step adds no gateway nobody asked for",
		'Add a step "Notify the line manager" after "Notify employee".',
		_drawn("modify_process", r"(?s)^(?!.*Gateway)(?=.*Notify the line manager)"),
	),
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}, "name"
	)
	if not suite:
		return
	for spec in CASES:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": spec["title"]}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = spec["title"]
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.bpmn_id = SHAPE
		case.input_user_prompt = spec["prompt"]
		case.input_context = json.dumps(spec["context"])
		case.set("assertions", spec["assertions"])
		case.set("expected_tool_calls", spec["calls"])
		if existing:
			case.save(ignore_permissions=True)  # patch: seeded eval case
		else:
			case.insert(ignore_permissions=True)  # patch: seeded eval case
