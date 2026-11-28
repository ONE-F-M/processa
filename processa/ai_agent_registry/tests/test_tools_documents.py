"""The document reading tools apply the acting user's permissions, and answer a raised error with their error value."""

import json
import os
import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.shared import tools_documents as tools

MODULE_PATH = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "definitions", "shared", "tools_documents.py"
)

PREFIX = "ZZ Docs Tool"
LIMITED_USER = "zz_docs_tool_limited@example.com"
MANAGER_USER = "zz_docs_tool_manager@example.com"
UNREADABLE = "Error Log"  # a plain desk user cannot read it
UNKNOWN = "ZZ No Such DocType"
BROKEN = RuntimeError("database went away")

SOURCE = "ZZ Docs Tool Source"
LINKED_READABLE = "ZZ Docs Tool Linked Open"
LINKED_HIDDEN = "ZZ Docs Tool Linked Hidden"
CUSTOM_DOCTYPES = (LINKED_READABLE, LINKED_HIDDEN, SOURCE)

DESCRIPTION_FILTER = {"description": ["like", f"{PREFIX}%"]}


def insufficient(doctype: str) -> dict:
	return {"error": f"Insufficient permissions for DocType '{doctype}'"}


def not_found(doctype: str) -> dict:
	return {"error": f"DocType '{doctype}' not found"}


def make_user(email: str, roles: tuple = ()) -> None:
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "ZZ Docs Tool",
			"user_type": "System User",
			"send_welcome_email": 0,
		}
	)
	user.insert()
	if roles:
		user.add_roles(*roles)


def make_doctype(name: str, fields: list, permissions: list, autoname: str) -> None:
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Custom",
			"custom": 1,
			"autoname": autoname,
			"fields": fields,
			"permissions": permissions,
		}
	).insert()


def make_todo(description: str, owner: str) -> str:
	todo = frappe.get_doc({"doctype": "ToDo", "description": description, "allocated_to": owner}).insert()
	frappe.db.set_value("ToDo", todo.name, "owner", owner, update_modified=False)
	return todo.name


def delete_fixtures() -> None:
	frappe.set_user("Administrator")
	frappe.db.delete("User Permission", {"user": ["in", [LIMITED_USER, MANAGER_USER]]})
	frappe.db.delete("ToDo", {"description": ["like", f"{PREFIX}%"]})
	for name in CUSTOM_DOCTYPES:
		if frappe.db.exists("DocType", name):
			frappe.delete_doc("DocType", name, force=True)
		# Deleting the DocType may leave its table behind, and a left-over table keeps old rows.
		if frappe.db.table_exists(name):
			frappe.db.delete(name)
	for email in (LIMITED_USER, MANAGER_USER):
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
	frappe.db.commit()


