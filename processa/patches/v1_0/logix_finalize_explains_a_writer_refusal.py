"""Logix's finalize step explains a writer the AI model declined, instead of asking what the script should do.

When the writer's run ended with MODEL_REFUSED there is no draft, and the old reply asked for details the person
had already given. Each edit runs once; a script without the anchor is logged and left as it is.
"""

import frappe

SCRIPT = "Logix \u2013 Tool Finalize"
MISSING_ANCHOR = "_MISSING = (\n"
REFUSED = (
	"_REFUSED = (\n"
	'    "I did not write this script. The request includes a step a Server Script may not run, such as a shell "\n'
	'    "command, so the AI model declined it. Ask for the result you need without that step instead."\n'
	")\n"
)
EMPTY_OLD = (
	"    elif not _final_text:\n"
	"        update_turn(context_docname, output={\n"
	'            "intent": "DISAMBIGUATE", "response": _MISSING, "diff": None,\n'
)
EMPTY_NEW = (
	"    elif not _final_text:\n"
	'        _inst = frappe.db.get_value("BPMN Process Instance", {"context_docname": context_docname}, "name", '
	'order_by="creation desc")\n'
	'        _refused = bool(_inst and frappe.get_all("AI Agent Run", filters={"instance": _inst, '
	'"bpmn_id": ["in", ["write_script", "write_agent_tool"]], "error_code": "MODEL_REFUSED"}, limit=1))\n'
	"        update_turn(context_docname, output={\n"
	'            "intent": intent if _refused else "DISAMBIGUATE", "response": _REFUSED if _refused else _MISSING, '
	'"diff": None,\n'
)


def execute():
	code = frappe.db.get_value("Server Script", SCRIPT, "script")
	if not code or "_REFUSED" in code:
		return
	new = explains_refusal(code)
	if new == code:
		frappe.log_error(title="logix_finalize_explains_a_writer_refusal: anchor not found", message=SCRIPT)
		return
	frappe.db.set_value("Server Script", SCRIPT, "script", new, update_modified=False)


def explains_refusal(code: str) -> str:
	"""Finalize with the refusal reply, or the input when an anchor is missing."""
	if code.count(MISSING_ANCHOR) != 1 or code.count(EMPTY_OLD) != 1:
		return code
	return code.replace(MISSING_ANCHOR, REFUSED + MISSING_ANCHOR).replace(EMPTY_OLD, EMPTY_NEW)
