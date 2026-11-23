# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Conformance check a chat agent passes before go-live.

screening_status passes when a Chat Message before_insert hook runs
ai_agent_security.screening.pii.screen_chat_message and AI Injection Pattern has an enabled rule.
validate_chat_map adds that a linked map exists, is not empty, and starts on Chat Conversation insert.
An agent with no map passes the map part. Any check that cannot be read counts as a failure.
"""

from __future__ import annotations

import frappe
from frappe import _


def screening_status() -> dict:
	"""Is the platform's message screening armed? {"ok": bool, "errors": [...]}.

	Fails closed on every uncertain answer: a screen that cannot be shown to be
	wired is treated as absent, because this authorises a release.
	"""
	errors = []

	try:
		from processa import hooks

		# before_insert is a STRING when one handler is wired and a LIST when
		# several are. Both forms are normal Frappe, and the substring test that
		# worked on the string form silently became an element-equality test when
		# the output screen was added alongside this one — the list holds the full
		# dotted path, which never equals the bare function name, so the gate
		# reported PII screening as absent while it was running fine.
		hooked = ((hooks.doc_events or {}).get("Chat Message") or {}).get("before_insert") or ""
		handlers = [hooked] if isinstance(hooked, str) else list(hooked or [])
		if not any("screen_chat_message" in str(h) for h in handlers):
			errors.append(
				_(
					"Chat Message screening is not wired: no before_insert hook runs "
					"security.pii.screen_chat_message, so stored messages reach the agent "
					"unscreened."
				)
			)
	except Exception:
		errors.append(_("The screening hook could not be read, so it cannot be shown to be active."))

	try:
		if not frappe.db.count("AI Injection Pattern", {"enabled": 1}):
			errors.append(
				_(
					"The injection pattern pack has no enabled rules, so screening would "
					"match nothing. Enable the seeded rules under AI Injection Pattern."
				)
			)
	except Exception:
		errors.append(_("The injection pattern pack could not be read, so screening cannot be verified."))

	return {"ok": not errors, "errors": errors}


def validate_chat_map(model_name: str) -> dict:
	"""Is this chat agent conforming? {"ok": bool, "errors": [...]}.

	Named for the map it used to inspect; it now verifies the screen an agent's
	messages actually pass through, and checks the map only for the thing a map
	can still get wrong. A chat agent with NO map is fine — that is the Direct
	API path — so a missing link is no longer an error.
	"""
	errors = list(screening_status()["errors"])

	if model_name:
		if not frappe.db.exists("BPMN Process Model", model_name):
			errors.append(_("Process map '{0}' does not exist.").format(model_name))
		else:
			xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml") or ""
			if not xml.strip():
				errors.append(_("Process map '{0}' is empty.").format(model_name))
			elif 'triggerDoctype="Chat Conversation"' not in xml:
				# The same rule validate_agent_config applies, said here too: a
				# chat agent pointed at a business process can never take a turn.
				errors.append(
					_(
						"Process map '{0}' is not a chat map — it has no start event on Chat "
						"Conversation insert, so this agent can never receive a message."
					).format(model_name)
				)

	return {"ok": not errors, "errors": errors}
