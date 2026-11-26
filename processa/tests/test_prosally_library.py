# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly reply, lint and prompt helpers moved into 'ProsAlly: Lib Replies' on the ProsAlly map."""

from processa.tests.library import library
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_replies_move_to_library as move
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

PROCESS = "ProsAlly Test"
P = "processa.ai_agent_registry.definitions.prosally"
SCRIPTS = {
	"build_context": "ProsAlly Test Build Context",
	"modify_process": "ProsAlly Test Modify Process",
}
OLD_SCRIPTS = {
	"build_context": (
		f"from {P}.helpers import pending_confirmation\n_confirmed = pending_confirmation(conversation_id)\n"
	),
	"modify_process": (
		f"from {P}.tools_prompts import stage_max_tokens, stage_system_prompt\n"
		f"from {P}.tools_replies import describe_changes\n"
		"_max_tokens = stage_max_tokens(_cfg)\n"
		"if True:\n"
		f"    from {P}.tools_replies import no_change_reply, similar_steps\n"
		'    _reply = no_change_reply("the main process", similar_steps)\n'
		'_text = "describe_changes is the name of a tool"\n'
	),
}
FINDINGS = {
	"scope": {"name": "Approval"},
	"fix": [
		{
			"category": "error",
			"name": "Check",
			"id": "t1",
			"message": "has no outgoing flow",
			"rule": "no-dead-end",
		}
	],
	"left": [{"name": "Start", "message": "has no label"}],
	"elsewhere": [("Billing", 2), ("", 1)],
}
BEFORE = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">'
	'<bpmn:process id="p" isExecutable="true">'
	'<bpmn:startEvent id="s" name="Start" /><bpmn:task id="a" name="Check request" />'
	'<bpmn:endEvent id="e" name="Done" />'
	'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="a" /><bpmn:sequenceFlow id="f2" sourceRef="a" targetRef="e" />'
	"</bpmn:process></bpmn:definitions>"
)
AFTER = (
	BEFORE.replace('name="Check request"', 'name="Review request"')
	.replace('targetRef="e" />', 'targetRef="b" />', 1)
	.replace(
		"</bpmn:process>",
		'<bpmn:task id="b" name="Approve" /><bpmn:sequenceFlow id="f3" sourceRef="b" targetRef="e" /></bpmn:process>',
	)
)


