# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly context helpers moved into 'ProsAlly: Lib Context', with their platform calls approved."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import helpers, tools_links, tools_lint, tools_prompts
from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_context_move_to_library as move
from processa.patches.v1_0 import prosally_ir_move_to_library as ir
from processa.patches.v1_0 import prosally_map_xml_move_to_library as map_xml
from processa.patches.v1_0 import prosally_replies_move_to_library as replies
from processa.patches.v1_0 import prosally_stage_replies_move_to_library as stage
from processa.processa_engine.agent_runtime import turn_state
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script
from processa.tests.test_prosally_convert_step import _diagram

PROCESS = "ProsAlly Context Test"
P = "processa.ai_agent_registry.definitions.prosally"
SCRIPTS = {
	"build_context": "ProsAlly Context Test Build Context",
	"get_process_links": "ProsAlly Context Test Process Links",
}
OLD_SCRIPTS = {
	"build_context": f"from {P}.helpers import recall_process_memory\nmemory = recall_process_memory(diagram, process)\n",
	"get_process_links": f"from {P}.tools_links import process_links_for_turn\nfound = process_links_for_turn(context_docname)\n",
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
		f'<bpmn:process id="prosally_context_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_context_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class _Adapter:
	async def complete(self, **kwargs):
		return SimpleNamespace(text=MODEL_REPLY)


class TestProsAllyContextLibraryCode(FrappeTestCase):
	def test_the_library_imports_only_platform_functions_by_full_path(self):
		code = (replies.DATA / "prosally_lib_context.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertNotIn("processa.ai_agent_registry.definitions", code)
		self.assertIn(
			"from processa.ai_agent_registry.provisioning.bpmn_task_config import match_lane_role", code
		)
		self.assertNotIn("def match_lane_role(", code)
		self.assertIn('return "Document Register"', code)
		self.assertIn('return "BPMN Process Model"', code)


class TestProsAllyContextLibraryOnTheMap(FrappeTestCase):
	def setUp(self):
		super().setUp()
		for target in ("processa.processa_engine.triggers.on_doc_event",):
			started = patch(target)
			started.start()
			self.addCleanup(started.stop)
		started = patch("processa.ai_agent_memory.tools.memory_search", return_value=[])
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
				"process_id": "prosally_context_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": PROCESS,
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			replies.execute()
			ir.execute()
			map_xml.execute()
			stage.execute()
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
		self.assertEqual(replies.task_scripts(self.xml)["lib_context"], move.LIBRARY)
		self.assertEqual(collect_script_security_violations(self.xml, PROCESS), [])
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertLessEqual({"build_context", "get_process_links", "lib_context"}, set(approved))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)

	def test_settings_and_model_call_through_import_script(self):
		cfg = {"sub_prompts": {"clarifier": {"prompt": "Ask one question."}}, "agent_id": "prosally_agent"}
		self.assertSame("complete_sub_prompt", helpers.complete_sub_prompt, cfg, "clarifier", "Draw leave")
		self.assertSame("prosally_config", helpers.prosally_config)
		self.assertSame(
			"queue_process_memory",
			helpers.queue_process_memory,
			{"memory_process": ""},
			{"intent": "CLARIFY"},
		)
		self.assertSame("recall_process_memory", helpers.recall_process_memory, replies.MODEL_NAME, PROCESS)

	def test_turn_readers_through_import_script(self):
		self.assertSame(
			"process_links_for_turn", tools_links.process_links_for_turn, "ctx-1", conversation="ctx-1"
		)
		self.assertSame("links_review_output", tools_links.links_review_output, "ctx-2", conversation="ctx-2")
		for model in (replies.MODEL_NAME, "no such map words"):
			self.assertSame(
				"read_process_map_for_turn",
				tools_links.read_process_map_for_turn,
				"ctx-3",
				model,
				conversation="ctx-3",
			)
		self.assertSame(
			"search_dms_for_turn",
			tools_prompts.search_dms_for_turn,
			"ctx-4",
			"leave policy",
			conversation="ctx-4",
		)

	def test_text_helpers_through_import_script(self):
		ir = {"lanes": [{"id": "u", "name": "Employee"}, {"id": "s", "name": "System"}]}
		history = [{"role": "user", "content": "Add a Manager lane"}]
		self.assertSame("describe_lanes", tools_prompts.describe_lanes, history, "Add a Manager lane", ir)
		self.assertSame("describe_lanes", tools_prompts.describe_lanes, history, "x", None)
		for texts in (
			["Fix the lint findings"],
			["yes", "fix the lint errors please"],
			["Draw a leave process"],
		):
			self.assertSame("lint_fix_requested", tools_lint.lint_fix_requested, texts)
