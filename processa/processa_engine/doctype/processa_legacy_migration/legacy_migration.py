# Copyright (c) 2026, one-fm and contributors
"""Processa Legacy Migration runs: setup checks, the background batches, the hourly check and the finish."""

import json
import time
from collections import Counter
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import create_batch, now_datetime
from frappe.utils.background_jobs import is_job_enqueued
from rq.timeouts import JobTimeoutException

from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_move import (
	log_error_row,
	migrate_record,
	other_maps_of_process,
	unstarted_record,
)
from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_replay import (
	OPEN_INSTANCE_STATUSES,
	build_context,
	state_field,
)
from processa.processa_engine.runtime.messages import receive_message

if TYPE_CHECKING:
	from processa.processa_engine.doctype.bpmn_process_model.bpmn_process_model import BPMNProcessModel
	from processa.processa_engine.doctype.processa_legacy_migration.processa_legacy_migration import (
		ProcessaLegacyMigration,
	)

BATCH_SIZE = 25
# Seconds a batch may run before it stops starting new records; its job times out at 600.
BATCH_STOP_SECONDS = 450
FINISHED_MESSAGE = "processa:legacy_migration:finished"


def start(migration_name: str) -> None:
	"""Queue a migration's batches; a failure before they are queued fails the run with one Error Log row
	that holds the traceback, so the run never waits for the hourly check."""
	try:
		_queue_batches(migration_name)
	except Exception:
		frappe.db.rollback()
		_fail_before_batches(migration_name, frappe.get_traceback(with_context=False))


def _queue_batches(migration_name: str) -> None:
	"""Queue a migration's records_to_move as run_batch jobs of BATCH_SIZE on the long queue."""
	plm = frappe.get_doc("Processa Legacy Migration", migration_name)
	user = plm.run_by or frappe.session.user
	from_model = frappe.get_doc("BPMN Process Model", plm.from_model) if plm.from_model else None
	to_model = frappe.get_doc("BPMN Process Model", plm.to_model)
	try:
		check_process_ownership(from_model, to_model, user)
		_check_old_map_deployed(from_model)
	except (frappe.PermissionError, frappe.ValidationError) as e:
		frappe.clear_messages()
		log_error_row(migration_name, frappe._dict(), "Error", str(e), idx=1)
		plm.db_set({"status": "Running", "run_by": user, "started_at": now_datetime()})
		finish(migration_name)
		return

	names = records_to_move(plm)
	batches = list(create_batch(names, BATCH_SIZE))
	plm.db_set(
		{
			"status": "Running",
			"run_by": user,
			"started_at": now_datetime(),
			"completed_at": None,
			"total_records": len(names),
			"total_batches": len(batches),
			"batches_done": 0,
			"migrated_count": 0,
			"failed_count": 0,
			"not_attempted_count": 0,
			"stop_reason": "",
		}
	)
	if not batches:
		finish(migration_name)
		return
	for n, batch in enumerate(batches, start=1):
		frappe.enqueue(
			"processa.processa_engine.doctype.processa_legacy_migration.legacy_migration.run_batch",
			queue="long",
			timeout=600,
			job_id=f"plm::{migration_name}::{n}",
			deduplicate=True,
			enqueue_after_commit=True,
			migration_name=migration_name,
			instance_names=list(batch),
			first_idx=(n - 1) * BATCH_SIZE + 1,
		)


def run_batch(migration_name: str, instance_names: list[str], first_idx: int = 1) -> None:
	"""Move one batch, committing after each record; records it never reached are logged as Not Attempted.
	A timeout fails only the running record, any other error fails the rest. Error Log row idx is
	first_idx plus the record's place in the batch, so batches never share one."""
	moved = failed = not_attempted = reached = 0
	began = time.monotonic()
	try:
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", migration_name))
		frappe.only_for(["System Manager", "Process Owner"])
		for name in instance_names:
			if time.monotonic() - began >= BATCH_STOP_SECONDS:
				reason = _("The batch stopped early to stay inside its time limit.")
				not_attempted += _log_unmoved(
					migration_name, instance_names[reached:], "Not Attempted", reason, first_idx + reached
				)
				frappe.db.set_value("Processa Legacy Migration", migration_name, "stop_reason", reason)
				break
			if _migrate_by_name(ctx, name, first_idx + reached):
				moved += 1
			else:
				failed += 1
			reached += 1
			frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		if isinstance(e, JobTimeoutException):
			failed += _log_unmoved(
				migration_name,
				instance_names[reached : reached + 1],
				"Timed out",
				_("The batch ran out of time."),
				first_idx + reached,
			)
			not_attempted += _log_unmoved(
				migration_name,
				instance_names[reached + 1 :],
				"Not Attempted",
				_("The batch ran out of time before reaching this record."),
				first_idx + reached + 1,
			)
			frappe.db.set_value(
				"Processa Legacy Migration", migration_name, "stop_reason", _("The batch ran out of time.")
			)
		else:
			detail = frappe.get_traceback(with_context=False)
			failed += _log_unmoved(
				migration_name, instance_names[reached:], "Error", detail, first_idx + reached
			)
		_count_batch(migration_name, moved, failed, not_attempted)
		raise
	_count_batch(migration_name, moved, failed, not_attempted)


