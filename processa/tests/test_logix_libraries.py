# Copyright (c) 2026, one-fm and contributors
"""The Logix helpers moved into 'Logix: Lib Replies' and 'Logix: Lib DocType Sources' on the Logix map."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import helpers
from processa.ai_agent_registry.definitions.logix.tools import reply_with_code
from processa.ai_agent_registry.definitions.lucrusher.tools import read_doctype_sources
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import logix_helpers_move_to_libraries as move
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

SCRIPTS = {
	"build_context": "Logix Test Build Context",
	"finalize": "Logix Test Finalize",
	"review_script": "Logix Test Review Script",
	"read_doctype_logic": "Logix Test Read DocType Logic",
}
OLD_SCRIPTS = {
	"build_context": (
		"from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs, doctype_inputs\n"
		"turn = {**debug_inputs(task_data.get('user_text'), '', ''), **doctype_inputs('', {}, '')}\n"
	),
	"finalize": (
		"from processa.ai_agent_registry.definitions.logix.tools import reply_with_code, revert_output\n"
		"final = reply_with_code(final, code)\n"
	),
	"review_script": (
		"from processa.ai_agent_registry.definitions.logix.helpers import field_findings\n"
		"_checks = _checks + field_findings(code, turn)\n"
	),
	"read_doctype_logic": (
		"from processa.ai_agent_registry.definitions.lucrusher.tools import read_doctype_sources\n"
		"_logic = read_doctype_sources(_names, 40)\n"
	),
}
LIBRARY_NAMES = {
	move.REPLIES: set(),
	move.SOURCES: {"ast", "getattr", "open", "os", "frappe.cache.get_value", "frappe.cache.set_value"},
}


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
		f'<bpmn:process id="logix_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="logix_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestLogixLibraryCode(FrappeTestCase):
	def test_each_library_only_defines_functions_and_needs_what_the_story_lists(self):
		for name, file_name in move.LIBRARIES.items():
			code = (move.DATA / file_name).read_text()
			self.assertFalse(runs_code_on_import(code), name)
			found = {f["name"] for f in validate_script(code).get("findings") or []}
			self.assertEqual(found, LIBRARY_NAMES[name], name)

	def test_the_box_is_added_once_and_holds_both_libraries(self):
		once = move.with_libraries_box(_map_xml())
		self.assertEqual(move.with_libraries_box(once), once)
		self.assertIn('spiffworkflow:scriptLibrary="true"', once)
		scripts = move.task_scripts(once)
		self.assertEqual(scripts["lib_replies"], move.REPLIES)
		self.assertEqual(scripts["lib_doctype_sources"], move.SOURCES)

	def test_the_scripts_load_the_libraries_and_no_longer_import_the_helpers(self):
		for task_id, old in OLD_SCRIPTS.items():
			new = move.with_edits(old, move.SCRIPT_EDITS[task_id])
			self.assertIn("import_script(", new, task_id)
			self.assertNotIn("definitions.logix.helpers import", new, task_id)
			self.assertNotIn("import reply_with_code", new, task_id)
			self.assertNotIn("lucrusher.tools import read_doctype_sources", new, task_id)
			compile(new, task_id, "exec")


class TestLogixLibrariesOnTheMap(FrappeTestCase):
	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		if not frappe.db.exists("Process", "Logix Test"):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": "Logix Test",
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
				"process_id": "logix_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": "Logix Test",
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			move.execute()
			move.execute()
		self.xml = frappe.db.get_value("BPMN Process Model", move.MODEL_NAME, "bpmn_xml")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _libraries(self):
		load = make_import_script(
			frappe._dict(process_model=move.MODEL_NAME), extract_script_task_config(self.xml)
		)
		return load(move.REPLIES), load(move.SOURCES)

	def test_a_second_run_creates_nothing_twice(self):
		self.assertEqual(self.xml.count('id="logix_libraries"'), 1)
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": "Logix Test", "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertEqual(sorted(approved), ["lib_doctype_sources", "read_doctype_logic", "review_script"])

	def test_debug_inputs_through_import_script(self):
		replies, _sources = self._libraries()
		args = ("Fix the Leave Application script, it fails", "x = 1", "")
		self.assertEqual(replies.debug_inputs(*args), helpers.debug_inputs(*args))

	def test_doctype_inputs_through_import_script(self):
		replies, _sources = self._libraries()
		args = ("Update each ToDo record", {"element_name": "Approve"}, "")
		self.assertEqual(replies.doctype_inputs(*args), helpers.doctype_inputs(*args))

	def test_reply_with_code_through_import_script(self):
		replies, _sources = self._libraries()
		for text, code in (("Here:\n```python\nold\n```", "x = 1"), ("No code here.", "y = 2")):
			self.assertEqual(replies.reply_with_code(text, code), reply_with_code(text, code))

	def test_field_findings_through_import_script(self):
		_replies, sources = self._libraries()
		code = "doc = frappe.get_doc('ToDo', 'x')\ndoc.descriptionz = 1\nfrappe.db.get_value('ToDo', 'x', 'statuz')"
		turn = {"user_text": "Update the ToDo record", "process_context": {}}
		found = sources.field_findings(code, turn)
		self.assertTrue(found)
		self.assertEqual(found, helpers.field_findings(code, turn))

	def test_read_doctype_sources_through_import_script(self):
		_replies, sources = self._libraries()
		self.assertEqual(sources.read_doctype_sources(["ToDo"], 20), read_doctype_sources(["ToDo"], 20))

	def test_a_task_with_nothing_to_approve_gets_no_request(self):
		frappe.db.set_value("Server Script", SCRIPTS["review_script"], "script", "result = 1\n")
		frappe.db.delete(
			"Script Approval Request", {"process_name": "Logix Test", "script_task": "review_script"}
		)
		with patch("processa.api.deploy.compile_process_model"):
			move.execute()
		self.assertFalse(
			frappe.db.exists(
				"Script Approval Request", {"process_name": "Logix Test", "script_task": "review_script"}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Script Approval Request", {"process_name": "Logix Test", "script_task": "read_doctype_logic"}
			)
		)
