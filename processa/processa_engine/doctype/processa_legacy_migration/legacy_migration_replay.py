# Copyright (c) 2026, one-fm and contributors
"""Replay an old instance's history, or fast-forward a record with none, on a new process map. Writes nothing."""

import datetime
import json
import re
from collections import Counter
from typing import TYPE_CHECKING
from uuid import UUID

import frappe
from frappe import _
from frappe.utils import CallbackManager

from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.engine import (
	BpmnWorkflow,
	CallActivityMixin,
	CatchingEvent,
	FrappeScriptEngine,
	MultiInstanceTask,
	SubWorkflowTask,
	TaskDataEnvironment,
	TaskNotFoundException,
	TaskState,
	WorkflowException,
)
from processa.processa_engine.runtime.active_tasks import parse_task_actions_json
from processa.processa_engine.runtime.common import task_bpmn_id

if TYPE_CHECKING:
	from processa.processa_engine.doctype.bpmn_process_instance.bpmn_process_instance import (
		BPMNProcessInstance,
	)
	from processa.processa_engine.doctype.processa_legacy_migration.processa_legacy_migration import (
		ProcessaLegacyMigration,
	)

# Engine steps one replay may run; a loop the history cannot leave hits it.
TASK_RUN_LIMIT = 500
# How many user tasks, and how many tries, a move forward to the mapped state may take.
FORWARD_STEPS = 6
FORWARD_TRIES = 200
OPEN_INSTANCE_STATUSES = ("Active", "Errored")


class MigrationSkip(Exception):
	"""A record that cannot move; reason is one of the Legacy Migration Error Log reasons."""

	def __init__(self, reason: str, detail: str):
		super().__init__(detail)
		self.reason = reason
		self.detail = detail


class ReplayScriptEngine(FrappeScriptEngine):
	def execute(self, task, script, **kwargs):
		"""Script tasks do not run during a replay; gateway conditions still evaluate."""


class FastForwardScriptEngine(FrappeScriptEngine):
	def execute(self, task, script, **kwargs):
		"""Run the script for the values it sets for gateways, then undo its database writes and drop
		the jobs it queued for after the commit."""
		queued = frappe.db.before_commit, frappe.db.after_commit
		frappe.db.before_commit, frappe.db.after_commit = CallbackManager(), CallbackManager()
		frappe.db.savepoint("plm_fast_forward_script")
		try:
			super().execute(task, script, **kwargs)
		finally:
			frappe.db.rollback(save_point="plm_fast_forward_script")
			frappe.db.before_commit, frappe.db.after_commit = queued


def build_context(plm: "ProcessaLegacyMigration") -> frappe._dict:
	"""What every replay of one Processa Legacy Migration needs, loaded once."""
	to_spec = json.loads(frappe.db.get_value("BPMN Process Model", plm.to_model, "serialized_spec"))
	from_ids = set()
	if plm.from_model:
		from_spec = json.loads(frappe.db.get_value("BPMN Process Model", plm.from_model, "serialized_spec"))
		from_ids = _element_ids(_spec_workflow(from_spec))
	to_wf = _spec_workflow(to_spec)
	return frappe._dict(
		plm=plm,
		to_spec=to_spec,
		to_wf=to_wf,
		to_ids=_element_ids(to_wf),
		from_ids=from_ids,
		state_map={d.old_state: d.new_state for d in plm.state_map},
		state_field=state_field(plm.target_doctype),
		set_states={
			bpmn_id: cfg["workflowState"]
			for bpmn_id, cfg in to_spec.get("service_task_extensions", {}).items()
			if cfg.get("workflowState")
		},
	)


