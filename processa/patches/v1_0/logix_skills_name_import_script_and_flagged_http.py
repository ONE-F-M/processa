"""Logix's script task contract names import_script and _, and the outbound HTTP skill treats requests as flagged.

Each fix replaces the exact stale text, so a skill already fixed is left as it is.
"""

import frappe

FIXES = {
	"bpmn-script-task-contract": (
		(
			"- `instance` and `bpmn_id`: the process instance and this shape's id. Only needed when the script "
			"calls a model itself (see the skill for that); ignore them otherwise.\n",
			"- `instance` and `bpmn_id`: the process instance and this shape's id. Only needed when the script "
			"calls a model itself (see the skill for that); ignore them otherwise.\n"
			'- `import_script`: loads a library script on the same map. `lib = import_script("<library name>")`, '
			"then `lib.<function>(...)`.\n"
			'- `_`: the translate function, as in any Server Script. Wrap a message the person sees: `frappe.throw(_("..."))`.\n',
		),
	),
	"frappe-outbound-http": (
		(
			"Never `import requests`, `urllib`, `urllib3`, `http` or `socket`. The security gate rejects the script "
			"on save. Call Frappe's helpers instead, by their FULLY QUALIFIED name:",
			"`requests`, `urllib`, `urllib3`, `http` and `socket` are not refused: the script saves, but its map "
			"cannot be deployed until they are approved. Keep such a call when an existing script already makes it. "
			"A new call goes through Frappe's helpers, by their FULLY QUALIFIED name:",
		),
	),
}


def execute():
	for skill, fixes in FIXES.items():
		if not frappe.db.exists("AI Skill", skill):
			continue
		doc = frappe.get_doc("AI Skill", skill)
		body = fixed(doc.body or "", fixes)
		if body != (doc.body or ""):
			doc.body = body
			doc.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def fixed(text: str, fixes: tuple) -> str:
	"""The text with each stale passage replaced, unless its new text is already there."""
	for old, new in fixes:
		if new not in text:
			text = text.replace(old, new)
	return text