class TestToolsDocuments(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		delete_fixtures()
		make_user(LIMITED_USER)
		make_user(MANAGER_USER, ("System Manager",))

		read_all = [{"role": "All", "read": 1}]
		manager_only = [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}]
		make_doctype(
			SOURCE,
			[{"fieldname": "title", "fieldtype": "Data", "label": "Title", "unique": 1}],
			read_all + manager_only,
			"field:title",
		)
		link = [{"fieldname": "source", "fieldtype": "Link", "label": "Source", "options": SOURCE}]
		make_doctype(LINKED_READABLE, link, read_all + manager_only, "hash")
		make_doctype(LINKED_HIDDEN, link, manager_only, "hash")

		cls.todo_one = make_todo(f"{PREFIX} one", LIMITED_USER)
		cls.todo_two = make_todo(f"{PREFIX} two", LIMITED_USER)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": LIMITED_USER,
				"allow": "ToDo",
				"for_value": cls.todo_one,
				"apply_to_all_doctypes": 1,
			}
		).insert()

		cls.source_name = frappe.get_doc({"doctype": SOURCE, "title": f"{PREFIX} source"}).insert().name
		cls.open_names = sorted(
			frappe.get_doc({"doctype": LINKED_READABLE, "source": cls.source_name}).insert().name
			for _ in range(2)
		)
		cls.hidden_name = frappe.get_doc({"doctype": LINKED_HIDDEN, "source": cls.source_name}).insert().name
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		delete_fixtures()
		super().tearDownClass()

	def setUp(self):
		frappe.clear_cache(user=LIMITED_USER)
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def as_limited_user(self):
		frappe.clear_cache(user=LIMITED_USER)
		frappe.set_user(LIMITED_USER)

	def test_user_permission_limits_get_list_and_its_count(self):
		self.as_limited_user()
		result = tools.get_list("ToDo", filters=DESCRIPTION_FILTER)
		self.assertEqual([row.name for row in result["data"]], [self.todo_one])
		self.assertEqual(result["count"], 1)
		self.assertEqual(result["page_count"], 1)

	def test_user_permission_limits_get_count(self):
		self.as_limited_user()
		self.assertEqual(tools.get_count("ToDo", DESCRIPTION_FILTER)["count"], 1)

	def test_user_permission_limits_query_documents(self):
		self.as_limited_user()
		result = tools.query_documents("ToDo", filters=DESCRIPTION_FILTER, fields=["name"])
		self.assertEqual([row.name for row in result["data"]], [self.todo_one])
		self.assertEqual(result["count"], 1)

	def test_user_permission_limits_query_doctypes(self):
		self.as_limited_user()
		rows = json.loads(tools.query_doctypes("ToDo", filters=DESCRIPTION_FILTER))
		self.assertEqual(rows, [{"name": self.todo_one}])

	def test_every_tool_refuses_a_doctype_the_user_cannot_read(self):
		self.as_limited_user()
		error = insufficient(UNREADABLE)
		self.assertEqual(tools.get_list(UNREADABLE), error)
		self.assertEqual(tools.get_count(UNREADABLE), error)
		self.assertEqual(tools.query_documents(UNREADABLE), error)
		self.assertEqual(tools.get_linked_documents(UNREADABLE, "anything"), error)
		self.assertEqual(json.loads(tools.query_doctypes(UNREADABLE)), error)

	def test_two_users_each_get_the_count_of_the_rows_they_can_read(self):
		def count_as(user: str) -> int:
			frappe.clear_cache(user=user)
			frappe.set_user(user)
			return tools.get_count("ToDo", DESCRIPTION_FILTER)["count"]

		self.assertEqual(count_as(LIMITED_USER), 1)
		self.assertEqual(count_as(MANAGER_USER), 2)
		self.assertEqual(count_as(LIMITED_USER), 1)
		self.assertEqual(count_as(MANAGER_USER), 2)

	def test_linked_documents_hold_only_what_the_user_can_read(self):
		self.as_limited_user()
		result = tools.get_linked_documents(SOURCE, self.source_name)
		self.assertEqual(result["source_doctype"], SOURCE)
		self.assertEqual(result["source_name"], self.source_name)
		self.assertEqual({row["doctype"] for row in result["linked_documents"]}, {LINKED_READABLE})
		self.assertEqual(sorted(row["name"] for row in result["linked_documents"]), self.open_names)
		self.assertEqual({row["fieldname"] for row in result["linked_documents"]}, {"source"})

	def test_linked_documents_hold_the_hidden_doctype_for_a_user_who_can_read_it(self):
		frappe.set_user(MANAGER_USER)
		result = tools.get_linked_documents(SOURCE, self.source_name)
		self.assertIn(
			{"doctype": LINKED_HIDDEN, "name": self.hidden_name, "fieldname": "source"},
			result["linked_documents"],
		)

	def test_linked_documents_of_a_missing_document_is_not_found(self):
		self.assertEqual(
			tools.get_linked_documents(SOURCE, "ZZ No Such Document"),
			{"error": f"Document 'ZZ No Such Document' of type '{SOURCE}' not found"},
		)

	def test_shapes_as_administrator(self):
		listed = tools.get_list("ToDo", filters=DESCRIPTION_FILTER)
		self.assertEqual(
			set(listed),
			{"doctype", "data", "count", "page_count", "limit_start", "limit_page_length"},
		)
		self.assertEqual((listed["doctype"], listed["count"], listed["page_count"]), ("ToDo", 2, 2))
		self.assertEqual((listed["limit_start"], listed["limit_page_length"]), (0, 20))

		counted = tools.get_count("ToDo", DESCRIPTION_FILTER)
		self.assertEqual(set(counted), {"doctype", "count", "filters"})
		self.assertEqual(counted["filters"], DESCRIPTION_FILTER)
		self.assertEqual(tools.get_count("ToDo")["filters"], {})

		queried = tools.query_documents("ToDo", filters=DESCRIPTION_FILTER)
		self.assertEqual(set(queried), {"doctype", "data", "count"})
		self.assertEqual(queried["count"], 2)
		self.assertIn("description", queried["data"][0])

		linked = tools.get_linked_documents(SOURCE, self.source_name)
		self.assertEqual(set(linked), {"source_doctype", "source_name", "linked_documents"})
		self.assertEqual(len(linked["linked_documents"]), 3)
		self.assertEqual(set(linked["linked_documents"][0]), {"doctype", "name", "fieldname"})

		rows = json.loads(tools.query_doctypes("ToDo", filters=DESCRIPTION_FILTER))
		self.assertEqual(sorted(row["name"] for row in rows), sorted([self.todo_one, self.todo_two]))

	def test_query_doctypes_resolves_a_name_that_differs_in_case(self):
		rows = json.loads(tools.query_doctypes("todo", filters=DESCRIPTION_FILTER))
		self.assertEqual(len(rows), 2)

	def test_every_tool_answers_not_found_for_an_unknown_doctype(self):
		error = not_found(UNKNOWN)
		self.assertEqual(tools.get_list(UNKNOWN), error)
		self.assertEqual(tools.get_count(UNKNOWN), error)
		self.assertEqual(tools.query_documents(UNKNOWN), error)
		self.assertEqual(tools.get_linked_documents(UNKNOWN, "anything"), error)
		self.assertEqual(json.loads(tools.query_doctypes(UNKNOWN)), error)

	def test_query_doctypes_limit_is_capped_at_50(self):
		self.addCleanup(frappe.db.delete, "ToDo", {"description": ["like", f"{PREFIX} bulk%"]})
		for index in range(55):
			make_todo(f"{PREFIX} bulk {index}", "Administrator")
		self.assertEqual(
			len(json.loads(tools.query_doctypes("ToDo", filters=DESCRIPTION_FILTER, limit=500))), 50
		)
		self.assertEqual(
			len(json.loads(tools.query_doctypes("ToDo", filters=DESCRIPTION_FILTER, limit=0))), 50
		)
		self.assertEqual(
			len(json.loads(tools.query_doctypes("ToDo", filters=DESCRIPTION_FILTER, limit=3))), 3
		)

	def test_a_raising_tool_returns_its_error_value_and_writes_one_error_log(self):
		cases = (
			("get_list", lambda: tools.get_list("ToDo"), {"doctype": "ToDo"}),
			("get_count", lambda: tools.get_count("ToDo"), {"doctype": "ToDo"}),
			("query_documents", lambda: tools.query_documents("ToDo"), {"doctype": "ToDo"}),
			(
				"get_linked_documents",
				lambda: tools.get_linked_documents("User", "Administrator"),
				{"doctype": "User"},
			),
			("query_doctypes", lambda: tools.query_doctypes("ToDo"), {"doctype": "ToDo"}),
		)
		for name, call, arguments in cases:
			with self.subTest(tool=name):
				title = f"Shared Tool - {name}"
				before = frappe.db.count("Error Log", {"method": title})
				real_get_list = frappe.get_list

				def broken_get_list(doctype, *args, **kwargs):
					# Only the tool's own read fails; writing the Error Log row may read through get_list too.
					if doctype in ("ToDo", "User"):
						raise BROKEN
					return real_get_list(doctype, *args, **kwargs)

				with patch.object(frappe, "get_list", side_effect=broken_get_list):
					result = call()
				expected = {"error": f"Failed to run {name} on DocType '{arguments['doctype']}'."}
				self.assertEqual(json.loads(result) if isinstance(result, str) else result, expected)
				self.assertEqual(isinstance(result, str), name == "query_doctypes")
				self.assertEqual(frappe.db.count("Error Log", {"method": title}), before + 1)

	def test_the_module_reads_through_get_list_only(self):
		with open(MODULE_PATH, encoding="utf-8") as handle:
			source = handle.read()
		for forbidden in (
			"frappe.db.sql",
			"frappe.db.count",
			"frappe.db.get_all",
			"@frappe.whitelist",
			"ignore_permissions",
			"frappe.db.commit",
			"frappe.cache",
		):
			self.assertNotIn(forbidden, source)
		get_all_calls = re.findall(r"frappe\.get_all\(\s*(\S+)", source)
		self.assertTrue(get_all_calls)
		self.assertEqual(set(get_all_calls), {'"DocType",'})
		self.assertLess(source.count("\n") + 1, 800)
