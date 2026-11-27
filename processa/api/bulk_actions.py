# Copyright (c) 2026, one-fm and contributors
"""Bulk action endpoints for the list view; the work is in processa_engine.instances.bulk_actions."""

import frappe
from frappe.rate_limiter import rate_limit

from processa.processa_engine.instances import bulk_actions


@frappe.whitelist()
def get_bulk_action_context(doctype: str, docnames: str) -> dict:
	"""The Processa actions every selected document offers, and why the others offer none."""
	frappe.has_permission(doctype, "read", throw=True)
	return bulk_actions.get_bulk_action_context(doctype, docnames)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60)
def bulk_task_action(doctype: str, docnames: str, action: str, comment: str | None = None) -> dict:
	"""Take one Processa action on every selected document, reporting what succeeded, failed and was skipped."""
	frappe.has_permission(doctype, "write", throw=True)
	return bulk_actions.bulk_task_action(doctype, docnames, action, comment)
