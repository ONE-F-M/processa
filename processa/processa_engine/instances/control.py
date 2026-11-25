# Copyright (c) 2026, one-fm and contributors
"""Operator controls for a process instance: cancel, suspend, resume and retry the failed step."""

import frappe
from frappe import _

from processa.processa_engine.instances import task_actions

RECOVERY_ROLES = {"System Manager", "Process Owner"}


def cancel_instance(instance_name: str, reason: str) -> dict:
	"""Cancel an unfinished instance and every task still waiting on it."""
	instance = _instance_for_recovery(instance_name, reason)
	if instance.status in ("Completed", "Cancelled"):
		frappe.throw(
			_('Instance "{0}" is already {1} and cannot be cancelled.').format(instance_name, instance.status)
		)

	instance.status = "Cancelled"
	for row in instance.active_tasks:
		if row.status == "Waiting":
			row.status = "Cancelled"
	instance.log_operator_action("Cancelled", reason)
	instance.save()
	return {"instance": instance_name, "status": instance.status}


def suspend_instance(instance_name: str, reason: str) -> dict:
	"""Pause an Active instance; timers, messages and parked AI jobs leave it alone until resumed."""
	instance = _instance_for_recovery(instance_name, reason)
	if instance.status != "Active":
		frappe.throw(
			_('Instance "{0}" is {1}. Only an Active instance can be suspended.').format(
				instance_name, instance.status
			)
		)

	instance.status = "Suspended"
	instance.log_operator_action("Suspended", reason)
	instance.save()
	return {"instance": instance_name, "status": instance.status}


def resume_instance(instance_name: str, reason: str = "") -> dict:
	"""Return a Suspended instance to Active and queue again any AI step parked on it."""
	instance = _instance_for_recovery(instance_name)
	if instance.status != "Suspended":
		frappe.throw(
			_('Instance "{0}" is {1}. Only a Suspended instance can be resumed.').format(
				instance_name, instance.status
			)
		)

	instance.status = "Active"
	instance.log_operator_action("Resumed", reason)
	instance.save()
	# A parked AI job that ran while the instance was suspended returned without doing its work.
	for unit in instance.get_parked_ai_units():
		task_actions.retry_ai_task(instance_name, unit["task_id"], kind=unit["kind"])
	return {"instance": instance_name, "status": instance.status}


def resume_suspended_agent(instance_name: str, agent_run: str, reason: str = "") -> dict:
	"""Give a suspended agent the sandbox result or delegated answer that arrived without waking it."""
	instance = _instance_for_recovery(instance_name)
	if instance.status != "Active":
		frappe.throw(
			_('Instance "{0}" is {1}. Only an Active instance can resume an agent.').format(
				instance_name, instance.status
			)
		)
	run = frappe.db.get_value(
		"AI Agent Run", agent_run, ["name", "instance", "status", "suspended_at", "checkpoint"], as_dict=True
	)
	if not run or run.instance != instance_name or run.status != "Suspended":
		frappe.throw(_("Agent run {0} is not paused in this instance.").format(agent_run))

	wait = task_actions.suspended_wait(run)
	if not wait["stuck"]:
		frappe.throw(_not_stuck_reason(wait))
	_wake(wait)
	instance.log_operator_action(
		"Resumed",
		reason or _("Agent run {0} was given the answer from {1}.").format(agent_run, wait["wait_name"]),
	)
	return {"instance": instance_name, "agent_run": agent_run, "resumed_with": wait["wait_name"]}


def _not_stuck_reason(wait: dict) -> str:
	"""Why a suspended agent cannot be resumed from here."""
	if wait["waits_on"] == "human":
		return _("This agent waits for a person. Complete its task instead.")
	if not wait["answered_at"]:
		return _("This agent's answer has not arrived yet ({0} is {1}).").format(
			wait["wait_name"], wait["wait_state"]
		)
	return _("This agent's answer arrived less than a minute ago. Give it a moment to resume by itself.")


def _wake(wait: dict) -> None:
	"""Hand the arrived answer to the suspended agent the same way its own callback would have."""
	if wait["waits_on"] == "agent_sandbox":
		from processa.api.agent_callback import enqueue_resume

		enqueue_resume(frappe.get_doc("Agent Sandbox Run", wait["wait_name"], for_update=True))
		return
	from processa.a2a.poller import wake_caller_if_any

	wake_caller_if_any(
		frappe.db.get_value(
			"A2A Task",
			wait["wait_name"],
			["name", "caller_instance", "caller_wf_task_id", "caller_agent_run", "wf_task_id"],
			as_dict=True,
		)
	)


def retry_failed_step(instance_name: str, reason: str = "") -> dict:
	"""Run an Errored instance again from its last saved state, so the step that failed runs again."""
	instance = _instance_for_recovery(instance_name)
	if instance.status != "Errored":
		frappe.throw(
			_('Instance "{0}" is {1}. Only an Errored instance can retry its failed step.').format(
				instance_name, instance.status
			)
		)

	instance.retry_failed_step()
	instance.log_operator_action("Retried", reason)
	return {"instance": instance_name, "status": instance.status}


def _instance_for_recovery(instance_name: str, reason: str | None = None):
	"""The instance, once the caller holds a recovery role and write permission on it."""
	if not RECOVERY_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only a Process Owner or System Manager can do this."), frappe.PermissionError)
	if reason is not None and not reason.strip():
		frappe.throw(_("A reason is required."))
	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")
	return instance
