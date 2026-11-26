# Copyright (c) 2026, one-fm and contributors
"""Logix's library contract says what the deploy check enforces: a library holds only def statements at the top level."""

import frappe

from processa.patches.v1_0.logix_library_script_contract import MODEL_NAME, SKILL
from processa.patches.v1_0.seed_logix_skills import _upsert_skill

OLD_RULE = (
	"- Define functions, and constants they use. Do no work at the top level: no query, no write, no call that runs "
	"when the script loads.\n"
)
NEW_RULE = (
	"- Only `def` statements at the top level. Put each import inside the function that needs it, and a value several "
	"functions share in a small function that returns it. A top-level import, assignment, call or docstring is refused "
	"when the map deploys.\n"
)
OLD_PROMPT = "Define functions and constants only; never read task_data, doc or result."
NEW_PROMPT = "Only def statements at the top level, with imports inside the functions; never read task_data, doc or result."


def execute():
	_upsert_skill(dict(SKILL, body=SKILL["body"].replace(OLD_RULE, NEW_RULE)))
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if xml.count(OLD_PROMPT) != 1:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml.replace(OLD_PROMPT, NEW_PROMPT))
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)
