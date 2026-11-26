"""Seeds the Overtime Request lifecycle into ProsAlly Regressions: its gateways test actions and script results, in Python.

Idempotent by suite and case title.
"""

import json

import frappe

from processa.patches.v1_0.seed_lucrusher_eval_suite import tool_call

AGENT_ID = "prosally_agent"
SHAPE = "run_prosally_agent"
SUITE_TITLE_LIKE = "%Regressions%"
TITLE = "Overtime gateways test actions and script results, in Python"

PROMPT = (
	"Create the Overtime Request Lifecycle process with the lanes Employee, Line Manager, Payroll Officer, "
	"Finance Manager and System (Automatic). An Overtime Request is created by an employee or by a manager. "
	"The system validates the overlap with other requests and the daily limit. A request the employee created "
	"goes to the line manager, who approves or rejects it. A request a manager created goes to the employee, "
	"who accepts or rejects it. Approved or accepted requests go to the payroll officer, who approves or rejects, "
	"then to the finance manager, who approves or rejects. A finance approval marks the request completed; "
	"any rejection ends it as rejected."
)
CONFIRMATION = (
	"I'll draw the Overtime Request Lifecycle process from scratch as an executable process, one the system runs. "
	"Shall I go ahead?"
)

# No condition may use JavaScript spellings, doc., or the approved and accepted flags no step sets.
CONDITION = r"<bpmn:conditionExpression[^>]*>[^<]*"
NO_BAD_CONDITION = (
	rf"^(?![\s\S]*{CONDITION}(?:\btrue\b|\bfalse\b|\bnull\b|\bdoc\.|&amp;&amp;|\|\||\bapproved\b|\baccepted\b))"
)
ROUTES_ON_ACTION = rf"{CONDITION}\baction\b"

ASSERTIONS = [
	{"assertion_type": "tool_calls", "value": "IN_ORDER"},
	*[
		{
			"assertion_type": "tool_artifact",
			"value": json.dumps({"tool": "generate_process", "path": "bpmn_xml", "matcher": "regex", "expected": expected}),
		}
		for expected in (NO_BAD_CONDITION, ROUTES_ON_ACTION)
	],
]
TRACE = [tool_call(1, "classify_intent"), tool_call(2, "generate_process")]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "title": ["like", SUITE_TITLE_LIKE]}, "name"
	)
	if not suite:
		return
	existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": TITLE}, "name")
	case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = TITLE
	case.case_type = "Trajectory"
	case.process_model = process_model
	case.bpmn_id = SHAPE
	case.input_user_prompt = "Yes, proceed"
	case.input_context = json.dumps(
		{
			"conversation_messages": [
				{"message_type": "User", "text": PROMPT},
				{
					"message_type": "Bot",
					"text": CONFIRMATION,
					"metadata": {"intent": "CONFIRM", "agent_result": {"action_intent": "GENERATE_NEW"}},
				},
			]
		}
	)
	case.set("assertions", ASSERTIONS)
	case.set("expected_tool_calls", TRACE)
	if existing:
		case.save(ignore_permissions=True)  # patch: seeded eval case
	else:
		case.insert(ignore_permissions=True)  # patch: seeded eval case
