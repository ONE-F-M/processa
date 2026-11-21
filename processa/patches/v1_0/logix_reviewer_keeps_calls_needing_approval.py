"""Logix's reviewer keeps a network call that needs approval instead of rewriting it.

The reviewer prompts and the safety skill described requests, urllib and the other flagged items as refused.
They are flagged: the script saves and the map waits for approval. Texts already fixed are left as they are.
"""

import re

import frappe

SAFETY_SKILL = "frappe-server-script-safety"

NETWORK_RULE = re.compile(
	r"`requests`, `urllib`, `urllib3`, `http`, and `socket` are ALL blocked by the security gate.*?and never log it\.",
	re.DOTALL,
)
NETWORK_TEXT = (
	"`requests`, `urllib`, `urllib3`, `http` and `socket` are not refused. A script that uses them needs approval "
	"before its map can be deployed, and the Review Script tool names those items in its reply. Keep such a call "
	"as the draft wrote it: do not set approved=false for it and do not rewrite it to another helper. A call to "
	"make_get_request, make_post_request or make_put_request keeps the full `frappe.integrations.utils.` prefix: "
	"the bare name raises NameError and `frappe.make_get_request` raises AttributeError. Move any hardcoded API "
	"key, token or secret to a read from a Settings or Single DocType or site config, and never log it."
)

SKILL_FIXES = (
	("# What the security gate rejects\n", "# What the security check flags\n"),
	(
		"Every script is checked on save and again at deploy. A rejected script costs a retry, and after two "
		'retries the whole turn fails with "could not generate a safe script". Write it clean the first time.',
		"Every script is checked on save and again at deploy. A script that does not parse is sent back for a "
		"rewrite. An item in the list below is flagged: the script still saves, but its map cannot be deployed "
		"until the item is approved. Avoid these unless the request needs them, and keep one an existing script "
		"already uses.",
	),
	("## Always rejected\n", "## Flagged, needs approval\n"),
	(
		"- Reach an outside system only through `frappe.integrations.utils.make_get_request` / "
		"`make_post_request` / `make_put_request`, fully qualified; the frappe-outbound-http skill has the details.",
		"- In a new script, reach an outside system through `frappe.integrations.utils.make_get_request` / "
		"`make_post_request` / `make_put_request`, fully qualified; the frappe-outbound-http skill has the details. "
		"Keep a `requests` call an existing script already makes.",
	),
	("the modules in the line above stay refused.", "the modules in the line above stay flagged."),
)


def execute():
	if frappe.db.exists("AI Skill", SAFETY_SKILL):
		_save(frappe.get_doc("AI Skill", SAFETY_SKILL), [(None, "body")], skill_text)
	main = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_agent"}, "name")
	if main:
		config = frappe.get_doc("AI Agent Configuration", main)
		rows = [d for d in config.sub_prompts if d.sub_agent_id == "script_reviewer"]
		_save(config, [(row, "prompt_text") for row in rows], reviewer_text)
	reviewer = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_script_reviewer"}, "name")
	if reviewer:
		_save(frappe.get_doc("AI Agent Configuration", reviewer), [(None, "system_prompt")], reviewer_text)


def reviewer_text(text: str) -> str:
	return NETWORK_RULE.sub(lambda _m: NETWORK_TEXT, text, count=1)


def skill_text(text: str) -> str:
	for old, new in SKILL_FIXES:
		text = text.replace(old, new)
	return text


def _save(doc, fields: list, fix) -> None:
	"""Save doc through the document, so caches clear, when one of its fields held stale text."""
	changed = False
	for row, field in fields:
		target = row or doc
		text = target.get(field) or ""
		if fix(text) != text:
			target.set(field, fix(text))
			changed = True
	if changed:
		doc.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
