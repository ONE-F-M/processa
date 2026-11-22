"""Revoke sharing on the google_drive connector gets an optional role, so a step can remove writer grants and keep readers."""

import frappe

OPERATION = "google_drive-revokePermissions"

ROLE_FIELD = {
	"field_name": "role",
	"field_label": "Only this role",
	"field_type": "Dropdown",
	"expression": 1,
	"choices": "Writer|writer\nCommenter|commenter\nReader|reader",
	"help_text": "Optional. Leave blank to revoke grants of every role; choose Writer to take edit rights away and keep readers.",
}


def execute():
	if not frappe.db.exists("BPMN Connector Operation", OPERATION):
		return
	op = frappe.get_doc("BPMN Connector Operation", OPERATION)
	if any(f.field_name == "role" for f in op.fields):
		return
	op.append("fields", ROLE_FIELD)
	op.save(ignore_permissions=True)  # patch: connector configuration