def replay(ctx: frappe._dict, old: "BPMNProcessInstance") -> frappe._dict:
	"""Replay one old instance on the new map. Writes nothing.
	Returns wf (the new workflow), old_wf, new_state (the mapped state) and last_state (the last set)."""
	old_wf, old_waits, new_state = check_instance(ctx, old)
	steps = _history(ctx, old, old_wf)

	wf = _spec_workflow(ctx.to_spec)
	wf.script_engine = ReplayScriptEngine(
		TaskDataEnvironment({"frappe": frappe, "datetime": datetime}),
		context_doctype=old.context_doctype,
		context_docname=old.context_docname,
	)
	wf.task_tree.data.update(_old_variables(old_wf))
	wf.task_tree.data.update(context_doctype=old.context_doctype, context_docname=old.context_docname)

	progress = {"last_state": None, "seen": set(), "runs": 0}
	try:
		_advance(ctx, wf, progress)
		for step in steps:
			_check_no_new_step(ctx, wf)
			_apply(ctx, wf, step, progress)
	except WorkflowException as e:
		# A gateway condition that cannot evaluate on the copied data.
		skip = MigrationSkip("Replay stuck", str(e))
		if old.status != "Active":
			raise skip from e
		return _placed(ctx, wf, old_wf, new_state, skip)
	except MigrationSkip as skip:
		# The status, not the path the history took, says where an open record waits.
		if old.status != "Active" or skip.reason not in ("Replay stuck", "Past a new step"):
			raise
		return _placed(ctx, wf, old_wf, new_state, skip)

	if old.status == "Active" and progress["last_state"] != new_state:
		wf = place_at_state(ctx, wf, new_state)
		progress["last_state"] = new_state
	elif old.status == "Active":
		_check_no_new_step(ctx, wf)
		new_waits = wait_ids(wf)
		if new_waits != old_waits:
			raise MigrationSkip(
				"Replay stuck",
				_("The new map waits at {0}, the old instance at {1}.").format(
					", ".join(sorted(new_waits)), ", ".join(sorted(old_waits))
				),
			)
	return frappe._dict(wf=wf, old_wf=old_wf, new_state=new_state, last_state=progress["last_state"])


def fast_forward(ctx: frappe._dict, record: frappe._dict) -> frappe._dict:
	"""Run a record that has no instance forward on the new map, each user task taking its first action and
	each script's writes undone, until a step sets the record's mapped state. Writes nothing.
	A user task it comes back to after completing it is not taken again: the record is placed with place_at_state.
	Returns wf, new_state, last_state and steps, the user tasks it completed."""
	new_state = _mapped_state(ctx, record)
	wf = _spec_workflow(ctx.to_spec)
	wf.script_engine = FastForwardScriptEngine(
		TaskDataEnvironment({"frappe": frappe, "datetime": datetime}),
		script_task_extensions=ctx.to_spec.get("script_task_extensions", {}),
		context_doctype=record.context_doctype,
		context_docname=record.context_docname,
		initiated_by=frappe.session.user,
	)
	wf.task_tree.data.update(_record_values(record))
	wf.task_tree.data.update(context_doctype=record.context_doctype, context_docname=record.context_docname)

	progress = {"last_state": None, "seen": set(), "runs": 0}
	steps = []
	# bpmn id of each user task completed -> the action taken and the messages its checks showed.
	completed = {}
	try:
		_advance(ctx, wf, progress)
		while new_state not in progress["seen"]:
			task = next(iter(bpmn_engine.get_ready_user_tasks(wf)), None)
			if task is None:
				raise MigrationSkip(
					"State not reached",
					_("The new map stops without setting {0}; it last set {1}.").format(
						new_state, progress["last_state"]
					),
				)
			name = bpmn_engine.get_task_display_name(task)
			if task_bpmn_id(task) in completed:
				# Taking its first action again would only go round again.
				action, messages = completed[task_bpmn_id(task)]
				try:
					wf = place_at_state(ctx, wf, new_state)
				except MigrationSkip as skip:
					raise _came_back(skip, name, action, messages) from None
				return frappe._dict(wf=wf, new_state=new_state, last_state=new_state, steps=steps)
			action = _first_action(ctx, task)
			task.data["action"] = action
			steps.append(frappe._dict(task_id=str(task.id), name=name, data={"action": action}))
			logged = len(frappe.local.message_log)
			task.run()
			_advance(ctx, wf, progress)
			messages = [_message_text(m) for m in frappe.local.message_log[logged:]]
			completed[task_bpmn_id(task)] = (action, [m for m in messages if m])
	except WorkflowException as e:
		raise MigrationSkip("Replay stuck", str(e)) from e
	return frappe._dict(wf=wf, new_state=new_state, last_state=progress["last_state"], steps=steps)


def _message_text(entry) -> str:
	"""The plain text of one message_log entry, which is a JSON string or a dict."""
	if isinstance(entry, str):
		try:
			entry = json.loads(entry)
		except ValueError:
			pass
	text = entry.get("message") if isinstance(entry, dict) else entry
	return re.sub(r"<[^>]+>", "", str(text or "")).strip()


def _came_back(skip: MigrationSkip, name: str, action: str, messages: list[str]) -> MigrationSkip:
	"""The skip with the step that came back, the action taken on it and its last message added."""
	detail = _("{0} The walk through the new map came back to {1} after taking the action {2} on it.").format(
		skip.detail, name, action or _("(none)")
	)
	if messages:
		detail += " " + _("The last message its checks showed: {0}").format(messages[-1])
	return MigrationSkip(skip.reason, detail)


