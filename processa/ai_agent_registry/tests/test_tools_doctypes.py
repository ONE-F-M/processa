# Copyright (c) 2026, one-fm and contributors
"""The DocType tools for General Chat and the BA Agent answer in the onefm_mcp shapes and respect read permission."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.shared import tools_doctypes as tools

MISSING = "ZZ No Such DocType"


class TestExistenceChecks(FrappeTestCase):
	def test_doctype_found_and_missing(self):
		self.assertEqual(
			tools.check_doctype_exists("ToDo"),
			{"status": "success", "exists": True, "message": "DocType 'ToDo' exists."},
		)
		self.assertEqual(
			tools.check_doctype_exists(MISSING),
			{"status": "failure", "exists": False, "message": f"DocType '{MISSING}' does not exist."},
		)

	def test_module_found_and_missing(self):
		self.assertEqual(
			tools.check_module_exists("Desk"),
			{"status": "success", "exists": True, "message": "Module 'Desk' exists."},
		)
		self.assertEqual(
			tools.check_module_exists("ZZ Module"),
			{"status": "failure", "exists": False, "message": "Module 'ZZ Module' does not exist."},
		)


class TestPermissionCheck(FrappeTestCase):
	def test_granted_for_administrator(self):
		self.assertEqual(
			tools.check_permission("ToDo"),
			{"doctype": "ToDo", "name": None, "permission_type": "read", "has_permission": True},
		)

	def test_refused_for_a_user_without_the_permission(self):
		with self.set_user("Guest"):
			result = tools.check_permission("ToDo", ptype="write")
		self.assertFalse(result["has_permission"])

	def test_missing_doctype_and_document(self):
		self.assertEqual(tools.check_permission(MISSING), {"error": f"DocType '{MISSING}' not found"})
		self.assertEqual(
			tools.check_permission("ToDo", name="ZZ-NONE"), {"error": "ToDo 'ZZ-NONE' not found"}
		)


class TestDocTypeLists(FrappeTestCase):
	def test_doctype_list_for_a_module(self):
		result = tools.get_doctype_list("Desk")
		self.assertEqual(result["module_filter"], "Desk")
		self.assertEqual(result["count"], len(result["doctypes"]))
		self.assertIn("ToDo", [row.name for row in result["doctypes"]])
		self.assertEqual({row.module for row in result["doctypes"]}, {"Desk"})

	def test_available_doctypes_leave_out_child_tables(self):
		rows = json.loads(tools.list_available_doctypes(search="ToDo"))
		self.assertIn("ToDo", [row["name"] for row in rows])
		self.assertEqual(set(rows[0]), {"name", "module", "description", "is_submittable"})
		child_tables = set(frappe.get_all("DocType", filters={"istable": 1}, pluck="name"))
		self.assertFalse(child_tables & {row["name"] for row in json.loads(tools.list_available_doctypes())})


class TestDocTypeSchema(FrappeTestCase):
	def test_resolves_a_lower_case_name(self):
		schema = json.loads(tools.get_doctype_schema("todo"))
		self.assertEqual(schema["name"], "ToDo")
		self.assertEqual(
			set(schema), {"name", "module", "is_submittable", "istable", "fields", "permissions", "links"}
		)
		self.assertIn("description", [f["fieldname"] for f in schema["fields"]])

	def test_unknown_name(self):
		self.assertEqual(
			json.loads(tools.get_doctype_schema(MISSING)),
			{
				"error": f"DocType '{MISSING}' not found. Try search_codebase or list_available_doctypes if unsure of the exact name."
			},
		)

	def test_refused_without_read_permission(self):
		with self.set_user("Guest"):
			result = json.loads(tools.get_doctype_schema("ToDo"))
		self.assertIn("permission", result["error"])
		self.assertNotIn("fields", result)
