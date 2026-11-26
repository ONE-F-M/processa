# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly stage reply helpers moved into 'ProsAlly: Lib Stage Replies', with their platform calls approved."""

from processa.tests.library import library
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_ir_move_to_library as ir
from processa.patches.v1_0 import prosally_map_xml_move_to_library as map_xml
from processa.patches.v1_0 import prosally_replies_move_to_library as replies
from processa.patches.v1_0 import prosally_stage_replies_move_to_library as move
from processa.processa_engine.agent_runtime import turn_state
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script
from processa.tests.test_prosally_convert_step import _diagram

PROCESS = "ProsAlly Stage Test"
P = "processa.ai_agent_registry.definitions.prosally"
SCRIPTS = {
	"build_context": "ProsAlly Stage Test Build Context",
	"finalize": "ProsAlly Stage Test Finalize",
}
OLD_SCRIPTS = {
	"build_context": f"from {P}.helpers import answer_to_confirmation\nanswer = answer_to_confirmation(conversation_id, text)\n",
	"finalize": (
		"if done:\n"
		"    result = {}\n"
		"else:\n"
		f"    from {P}.tools_replies import clarify_output, no_stage_reply, redirect_output\n"
		"    result = clarify_output(context_docname) if routed else no_stage_reply(context_docname)\n"
	),
}
MODEL_REPLY = json.dumps(
	{
		"question": "Which step should approve it?",
		"options": ["Manager", "HR"],
		"origin": "diagram",
		"root_cause": "x",
	}
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
		f'<bpmn:process id="prosally_stage_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_stage_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class _Adapter:
	async def complete(self, **kwargs):
		return SimpleNamespace(text=MODEL_REPLY)


class TestProsAllyStageRepliesLibraryCode(FrappeTestCase):
	def test_the_library_imports_only_platform_functions_by_full_path(self):
		code = (replies.DATA / "prosally_lib_stage_replies.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertNotIn("processa.ai_agent_registry.definitions", code)
		names = {f["name"] for f in validate_script(code).get("findings") or []}
		self.assertIn("processa.processa_engine.agent_runtime.turn_state.update_turn", names)
		self.assertFalse([n for n in names if n.startswith("processa.ai_agent_registry.definitions")])


class TestProsAllyStageRepliesLibraryOnTheMap(FrappeTestCase):
	def setUp(self):
		super().setUp()
		for target in ("processa.processa_engine.triggers.on_doc_event",):
			started = patch(target)
			started.start()
			self.addCleanup(started.stop)
		for target in (
			"processa.processa_engine.agent_runtime.llm_factory.get_llm_adapter_from_settings",
			f"{P}.helpers.get_llm_adapter_from_settings",
		):
			started = patch(target, return_value=_Adapter())
			started.start()
			self.addCleanup(started.stop)
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
		if frappe.db.exists("BPMN Process Model", replies.MODEL_NAME):
			frappe.delete_doc("BPMN Process Model", replies.MODEL_NAME, force=True)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"name": replies.MODEL_NAME,
				"title": replies.MODEL_NAME,
				"process_id": "prosally_stage_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": PROCESS,
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			replies.execute()
			ir.execute()
			map_xml.execute()
			move.execute()
			move.execute()
		self.xml = frappe.db.get_value("BPMN Process Model", replies.MODEL_NAME, "bpmn_xml")
		load = make_import_script(
			frappe._dict(process_model=replies.MODEL_NAME), extract_script_task_config(self.xml)
		)
		self.lib = load(move.LIBRARY)
		self.turn = {
			"process_name": "Leave",
			"intent_reason": "no approver named",
			"user_text": "Add approval",
		}

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def assertSame(self, name, backend, *args, conversation=None):
		results = []
		for fn in (getattr(self.lib, name), backend):
			if conversation:
				turn_state.set_turn(conversation, copy.deepcopy(self.turn))
			results.append(
				(fn(*copy.deepcopy(args)), turn_state.get_turn(conversation) if conversation else None)
			)
		self.assertEqual(results[0], results[1], name)

	def test_the_box_holds_the_library_and_the_map_needs_no_approval(self):
		self.assertEqual(replies.task_scripts(self.xml)["lib_stage_replies"], move.LIBRARY)
		self.assertEqual(collect_script_security_violations(self.xml, PROCESS), [])
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertLessEqual({"build_context", "finalize", "lib_stage_replies"}, set(approved))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)
		finalize = frappe.db.get_value("Server Script", SCRIPTS["finalize"], "script")
		self.assertIn("    " + move.LOAD + "\n", finalize)
		compile(finalize, "finalize", "exec")

	def test_turn_replies_through_import_script(self):
		with patch("frappe.log_error"):
			self.assertSame(
				"no_stage_reply",
				library("prosally_lib_stage_replies.py").no_stage_reply,
				"stage-test-1",
				conversation="stage-test-1",
			)
		self.assertSame(
			"clarify_output",
			library("prosally_lib_stage_replies.py").clarify_output,
			"stage-test-2",
			conversation="stage-test-2",
		)
		self.assertSame(
			"redirect_output",
			library("prosally_lib_stage_replies.py").redirect_output,
			"stage-test-3",
			conversation="stage-test-3",
		)
		self.assertSame(
			"answer_to_confirmation",
			library("prosally_lib_stage_replies.py").answer_to_confirmation,
			"no-such-conversation",
			"yes",
		)

	def test_diagram_replies_through_import_script(self):
		diagram = _diagram()
		texts = ["Turn Complete Payroll Clearance into a sub-process"]
		self.assertSame(
			"similar_steps", library("prosally_lib_stage_replies.py").similar_steps, diagram, texts
		)
		self.assertSame(
			"similar_steps",
			library("prosally_lib_stage_replies.py").similar_steps,
			diagram,
			["Change the payroll clearance step"],
			"",
		)
		self.assertSame(
			"unapplied_proposal",
			library("prosally_lib_stage_replies.py").unapplied_proposal,
			"no-such-conversation",
			diagram,
			"",
		)
		self.assertSame(
			"unapplied_proposal",
			library("prosally_lib_stage_replies.py").unapplied_proposal,
			"no-such-conversation",
			"",
			"",
		)
		with patch("frappe.log_error"):
			self.assertSame(
				"diagnose_output",
				library("prosally_lib_stage_replies.py").diagnose_output,
				diagram,
				["Error: a flow has no target"],
				[],
			)

	def test_a_lint_finding_the_chat_cannot_fix_is_explained_not_offered(self):
		xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
			'<bpmn:process id="p1"><bpmn:sequenceFlow id="flow_a" name="Resubmit"/></bpmn:process></bpmn:definitions>'
		)
		message = 'Diagnose this lint finding on flow_a: Line crosses "Resubmit". (custom/no-crossing-edges)'
		lint = [
			{
				"id": "flow_a",
				"rule": "custom/no-crossing-edges",
				"message": "Line crosses",
				"category": "warn",
			}
		]
		reply = json.dumps({"origin": "map", "root_cause": "Two paths cross.", "fix_steps": ["Move a step"]})
		fakes = {"complete_sub_prompt": lambda *args, **kwargs: reply, "prosally_config": dict}
		with patch.dict(self.lib.diagnose_output.__globals__, fakes):
			answer = self.lib.diagnose_output(xml, [message], lint)
		self.assertEqual(answer["intent"], "CLARIFY")
		self.assertNotIn("options", answer)
		self.assertIn(self.lib.diagnose_output.__globals__["layout_is_automatic"](), answer["response"])
