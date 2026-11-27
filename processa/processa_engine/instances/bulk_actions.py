# Copyright (c) 2026, one-fm and contributors
"""Take one Processa action on a selection of documents, the way the list view's Actions menu offers it.

The rules are complete_task's own; this module only works out which waiting task on each record an action
names, and keeps one record's failure from undoing the records that already went through.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import get_link_to_form, strip_html

from processa.processa_engine.instances import task_actions
from processa.processa_engine.runtime.active_tasks import parse_task_actions_json

# Mirrors frappe.model.workflow.bulk_workflow_approval so a bulk Processa action behaves like a bulk
# workflow approval: a small selection runs in the request, a larger one on a worker.
INLINE_LIMIT = 20
MAX_DOCUMENTS = 500
BULK_JOB_TIMEOUT = 3600

# An action the model flags for a signature is acknowledged one record at a time on the form, so bulk skips it.
SIGNATURE_FLAG = "requireDigitalSignature"


def parse_docnames(docnames) -> list:
	"""The selected names as a de-duplicated list, refusing an empty or oversized selection."""
	names = frappe.parse_json(docnames) if isinstance(docnames, str) else docnames
	if not isinstance(names, list):
		frappe.throw(_("docnames must be a list of document names."))

	names = list(dict.fromkeys(name for name in names if name))
	if not names:
		frappe.throw(_("Select at least one document."))
	if len(names) > MAX_DOCUMENTS:
		frappe.throw(
			_("A bulk action supports up to {0} documents.").format(MAX_DOCUMENTS),
			title=_("Too Many Documents"),
		)
	return names


def resolve_selection(doctype: str, names: list, user: str | None = None) -> dict:
	"""For each name, the actions ``user`` can take right now and why it offers none.

	Three queries whatever the selection size: the readable documents, their instances, and the waiting
	task rows of the active ones.
	"""
	user = user or frappe.session.user

	readable = set(
		frappe.get_list(doctype, filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	)

	instances = (
		frappe.get_all(
			"BPMN Process Instance",
			filters={"context_doctype": doctype, "context_docname": ["in", list(readable)]},
			fields=["name", "context_docname", "status", "engine_in_progress"],
			limit_page_length=0,
		)
		if readable
		else []
	)

	by_doc = defaultdict(list)
	for row in instances:
		by_doc[row.context_docname].append(row)

	active = [row.name for row in instances if row.status == "Active"]
	rows = (
		frappe.get_all(
			"BPMN Active Task",
			filters={"parent": ["in", active], "parenttype": "BPMN Process Instance", "status": "Waiting"},
			fields=[
				"parent",
				"task_id",
				"task_name",
				"task_type",
				"task_actions",
				"assigned_user",
				"assigned_role",
				"other_allowed_users",
				"relieved_user",
				"reliever_user",
			],
			limit_page_length=0,
		)
		if active
		else []
	)

	waiting_by_instance = defaultdict(list)
	for row in rows:
		waiting_by_instance[row.parent].append(row)

	return {
		name: _record_actions(
			doctype, name, by_doc.get(name) or [], waiting_by_instance, user, name in readable
		)
		for name in names
	}


def _record_actions(
	doctype: str, docname: str, instances: list, waiting_by_instance: dict, user: str, readable: bool
):
	"""One record's actions as {action: (instance, task_id)}, or the reason it has none."""
	if not readable:
		return frappe._dict(has_instance=False, actions={}, reason=_("No permission"))
	if not instances:
		return frappe._dict(has_instance=False, actions={}, reason=_("No process instance"))

	active = [row for row in instances if row.status == "Active"]
	if not active:
		return frappe._dict(has_instance=True, actions={}, reason=_("Process is not active"))
	if any(row.engine_in_progress for row in active):
		return frappe._dict(has_instance=True, actions={}, reason=_("Already processing"))

	# A question an agent asked is answered in its own panel, never from a bulk action.
	waiting = [
		(row.name, task)
		for row in active
		for task in waiting_by_instance.get(row.name, [])
		if (task.task_type or "") != "AI Human Task"
	]
	if not waiting:
		return frappe._dict(has_instance=True, actions={}, reason=_("No waiting task"))

	found, ambiguous, needs_signature = {}, set(), set()
	authorized = False
	for instance_name, task in waiting:
		if task_authorization_refusal(doctype, docname, task, user):
			continue
		authorized = True
		for detail in parse_task_actions_json(task.task_actions or ""):
			action = (detail.get("action") or "").strip()
			if not action:
				continue
			if str(detail.get(SIGNATURE_FLAG, "")).lower() == "true":
				needs_signature.add(action)
			elif action in found:
				# Two waiting tasks offer the same action, so no bulk click can say which one was meant.
				ambiguous.add(action)
			else:
				found[action] = (instance_name, task.task_id)

	for action in ambiguous:
		found.pop(action, None)

	if found:
		return frappe._dict(has_instance=True, actions=found, reason=None)
	if ambiguous:
		return frappe._dict(has_instance=True, actions={}, reason=_("More than one task offers this action"))
	if needs_signature:
		return frappe._dict(has_instance=True, actions={}, reason=_("Digital signature required"))
	if not authorized:
		return frappe._dict(has_instance=True, actions={}, reason=_("Not authorized"))
	return frappe._dict(has_instance=True, actions={}, reason=_("No action available"))


def task_authorization_refusal(doctype: str, docname: str, task, user: str) -> str | None:
	"""Why ``user`` may not complete this waiting row, using the check complete_task enforces on write."""
	instance = frappe._dict(context_doctype=doctype, context_docname=docname)
	return task_actions.task_authorization(instance, task, user)[0]


