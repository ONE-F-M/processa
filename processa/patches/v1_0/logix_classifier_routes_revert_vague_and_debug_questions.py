"""Logix routes a revert, a script request with no subject and a why-question the way its Baseline cases expect.

The classifier learns REVERT, a request with nothing to write about, a why-question about the linked script and a
request that carries a blocked step. The clarifier repeats the request's condition, and the writers say what to ask
for instead of a step the safety check refuses. Each rule is added once.
"""

import frappe

CLASSIFIER = (
	"More rules, which override the leanings above:\n"
	"- REVERT: a request to undo, revert or roll back the last change to the linked script, or to bring back an "
	'earlier version ("revert your last change", "undo that", "the script is gone, put it back") is REVERT and next = '
	'"finalize". With no script linked it is DISAMBIGUATE.\n'
	"- A request for a script that says nothing about what it should do, with no DocType, record, event or outcome "
	'("can you generate a script for me?", "prepare a perfect server script", "write me a script") is DISAMBIGUATE, '
	'whether or not a script is linked, unless it points at the linked script ("fix this script").\n'
	"- A question about why the linked script returns nothing, the wrong records or the wrong value (\"why isn't this "
	'returning any employees?", "why is the total wrong?") is DEBUG_EXISTING and next = "debug_script", even when the '
	"person asks for no change.\n"
	"- A request that also asks for a shell command, os.system, subprocess or another step the safety check refuses "
	"is classified by the rest of the work, as CREATE or MODIFY with the usual next; the writer leaves the refused "
	"step out and says why. The intent is never empty."
)
CLARIFIER = (
	"Repeat every condition the request gives (an amount, a limit, a date, a role) in your question, written the "
	'way the person wrote it ("invoices under 500").'
)
WRITER = (
	"Refused steps: when you leave out or change a step the safety check refuses (ignore_permissions, a shell "
	"command, a direct commit), name the operation you removed and the rule that refuses it, and end with one "
	'sentence that starts with "Instead," and says what the person can ask for.'
)
AGENT = (
	'Other next values: when classify_intent returns next = "finalize" (a revert), call finalize next; when it '
	'returns next = "debug_script", call debug_script next. Do not call a writer in either case.'
)
RULES = {
	"logix_agent": AGENT,
	"logix_intent_classifier": CLASSIFIER,
	"logix_clarifier": CLARIFIER,
	"logix_script_writer": WRITER,
	"logix_tool_writer": WRITER,
}


def execute():
	for agent_id, rule in RULES.items():
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if not name:
			continue
		config = frappe.get_doc("AI Agent Configuration", name)
		prompt = with_rule(config.system_prompt or "", rule)
		if prompt != (config.system_prompt or ""):
			config.system_prompt = prompt
			config.save(
				ignore_permissions=True
			)  # a patch runs as Administrator with no request user to check


def with_rule(prompt: str, rule: str) -> str:
	"""The prompt with the rule appended once."""
	return prompt if rule in prompt else (prompt.rstrip() + "\n\n" + rule).strip()