def _migrate_by_name(ctx: frappe._dict, name: str, idx: int) -> bool:
	"""migrate_record for one instance name, or record name when there is no old map; an instance deleted
	since start gets an Error Log row instead."""
	if not ctx.plm.from_model:
		return migrate_record(ctx, unstarted_record(ctx.plm.target_doctype, name), idx)
	if not frappe.db.exists("BPMN Process Instance", name):
		detail = _("The instance was deleted before its batch ran.")
		log_error_row(ctx.plm.name, frappe._dict(name=name), "No longer open", detail, idx)
		return False
	return migrate_record(ctx, frappe.get_doc("BPMN Process Instance", name), idx)


def fail_stalled_migrations() -> None:
	"""Hourly: end Queued or Running runs whose jobs are all gone, logging the records they never reached.

	A migration whose check fails is rolled back and logged, so the others are still checked."""
	for name in frappe.get_all(
		"Processa Legacy Migration", filters={"status": ["in", ["Queued", "Running"]]}, pluck="name"
	):
		try:
			_fail_if_stalled(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Processa Legacy Migration stalled-run check failed"),
				reference_doctype="Processa Legacy Migration",
				reference_name=name,
			)
			frappe.db.commit()


def _fail_if_stalled(name: str) -> None:
	plm = frappe.get_doc("Processa Legacy Migration", name)
	job_ids = [f"plm::{name}::start", *(f"plm::{name}::{n}" for n in range(1, plm.total_batches + 1))]
	if any(is_job_enqueued(job_id) for job_id in job_ids):
		return
	if not plm.total_batches:
		_fail_before_batches(
			name,
			_(
				"The run never queued its batches, so no record was moved. The map step that starts it "
				"failed or never ran: check the Error Log of the Action Processa Legacy Migration script."
			),
		)
		return

	logged = {row.old_instance if plm.from_model else row.document_name for row in plm.error_logs}
	unhandled = [name for name in records_to_move(plm) if name not in logged]
	detail = _("The run's background job stopped before this record was reached.")
	next_idx = max((row.idx for row in plm.error_logs), default=0) + 1
	not_attempted = _log_unmoved(name, unhandled, "Not Attempted", detail, next_idx)
	if not_attempted:
		frappe.db.set_value(
			"Processa Legacy Migration",
			name,
			{
				"not_attempted_count": plm.not_attempted_count + not_attempted,
				"stop_reason": _("The run's background job stopped before these records were reached."),
			},
		)
	finish(name)


def _fail_before_batches(migration_name: str, detail: str) -> None:
	"""Fail a run that never queued its batches with one Error Log row; no record was touched."""
	plm = frappe.get_doc("Processa Legacy Migration", migration_name)
	next_idx = max((row.idx for row in plm.error_logs), default=0) + 1
	log_error_row(migration_name, frappe._dict(), "Error", detail, next_idx)
	finish(migration_name)


def _log_unmoved(
	migration_name: str, instance_names: list[str], reason: str, detail: str, first_idx: int
) -> int:
	"""An Error Log row for each instance, or record when there is no old map, a batch did not move,
	deleted ones included; returns how many."""
	if not instance_names:
		return 0
	from_model, target_doctype = frappe.db.get_value(
		"Processa Legacy Migration", migration_name, ["from_model", "target_doctype"]
	)
	if from_model:
		instances = {
			d.name: d
			for d in frappe.get_all(
				"BPMN Process Instance",
				filters={"name": ["in", instance_names]},
				fields=["name", "context_doctype", "context_docname"],
			)
		}
		olds = [instances.get(name, frappe._dict(name=name)) for name in instance_names]
	else:
		olds = [unstarted_record(target_doctype, name) for name in instance_names]
	for i, old in enumerate(olds):
		log_error_row(migration_name, old, reason, detail, first_idx + i)
	return len(instance_names)


