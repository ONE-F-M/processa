# Copyright (c) 2026, one-fm and contributors
"""Lint, readiness, deploy and the request see what a script task gets through import_script."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks import script_gate
from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.ai_agent_security.code_checks.script_validator import IMPORT_ERROR, inspect_script
from processa.patches.v1_0 import seed_script_import_categories
from processa.processa_engine.engine import check_server_script

PROCESS = "Import Check Process"
LIBRARY = "Import Check Lib Replies"
CALLER = "Import Check Finalize"
TASK = "finalize"
CALLER_CODE = f'lib = import_script("{LIBRARY}")\nresult["clean"] = lib.strip_fences("x")\n'


class TestImportScriptChecks(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Requests are checked here without the Script Security Approval map.
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		clear_category_cache()
		seed_script_import_categories.execute()
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": PROCESS,
					"process_owner": "Administrator",
				}
			).insert()
		self._script(LIBRARY, "def strip_fences(text):\n\treturn text.strip()\n")
		self._script(CALLER, CALLER_CODE)
		self.xml = _map_xml({"lib": LIBRARY, TASK: CALLER})

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _script(self, name, body):
		if frappe.db.exists("Server Script", name):
			frappe.db.set_value("Server Script", name, "script", body)
			return
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name),
				"script": body,
			}
		).insert()

	def _model(self, xml):
		name = "Import Check Map"
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1)
		model = frappe.new_doc("BPMN Process Model")
		model.update(
			{"name": name, "title": name, "process_id": "import_check_map", "version": 1, "bpmn_xml": xml}
		)
		model.insert()
		frappe.db.set_value("BPMN Process Model", name, "process_name", PROCESS)

	def test_a_script_name_that_is_not_in_quotes_is_a_finding(self):
		findings = inspect_script("name = 'X'\nlib = import_script(name)")
		self.assertEqual(
			[(f["category"], f["line"], f["message"]) for f in findings],
			[(IMPORT_ERROR, 2, "import_script needs the script name in quotes")],
		)

	def test_a_library_not_on_the_map_is_a_finding_at_readiness_deploy_and_lint(self):
		self._script(CALLER, 'lib = import_script("X")')
		expected = "Script Task 'finalize' imports 'X', which is not in this process"
		messages = [f["message"] for f in script_gate.collect_script_security_violations(self.xml, PROCESS)]
		self.assertIn(expected, messages)
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_scripts(self.xml, PROCESS)
		self._model(self.xml)
		lint = script_gate.lint_script('lib = import_script("X")', CALLER, PROCESS, TASK)
		self.assertIn(expected, [f["message"] for f in lint["findings"]])

	def test_what_the_library_uses_is_flagged_on_the_importing_task_naming_the_library(self):
		self._script(LIBRARY, "import requests\ndef strip_fences(text):\n\treturn text\n")
		self._model(self.xml)
		lint = script_gate.lint_script(CALLER_CODE, CALLER, PROCESS, TASK)
		finding = next(f for f in lint["findings"] if f["name"] == "requests")
		self.assertEqual(
			(finding["category"], finding["library"], finding["approved"]), ("Network", LIBRARY, False)
		)
		self.assertIn(LIBRARY, finding["message"])

	def test_an_approval_on_the_importing_task_covers_the_library(self):
		self._script(LIBRARY, "import requests\ndef strip_fences(text):\n\treturn text\n")
		request = frappe.get_doc(
			{
				"doctype": "Script Approval Request",
				"process_name": PROCESS,
				"script_task": TASK,
				"server_script": CALLER,
			}
		).insert()
		self.assertEqual([(d.item_name, d.library) for d in request.requested_items], [("requests", LIBRARY)])
		request.db_set("status", "Approved")
		self.assertEqual(script_gate.script_task_findings(CALLER_CODE, PROCESS, TASK, CALLER), [])
		check_server_script(frappe.get_doc("Server Script", CALLER), PROCESS, TASK)

	def test_the_run_refuses_a_library_item_the_task_is_not_approved_for(self):
		self._script(LIBRARY, "import requests\ndef strip_fences(text):\n\treturn text\n")
		with self.assertRaises(frappe.ValidationError) as caught:
			check_server_script(frappe.get_doc("Server Script", CALLER), PROCESS, TASK)
		self.assertIn(LIBRARY, str(caught.exception))

	def test_a_library_that_imports_another_script_is_a_finding(self):
		self._script(LIBRARY, f'other = import_script("{CALLER}")\n')
		messages = [
			f["message"] for f in script_gate.script_task_findings(CALLER_CODE, PROCESS, TASK, CALLER)
		]
		self.assertIn(f"Library '{LIBRARY}' cannot import another script", messages)

	def test_a_library_that_runs_code_on_import_is_a_finding(self):
		self._script(LIBRARY, "def strip_fences(text):\n\treturn text.strip()\n\nresult['x'] = 1\n")
		self._model(self.xml)
		lint = script_gate.lint_script(CALLER_CODE, CALLER, PROCESS, TASK)
		self.assertIn(
			f"Library '{LIBRARY}' runs code when it is imported; keep only functions in it",
			[f["message"] for f in lint["findings"]],
		)

	def test_a_private_library_function_is_a_finding(self):
		code = f'lib = import_script("{LIBRARY}")\nresult["clean"] = lib._strip("x")\n'
		self._model(self.xml)
		lint = script_gate.lint_script(code, CALLER, PROCESS, TASK)
		self.assertIn(
			f"_strip is private to library '{LIBRARY}'; rename it without the leading underscore",
			[f["message"] for f in lint["findings"]],
		)

	def test_import_script_with_a_default_only_library_is_clean(self):
		self._model(self.xml)
		lint = script_gate.lint_script(CALLER_CODE, CALLER, PROCESS, TASK)
		self.assertEqual(lint["findings"], [])
		self.assertEqual(lint["status"], "Clear")

	def _approve_caller(self):
		request = frappe.get_doc(
			{
				"doctype": "Script Approval Request",
				"process_name": PROCESS,
				"script_task": TASK,
				"server_script": CALLER,
			}
		).insert()
		request.db_set("status", "Approved")

	def test_a_library_in_a_libraries_box_is_checked_only_through_the_task_that_loads_it(self):
		self._script(LIBRARY, "def strip_fences(text):\n\timport requests\n\n\treturn text\n")
		self._approve_caller()
		boxed = _map_xml({TASK: CALLER}, libraries={"lib": LIBRARY})
		self.assertEqual(script_gate.collect_script_security_violations(boxed, PROCESS), [])
		script_gate.validate_process_model_scripts(boxed, PROCESS)

	def test_a_loose_library_task_is_still_checked_on_its_own(self):
		self._script(LIBRARY, "def strip_fences(text):\n\timport requests\n\n\treturn text\n")
		self._approve_caller()
		labels = {f["label"] for f in script_gate.collect_script_security_violations(self.xml, PROCESS)}
		self.assertTrue(any("'lib'" in label for label in labels), labels)

	def test_a_syntax_error_in_a_libraries_box_still_stops_the_deploy(self):
		self._script(LIBRARY, "def strip_fences(text:\n\treturn text\n")
		boxed = _map_xml({TASK: CALLER}, libraries={"lib": LIBRARY})
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_syntax(boxed)


def _map_xml(tasks: dict, libraries: dict | None = None) -> str:
	shapes = "".join(
		f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{script}" />'
		for task_id, script in tasks.items()
	)
	if libraries:
		shapes += (
			'<bpmn:adHocSubProcess id="libraries" spiffworkflow:scriptLibrary="true">'
			+ "".join(
				f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{script}" />'
				for task_id, script in libraries.items()
			)
			+ "</bpmn:adHocSubProcess>"
		)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		f'<bpmn:process id="import_check_map" isExecutable="true">{shapes}</bpmn:process></bpmn:definitions>'
	)