def _record_values(record: frappe._dict) -> dict:
	"""The record's plain field values, which gateway conditions read."""
	doc = frappe.get_doc(record.context_doctype, record.context_docname)
	values = {
		df.fieldname: doc.get(df.fieldname)
		for df in doc.meta.fields
		if isinstance(doc.get(df.fieldname), str | int | float | bool | None)
	}
	values["docstatus"] = doc.docstatus
	return values


def _first_action(ctx: frappe._dict, task) -> str:
	"""The first action a user task offers; empty when it offers none."""
	raw = ctx.to_spec.get("user_task_extensions", {}).get(task_bpmn_id(task), {}).get("taskActions", "")
	actions = [a.get("action", "") for a in parse_task_actions_json(raw) if isinstance(a, dict)]
	return next((a for a in actions if a), "")


def _placed(ctx, wf, old_wf, new_state, skip) -> frappe._dict:
	"""The replay result with wf placed at new_state; the history's own refusal when no placement works."""
	try:
		wf = place_at_state(ctx, wf, new_state)
	except MigrationSkip:
		raise skip from None
	return frappe._dict(wf=wf, old_wf=old_wf, new_state=new_state, last_state=new_state)


def place_at_state(ctx: frappe._dict, wf: BpmnWorkflow, state: str) -> BpmnWorkflow:
	"""The workflow waiting at the steps after the one that sets state: back to where it last set it, else forward."""
	back = _back_to_state(ctx, wf, state)
	if back is not None:
		return back
	ahead = _forward_to_state(ctx, wf, state) or _start_at_state(ctx, wf, state)
	if ahead is None:
		raise MigrationSkip(
			"State not reached",
			_("No path through the new map's steps sets {0} from where the record is.").format(state),
		)
	return ahead


def _back_to_state(ctx: frappe._dict, wf: BpmnWorkflow, state: str) -> BpmnWorkflow | None:
	"""A copy of wf run again from the step that last set state, when it has set it before."""
	setters = {bpmn_id for bpmn_id, value in ctx.set_states.items() if value == state}
	done = [t for t in wf.get_tasks(state=TaskState.COMPLETED) if task_bpmn_id(t) in setters]
	if not done:
		return None
	trial = _copy(wf)
	progress = {"last_state": None, "seen": set(), "runs": 0}
	if not _ran(
		ctx,
		trial,
		progress,
		lambda: trial.reset_from_task_id(max(done, key=lambda t: t.last_state_change).id),
	):
		return None
	return trial if progress["last_state"] == state else None


def _forward_to_state(ctx: frappe._dict, wf: BpmnWorkflow, state: str) -> BpmnWorkflow | None:
	"""A copy of wf moved on through its waiting user tasks, one action at a time, until a step sets state."""
	actions = {
		bpmn_id: [
			a.get("action") for a in parse_task_actions_json(cfg.get("taskActions", "")) if a.get("action")
		]
		for bpmn_id, cfg in ctx.to_spec.get("user_task_extensions", {}).items()
	}
	frontier, tries = [(wf, 0)], 0
	while frontier:
		current, depth = frontier.pop(0)
		for task in bpmn_engine.get_ready_user_tasks(current):
			for action in actions.get(task_bpmn_id(task)) or [None]:
				tries += 1
				if tries > FORWARD_TRIES:
					return None
				trial = _copy(current)
				step = trial.get_task_from_id(task.id)
				if action:
					step.data["action"] = action
				progress = {"last_state": None, "seen": set(), "runs": 0}
				if not _ran(ctx, trial, progress, step.run):
					continue
				if progress["last_state"] == state:
					return trial
				if depth + 1 < FORWARD_STEPS:
					frontier.append((trial, depth + 1))
	return None


def _start_at_state(ctx: frappe._dict, wf: BpmnWorkflow, state: str) -> BpmnWorkflow | None:
	"""A copy of wf with every open step cancelled and the step that sets state run, then on to the next waits.

	For a status no path through the map reaches, such as one behind a script's decision. Top-level steps only."""
	trial = _copy(wf)
	setters = [b for b, value in ctx.set_states.items() if value == state and b in trial.spec.task_specs]
	open_tasks = trial.get_tasks(state=TaskState.READY | TaskState.WAITING)
	anchor = next((t for t in open_tasks if t.workflow is trial and t.parent is not None), None)
	if not setters or anchor is None:
		return None
	parent, data = anchor.parent, dict(anchor.data)
	for task in open_tasks:
		task.cancel()
	# Added as a future task and predicted, so the steps after it exist when it completes.
	start = parent._add_child(trial.spec.task_specs[setters[0]], TaskState.FUTURE)
	start.data = data
	progress = {"last_state": None, "seen": set(), "runs": 0}

	def ready():
		start.task_spec._predict(start, mask=TaskState.PREDICTED_MASK | TaskState.FUTURE)
		start._ready()

	if not _ran(ctx, trial, progress, ready):
		return None
	if progress["last_state"] != state or not wait_ids(trial):
		return None
	return trial


