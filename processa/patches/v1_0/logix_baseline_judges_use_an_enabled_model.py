"""Logix Baseline judges that name a disabled model grade with the Logix classifier's model instead.

A judge on a disabled model errors before it grades, so the case can never pass.
"""

import frappe

SUITE_TITLE = "Logix - Baseline"


def execute():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	model = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_intent_classifier"}, "ai_model")
	if not suite or not model:
		return
	provider = frappe.db.get_value("AI Model", model, "provider")
	for case in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
		doc = frappe.get_doc("AI Eval Case", case)
		if move_disabled_judges(doc, model, provider):
			doc.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check


def move_disabled_judges(case, model: str, provider: str) -> bool:
	"""Point each llm_judge on a disabled AI Model at model; True when one changed."""
	changed = False
	for row in case.assertions:
		if row.assertion_type == "llm_judge" and row.judge_model and not _enabled(row.judge_model):
			row.judge_model, row.judge_provider = model, provider
			changed = True
	return changed


def _enabled(model: str) -> bool:
	return bool(frappe.db.get_value("AI Model", model, "enable_model"))