def _count_batch(migration_name: str, moved: int, failed: int, not_attempted: int = 0) -> None:
	"""Add one batch's counts in a single update and commit them; the batch that ends the run calls finish.

	The counts commit before finish, so a finish that fails leaves the run for the hourly check to finish."""
	plm_table = frappe.qb.DocType("Processa Legacy Migration")
	(
		frappe.qb.update(plm_table)
		.set(plm_table.migrated_count, plm_table.migrated_count + moved)
		.set(plm_table.failed_count, plm_table.failed_count + failed)
		.set(plm_table.not_attempted_count, plm_table.not_attempted_count + not_attempted)
		.set(plm_table.batches_done, plm_table.batches_done + 1)
		.where(plm_table.name == migration_name)
	).run()
	plm = frappe.db.get_value(
		"Processa Legacy Migration",
		migration_name,
		[
			"migrated_count",
			"failed_count",
			"not_attempted_count",
			"total_records",
			"batches_done",
			"total_batches",
			"run_by",
		],
		as_dict=True,
	)
	frappe.publish_realtime(
		"legacy_migration_progress",
		{
			"migration_name": migration_name,
			"migrated": plm.migrated_count,
			"failed": plm.failed_count,
			"not_attempted": plm.not_attempted_count,
			"total": plm.total_records,
			"batches_done": plm.batches_done,
			"total_batches": plm.total_batches,
		},
		user=plm.run_by,
		after_commit=True,
	)
	frappe.db.commit()
	if plm.batches_done == plm.total_batches:
		finish(migration_name)
		frappe.db.commit()


def finish(migration_name: str) -> None:
	"""Close a run: Completed when a record moved or there was nothing to move, else Failed.

	Tells the PLM's own process through the finish message."""
	plm = frappe.get_doc("Processa Legacy Migration", migration_name)
	nothing_to_move = not plm.total_records and not plm.error_logs
	status = "Completed" if plm.migrated_count or nothing_to_move else "Failed"
	plm.db_set({"status": status, "completed_at": now_datetime()})
	frappe.publish_realtime(
		"legacy_migration_progress",
		{"migration_name": migration_name, "completed": True},
		user=plm.run_by,
		after_commit=True,
	)
	own_instance = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": "Processa Legacy Migration",
			"context_docname": migration_name,
			"status": "Active",
		},
	)
	if own_instance:
		receive_message(
			frappe.get_doc("BPMN Process Instance", own_instance),
			FINISHED_MESSAGE,
			{"migration_status": status},
		)


def validate_setup(plm: "ProcessaLegacyMigration") -> None:
	"""Refuse a migration that could never run; fills each State Mapping row's Record Count."""
	from_model = frappe.get_doc("BPMN Process Model", plm.from_model) if plm.from_model else None
	to_model = frappe.get_doc("BPMN Process Model", plm.to_model)
	check_process_ownership(from_model, to_model)
	_check_maps(plm, from_model, to_model)
	fieldname = state_field(plm.target_doctype)
	if not fieldname:
		frappe.throw(_("{0} has neither a workflow_state nor a status field.").format(plm.target_doctype))
	_check_state_map(plm, to_model)
	_check_open_states_mapped(plm, fieldname)


def check_process_ownership(
	from_model: "BPMNProcessModel | None", to_model: "BPMNProcessModel", user: str | None = None
) -> None:
	"""Throw PermissionError unless *user* (default the session user) owns the processes of both maps,
	or of the new map when there is no old one. A System Manager passes."""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return
	for model in filter(None, (from_model, to_model)):
		if frappe.db.get_value("Process", model.process_name, "process_owner") != user:
			frappe.throw(
				_("You are not the Process Owner of {0}, the process of {1}.").format(
					model.process_name, model.name
				),
				frappe.PermissionError,
			)


def _check_maps(plm, from_model, to_model) -> None:
	if from_model and from_model.name == to_model.name:
		frappe.throw(_("Old Process Map and New Process Map must be different."))
	_check_old_map_deployed(from_model)
	if not to_model.serialized_spec:
		frappe.throw(_("New Process Map {0} is not currently deployed.").format(to_model.name))
	for model in filter(None, (from_model, to_model)):
		doctypes = _model_doctypes(model)
		if plm.target_doctype not in doctypes:
			frappe.throw(
				_("{0} runs on {1}, not on {2}.").format(
					model.name, ", ".join(sorted(doctypes)) or _("no DocType"), plm.target_doctype
				)
			)


