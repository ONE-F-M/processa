"""Seeds the Maintenance Work Order lifecycle into ProsAlly Regressions: no Update Field row may carry a description or a status the field lacks.

Idempotent by suite and case title.
"""

import json

import frappe

from processa.patches.v1_0.seed_lucrusher_eval_suite import tool_call

AGENT_ID = "prosally_agent"
SHAPE = "run_prosally_agent"
SUITE_TITLE_LIKE = "%Regressions%"
TITLE = "Update Field rows on the Maintenance Work Order hold only values the fields accept"

CONFIRMATION = (
	"I'll draw the Maintenance Work Order Lifecycle process from scratch as an executable process, one the system runs. "
	"Shall I go ahead?"
)
PROMPT = (
	"Create the Maintenance Work Order Lifecycle process with the lanes System, Maintenance Team Lead and Technician. "
	"When a Maintenance Schedule Entry becomes due, the system creates a Maintenance Work Order with status Open and "
	"sets the schedule entry's status to Work Order Created. It fills the object name, team and checklist from the "
	"Object, fetches the target response and resolution minutes from the client's SLA and freezes the SLA trigger time. "
	"It sets the status to Pre-Start, then to Active Counting once the trigger time passes, and to Fail when the elapsed "
	"minutes exceed the target. The team lead can drag the work order to a new date, which shifts the planned deadline "
	"and the SLA trigger time. The technician checks in on site, which stamps the first check-in time. When parts are "
	"missing the status is On Hold - Parts Required, and the paused minutes are incremented when the parts arrive. "
	"The technician completes the checklist, sets the status to Completed and submits it, and the completion time is stamped."
)

# A value written as a description, or a status the Select field does not offer, fails the case.
QUOTE = r'(?:&quot;|&#34;|")'
NOT_A_VALUE = (
	rf"^(?![\s\S]*value{QUOTE}\s*:\s*{QUOTE}"
	r"(?:fetched|fetched_if_empty|routed_if_empty|computed|shifted|incremented|matched_sla|Pre-Start|Active Counting)"
	rf"{QUOTE})"
)

ASSERTIONS = [
	{"assertion_type": "tool_calls", "value": "IN_ORDER"},
	{
		"assertion_type": "tool_artifact",
		"value": json.dumps(
			{"tool": "generate_process", "path": "bpmn_xml", "matcher": "regex", "expected": NOT_A_VALUE}
		),
	},
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
