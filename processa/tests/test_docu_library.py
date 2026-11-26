# Copyright (c) 2026, one-fm and contributors
"""The Docu schema helpers moved into 'Docu: Lib Schema' on the Docu map."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.docu import tools, validators
from processa.ai_agent_registry.definitions.shared import helpers
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import docu_helpers_move_to_library as move
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script

SCRIPTS = {
	"classify_intent": "Docu Test Classify",
	"edit_field_property": "Docu Test Edit Field",
	"review_schema": "Docu Test Review Schema",
}
OLD_SCRIPTS = {
	"classify_intent": (
		"from processa.ai_agent_registry.definitions.shared.helpers import extract_json\n"
		"from processa.ai_agent_registry.definitions.docu.tools import read_doctype_definition\n"
		"_data = extract_json(raw) or {}\n"
	),
	"edit_field_property": (
		"from processa.ai_agent_registry.definitions.docu.validators import RESERVED_FIELDNAMES\n"
		'if _kind == "remove_field" and _fn in RESERVED_FIELDNAMES:\n'
		"    pass\n"
	),
	"review_schema": (
		"from processa.ai_agent_registry.definitions.docu.tools import doctype_exists, merge_into_live_fields\n"
		"# The gate is validate_doctype_ir, so run it first.\n"
		'tool = ToolSpec(fn=validate_doctype_json, name="validate_doctype")\n'
		"merge_into_live_fields(_baseline, candidate)\n"
	),
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
		f'<bpmn:process id="docu_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="docu_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestDocuLibraryCode(FrappeTestCase):
	def test_the_library_only_defines_functions_and_needs_no_approval(self):
		code = (move.DATA / "docu_lib_schema.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		self.assertEqual(validate_script(code).get("findings") or [], [])

	def test_scripts_drop_only_the_moved_names_and_call_the_library(self):
		classify = move.uses_library(OLD_SCRIPTS["classify_intent"])
		self.assertIn(move.LOAD, classify)
		self.assertIn("import read_doctype_definition", classify)
		self.assertIn("_schema.extract_json(raw)", classify)
		self.assertNotIn("helpers import extract_json", classify)

		field = move.uses_library(OLD_SCRIPTS["edit_field_property"])
		self.assertIn("_fn in _schema.reserved_fieldnames():", field)
		self.assertNotIn("import RESERVED_FIELDNAMES", field)

		review = move.uses_library(OLD_SCRIPTS["review_schema"])
		self.assertIn("import doctype_exists\n", review)
		self.assertIn("ToolSpec(fn=_schema.validate_doctype_json", review)
		self.assertIn("_schema.merge_into_live_fields(_baseline", review)
		self.assertIn("# The gate is validate_doctype_ir, so run it first.", review)

	def test_a_second_edit_and_a_script_without_moved_names_change_nothing(self):
		once = move.uses_library(OLD_SCRIPTS["review_schema"])
		self.assertEqual(move.uses_library(once), once)
		other = "from processa.ai_agent_registry.definitions.docu.tools import timed\nresult['x'] = 1\n"
		self.assertEqual(move.uses_library(other), other)


class TestDocuLibraryOnTheMap(FrappeTestCase):
	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		if not frappe.db.exists("Process", "Docu Test"):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": "Docu Test",
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
				"process_id": "docu_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": "Docu Test",
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
		self.todo = tools.read_doctype_definition("ToDo")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_box_and_the_script_edits_are_made_once(self):
		self.assertEqual(self.xml.count(f'id="{move.BOX_ID}"'), 1)
		for name in SCRIPTS.values():
			self.assertEqual(frappe.db.get_value("Server Script", name, "script").count(move.LOAD), 1)

	def test_extract_json_through_import_script(self):
		for raw in ('Here: ```json\n{"a": 1}\n```', "no json", '{"b": [1, 2]}'):
			self.assertEqual(self.lib.extract_json(raw), helpers.extract_json(raw))

	def test_format_history_through_import_script(self):
		history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}] * 8
		self.assertEqual(self.lib.format_history(history, "Docu"), helpers.format_history(history, "Docu"))

	def test_reserved_fieldnames_through_import_script(self):
		self.assertEqual(self.lib.reserved_fieldnames(), validators.RESERVED_FIELDNAMES)

	def test_validate_doctype_ir_through_import_script(self):
		bad = json.loads(json.dumps(self.todo))
		bad["fields"] += [
			{"fieldname": "name", "fieldtype": "Data"},
			{"fieldname": "x y", "fieldtype": "Bogus"},
		]
		found = self.lib.validate_doctype_ir(bad)
		self.assertTrue(found["violations"])
		self.assertEqual(found, validators.validate_doctype_ir(bad))

	def test_validate_doctype_json_through_import_script(self):
		for text in (json.dumps(self.todo), "{nope"):
			self.assertEqual(self.lib.validate_doctype_json(text), tools.validate_doctype_json(text))

	def test_diff_ir_and_merge_into_live_fields_through_import_script(self):
		changed = json.loads(json.dumps(self.todo))
		changed["fields"] = [*changed["fields"][1:], {"fieldname": "new_f", "fieldtype": "Data", "label": "New"}]
		self.assertEqual(self.lib.diff_ir(self.todo, changed), tools.diff_ir(self.todo, changed))
		live_a, live_b = json.loads(json.dumps(self.todo)), json.loads(json.dumps(self.todo))
		self.lib.merge_into_live_fields(live_a, json.loads(json.dumps(changed)))
		tools.merge_into_live_fields(live_b, json.loads(json.dumps(changed)))
		self.assertEqual(live_a, live_b)