def _map_xml():
	tasks = "".join(
		f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{name}" />'
		for task_id, name in SCRIPTS.items()
	)
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{task_id}_di" bpmnElement="{task_id}"><dc:Bounds x="{100 + 150 * i}" y="100" '
		'width="100" height="80" /></bpmndi:BPMNShape>'
		for i, task_id in enumerate(SCRIPTS)
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		f'<bpmn:process id="prosally_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestProsAllyLibraryCode(FrappeTestCase):
	def test_the_library_only_defines_functions_and_needs_no_approval(self):
		code = (move.DATA / "prosally_lib_replies.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertEqual(validate_script(code).get("findings") or [], [])

	def test_only_the_moved_names_leave_the_imports_and_strings_stay(self):
		edited = move.uses_library(OLD_SCRIPTS["modify_process"], move.MOVED, move.LOAD)
		self.assertEqual(edited.count(move.LOAD), 1)
		self.assertIn(f"from {P}.tools_prompts import stage_system_prompt\n", edited)
		self.assertIn(f"    from {P}.tools_replies import similar_steps\n", edited)
		self.assertIn("_max_tokens = _replies.stage_max_tokens(_cfg)", edited)
		self.assertIn('_reply = _replies.no_change_reply("the main process", similar_steps)', edited)
		self.assertIn('"describe_changes is the name of a tool"', edited)
		self.assertNotIn("tools_replies import describe_changes", edited)
		self.assertEqual(move.uses_library(edited, move.MOVED, move.LOAD), edited)


class TestProsAllyLibraryOnTheMap(FrappeTestCase):
	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": "x",
					"process_owner": "Administrator",
				}
			).insert()
		for task_id, name in SCRIPTS.items():
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True)
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": frappe.scrub(name),
					"script": OLD_SCRIPTS[task_id],
				}
			).db_insert()
		if frappe.db.exists("BPMN Process Model", move.MODEL_NAME):
			frappe.delete_doc("BPMN Process Model", move.MODEL_NAME, force=True)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"name": move.MODEL_NAME,
				"title": move.MODEL_NAME,
				"process_id": "prosally_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": PROCESS,
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			move.execute()
			move.execute()
		self.xml = frappe.db.get_value("BPMN Process Model", move.MODEL_NAME, "bpmn_xml")
		load = make_import_script(
			frappe._dict(process_model=move.MODEL_NAME), extract_script_task_config(self.xml)
		)
		self.lib = load(move.LIBRARY)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def assertSame(self, name, backend, *args):
		self.assertEqual(getattr(self.lib, name)(*args), backend(*args), name)

	def test_the_box_and_the_edits_are_made_once_and_no_approval_is_asked(self):
		self.assertEqual(self.xml.count(f'id="{move.BOX_ID}"'), 1)
		self.assertEqual(move.task_scripts(self.xml)[move.TASK_IDS[move.LIBRARY]], move.LIBRARY)
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
		self.assertFalse(frappe.db.exists("Script Approval Request", {"process_name": PROCESS}))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)

	def test_reply_helpers_through_import_script(self):
		turn = {
			"dms_documents": [
				{"document_code": "SOP-1", "title": "Leave", "document_type": "SOP"},
				{"document_code": "SOP-1", "title": "Leave", "document_type": "SOP"},
			]
		}
		self.assertSame(
			"add_document_sources", library("prosally_lib_replies.py").add_document_sources, "Here it is.", "BPMN_GENERATED", turn
		)
		self.assertSame("add_document_sources", library("prosally_lib_replies.py").add_document_sources, "Hi", "CLARIFY", turn)
		self.assertSame("pending_confirmation", library("prosally_lib_replies.py").pending_confirmation, "no-such-conversation")
		self.assertSame(
			"join_confirmation", library("prosally_lib_replies.py").join_confirmation, "Add an Approve step.", "Shall I apply it?"
		)
		self.assertSame(
			"join_confirmation", library("prosally_lib_replies.py").join_confirmation, {"steps": ["Add Approve"]}, "Go ahead?"
		)
		self.assertSame("stage_max_tokens", library("prosally_lib_replies.py").stage_max_tokens, {"max_tokens": 1000})
		self.assertSame("stage_max_tokens", library("prosally_lib_replies.py").stage_max_tokens, {})
		self.assertSame(
			"format_removal_warning",
			library("prosally_lib_replies.py").format_removal_warning,
			[{"name": "Check", "type": "scriptTask", "configs": ["script", "assignee", "timer", "docs"]}],
		)
		self.assertSame(
			"no_change_reply", library("prosally_lib_replies.py").no_change_reply, "the main process", ["Approve", "Review"]
		)
		self.assertSame("no_change_reply", library("prosally_lib_replies.py").no_change_reply, "the main process", [])

	def test_request_readers_through_import_script(self):
		for text in (
			"Review the links to other maps and draw the signals",
			"Make the Billing sub-process a call activity",
			"Space the steps out and line them up, only change the Approve step",
			"Add a gateway after Review",
		):
			self.assertSame("asks_for_links_review", library("prosally_lib_replies.py").asks_for_links_review, text)
			self.assertSame("asks_to_make_call_activity", library("prosally_lib_replies.py").asks_to_make_call_activity, text)
			self.assertSame("layout_asks", library("prosally_lib_replies.py").layout_asks, text)
			constraints = library("prosally_lib_replies.py").request_constraints(text)
			self.assertSame("request_constraints", library("prosally_lib_replies.py").request_constraints, text)
			self.assertSame("constraint_prompt", library("prosally_lib_replies.py").constraint_prompt, constraints)
			self.assertSame(
				"unrequested_changes", library("prosally_lib_replies.py").unrequested_changes, BEFORE, AFTER, text, constraints
			)

	def test_change_and_lint_replies_through_import_script(self):
		self.assertSame("describe_changes", library("prosally_lib_replies.py").describe_changes, BEFORE, AFTER)
		self.assertSame("describe_changes", library("prosally_lib_replies.py").describe_changes, BEFORE, BEFORE)
		topology = {"planar": False, "obstruction": ["a", "b"]}
		nodes = [{"id": "a", "name": "Check"}, {"id": "b", "name": "Approve"}]
		self.assertSame("crossing_line_note", library("prosally_lib_replies.py").crossing_line_note, nodes, topology, None)
		self.assertSame("crossing_line_note", library("prosally_lib_replies.py").crossing_line_note, nodes, {"planar": True}, None)
		self.assertSame("lint_prompt", library("prosally_lib_replies.py").lint_prompt, FINDINGS)
		self.assertSame("lint_leftovers", library("prosally_lib_replies.py").lint_leftovers, FINDINGS)
		self.assertSame("lint_unfixed_reply", library("prosally_lib_replies.py").lint_unfixed_reply, "the main process", FINDINGS)
		self.assertSame("no_lint_fix_reply", library("prosally_lib_replies.py").no_lint_fix_reply, FINDINGS)
		self.assertSame("no_lint_fix_reply", library("prosally_lib_replies.py").no_lint_fix_reply, None)
