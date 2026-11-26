# Copyright (c) 2026, one-fm and contributors
"""The LuCrusher codebase helpers moved into 'LuCrusher: Lib Codebase' on the LuCrusher map."""

from processa.tests.library import library
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.lucrusher import tools
from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import lucrusher_helpers_move_to_library as move
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

PROCESS = "LuCrusher Test"
SCRIPTS = {
	"scan_codebase_for_process": "LuCrusher Test Scan Codebase",
	"read_doctype_logic": "LuCrusher Test Read DocType Logic",
}
OLD_SCRIPTS = {
	"scan_codebase_for_process": (
		"if True:\n"
		"    from processa.ai_agent_registry.definitions.lucrusher.tools import find_whitelisted_methods, get_codebase_index\n"
		"    index = get_codebase_index()\n"
		"    candidates = find_whitelisted_methods(['processa'], ['lucrusher'])\n"
	),
	"read_doctype_logic": (
		"from processa.ai_agent_registry.definitions.lucrusher.tools import read_doctype_sources\n"
		"docs = read_doctype_sources(['ToDo'], 40)\n"
	),
}
LIBRARY_NAMES = {"ast", "getattr", "open", "os", "glob", "frappe.cache.get_value", "frappe.cache.set_value"}


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
		f'<bpmn:process id="lucrusher_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="lucrusher_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestLuCrusherLibraryCode(FrappeTestCase):
	def test_the_library_only_defines_functions_and_needs_what_the_story_lists(self):
		code = (move.DATA / "lucrusher_lib_codebase.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertEqual({f["name"] for f in validate_script(code).get("findings") or []}, LIBRARY_NAMES)


class TestLuCrusherLibraryOnTheMap(FrappeTestCase):
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
				"process_id": "lucrusher_test",
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

	def test_a_second_run_creates_nothing_twice(self):
		self.assertEqual(self.xml.count(f'id="{move.BOX_ID}"'), 1)
		self.assertEqual(move.task_scripts(self.xml)[move.TASK_IDS[move.LIBRARY]], move.LIBRARY)
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertEqual(sorted(approved), sorted(move.APPROVED_TASKS))

	def test_the_scripts_load_the_library_and_no_longer_import_the_helpers(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			self.assertNotIn("lucrusher.tools import", script, name)
			compile(script, name, "exec")

	def test_the_map_needs_no_approval_after_the_patch(self):
		self.assertEqual(collect_script_security_violations(self.xml, PROCESS), [])

	def test_get_codebase_index_through_import_script(self):
		frappe.cache.delete_value(tools.INDEX_CACHE_KEY)
		self.assertEqual(self.lib.get_codebase_index(), tools.build_codebase_index())

	def test_find_whitelisted_methods_through_import_script(self):
		found = self.lib.find_whitelisted_methods(["processa"], ["ai_agent"])
		self.assertTrue(found)
		self.assertEqual(found, library("lucrusher_lib_codebase.py").find_whitelisted_methods(["processa"], ["ai_agent"]))

	def test_read_doctype_sources_through_import_script(self):
		names = ["ToDo", "No Such DocType"]
		self.assertEqual(self.lib.read_doctype_sources(names, 20), tools.read_doctype_sources(names, 20))
