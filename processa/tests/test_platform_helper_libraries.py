# Copyright (c) 2026, one-fm and contributors
"""Logix's debug stage helpers and LuCrusher's document search moved into libraries on their maps."""

from processa.tests.library import library
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import tools as logix_tools
from processa.ai_agent_registry.definitions.shared import tools_dms
from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import platform_helpers_move_to_libraries as move
from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA
from processa.processa_engine.agent_runtime import turn_state
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

D = "processa.ai_agent_registry.definitions"
LOGIX, LUCRUSHER = move.MOVES
OLD_SCRIPTS = {
	"debug_script": f"from {D}.logix.tools import run_debug_stage\nresult.update(run_debug_stage(context_docname))\n",
	"finalize": (
		f"from {D}.logix.tools import reply_with_code, revert_output\n"
		"if turn.get('intent') == 'REVERT':\n"
		"    result.update(revert_output(context_docname))\n"
	),
	"search_dms_documents": f"from {D}.shared.tools_dms import search_dms_documents\nfound = search_dms_documents(query)\n",
}
SCRIPTS = {task_id: f"Platform Lib Test {task_id}" for task_id in OLD_SCRIPTS}
MAP_TASKS = {LOGIX["model"]: ("debug_script", "finalize"), LUCRUSHER["model"]: ("search_dms_documents",)}
DEBUG_REPLY = {"fixed_script": "result['x'] = 2", "explanation": "x was 1", "findings": [], "verdict": "ok"}


def _map_xml(process_id, task_ids):
	tasks = "".join(
		f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{SCRIPTS[task_id]}" />'
		for task_id in task_ids
	)
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{task_id}_di" bpmnElement="{task_id}"><dc:Bounds x="{100 + 150 * i}" y="100" '
		'width="100" height="80" /></bpmndi:BPMNShape>'
		for i, task_id in enumerate(task_ids)
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		f'<bpmn:process id="{process_id}" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="{process_id}">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class _Adapter:
	async def step(self, **kwargs):
		return SimpleNamespace(content=json.dumps(DEBUG_REPLY))


class TestPlatformHelperLibraryCode(FrappeTestCase):
	def test_each_library_imports_only_platform_functions(self):
		for spec in move.MOVES:
			code = (DATA / spec["data_file"]).read_text()
			self.assertFalse(runs_code_on_import(code), spec["library"])
			self.assertNotIn(D, code, spec["library"])
			self.assertTrue(validate_script(code).get("findings"), spec["library"])


class TestPlatformHelperLibrariesOnTheMaps(FrappeTestCase):
	def setUp(self):
		super().setUp()
		started = patch("processa.processa_engine.triggers.on_doc_event")
		started.start()
		self.addCleanup(started.stop)
		for target in (
			"processa.processa_engine.agent_runtime.llm_factory.get_llm_adapter_from_settings",
			f"{D}.logix.tools.get_llm_adapter_from_settings",
		):
			started = patch(target, return_value=_Adapter())
			started.start()
			self.addCleanup(started.stop)
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
		for index, (model, task_ids) in enumerate(MAP_TASKS.items()):
			process = f"Platform Lib Test {index}"
			if not frappe.db.exists("Process", process):
				frappe.get_doc(
					{
						"doctype": "Process",
						"process_name": process,
						"description": "x",
						"process_owner": "Administrator",
					}
				).insert()
			if frappe.db.exists("BPMN Process Model", model):
				frappe.delete_doc("BPMN Process Model", model, force=True)
			frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"name": model,
					"title": model,
					"process_id": f"platform_lib_test_{index}",
					"version": 1,
					"bpmn_xml": _map_xml(f"platform_lib_test_{index}", task_ids),
					"process_name": process,
				}
			).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			move.execute()
			move.execute()
		self.libs = {}
		for spec in move.MOVES:
			xml = frappe.db.get_value("BPMN Process Model", spec["model"], "bpmn_xml")
			load = make_import_script(
				frappe._dict(process_model=spec["model"]), extract_script_task_config(xml)
			)
			self.libs[spec["library"]] = load(spec["library"])

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_each_map_holds_its_library_once_and_needs_no_approval(self):
		for index, spec in enumerate(move.MOVES):
			xml = frappe.db.get_value("BPMN Process Model", spec["model"], "bpmn_xml")
			self.assertEqual(xml.count(f'id="{spec["box_id"]}"'), 1)
			self.assertEqual(xml.count(f'id="{spec["task_id"]}"'), 1)
			process = f"Platform Lib Test {index}"
			self.assertEqual(collect_script_security_violations(xml, process), [])
			approved = frappe.get_all(
				"Script Approval Request",
				filters={"process_name": process, "source": "Shipped by patch", "status": "Approved"},
				pluck="script_task",
			)
			self.assertEqual(sorted(approved), sorted(spec["approved_tasks"]))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		moved = {name for spec in move.MOVES for name in spec["moved"]}
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			for line in script.splitlines():
				if " import " in line:
					self.assertFalse(
						{n.strip() for n in line.split(" import ", 1)[1].split(",")} & moved, line
					)
		finalize = frappe.db.get_value("Server Script", SCRIPTS["finalize"], "script")
		self.assertIn(f"from {D}.logix.tools import reply_with_code\n", finalize)
		self.assertIn("result.update(_debug_lib.revert_output(context_docname))", finalize)

	def _same(self, library, name, backend, conversation, turn, *args):
		results = []
		for fn in (getattr(self.libs[library], name), backend):
			turn_state.set_turn(conversation, copy.deepcopy(turn))
			results.append((fn(*copy.deepcopy(args)), turn_state.get_turn(conversation)))
		self.assertEqual(results[0], results[1], name)

	def test_debug_stage_through_import_script(self):
		lib = LOGIX["library"]
		self._same(lib, "run_debug_stage", logix_tools.run_debug_stage, "dbg-1", {}, "dbg-1")
		turn = {"script_text": "result['x'] = 1", "last_error": "x is wrong", "process_context": {}}
		self._same(lib, "run_debug_stage", logix_tools.run_debug_stage, "dbg-2", turn, "dbg-2")

	def test_revert_through_import_script(self):
		lib = LOGIX["library"]
		self._same(lib, "revert_output", library("logix_lib_debug.py").revert_output, "rev-1", {}, "rev-1")
		turn = {"current_script": SCRIPTS["debug_script"]}
		self._same(lib, "revert_output", library("logix_lib_debug.py").revert_output, "rev-2", turn, "rev-2")

	def test_document_search_through_import_script(self):
		search = self.libs[LUCRUSHER["library"]].search_dms_documents
		for args in (("leave policy approval",), ("leave", "Not A Type"), ("",)):
			self.assertEqual(search(*args), tools_dms.search_dms_documents(*args), args)
