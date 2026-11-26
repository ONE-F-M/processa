# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly IR helpers moved into 'ProsAlly: Lib IR', in the same Libraries box as 'ProsAlly: Lib Replies'."""

import copy
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_operations, tools_pipeline
from processa.ai_agent_registry.definitions.shared import helpers
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_ir_move_to_library as move
from processa.patches.v1_0 import prosally_replies_move_to_library as replies
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

PROCESS = "ProsAlly IR Test"
P = "processa.ai_agent_registry.definitions"
SCRIPTS = {
	"generate_process": "ProsAlly IR Test Generate Process",
	"confirm": "ProsAlly IR Test Confirm",
}
OLD_SCRIPTS = {
	"generate_process": (
		f"from {P}.shared.helpers import extract_json, format_history\n"
		f"from {P}.prosally.tools_pipeline import auto_fix_ir, compile_ir, merge_chunked_ir\n"
		f"from {P}.prosally.tools_prompts import stage_max_tokens\n"
		"_max = stage_max_tokens(_cfg)\n"
		"ir = extract_json(raw) or {}\n"
		"fixes = auto_fix_ir(ir)\n"
	),
	"confirm": (f"from {P}.shared.helpers import format_history\n_hist = format_history(chat_history)\n"),
}
IR = {
	"lanes": [{"id": "user", "name": "User"}],
	"nodes": [
		{"id": "s", "type": "startEvent", "name": "Start", "lane": "user"},
		{"id": "g", "type": "exclusiveGateway", "name": "Approved?"},
		{"id": "a", "type": "userTask", "name": "Approve"},
		{"id": "r", "type": "serviceTask", "name": "Notify"},
	],
	"flows": [
		{"from": "s", "to": "g"},
		{"from": "g", "to": "a", "condition": "yes"},
		{"from": "g", "to": "r"},
		{"from": "g", "to": "x"},
	],
}
XML = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">'
	'<bpmn:process id="p" name="Leave Request" isExecutable="true">'
	'<bpmn:startEvent id="s" name="Start" /><bpmn:task id="a" name="Approve" />'
	'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="a" /></bpmn:process></bpmn:definitions>'
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
		f'<bpmn:process id="prosally_ir_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_ir_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestProsAllyIRLibraryCode(FrappeTestCase):
	def test_the_library_only_defines_functions_and_needs_no_approval(self):
		code = (replies.DATA / "prosally_lib_ir.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertEqual(validate_script(code).get("findings") or [], [])

	def test_the_library_holds_its_own_copy_of_the_shared_helpers(self):
		code = (replies.DATA / "prosally_lib_ir.py").read_text()
		self.assertIn("def extract_json(", code)
		self.assertIn("def format_history(", code)
		self.assertNotIn("import_script(", code)


class TestProsAllyIRLibraryOnTheMap(FrappeTestCase):
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
		if frappe.db.exists("BPMN Process Model", replies.MODEL_NAME):
			frappe.delete_doc("BPMN Process Model", replies.MODEL_NAME, force=True)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"name": replies.MODEL_NAME,
				"title": replies.MODEL_NAME,
				"process_id": "prosally_ir_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": PROCESS,
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			replies.execute()
			move.execute()
			move.execute()
		self.xml = frappe.db.get_value("BPMN Process Model", replies.MODEL_NAME, "bpmn_xml")
		load = make_import_script(
			frappe._dict(process_model=replies.MODEL_NAME), extract_script_task_config(self.xml)
		)
		self.lib = load(move.LIBRARY)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def assertSame(self, name, backend, *args):
		lib_args, backend_args = copy.deepcopy(args), copy.deepcopy(args)
		self.assertEqual(getattr(self.lib, name)(*lib_args), backend(*backend_args), name)
		self.assertEqual(lib_args, backend_args, name)

	def test_both_libraries_sit_in_one_box_once(self):
		self.assertEqual(self.xml.count(f'id="{replies.BOX_ID}"'), 1)
		self.assertEqual(self.xml.count('id="lib_ir"'), 1)
		scripts = replies.task_scripts(self.xml)
		self.assertEqual(scripts["lib_replies"], replies.LIBRARY)
		self.assertEqual(scripts["lib_ir"], move.LIBRARY)
		box = self.xml.split(f'id="{replies.BOX_ID}"', 1)[1].split("adHocSubProcess>", 1)[0]
		self.assertIn('id="lib_replies"', box)
		self.assertIn('id="lib_ir"', box)
		self.assertFalse(frappe.db.exists("Script Approval Request", {"process_name": PROCESS}))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)
		generate = frappe.db.get_value("Server Script", SCRIPTS["generate_process"], "script")
		self.assertIn(f"from {P}.prosally.tools_pipeline import compile_ir\n", generate)
		self.assertIn("fixes = _ir_lib.auto_fix_ir(ir)", generate)

	def test_reading_helpers_through_import_script(self):
		for raw in ('Here: ```json\n{"a": 1}\n```', "no json", '{"b": [1, 2]}'):
			self.assertSame("extract_json", helpers.extract_json, raw)
		history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}] * 8
		self.assertSame("format_history", helpers.format_history, history)
		self.assertSame("format_history", helpers.format_history, history, "Docu")
		self.assertSame("extract_process_name", tools_pipeline.extract_process_name, XML)
		self.assertSame("extract_element_ids", tools_pipeline.extract_element_ids, XML)

	def test_ir_helpers_through_import_script(self):
		self.assertSame("auto_fix_ir", tools_pipeline.auto_fix_ir, IR)
		self.assertSame("ensure_default_lanes", tools_pipeline.ensure_default_lanes, {"nodes": IR["nodes"]})
		self.assertSame("ensure_default_lanes", tools_pipeline.ensure_default_lanes, IR)
		chunks = [
			{"nodes": IR["nodes"][:2], "flows": IR["flows"][:1]},
			{"nodes": IR["nodes"][2:], "flows": []},
		]
		self.assertSame("merge_chunked_ir", tools_pipeline.merge_chunked_ir, IR["lanes"], chunks)
		self.assertSame("chunk_exit_node_id", tools_pipeline.chunk_exit_node_id, chunks[0])
		self.assertSame("chunk_exit_node_id", tools_pipeline.chunk_exit_node_id, {"nodes": []})

	def test_problem_text_and_operations_through_import_script(self):
		problems = [
			{"rule": "single-start", "elementId": "s2", "message": "two starts"},
			{"rule": "no-bpmndi", "message": "no shapes"},
			{"kind": "layout", "message": "crowded"},
			{"rule": "single-start", "elementId": "s2", "message": "two starts"},
		]
		self.assertSame("translate_problems", tools_pipeline.translate_problems, problems)
		violations = ["[single-start] two starts", "[no-bpmndi] x", "free text", "[single-start] again"]
		self.assertSame("translate_violations", tools_pipeline.translate_violations, violations)
		operations = [
			{"op": "add", "type": "userTask", "id": "c", "name": "Check", "lane": "user"},
			{"op": "rename", "id": "a", "name": "Approve request"},
			{"op": "reconnect", "id": "f9", "from": "s", "to": "c"},
		]
		self.assertSame("apply_operations", tools_operations.apply_operations, IR, operations)
		self.assertSame("apply_operations", tools_operations.apply_operations, IR, [{"op": "explode"}])
