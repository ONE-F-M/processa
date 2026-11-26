"""Tick Support Effort on the Claude AI Models whose API accepts all five effort levels.

Rows are matched on model_api_name, so a per-agent row gets the same value as its
catalogue row. Every other model stays unticked and is sent no effort.
"""

import re

import frappe

# The 5 series, Fable, Mythos and Opus 4.7 and 4.8. Sonnet 4.5 and Haiku 4.5 reject effort; Opus 4.5 and the 4.6 models lack xhigh.
ACCEPTS_EFFORT = re.compile(r"^claude-(?:(?:sonnet|opus|haiku)-5(?:-|$)|fable-|mythos-|opus-4-[78](?:-|$))")


def execute():
	for model in frappe.get_all("AI Model", fields=["name", "model_api_name", "support_effort"]):
		if accepts_effort(model.model_api_name or model.name) and not model.support_effort:
			frappe.db.set_value("AI Model", model.name, "support_effort", 1, update_modified=False)


def accepts_effort(api_name: str) -> bool:
	return bool(ACCEPTS_EFFORT.match(api_name or ""))
