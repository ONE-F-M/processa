# Copyright (c) 2026, one-fm and contributors
"""ProsAlly - Baseline gains a case where ProsAlly names the library scripts in the map's Libraries box."""

import json

import frappe

from processa.patches.v1_0.seed_prosally_baseline_suite import AGENT_ID, BASE_ASSERTIONS, SHAPE, SUITE_TITLE
from processa.patches.v1_0.seed_prosally_route_and_constraint_cases import MAP_XML, _calls

TITLE = "ProsAlly names the library scripts in the Libraries box, with nothing drawn"
SPIFF = 'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"'
LIBRARIES = (
	'<bpmn:adHocSubProcess id="Libraries_1" name="Libraries" spiffworkflow:scriptLibrary="true">'
	'<bpmn:scriptTask id="Lib_Replies" name="Replies" spiffworkflow:serverScript="Leave: Lib Replies" />'
	'<bpmn:scriptTask id="Lib_Dates" name="Dates" spiffworkflow:serverScript="Leave: Lib Dates" />'
	"</bpmn:adHocSubProcess>"
)
LIBRARY_SHAPES = (
	'<bpmndi:BPMNShape id="Libraries_1_di" bpmnElement="Libraries_1" isExpanded="true">'
	'<dc:Bounds x="160" y="600" width="300" height="140" /></bpmndi:BPMNShape>'
	'<bpmndi:BPMNShape id="Lib_Replies_di" bpmnElement="Lib_Replies"><dc:Bounds x="190" y="630" width="100" height="80" /></bpmndi:BPMNShape>'
	'<bpmndi:BPMNShape id="Lib_Dates_di" bpmnElement="Lib_Dates"><dc:Bounds x="330" y="630" width="100" height="80" /></bpmndi:BPMNShape>'
)


def library_map() -> str:
	"""The baseline Leave Request map with a Libraries box holding two library scripts."""
	return (
		MAP_XML.replace("<bpmn:definitions ", f"<bpmn:definitions {SPIFF} ", 1)
		.replace("</bpmn:process>", LIBRARIES + "</bpmn:process>", 1)
		.replace("</bpmndi:BPMNPlane>", LIBRARY_SHAPES + "</bpmndi:BPMNPlane>", 1)
	)


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}, "name"
	)
	if not suite or frappe.db.exists("AI Eval Case", {"suite": suite, "title": TITLE}):
		return
	case = frappe.new_doc("AI Eval Case")
	case.suite = suite
	case.title = TITLE
	case.case_type = "Trajectory"
	case.process_model = process_model
	case.bpmn_id = SHAPE
	case.input_user_prompt = "Which library scripts does this map have?"
	case.input_context = json.dumps({"current_xml": library_map()})
	case.set(
		"assertions",
		[
			*BASE_ASSERTIONS,
			{"assertion_type": "no_tool_call", "value": "generate_process, modify_process, confirm"},
			{"assertion_type": "regex", "value": "Leave: Lib Replies"},
			{"assertion_type": "regex", "value": "Leave: Lib Dates"},
		],
	)
	case.set("expected_tool_calls", _calls("classify_intent"))
	case.insert(ignore_permissions=True)  # patch: seeded eval case
