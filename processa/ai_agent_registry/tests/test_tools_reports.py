"""The report tools list and run only what the session user can open, and cache rows per user."""

import json
from datetime import date, datetime
from decimal import Decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.shared.tools_reports import (
	CACHE_KEY_PREFIX,
	get_report_data,
	list_reports,
	serialize_value,
)

REPORT = "ToDo"
OUTSIDER = "zz_report_outsider@example.com"


class TestToolsReports(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", OUTSIDER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OUTSIDER,
					"first_name": "Outsider",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")
		self._clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._clear_cache()

	def _clear_cache(self):
		for key in frappe.cache.get_keys(CACHE_KEY_PREFIX):
			frappe.cache.delete_value(key.decode() if isinstance(key, bytes) else key)

	def test_the_report_data_has_the_documented_keys(self):
		result = get_report_data(REPORT, cache=False)
		self.assertEqual(
			set(result), {"report_name", "columns", "data", "message", "from_cache"}
		)
		self.assertEqual(result["report_name"], REPORT)
		self.assertFalse(result["from_cache"])
		self.assertIsInstance(result["columns"], list)
		self.assertIsInstance(result["data"], list)
		json.dumps(result)

	def test_a_one_item_list_filter_is_replaced_by_its_item(self):
		self.assertEqual(
			get_report_data(REPORT, {"status": ["Open"]}, cache=False)["data"],
			get_report_data(REPORT, {"status": "Open"}, cache=False)["data"],
		)

	def test_a_report_the_user_cannot_open_returns_an_error_without_data(self):
		frappe.set_user(OUTSIDER)
		result = get_report_data(REPORT)
		self.assertIn("error", result)
		self.assertNotIn("data", result)
		self.assertNotIn("columns", result)

	def test_the_cache_is_never_served_to_another_user(self):
		self.assertFalse(get_report_data(REPORT, cache=True)["from_cache"])
		self.assertTrue(get_report_data(REPORT, cache=True)["from_cache"])

		frappe.set_user(OUTSIDER)
		result = get_report_data(REPORT, cache=True)
		self.assertIn("error", result)
		self.assertNotIn("data", result)

	def test_a_second_call_by_the_same_user_comes_from_the_cache(self):
		first = get_report_data(REPORT, cache=True)
		second = get_report_data(REPORT, cache=True)
		self.assertFalse(first["from_cache"])
		self.assertTrue(second["from_cache"])
		self.assertEqual(second["data"], first["data"])

	def test_cache_false_does_not_store_or_read(self):
		get_report_data(REPORT, cache=False)
		self.assertFalse(get_report_data(REPORT, cache=True)["from_cache"])

	def test_a_missing_report_returns_not_found(self):
		self.assertEqual(
			get_report_data("ZZ No Such Report"), {"error": "Report 'ZZ No Such Report' not found"}
		)

	def test_the_list_holds_the_reports_an_administrator_can_open(self):
		result = list_reports()
		self.assertEqual(result["count"], len(result["reports"]))
		self.assertIn(REPORT, [row["name"] for row in result["reports"]])
		self.assertEqual(
			set(result["reports"][0]), {"name", "module", "ref_doctype", "report_type"}
		)
		self.assertIsNone(result["module"])
		self.assertIsNone(result["doctype"])

	def test_the_list_can_be_narrowed_by_doctype(self):
		result = list_reports(doctype="ToDo")
		self.assertEqual(result["doctype"], "ToDo")
		self.assertTrue(result["reports"])
		self.assertTrue(all(row["ref_doctype"] == "ToDo" for row in result["reports"]))

	def test_the_list_leaves_out_reports_on_a_doctype_the_user_cannot_report_on(self):
		frappe.set_user(OUTSIDER)
		result = list_reports()
		self.assertNotIn("ToDo", [row["ref_doctype"] for row in result["reports"]])
		self.assertEqual(result["count"], len(result["reports"]))

	def test_serialize_value_makes_values_json_safe(self):
		value = {
			"day": date(2024, 1, 31),
			"moment": datetime(2024, 1, 31, 8, 30),
			"amount": Decimal("12.50"),
			"nested": {"rows": [date(2024, 2, 1), (Decimal("1.5"), "text", None)]},
		}
		expected = {
			"day": "2024-01-31",
			"moment": "2024-01-31T08:30:00",
			"amount": 12.5,
			"nested": {"rows": ["2024-02-01", [1.5, "text", None]]},
		}
		self.assertEqual(serialize_value(value), expected)
		json.dumps(serialize_value(value))