def _ran(ctx, wf, progress, first) -> bool:
	"""Whether first() and the engine steps after it ran; a gateway that cannot decide means no placement this way."""
	try:
		first()
		_advance(ctx, wf, progress)
	except (WorkflowException, MigrationSkip):
		return False
	return True


def _copy(wf: BpmnWorkflow) -> BpmnWorkflow:
	copied = bpmn_engine.restore_workflow(bpmn_engine.serialize_workflow(wf))
	copied.script_engine = wf.script_engine
	return copied


def check_instance(ctx: frappe._dict, old: "BPMNProcessInstance") -> tuple[BpmnWorkflow, set[str], str]:
	"""Refuse an instance that cannot be replayed; returns its workflow, wait points and mapped new state."""
	if old.status not in OPEN_INSTANCE_STATUSES:
		raise MigrationSkip("No longer open", _("The instance is {0}.").format(old.status))
	old_wf = bpmn_engine.restore_workflow(json.loads(old.workflow_state))
	running = [
		t for t in old_wf.get_tasks(state=TaskState.STARTED) if isinstance(t.task_spec, CallActivityMixin)
	]
	if running:
		raise MigrationSkip(
			"Sub-process running",
			_("{0} has not finished.").format(bpmn_engine.get_task_display_name(running[0])),
		)

	old_waits = wait_ids(old_wf)
	removed = old_waits - ctx.to_ids
	if old.status == "Active" and removed:
		raise MigrationSkip(
			"Waiting at removed step",
			_("The new map has no {0}.").format(", ".join(sorted(removed))),
		)
	return old_wf, old_waits, _mapped_state(ctx, old)


def _mapped_state(ctx: frappe._dict, record) -> str:
	"""Refuse a record already on the new map or in an unmapped state; returns its mapped new state."""
	if frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": ctx.plm.to_model,
			"context_doctype": record.context_doctype,
			"context_docname": record.context_docname,
			"status": "Active",
		},
	):
		raise MigrationSkip(
			"Already on new map", _("The record has an Active instance on {0}.").format(ctx.plm.to_model)
		)

	state = frappe.db.get_value(record.context_doctype, record.context_docname, ctx.state_field)
	if state not in ctx.state_map:
		raise MigrationSkip("No state mapping", _("No State Mapping row for {0}.").format(state))
	return ctx.state_map[state]


def _history(ctx: frappe._dict, old: "BPMNProcessInstance", old_wf: BpmnWorkflow) -> list[frappe._dict]:
	"""The old instance's completed user tasks and received messages that the new map can take, oldest first.

	Rows copied in by an earlier migration name tasks of the instance it came from, so they are read there."""
	rows = frappe.get_all(
		"BPMN Activity Log",
		filters={"instance": old.name, "action": ["in", ["Completed", "Message Received", "Migrated"]]},
		fields=["task_id", "task_name", "action", "data"],
		order_by="timestamp asc, creation asc",
	)
	steps = []
	if old.migrated_from:
		source = frappe.get_doc("BPMN Process Instance", old.migrated_from)
		steps = _history(ctx, source, bpmn_engine.restore_workflow(json.loads(source.workflow_state)))
		# Its own "Migrated" row is the last one; earlier ones were copied with the history.
		own_migrated = max(i for i, row in enumerate(rows) if row.action == "Migrated")
		rows = rows[own_migrated + 1 :]

	for row in rows:
		data = json.loads(row.data) if row.data else {}
		if row.action == "Message Received":
			name = row.task_name.removeprefix("Message: ")
			if bpmn_engine.declares_message(ctx.to_wf, name):
				steps.append(frappe._dict(kind="message", name=name, data=data))
			continue
		# A fast-forwarded instance has its "Migrated" row but no instance it came from.
		if row.action == "Migrated":
			continue

		try:
			task = old_wf.get_task_from_id(UUID(row.task_id))
		except TaskNotFoundException as e:
			raise MigrationSkip(
				"Replay stuck", _("{0} is in the history but not in the old instance.").format(row.task_name)
			) from e
		if task.task_spec.manual and task_bpmn_id(task) in ctx.to_ids:
			steps.append(frappe._dict(kind="user", bpmn_id=task_bpmn_id(task), name=row.task_name, data=data))
	return steps


