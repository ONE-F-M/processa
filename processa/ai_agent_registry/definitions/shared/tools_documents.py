"""Document reading tools the Server Scripts of more than one agent call, with the acting user's permissions applied.

These are plain functions, not whitelisted: a Server Script imports them and they run as the acting user.
Every row and every count is read with frappe.get_list, which applies the user's role permissions and User Permissions.
"""

import json

import frappe

from processa.ai_agent_registry.definitions.shared.helpers import tool_envelope

QUERY_DOCTYPES_MAX_ROWS = 50


def _not_found(doctype: str) -> dict:
	return {"error": f"DocType '{doctype}' not found"}


def _no_permission(doctype: str) -> dict:
	return {"error": f"Insufficient permissions for DocType '{doctype}'"}


def _failed(function_name: str, doctype) -> dict:
	return {"error": f"Failed to run {function_name} on DocType '{doctype}'."}


def _readable_count(doctype: str, filters: dict | None) -> int:
	"""The number of rows of the DocType the user can read that match the filters."""
	return frappe.get_list(doctype, filters=filters or {}, fields=["count(name) as total"])[0].total


@tool_envelope("Shared Tool - get_list", lambda doctype, **_: _failed("get_list", doctype))
def get_list(
	doctype: str,
	filters: dict | None = None,
	fields: list[str] | None = None,
	limit_start: int = 0,
	limit_page_length: int = 20,
	order_by: str | None = None,
) -> dict:
	"""One page of the documents of a DocType the user can read, with the number of readable documents that match."""
	if not frappe.db.exists("DocType", doctype):
		return _not_found(doctype)
	if not frappe.has_permission(doctype, "read"):
		return _no_permission(doctype)

	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=fields or ["name"],
		start=limit_start,
		page_length=limit_page_length,
		order_by=order_by or "modified desc",
	)
	return {
		"doctype": doctype,
		"data": rows,
		"count": _readable_count(doctype, filters),
		"page_count": len(rows),
		"limit_start": limit_start,
		"limit_page_length": limit_page_length,
	}


@tool_envelope("Shared Tool - get_count", lambda doctype, **_: _failed("get_count", doctype))
def get_count(doctype: str, filters: dict | None = None) -> dict:
	"""The number of documents of a DocType that match the filters and that the user can read."""
	if not frappe.db.exists("DocType", doctype):
		return _not_found(doctype)
	if not frappe.has_permission(doctype, "read"):
		return _no_permission(doctype)

	return {"doctype": doctype, "count": _readable_count(doctype, filters), "filters": filters or {}}


@tool_envelope("Shared Tool - query_documents", lambda doctype, **_: _failed("query_documents", doctype))
def query_documents(
	doctype: str,
	filters: dict | None = None,
	fields: list[str] | None = None,
	group_by: str | None = None,
	order_by: str | None = None,
	limit: int = 0,
) -> dict:
	"""The documents of a DocType the user can read. Filters are {"field": value} or {"field": [operator, value]}; limit 0 is no limit."""
	if not frappe.db.exists("DocType", doctype):
		return _not_found(doctype)
	if not frappe.has_permission(doctype, "read"):
		return _no_permission(doctype)

	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=fields or ["*"],
		group_by=group_by,
		order_by=order_by,
		limit_page_length=limit or None,
	)
	return {"doctype": doctype, "data": rows, "count": len(rows)}


def _link_field_parents(doctype: str) -> list[tuple[str, str]]:
	"""(DocType, fieldname) of every Link field, standard or custom, whose options are the DocType."""
	pairs = {
		(row["parent"], row["fieldname"])
		for row in frappe.db.get_values(
			"DocField",
			{"fieldtype": "Link", "options": doctype, "parenttype": "DocType"},
			["parent", "fieldname"],
			as_dict=True,
		)
	}
	pairs |= {
		(row["dt"], row["fieldname"])
		for row in frappe.db.get_values(
			"Custom Field",
			{"fieldtype": "Link", "options": doctype},
			["dt", "fieldname"],
			as_dict=True,
		)
	}
	if not pairs:
		return []
	# Single and child DocTypes have no rows of their own to link from.
	eligible = {
		row.name
		for row in frappe.get_all(
			"DocType",
			filters={"name": ["in", sorted({parent for parent, _ in pairs})], "issingle": 0, "istable": 0},
			fields=["name"],
		)
	}
	return sorted(pair for pair in pairs if pair[0] in eligible)


@tool_envelope("Shared Tool - get_linked_documents", lambda doctype, **_: _failed("get_linked_documents", doctype))
def get_linked_documents(doctype: str, name: str) -> dict:
	"""The documents the user can read that link to the document, found through the Link fields of every DocType."""
	if not frappe.db.exists("DocType", doctype):
		return _not_found(doctype)
	if not frappe.has_permission(doctype, "read"):
		return _no_permission(doctype)
	if not frappe.db.exists(doctype, name) or not frappe.has_permission(doctype, "read", doc=name):
		return {"error": f"Document '{name}' of type '{doctype}' not found"}

	linked = []
	readable = {}
	for linking_doctype, fieldname in _link_field_parents(doctype):
		if linking_doctype not in readable:
			readable[linking_doctype] = bool(frappe.has_permission(linking_doctype, "read"))
		if not readable[linking_doctype]:
			continue
		for row in frappe.get_list(linking_doctype, filters={fieldname: name}, fields=["name"]):
			linked.append({"doctype": linking_doctype, "name": row.name, "fieldname": fieldname})
	return {"source_doctype": doctype, "source_name": name, "linked_documents": linked}


def _resolve_doctype_name(doctype: str) -> str | None:
	"""The DocType's exact name: an exact match, a case-insensitive match, or the one DocType that contains the text."""
	if frappe.db.exists("DocType", doctype):
		return doctype
	matched = frappe.db.get_value("DocType", {"name": ["like", doctype]}, "name")
	if matched:
		return matched
	candidates = frappe.get_all(
		"DocType",
		filters={"name": ["like", f"%{doctype}%"], "istable": 0},
		fields=["name"],
		limit=2,
	)
	return candidates[0].name if len(candidates) == 1 else None


@tool_envelope(
	"Shared Tool - query_doctypes",
	lambda doctype, **_: json.dumps(_failed("query_doctypes", doctype)),
)
def query_doctypes(
	doctype: str,
	filters: dict | None = None,
	fields: list[str] | None = None,
	order_by: str | None = None,
	limit: int = 20,
) -> str:
	"""The documents of a DocType the user can read, as JSON, at most 50. The DocType name may be partial."""
	resolved = _resolve_doctype_name(doctype)
	if not resolved:
		return json.dumps(_not_found(doctype))
	if not frappe.has_permission(resolved, "read"):
		return json.dumps(_no_permission(resolved))

	# A page length of 0 would mean no limit to frappe.get_list, so 0 and below fall back to the cap.
	page_length = min(limit, QUERY_DOCTYPES_MAX_ROWS) if limit > 0 else QUERY_DOCTYPES_MAX_ROWS
	rows = frappe.get_list(
		resolved,
		filters=filters,
		fields=fields or ["name"],
		order_by=order_by,
		limit_page_length=page_length,
	)
	return json.dumps(rows, default=str)
