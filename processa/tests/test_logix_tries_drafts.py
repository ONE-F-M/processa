# Copyright (c) 2026, one-fm and contributors
"""Logix tries a draft on a record, reads the newest error of a script, and shows the real error of a check."""

import ast
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import dry_run as trial
from processa.ai_agent_registry.definitions.logix import tools
from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs, doctype_inputs, field_findings
from processa.api.server_scripts import run_logix_test_case
from processa.patches.v1_0 import logix_tries_drafts_on_a_record as p

MODEL = frappe._dict(name="Trial Model", trigger_doctype="Note", bpmn_xml="")
TURN = {"process_context": {"process_name": "trial", "element_id": "t"}}
SCRIPT = "Trial Attendance Script"


class TestLogixTriesDrafts(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.note = frappe.get_doc({"doctype": "Note", "title": "trial sample"}).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _try(self, code):
		with patch.object(trial, "_process_model", return_value=MODEL):
			return trial.dry_run(code, TURN)

	def test_the_map_open_in_the_editor_is_found_by_its_name(self):
		model = frappe.new_doc("BPMN Process Model")
		model.update(
			{"name": "Trial Map - v1", "title": "Trial Map - v1", "process_id": "trial_map", "version": 1}
		)
		model.trigger_doctype = "Note"
		model.bpmn_xml = (
			'<?xml version="1.0" encoding="UTF-8"?>'
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
			'<bpmn:process id="trial_map" name="Trial Map" isExecutable="true" /></bpmn:definitions>'
		)
		model.insert()
		turn = {
			"process_context": {
				"process_name": "Trial Map",
				"process_model": "Trial Map - v1",
				"element_id": "t",
			}
		}
		outcome = trial.dry_run('result["title"] = doc.title\n', turn)
		self.assertTrue(outcome["ran"], outcome)
		self.assertEqual(trial._process_model({"process_name": "trial_map"}).name, "Trial Map - v1")

	def test_a_draft_using_an_approved_item_is_tried(self):
		code = 'import requests\nresult["title"] = doc.title\n'
		with patch.object(trial, "approved_request_names", return_value={"requests"}):
			outcome = self._try(code)
		self.assertTrue(outcome["ran"], outcome)
		with patch.object(trial, "approved_request_names", return_value=set()):
			self.assertFalse(self._try(code)["ran"])

	def test_a_failing_draft_returns_its_traceback_and_failing_line(self):
		outcome = self._try('x = 1\nresult["date"] = doc.appointment_date.year\n')
		self.assertEqual(
			(outcome["line"], outcome["code"]), (2, 'result["date"] = doc.appointment_date.year')
		)
		self.assertIn("AttributeError", outcome["error"])
		self.assertIn("It failed on Note", outcome["summary"])

	def test_a_working_draft_is_described_and_undone(self):
		count = frappe.db.count("Note")
		outcome = self._try(
			'frappe.get_doc({"doctype": "Note", "title": doc.title + " copy"}).insert()\n'
			'frappe.sendmail(recipients=["a@example.com"], subject="s", message="m")\n'
			'result["seen"] = doc.name\n'
		)
		self.assertNotIn("error", outcome)
		self.assertEqual(outcome["record"], f"Note {self.note.name}")
		self.assertTrue(any(w.startswith("insert Note") for w in outcome["writes"]), outcome["writes"])
		self.assertEqual(outcome["stubbed"], ["sendmail"])
		self.assertEqual(outcome["result"], {"seen": self.note.name})
		self.assertIn("Not executed in the trial: sendmail", outcome["summary"])
		self.assertEqual(frappe.db.count("Note"), count)

	def test_a_throw_is_reported_as_a_stop_not_a_failure(self):
		outcome = self._try('frappe.throw("Date and Time Confirmation is missing")\n')
		self.assertNotIn("error", outcome)
		self.assertIn("Date and Time Confirmation is missing", outcome["summary"])

	def test_it_runs_as_the_person_who_asked(self):
		frappe.flags.requesting_user = "Guest"
		self.addCleanup(frappe.flags.pop, "requesting_user", None)
		outcome = self._try('result["user"] = frappe.session.user\n')
		self.assertEqual(outcome["result"], {"user": "Guest"})
		self.assertEqual(frappe.session.user, "Administrator")

	def test_a_draft_the_gate_refuses_is_not_run(self):
		outcome = self._try("import os\nos.remove('x')\n")
		self.assertFalse(outcome["ran"])

	def test_with_no_record_to_try_it_is_not_run(self):
		with patch.object(trial, "_process_model", return_value=None):
			self.assertFalse(trial.dry_run('result["x"] = 1', TURN)["ran"])

	def test_the_review_script_edits_land_once_and_still_parse(self):
		code = frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script")
		if not code:
			self.skipTest("the Logix review script is not on this site")
		for pattern, new in p.EDITS:
			self.assertEqual(len(pattern.findall(code)), 1)
			code = pattern.sub(new, code, count=1)
		ast.parse(code)
		self.assertIn("dry_run(code, turn)", code)


class TestLogixReadsTheNewestError(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if frappe.db.exists("Server Script", SCRIPT):
			frappe.delete_doc("Server Script", SCRIPT, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT,
				"script_type": "API",
				"api_method": "trial_attendance_script",
				"script": 'result["saved"] = 1',
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_debug_reads_the_saved_script_and_the_newest_error_from_any_path(self):
		frappe.log_error(
			title=f'BPMN ScriptTask: "{SCRIPT}" execution failed', message="old appointment_date error"
		)
		frappe.log_error(
			title="BPMN runtime failure [X]",
			message=f'File "<serverscript>: {frappe.scrub(SCRIPT)}", line 51\nAttributeError: commit',
		)
		inputs = debug_inputs("still not creating attendance", 'result["editor"] = 1', SCRIPT)
		self.assertEqual(inputs["script_text"], 'result["saved"] = 1')
		self.assertIn("line 51", inputs["last_error"])
		self.assertIn("the script was last saved", inputs["last_error"])

	def test_a_fix_that_only_changes_spacing_is_not_offered(self):
		self.assertEqual(tools._code_lines("a = 1\n\nb = 2"), tools._code_lines("a = 1  \nb = 2\n"))
		self.assertNotEqual(tools._code_lines("a = 1"), tools._code_lines("a = 2"))

	def test_a_failing_check_shows_the_real_error_and_logs_it(self):
		frappe.db.set_value("Server Script", SCRIPT, "script", 'result["x"] = doc.appointment_date.year')
		outcome = run_logix_test_case(SCRIPT, "{}")
		self.assertIn("AttributeError", outcome["summary"])
		self.assertTrue(frappe.db.exists("Error Log", {"method": f'Logix check: "{SCRIPT}" failed'}))


class TestLogixChecksFields(FrappeTestCase):
	def _names(self, code, trigger="Note"):
		return [f["name"] for f in field_findings(code, {"doc_doctype": trigger})]

	def test_a_field_the_doctype_lacks_is_found_wherever_the_script_uses_it(self):
		code = (
			'result["a"] = doc.arrival_date\n'
			'result["b"] = doc.get("departure")\n'
			'rows = frappe.get_all("ToDo", filters={"status": "Open", "priority_level": 1}, fields=["name", "due"])\n'
			'todo = frappe.get_doc("ToDo", rows[0].name)\n'
			"todo.closing_note = 1\n"
			'frappe.db.set_value("ToDo", todo.name, "reviewer", "x")\n'
		)
		self.assertEqual(
			self._names(code),
			["arrival_date", "departure", "priority_level", "due", "closing_note", "reviewer"],
		)
		self.assertIn("is not a field of Note", field_findings(code, {"doc_doctype": "Note"})[0]["rule"])

	def test_real_fields_methods_and_standard_fields_pass(self):
		code = (
			'result["t"] = doc.title\n'
			'doc.db_set("public", 1)\n'
			"doc.save()\n"
			'names = frappe.get_all("ToDo", filters=[["status", "=", "Open"]], fields=["name", "description", "count(name) as n"], pluck="name")\n'
			'result["d"] = frappe.db.get_value("ToDo", names[0], ["allocated_to", "modified"])\n'
			'frappe.get_doc({"doctype": "ToDo", "description": "x", "allocated_to": "Administrator"}).insert()\n'
		)
		self.assertEqual(field_findings(code, {"doc_doctype": "Note"}), [])

	def test_a_doctype_that_does_not_exist_is_found_and_not_guessed(self):
		findings = field_findings('x = frappe.get_doc("Arrival Register", "A-1")\n', {})
		self.assertEqual(findings[0]["name"], "Arrival Register")
		self.assertIn("ask which DocType", findings[0]["rule"])

	def test_the_turn_loads_named_doctypes_with_child_tables_and_lists_missing_ones(self):
		out = doctype_inputs("Copy the ToDo records into the Arrival Register DocType", {}, "")
		self.assertEqual(list(out["doctype_fields"]), ["ToDo"])
		self.assertIn("allocated_to", out["doctype_fields"]["ToDo"]["fields"])
		self.assertEqual(out["missing_doctypes"], ["Arrival Register"])
		user = doctype_inputs("Update the User record", {}, "")["doctype_fields"]["User"]
		self.assertEqual(user["child_tables"]["roles"]["doctype"], "Has Role")
		self.assertIn("role", user["child_tables"]["roles"]["fields"])

	def test_this_record_named_in_the_request_is_the_doc_the_script_reads(self):
		out = doctype_inputs("Close this ToDo and set its due date from the Note title", {}, "")
		self.assertEqual(out["doc_doctype"], "ToDo")
		self.assertEqual(set(out["doctype_fields"]), {"ToDo", "Note"})
		self.assertEqual([f["name"] for f in field_findings("doc.due_on = 1\n", out)], ["due_on"])

	def test_a_filter_row_with_a_computed_field_is_skipped_not_a_crash(self):
		code = 'field = "status"\nrows = frappe.get_all("ToDo", filters=[["ToDo", field, "=", "Open"], ["priority", "=", 1]])\n'
		self.assertEqual(field_findings(code, {}), [])