def _check_old_map_deployed(from_model) -> None:
	if not from_model:
		return
	if not from_model.serialized_spec:
		frappe.throw(
			_(
				"Old Process Map {0} is not currently deployed. Leave Old Process Map empty to place its "
				"records by their state."
			).format(from_model.name)
		)


def _model_doctypes(model) -> set[str]:
	"""DocTypes a process model runs on: its target DocTypes, else its start events' trigger DocTypes."""
	doctypes = {d.doctype_name for d in model.target_doctypes}
	return doctypes or {e.trigger_doctype for e in model.start_events if e.trigger_doctype}


def _check_state_map(plm, to_model) -> None:
	for state, count in Counter(d.old_state for d in plm.state_map).items():
		if count > 1:
			frappe.throw(_("Old State {0} is mapped more than once.").format(state))

	spec = json.loads(to_model.serialized_spec)
	set_states = {cfg.get("workflowState") for cfg in spec.get("service_task_extensions", {}).values()}
	for d in plm.state_map:
		if d.new_state not in set_states:
			frappe.throw(_("No Set Workflow State step in {0} sets {1}.").format(to_model.name, d.new_state))


def _check_open_states_mapped(plm, fieldname: str) -> None:
	# With no old map, the State Mapping itself chooses which records move, so no state is missing.
	if not plm.from_model:
		_count_unstarted(plm)
		return
	docnames = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"process_model": plm.from_model,
			"context_doctype": plm.target_doctype,
			"status": ["in", OPEN_INSTANCE_STATUSES],
		},
		pluck="context_docname",
	)
	states = (
		frappe.get_all(plm.target_doctype, filters={"name": ["in", docnames]}, pluck=fieldname)
		if docnames
		else []
	)
	counts = Counter(states)
	for d in plm.state_map:
		d.record_count = counts[d.old_state]

	mapped = {d.old_state for d in plm.state_map}
	missing = [f"{state or _('(empty)')} ({count})" for state, count in counts.items() if state not in mapped]
	if missing:
		frappe.throw(
			_("Open records on {0} are in states with no State Mapping row: {1}").format(
				plm.from_model, ", ".join(missing)
			)
		)


def records_to_move(plm: "ProcessaLegacyMigration") -> list[str]:
	"""The old map's open instances, oldest first; with no old map, the records in a mapped Old State
	that no open instance runs, other than on another map of the new map's process."""
	if plm.from_model:
		return frappe.get_all(
			"BPMN Process Instance",
			filters={
				"process_model": plm.from_model,
				"context_doctype": plm.target_doctype,
				"status": ["in", OPEN_INSTANCE_STATUSES],
			},
			pluck="name",
			order_by="started_at asc",
		)
	record = frappe.qb.DocType(plm.target_doctype)
	return _unstarted(plm).select(record.name).orderby(record.creation).run(pluck=True)


def _count_unstarted(plm) -> None:
	"""Fill each State Mapping row's Record Count with the records a run with no old map would start."""
	# Save runs this before Frappe's mandatory check, so the State Mapping can still be empty.
	if not plm.state_map:
		return
	state = frappe.qb.DocType(plm.target_doctype)[state_field(plm.target_doctype)]
	counts = dict(_unstarted(plm).select(state, Count("*")).groupby(state).run())
	for d in plm.state_map:
		d.record_count = counts.get(d.old_state, 0)


def _unstarted(plm):
	"""A query over the Target DocType's records in a mapped Old State that no open instance runs.
	An open instance on another map of the new map's process does not count: the move retires it."""
	record = frappe.qb.DocType(plm.target_doctype)
	instance = frappe.qb.DocType("BPMN Process Instance")
	running = (
		frappe.qb.from_(instance)
		.select(instance.context_docname)
		.where(instance.context_doctype == plm.target_doctype)
		.where(instance.status.isin(OPEN_INSTANCE_STATUSES))
	)
	replaced_maps = other_maps_of_process(plm.to_model)
	if replaced_maps:
		running = running.where(instance.process_model.notin(replaced_maps))
	return (
		frappe.qb.from_(record)
		.where(record[state_field(plm.target_doctype)].isin([d.old_state for d in plm.state_map]))
		.where(record.name.notin(running))
	)
