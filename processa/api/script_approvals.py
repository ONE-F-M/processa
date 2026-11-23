"""The Logix calls for script security: each finding with its approval state, and raising a request."""

import frappe
from frappe import _

from processa.ai_agent_security.code_checks.script_gate import lint_script
from processa.ai_agent_security.doctype.script_approval_request.script_approval_request import (
	approval_instances,
)
from processa.processa_engine.triggers import on_doc_event


@frappe.whitelist()
def lint_server_script(
	code: str = "", script_name: str = "", process: str = "", script_task: str = ""
) -> dict:
	"""Each finding in the code with its category, line and approval state, and the script task's status."""
	result = lint_script(code, script_name, process, script_task)
	result["violations"] = [f["message"] for f in result["findings"] if not f["approved"]]
	result["valid"] = not result["violations"]
	return result


@frappe.whitelist(methods=["POST"])
def request_script_approval(
	server_script: str, process: str, script_task: str, reason: str = "", script_task_label: str = ""
) -> dict:
	"""Raise a Script Approval Request for one script task from its saved Server Script."""
	frappe.get_doc("Server Script", server_script).check_permission("write")
	if not (reason or "").strip():
		frappe.throw(_("Say why this script needs the items it uses."))
	request = frappe.get_doc(
		{
			"doctype": "Script Approval Request",
			"process_name": process,
			"script_task": script_task,
			"script_task_label": script_task_label,
			"server_script": server_script,
			"reason": reason.strip(),
		}
	).insert()
	return {"name": request.name, "status": request.status}


@frappe.whitelist(methods=["POST"])
def update_script_approval(request: str) -> dict:
	"""Refresh a Pending Review request's items and script copy from its saved Server Script."""
	doc = frappe.get_doc("Script Approval Request", request)
	doc.check_permission("write")
	script = frappe.get_doc("Server Script", doc.server_script)
	script.check_permission("write")
	if doc.requested_by != frappe.session.user:
		frappe.throw(
			_("Only {0}, who raised {1}, can update it.").format(doc.requested_by, doc.name),
			frappe.PermissionError,
		)
	if doc.status != "Pending Review":
		frappe.throw(
			_("{0} is {1}, so it can no longer be updated. Request the rest after it is decided.").format(
				doc.name, doc.status
			)
		)
	doc.set_requested_items(script.script)
	doc.script_at_time_of_request = script.script
	doc.save()
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def retry_script_approval(request: str) -> dict:
	"""Start the Script Security Approval process for a request whose start did not happen."""
	doc = frappe.get_doc("Script Approval Request", request)
	doc.check_permission("read")
	if not approval_instances(doc.name):
		on_doc_event(doc, "after_insert")
	return {"started": bool(approval_instances(doc.name))}
