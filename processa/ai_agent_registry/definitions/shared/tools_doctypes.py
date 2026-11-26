"""DocType, module and permission lookups for the General Chat and BA Agent maps, in the onefm_mcp output shapes."""

import json

import frappe
from frappe import _

from processa.ai_agent_registry.definitions.shared.helpers import tool_envelope


@tool_envelope(
	"DocType Tool - check_doctype_exists",
	lambda doctype_name: {
		"status": "failure",
		"exists": False,
		"message": f"Error checking DocType '{doctype_name}'.",
	},
)
def check_doctype_exists(doctype_name: str) -> dict:
	"""Whether a DocType exists, with a status and message."""
	if frappe.db.exists("DocType", doctype_name):
		return {"status": "success", "exists": True, "message": f"DocType '{doctype_name}' exists."}
	return {"status": "failure", "exists": False, "message": f"DocType '{doctype_name}' does not exist."}


@tool_envelope(
	"DocType Tool - check_module_exists",
	lambda module_name: {
		"status": "failure",
		"exists": False,
		"message": f"Error checking Module '{module_name}'.",
	},
)
def check_module_exists(module_name: str) -> dict:
	"""Whether a Module Def exists, with a status and message."""
	if frappe.db.exists("Module Def", module_name):
		return {"status": "success", "exists": True, "message": f"Module '{module_name}' exists."}
	return {"status": "failure", "exists": False, "message": f"Module '{module_name}' does not exist."}


@tool_envelope(
	"DocType Tool - check_permission",
	lambda doctype, name, ptype: {"error": f"Failed to check {ptype} permission on {doctype}."},
)
def check_permission(doctype: str, name: str | None = None, ptype: str = "read") -> dict:
	"""Whether the session user has ptype on a DocType, or on one document of it when name is given."""
	if not frappe.db.exists("DocType", doctype):
		return {"error": f"DocType '{doctype}' not found"}
	if name and not frappe.db.exists(doctype, name):
		return {"error": f"{doctype} '{name}' not found"}

	return {
		"doctype": doctype,
		"name": name,
		"permission_type": ptype,
		"has_permission": bool(frappe.has_permission(doctype, ptype, doc=name)),
	}


@tool_envelope(
	"DocType Tool - get_doctype_list",
	lambda module: {"error": "Failed to list DocTypes."},
)
def get_doctype_list(module: str | None = None) -> dict:
	"""The DocTypes the user can see (name, module, is_submittable), optionally in one module."""
	filters = {"module": module} if module else {}
	doctypes = frappe.get_list(
		"DocType", filters=filters, fields=["name", "module", "is_submittable"], order_by="name"
	)
	return {"count": len(doctypes), "doctypes": doctypes, "module_filter": module}


@tool_envelope(
	"DocType Tool - list_available_doctypes",
	lambda module, search: json.dumps({"error": "Failed to list DocTypes."}),
)
def list_available_doctypes(module: str | None = None, search: str | None = None) -> str:
	"""Non-child DocTypes the user can see as JSON, filtered by module and a name search."""
	filters = {"istable": 0}
	if module:
		filters["module"] = module
	if search:
		filters["name"] = ["like", f"%{search}%"]

	doctypes = frappe.get_list(
		"DocType",
		filters=filters,
		fields=["name", "module", "description", "is_submittable"],
		order_by="name",
		limit_page_length=100 if search else 1000,
	)
	return json.dumps(doctypes, default=str)


@tool_envelope(
	"DocType Tool - get_doctype_schema",
	lambda doctype: json.dumps({"error": f"Failed to read the schema of DocType '{doctype}'."}),
)
def get_doctype_schema(doctype: str) -> str:
	"""Fields, permissions and links of a DocType as JSON; the name may be partial or in any case."""
	resolved = _resolve_doctype_name(doctype)
	if not resolved:
		return json.dumps(
			{
				"error": f"DocType '{doctype}' not found. Try search_codebase or list_available_doctypes if unsure of the exact name."
			}
		)
	if not frappe.has_permission(resolved, "read"):
		return json.dumps({"error": _("You do not have permission to read DocType {0}.").format(resolved)})

	meta = frappe.get_meta(resolved)
	schema = {
		"name": meta.name,
		"module": meta.module,
		"is_submittable": meta.is_submittable,
		"istable": meta.istable,
		"fields": [
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label,
				"options": f.options,
				"reqd": f.reqd,
				"unique": f.unique,
				"in_list_view": f.in_list_view,
				"search_index": f.search_index,
			}
			for f in meta.fields
			if not f.get("hidden")
		],
		"permissions": [
			{
				"role": p.role,
				"read": p.read,
				"write": p.write,
				"create": p.create,
				"delete": p.delete,
				"submit": p.submit,
				"cancel": p.cancel,
				"amend": p.amend,
			}
			for p in meta.permissions
		],
		"links": [
			{"link_doctype": link.link_doctype, "link_fieldname": link.link_fieldname, "group": link.group}
			for link in meta.links
		],
	}
	return json.dumps(schema, default=str)


def _resolve_doctype_name(doctype: str) -> str | None:
	"""The stored DocType name for doctype in any case, else the only non-child partial match."""
	if name := frappe.db.exists("DocType", doctype):
		return name

	matches = frappe.get_list(
		"DocType", filters={"name": ["like", f"%{doctype}%"], "istable": 0}, pluck="name", limit=2
	)
	return matches[0] if len(matches) == 1 else None
