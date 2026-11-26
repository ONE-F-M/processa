# Copyright (c) 2026, one-fm and contributors
"""Deploy, disable, activate and deactivate a BPMN Process Model; the work is in processa_engine.compiler."""

import frappe
from frappe import _

from processa.processa_engine.compiler.compile_step import compile_model
from processa.processa_engine.compiler.lifecycle import (
	activate_non_executable,
	deactivate_non_executable,
	disable_model,
)
from processa.processa_engine.instances.control import RECOVERY_ROLES


@frappe.whitelist()
def compile_process_model(model_name: str) -> dict:
	"""Compile and deploy a process model; returns success, model, version, subprocess_count and any warnings."""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return compile_model(model)


@frappe.whitelist()
def disable_process_model(model_name: str, cancel_running: int = 0) -> dict:
	"""Disable a deployed process model and return the running instance count.

	Running instances continue unless cancel_running is 1, which cancels them in a background job and
	needs the System Manager or Process Owner role.
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	cancel_running = frappe.utils.cint(cancel_running)
	if cancel_running and not RECOVERY_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only a Process Owner or System Manager can do this."), frappe.PermissionError)

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return disable_model(model, cancel_running=bool(cancel_running))


@frappe.whitelist(methods=["POST"])
def activate_non_executable_model(model_name: str) -> dict:
	"""Mark a non-executable process model Active; saving it deactivates its siblings."""
	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return activate_non_executable(model)


@frappe.whitelist(methods=["POST"])
def deactivate_non_executable_model(model_name: str) -> dict:
	"""Mark a non-executable process model Inactive."""
	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return deactivate_non_executable(model)
