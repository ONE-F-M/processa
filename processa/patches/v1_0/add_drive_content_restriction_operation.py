"""The google_drive connector gets Lock or unlock file (setContentRestriction) on a site that already has it.

Drive refuses a reason unless readOnly is true, so the body sends the reason only when locking.
"""

import frappe

from processa.processa_connectors.seed import import_operation

DRIVE_ID = "processa.processa_connectors.google.common.normalize_drive_id"

OPERATION = {
	"value": "setContentRestriction",
	"label": "Lock or unlock file",
	"method": "files.update",
	"description": (
		"Locks a file so nobody can edit it, or lifts the lock. Use it while a document is under approval "
		"or once it is published. Locking a locked file, or unlocking an unlocked one, is accepted. "
		"A shared drive Manager can still lift the lock from the Drive UI."
	),
	"executionType": "HTTP Request",
	"http": {
		"method": "PATCH",
		"url": "files/{{ params.file }}",
		"query": {"supportsAllDrives": "true", "fields": "id,name,contentRestrictions"},
		"contentType": "application/json",
		"body": (
			'{%- set r = {"readOnly": params.readOnly} -%}'
			'{%- if params.readOnly and params.reason %}{% set _ = r.update({"reason": params.reason}) %}{% endif -%}'
			'{{ {"contentRestrictions": [r]} | tojson }}'
		),
		"responseMap": {
			"id": "id",
			"name": "name",
			"readOnly": "contentRestrictions[0].readOnly",
			"reason": "contentRestrictions[0].reason",
		},
	},
	"output": {
		"id": "File id",
		"name": "File name",
		"readOnly": "true when the file is now locked; empty when it has no lock",
		"reason": "Why it is locked",
	},
	"fields": [
		{
			"name": "file",
			"label": "File",
			"type": "String",
			"required": True,
			"transform": DRIVE_ID,
			"help": "The file to lock or unlock. Paste its link or id.",
		},
		{
			"name": "readOnly",
			"label": "Lock the file",
			"type": "Boolean",
			"required": True,
			"default": True,
			"transform": "frappe.utils.sbool",
			"help": "On locks the file. Off lifts the lock.",
		},
		{
			"name": "reason",
			"label": "Reason",
			"type": "String",
			"help": "Shown in Drive on the locked file, for example Under approval or Published. Only sent when locking.",
		},
	],
}


def execute():
	if not frappe.db.exists("BPMN Connector", "google_drive"):
		return
	import_operation("google_drive", OPERATION, 9)