def get_bulk_action_context(doctype: str, docnames) -> dict:
	"""What the whole selection can do: the actions every record offers, and why the others offer none.

	A selection that mixes documents Processa runs with documents it does not offers nothing, so a bulk
	click can never act on half of it.
	"""
	names = parse_docnames(docnames)
	selection = resolve_selection(doctype, names)

	with_instance = sum(1 for record in selection.values() if record.has_instance)
	common = None
	for record in selection.values():
		common = set(record.actions) if common is None else common & set(record.actions)

	return {
		"total": len(names),
		"with_instance": with_instance,
		"without_instance": len(names) - with_instance,
		"mixed": bool(with_instance) and with_instance != len(names),
		"actions": sorted(common or []) if with_instance == len(names) else [],
		"eligible": sum(1 for record in selection.values() if record.actions),
		"blocked": {name: record.reason for name, record in selection.items() if record.reason},
	}


def bulk_task_action(doctype: str, docnames, action: str, comment: str | None = None) -> dict:
	"""Apply ``action`` to every selected document, in the request for a small selection and on a worker
	for a larger one."""
	if not action:
		frappe.throw(_("An action is required."))

	names = parse_docnames(docnames)
	if len(names) < INLINE_LIMIT:
		return {**run_bulk_task_action(doctype, names, action, comment), "mode": "sync"}

	frappe.msgprint(_("Bulk {0} is enqueued in background.").format(action), alert=True)
	job = frappe.enqueue(
		"processa.processa_engine.instances.bulk_actions.run_bulk_task_action",
		queue="long",
		timeout=BULK_JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=f"processa-bulk::{frappe.session.user}::{frappe.generate_hash(length=8)}",
		doctype=doctype,
		names=names,
		action=action,
		comment=comment,
		user=frappe.session.user,
	)
	return {"mode": "async", "job_id": getattr(job, "id", None), "total": len(names), "action": action}


def run_bulk_task_action(
	doctype: str, names: list, action: str, comment: str | None = None, user: str | None = None
) -> dict:
	"""Complete one waiting task per record and report the three outcomes.

	Each record commits on its own: a record that throws is rolled back and logged, and the records that
	already went through stay through.
	"""
	# set_user wipes session data, which a web request would write back under the browser's sid.
	if user and user != frappe.session.user:
		frappe.set_user(user)

	selection = resolve_selection(doctype, names, user=frappe.session.user)
	succeeded, failed, skipped = [], [], []
	frappe.clear_messages()

	for idx, docname in enumerate(names, 1):
		_show_progress(names, action, idx, docname)
		record = selection.get(docname) or frappe._dict(actions={}, reason=_("No process instance"))
		target = record.actions.get(action)
		if not target:
			skipped.append({"docname": docname, "reason": record.reason or _("Action not offered")})
			continue

		instance_name, task_id = target
		data = {"action": action}
		if comment:
			data["comment"] = comment

		try:
			task_actions.complete_task(instance_name, task_id, data)
			frappe.db.commit()
			succeeded.append(docname)
		except Exception as exc:
			frappe.db.rollback()
			failed.append({"docname": docname, "reason": _failure_message(exc)})
			frappe.log_error(
				title=f"Processa bulk {action} failed for {doctype} {docname}",
				message=frappe.get_traceback(),
			)
		finally:
			# A document's own messages would otherwise stack up behind the summary, one set per record.
			frappe.clear_messages()

	summary = {
		"total": len(names),
		"action": action,
		"succeeded": succeeded,
		"failed": failed,
		"skipped": skipped,
	}
	_print_summary(doctype, summary)
	return summary


def _show_progress(names: list, action: str, idx: int, docname: str) -> None:
	"""The progress bar frappe.model.workflow shows for the same gesture, from five records up."""
	if len(names) >= 5:
		frappe.publish_progress(
			float(idx) * 100 / len(names), title=_("Applying: {0}").format(action), description=docname
		)


def _failure_message(exc: Exception) -> str:
	"""What to show against a record that threw: its own message, else the last message it logged."""
	message = strip_html(str(exc) or "").strip()
	if not message:
		log = frappe.get_message_log() or []
		message = strip_html(log[-1].get("message", "")) if log else exc.__class__.__name__
	return message[:140]


def _print_summary(doctype: str, summary: dict) -> None:
	"""One minimizable message listing each record and what happened to it, as a bulk approval does."""
	if summary["failed"]:
		indicator = "orange" if summary["succeeded"] else "red"
	else:
		indicator = "green" if summary["succeeded"] else "orange"

	sections = [
		(_("Successful"), [{"docname": name, "reason": ""} for name in summary["succeeded"]]),
		(_("Failed"), summary["failed"]),
		(_("Skipped"), summary["skipped"]),
	]

	html = ""
	for title, rows in sections:
		if not rows:
			continue
		html += f"<h5>{title} ({len(rows)})</h5>"
		for row in rows:
			link = get_link_to_form(doctype, row["docname"])
			reason = row.get("reason")
			html += f"<div>{link}"
			if reason:
				html += f" <span class='text-muted small'>{frappe.utils.escape_html(reason)}</span>"
			html += "</div>"

	frappe.msgprint(
		html,
		title=_("{0}: {1} of {2}").format(summary["action"], len(summary["succeeded"]), summary["total"]),
		indicator=indicator,
		is_minimizable=True,
		realtime=True,
	)
