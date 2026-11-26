"""Report tools the Server Scripts of more than one agent call: list the reports a user can open and run one."""

import json
from datetime import date, datetime
from decimal import Decimal

import frappe
import frappe.boot
import frappe.desk.query_report

from processa.ai_agent_registry.definitions.shared.helpers import tool_envelope

CACHE_KEY_PREFIX = "processa_report_data"
CACHE_SECONDS = 3600


@tool_envelope(
	"General Chat Tool - list_reports",
	lambda module, doctype: {"error": "Failed to list reports."},
)
def list_reports(module: str | None = None, doctype: str | None = None) -> dict:
	"""The enabled reports the session user can open, optionally for one module or one reference DocType."""
	filters = {"disabled": 0}
	if module:
		filters["module"] = module
	if doctype:
		filters["ref_doctype"] = doctype

	rows = frappe.get_list(
		"Report",
		filters=filters,
		fields=["name", "module", "ref_doctype", "report_type"],
		order_by="name",
	)
	allowed_names = frappe.boot.get_allowed_report_names()
	reports = [
		row
		for row in rows
		if row.get("name") in allowed_names and frappe.has_permission(row.get("ref_doctype"), "report")
	]
	return {"count": len(reports), "reports": reports, "module": module, "doctype": doctype}


@tool_envelope(
	"General Chat Tool - get_report_data",
	lambda report_name, filters, cache: {"error": f"Failed to run report '{report_name}'."},
)
def get_report_data(report_name: str, filters: dict | None = None, cache: bool = True) -> dict:
	"""The columns, rows and message of a report the session user can open, cached per user for an hour."""
	if not frappe.db.exists("Report", report_name):
		return {"error": f"Report '{report_name}' not found"}

	try:
		frappe.desk.query_report.get_report_doc(report_name)
	except (frappe.PermissionError, frappe.ValidationError) as error:
		return {"error": str(error)}

	filters = {
		key: value[0] if isinstance(value, list) and len(value) == 1 else value
		for key, value in (filters or {}).items()
	}
	cache_key = report_cache_key(report_name, filters)

	if cache:
		cached = frappe.cache.get_value(cache_key, expires=True)
		if cached:
			return {**cached, "from_cache": True}

	result = frappe.desk.query_report.run(report_name, filters=filters)
	data = {
		"report_name": report_name,
		"columns": serialize_value(result.get("columns", [])),
		"data": serialize_value(result.get("result", [])),
		"message": serialize_value(result.get("message")),
		"from_cache": False,
	}
	if cache:
		frappe.cache.set_value(cache_key, data, expires_in_sec=CACHE_SECONDS)
	return data


def serialize_value(value):
	"""The value with dates, datetimes and Decimals turned into JSON-safe values, through lists and dicts."""
	if isinstance(value, (datetime, date)):
		return value.isoformat()
	if isinstance(value, Decimal):
		return float(value)
	if isinstance(value, (list, tuple)):
		return [serialize_value(item) for item in value]
	if isinstance(value, dict):
		return {key: serialize_value(item) for key, item in value.items()}
	return value


def report_cache_key(report_name: str, filters: dict) -> str:
	"""The cache key of one user's run of a report with these filters."""
	return ":".join(
		[
			CACHE_KEY_PREFIX,
			frappe.session.user,
			report_name,
			json.dumps(filters, sort_keys=True, default=str),
		]
	)
