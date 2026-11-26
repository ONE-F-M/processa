# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly layout helpers moved into 'ProsAlly: Lib Layout', with subprocess approved by the patch."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_pipeline, tools_replies, tools_review
from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_ir_move_to_library as ir
from processa.patches.v1_0 import prosally_layout_move_to_library as move
from processa.patches.v1_0 import prosally_map_xml_move_to_library as map_xml
from processa.patches.v1_0 import prosally_replies_move_to_library as replies
from processa.processa_engine.agent_runtime import turn_state
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script
from processa.tests.test_prosally_convert_step import _diagram
from processa.tests.test_prosally_subprocess_scope import STEPS

PROCESS = "ProsAlly Layout Test"
P = "processa.ai_agent_registry.definitions.prosally"
SCRIPTS = {
	"generate_process": "ProsAlly Layout Test Generate Process",
	"modify_process": "ProsAlly Layout Test Modify Process",
}
OLD_SCRIPTS = {
	"generate_process": f"from {P}.tools_pipeline import compile_ir\ncompiled = compile_ir(ir_dict)\n",
	"modify_process": (
		f"from {P}.tools_pipeline import compile_ir\n"
		f"from {P}.tools_replies import layout_note\n"
		f"from {P}.tools_review import relayout, relayout_output\n"
		"output = relayout_output(current_xml, text)\n"
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
		f'<bpmn:process id="prosally_layout_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_layout_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class _Adapter:
	async def complete(self, **kwargs):
		return SimpleNamespace(text=MODEL_REPLY)


class TestProsAllyLayoutLibraryCode(FrappeTestCase):
	def test_the_library_imports_only_platform_functions_by_full_path(self):
		code = (replies.DATA / "prosally_lib_layout.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertNotIn("processa.ai_agent_registry.definitions", code)
		self.assertNotIn("__file__", code)
		self.assertIn(
			"from processa.ai_agent_registry.provisioning.bpmn_task_config import match_lane_role", code
		)
		names = {f["name"] for f in validate_script(code).get("findings") or []}
		self.assertLessEqual({"subprocess", "os", "networkx", "xml.etree.ElementTree"}, names)


class TestProsAllyLayoutLibraryOnTheMap(FrappeTestCase):
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
				"process_id": "prosally_layout_test",
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
		self.lib_raw = self._raw_library()
		self.turn = {
			"process_name": "Leave",
			"intent_reason": "no approver named",
			"user_text": "Add approval",
		}

	def _raw_library(self):
		namespace = {"frappe": frappe}
		exec(frappe.db.get_value("Server Script", move.LIBRARY, "script"), namespace)
		return frappe._dict(namespace)

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
		self.assertEqual(replies.task_scripts(self.xml)["lib_layout"], move.LIBRARY)
		self.assertEqual(collect_script_security_violations(self.xml, PROCESS), [])
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertLessEqual({"generate_process", "lib_layout", "modify_process"}, set(approved))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)

	def test_the_pipeline_path_matches_the_backend(self):
		self.assertEqual(self.lib_raw._pipeline_path(), tools_pipeline._pipeline_path())

	def test_compile_and_relayout_through_import_script(self):
		ir = json.loads(json.dumps(STEPS))
		self.assertSame("compile_ir", tools_pipeline.compile_ir, ir)
		xml = tools_pipeline.compile_ir(json.loads(json.dumps(STEPS)))["xml"]
		self.assertSame("relayout", tools_review.relayout, xml)
		self.assertSame("relayout_output", tools_review.relayout_output, xml, "space the steps out")
		self.assertSame("layout_note", tools_replies.layout_note, xml, xml, "line them up")
		self.assertSame("layout_note", tools_replies.layout_note, xml, xml, "add a step")

	def test_diagram_edit_through_import_script(self):
		diagram = _diagram(lanes=True)
		for text in (
			"Move Prepare to the Audit lane",
			"Rename Prepare to Prepare payslip",
			"Draw a new process",
		):
			self.assertSame("diagram_edit_output", tools_review.diagram_edit_output, diagram, text)