def _apply(ctx, wf, step, progress) -> None:
	"""Complete one history step on the new map and run on to the next wait point."""
	if step.kind == "user":
		task = next(
			(t for t in bpmn_engine.get_ready_user_tasks(wf) if task_bpmn_id(t) == step.bpmn_id), None
		)
		if task is None:
			raise MigrationSkip(
				"Replay stuck", _("{0} is not waiting when the history completes it.").format(step.name)
			)
		task.data.update(step.data)
		task.run()
	elif not bpmn_engine.send_message(wf, step.name, step.data):
		raise MigrationSkip("Replay stuck", _("Nothing waits for message {0}.").format(step.name))
	_advance(ctx, wf, progress)


def _advance(ctx, wf, progress) -> None:
	"""Run engine steps until only waits remain.

	Scripts do nothing; service tasks and call activities complete without running."""
	while _complete_started(ctx, wf, progress) or _run_next(wf, progress):
		progress["runs"] += 1
		if progress["runs"] > TASK_RUN_LIMIT:
			detail = _("The new map ran {0} steps without reaching a wait.").format(TASK_RUN_LIMIT)
			repeated = [name for name, count in progress.get("ran", Counter()).most_common(5) if count > 1]
			if repeated:
				detail += " " + _("It kept repeating: {0}.").format(", ".join(repeated))
			raise MigrationSkip("Replay stuck", detail)


def _complete_started(ctx, wf, progress) -> bool:
	"""Complete STARTED service tasks and call activities without dispatching them; True if any completed."""
	completed = False
	for task in wf.get_tasks(state=TaskState.STARTED):
		spec = task.task_spec
		if isinstance(spec, CallActivityMixin):
			wf.delete_subprocess(task)
		elif spec.manual or isinstance(spec, (SubWorkflowTask, MultiInstanceTask)):
			continue
		if task_bpmn_id(task) in ctx.set_states:
			progress["last_state"] = ctx.set_states[task_bpmn_id(task)]
			progress["seen"].add(progress["last_state"])
		task.complete()
		completed = True
	return completed


def _run_next(wf, progress) -> bool:
	"""Run the next ready engine task, counting it by display name in progress; True if one ran."""
	task = wf.get_next_task(state=TaskState.READY, manual=False)
	if task is None:
		wf.refresh_waiting_tasks()
		task = wf.get_next_task(state=TaskState.READY, manual=False)
	if task is None:
		return False
	task.run()
	if task.task_spec.bpmn_id:
		progress.setdefault("ran", Counter())[bpmn_engine.get_task_display_name(task)] += 1
	return True


def _check_no_new_step(ctx, wf) -> None:
	new_steps = wait_ids(wf) - ctx.from_ids
	if new_steps:
		raise MigrationSkip(
			"Past a new step",
			_("The new map stops at {0}, which the old map does not have.").format(
				", ".join(sorted(new_steps))
			),
		)


def state_field(doctype: str) -> str | None:
	"""The field a record's state lives in: workflow_state, else status."""
	meta = frappe.get_meta(doctype)
	return next((f for f in ("workflow_state", "status") if meta.has_field(f)), None)


def wait_ids(wf: BpmnWorkflow) -> set[str]:
	"""Element ids of the user tasks and catch events a workflow waits at."""
	user_tasks = {task_bpmn_id(t) for t in bpmn_engine.get_ready_user_tasks(wf)}
	catches = {
		task_bpmn_id(t)
		for t in wf.get_tasks(state=TaskState.WAITING)
		if isinstance(t.task_spec, CatchingEvent)
	}
	return user_tasks | catches


def _old_variables(old_wf) -> dict:
	"""The old instance's workflow variables: root data, the last completed task, then its waiting tasks."""
	data = dict(old_wf.task_tree.data)
	if old_wf.last_task:
		data.update(old_wf.last_task.data)
	for task in old_wf.get_tasks(state=TaskState.READY | TaskState.WAITING):
		data.update(task.data)
	data.pop("doc", None)
	return data


def _spec_workflow(spec: dict):
	return bpmn_engine.get_serializer().deserialize_json(json.dumps(spec))


def _element_ids(wf) -> set:
	"""Every element id in a compiled map, its sub-processes included."""
	return {
		ts.bpmn_id
		for spec in (wf.spec, *wf.subprocess_specs.values())
		for ts in spec.task_specs.values()
		if ts.bpmn_id
	}
