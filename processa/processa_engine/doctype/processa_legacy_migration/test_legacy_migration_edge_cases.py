# Copyright (c) 2026, one-fm and contributors
"""Records that change while a migration runs, a record moved twice, runs whose jobs or checks fail,
and runs with no old map, which start records that no instance runs or that another map of the
process still runs."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.assignment import add_frappe_assignment
from processa.processa_engine.doctype.processa_legacy_migration import legacy_migration
from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_move import (
	migrate_record,
	unstarted_record,
)
from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_replay import (
	build_context,
	fast_forward,
	wait_ids,
)
from processa.processa_engine.doctype.processa_legacy_migration.test_legacy_migration import (
	review_assigned_to,
)
from processa.processa_engine.doctype.processa_legacy_migration.test_processa_legacy_migration import (
	APPROVED,
	DONE,
	DRAFT,
	DT,
	OLD,
	PR_OPENED,
	definitions,
	deploy,
	loop_xml,
	migration,
	node,
	old_instance,
	run_batch_jobs,
	run_start,
	with_changes,
)
from processa.processa_engine.engine import restore_workflow

MAPPING = [(DRAFT, DRAFT), (APPROVED, APPROVED)]
NOBODY = "_plm_edge_nobody@example.com"
PENDING = "PLM Edge Pending"


def returning_xml(pid, actions, script=None):
	"""Start, Set Draft, user task Draft with actions, then a gateway that can send the flow back to Draft,
	Set Pending, user task Pending, Set Done, End.

	With a script, it runs before the gateway and the default flow goes back to Draft; the other flow
	goes on when the script's step_valid is true. Without one, the first action sends the flow back."""
	task_actions = json.dumps([{"action": a} for a in actions]).replace('"', "&#34;")
	ask = (
		'<bpmn:userTask id="Task_ask" name="Draft" spiffworkflow:assigneeMode="DocField" '
		f'spiffworkflow:targetDoctype="{DT}" spiffworkflow:assigneeDocfield="owner" '
		f'spiffworkflow:taskActions="{task_actions}">'
		"<bpmn:incoming>Flow_1</bpmn:incoming><bpmn:incoming>Flow_back</bpmn:incoming>"
		"<bpmn:outgoing>Flow_2</bpmn:outgoing></bpmn:userTask>"
	)
	check = (
		'<bpmn:scriptTask id="Script_check" name="Check"><bpmn:incoming>Flow_2</bpmn:incoming>'
		f"<bpmn:outgoing>Flow_3</bpmn:outgoing><bpmn:script>{script}</bpmn:script></bpmn:scriptTask>"
		'<bpmn:sequenceFlow id="Flow_3" sourceRef="Script_check" targetRef="Gateway_1" />'
		if script
		else ""
	)
	back_is_default = bool(script)
	back_condition = "" if back_is_default else "<bpmn:conditionExpression>action == 'Retry'</bpmn:conditionExpression>"
	ok_condition = "<bpmn:conditionExpression>step_valid</bpmn:conditionExpression>" if script else ""
	return definitions(
		pid,
		'<bpmn:startEvent id="Start_1"><bpmn:outgoing>Flow_0</bpmn:outgoing></bpmn:startEvent>'
		+ node("state", "Task_draft", DRAFT, "Flow_0", "Flow_1")
		+ ask
		+ check
		+ f'<bpmn:exclusiveGateway id="Gateway_1" default="{"Flow_back" if back_is_default else "Flow_ok"}">'
		f"<bpmn:incoming>{'Flow_3' if script else 'Flow_2'}</bpmn:incoming>"
		"<bpmn:outgoing>Flow_back</bpmn:outgoing><bpmn:outgoing>Flow_ok</bpmn:outgoing>"
		"</bpmn:exclusiveGateway>"
		+ node("state", "Task_pending", PENDING, "Flow_ok", "Flow_4")
		+ node("user", "Task_wait", "Pending", "Flow_4", "Flow_5")
		+ node("state", "Task_done", DONE, "Flow_5", "Flow_6")
		+ '<bpmn:endEvent id="End_1"><bpmn:incoming>Flow_6</bpmn:incoming></bpmn:endEvent>'
		'<bpmn:sequenceFlow id="Flow_0" sourceRef="Start_1" targetRef="Task_draft" />'
		'<bpmn:sequenceFlow id="Flow_1" sourceRef="Task_draft" targetRef="Task_ask" />'
		'<bpmn:sequenceFlow id="Flow_2" sourceRef="Task_ask" '
		f'targetRef="{"Script_check" if script else "Gateway_1"}" />'
		'<bpmn:sequenceFlow id="Flow_back" sourceRef="Gateway_1" targetRef="Task_ask">'
		f"{back_condition}</bpmn:sequenceFlow>"
		'<bpmn:sequenceFlow id="Flow_ok" sourceRef="Gateway_1" targetRef="Task_pending">'
		f"{ok_condition}</bpmn:sequenceFlow>"
		'<bpmn:sequenceFlow id="Flow_4" sourceRef="Task_pending" targetRef="Task_wait" />'
		'<bpmn:sequenceFlow id="Flow_5" sourceRef="Task_wait" targetRef="Task_done" />'
		'<bpmn:sequenceFlow id="Flow_6" sourceRef="Task_done" targetRef="End_1" />',
	)


class TestLegacyMigrationEdgeCases(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for state in (DRAFT, APPROVED, DONE):
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
				).insert()
		frappe.get_doc(
			{
				"doctype": "User",
				"email": NOBODY,
				"first_name": "plm",
				"send_welcome_email": 0,
				"roles": [{"role": "Blogger"}],
			}
		).insert()
		cls.old_map = deploy("PLM Edge Old", OLD)
		cls.new_map = deploy("PLM Edge New", OLD)
		cls.waiting_review = old_instance(cls.old_map)
		cls.waiting_pr = old_instance(cls.old_map, "Task_review")
		cls.waiting_merge = old_instance(cls.old_map, "Task_review", PR_OPENED)
		cls.second_review = old_instance(cls.old_map)

	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_edge_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_edge_test")

	def _move(self, old, to_model):
		"""migrate_record under a Running PLM; returns moved, the PLM and the new instance."""
		from_model = frappe.db.get_value("BPMN Process Instance", old, "process_model")
		name = migration(from_model, to_model, MAPPING, status="Running")
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", name))
		moved = migrate_record(ctx, frappe.get_doc("BPMN Process Instance", old), 1)
		return moved, name, frappe.db.get_value("BPMN Process Instance", {"migrated_from": old}, "name")

	@staticmethod
	def _plm(name):
		return frappe.get_doc("Processa Legacy Migration", name)

	def test_a_record_moved_once_moves_again_to_a_newer_map(self):
		# The script step shifts every later task's id, so the copied Review row matches no task on this map.
		shifted = deploy(
			"PLM Edge Shifted", with_changes(OLD, after={"Task_draft": [("script", "Task_s", None)]})
		)
		_moved, _plm, first = self._move(self.waiting_pr, shifted)
		newer = deploy("PLM Edge Newer", with_changes(OLD, relabel={"Task_review": "Manager Review"}))
		moved, plm, second = self._move(first, newer)
		self.assertEqual(self._plm(plm).error_logs, [])
		logged = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": second, "action": "Migrated"},
			pluck="data",
			order_by="timestamp asc, creation asc",
		)
		self.assertEqual(json.loads(logged[-1]), {"migrated_from": first, "migration": plm})
		self.assertTrue(moved)
		workflow_state = frappe.db.get_value("BPMN Process Instance", second, "workflow_state")
		self.assertEqual(wait_ids(restore_workflow(json.loads(workflow_state))), {"Catch_pr"})

	def test_a_record_moved_twice_moves_a_third_time(self):
		shifted = deploy(
			"PLM Edge Shifted", with_changes(OLD, after={"Task_draft": [("script", "Task_s", None)]})
		)
		relabelled = deploy(
			"PLM Edge Relabelled", with_changes(OLD, relabel={"Task_review": "Manager Review"})
		)
		_moved, _plm, first = self._move(self.waiting_pr, shifted)
		_moved, _plm, second = self._move(first, relabelled)
		moved, plm, third = self._move(second, self.new_map)
		self.assertEqual(self._plm(plm).error_logs, [])
		self.assertTrue(moved)
		workflow_state = frappe.db.get_value("BPMN Process Instance", third, "workflow_state")
		self.assertEqual(wait_ids(restore_workflow(json.loads(workflow_state))), {"Catch_pr"})

	def test_an_instance_that_finished_after_the_run_started_is_not_moved(self):
		frappe.db.set_value("BPMN Process Instance", self.waiting_review, "status", "Completed")
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		moved, plm, new = self._move(self.waiting_review, self.new_map)
		self.assertFalse(moved)
		self.assertIsNone(new)
		row = self._plm(plm).error_logs[0]
		self.assertEqual((row.reason, row.old_instance), ("No longer open", self.waiting_review))
		self.assertEqual(frappe.db.get_value(DT, record, "workflow_state"), DRAFT)

	def test_an_instance_deleted_after_the_run_started_is_logged_and_its_batch_counted(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		jobs, _errors = run_start(name, run_jobs=False)
		frappe.db.delete("BPMN Process Instance", self.waiting_review)
		errors = run_batch_jobs(jobs)
		plm = self._plm(name)
		self.assertEqual(errors, [])
		self.assertEqual(
			[(r.reason, r.old_instance) for r in plm.error_logs], [("No longer open", self.waiting_review)]
		)
		self.assertEqual(
			(plm.migrated_count, plm.failed_count, plm.batches_done, plm.status), (3, 1, 1, "Completed")
		)

	def test_error_log_rows_keep_their_place_when_batches_run_out_of_order(self):
		name = migration(self.old_map, self.new_map, [(DONE, DONE)], status="Queued")
		with patch.object(legacy_migration, "BATCH_SIZE", 2):
			jobs, _errors = run_start(name, run_jobs=False)
		run_batch_jobs(list(reversed(jobs)))
		order = [n for _m, kwargs in jobs for n in kwargs["instance_names"]]
		rows = {r.old_instance: r.idx for r in self._plm(name).error_logs}
		self.assertEqual(rows, {n: i for i, n in enumerate(order, start=1)})

	def test_a_finish_that_fails_keeps_the_last_batch_counted(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		with patch.object(legacy_migration, "finish", side_effect=RuntimeError("message failed")):
			_jobs, errors = run_start(name)
		plm = self._plm(name)
		self.assertIsInstance(errors[0], RuntimeError)
		self.assertEqual((plm.batches_done, plm.total_batches, plm.migrated_count), (1, 1, 4))

	def test_one_failing_migration_does_not_stop_the_hourly_check(self):
		first, second = (migration(self.old_map, self.new_map, MAPPING, status="Running") for _ in range(2))
		for name in (self.waiting_pr, self.waiting_merge):
			frappe.db.set_value("BPMN Process Instance", name, "status", "Cancelled")
		real_finish = legacy_migration.finish

		def finish(migration_name):
			if migration_name == first:
				raise RuntimeError("finish failed")
			real_finish(migration_name)

		frappe.db.savepoint("plm_stalled_test")
		rollback = frappe.db.rollback
		with (
			patch.object(legacy_migration, "finish", side_effect=finish),
			patch.object(legacy_migration, "is_job_enqueued", return_value=False),
			patch.object(frappe.db, "commit", side_effect=lambda: frappe.db.savepoint("plm_stalled_test")),
			patch.object(
				frappe.db, "rollback", side_effect=lambda **kw: rollback(save_point="plm_stalled_test")
			),
		):
			legacy_migration.fail_stalled_migrations()
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", first, "status"), "Running")
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", second, "status"), "Failed")
		self.assertTrue(
			frappe.db.exists(
				"Error Log", {"reference_doctype": "Processa Legacy Migration", "reference_name": first}
			)
		)

	def test_a_todo_that_names_a_longer_instance_name_is_left_alone(self):
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": "Administrator",
				"reference_type": DT,
				"reference_name": record,
				"description": f'BPMN Task: "Other" on instance {self.waiting_review}9',
				"status": "Open",
			}
		).insert()
		frappe.db.set_value("ToDo", todo.name, "type", "Process")
		moved, _plm, _new = self._move(self.waiting_review, self.new_map)
		self.assertTrue(moved)
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "description"), todo.description)

	def test_a_batch_run_by_a_user_without_either_role_moves_nothing(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Running")
		with self.set_user(NOBODY), patch.dict(frappe.local.flags, {"in_test": False}):
			errors = run_batch_jobs(
				[(None, {"migration_name": name, "instance_names": [self.second_review], "first_idx": 1})]
			)
		self.assertIsInstance(errors[0], frappe.PermissionError)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")
		self.assertEqual([r.reason for r in self._plm(name).error_logs], ["Error"])

	def _unstarted(self, state):
		"""A record in state that no process instance runs."""
		record = frappe.get_doc({"doctype": DT}).insert().name
		frappe.db.set_value(DT, record, "workflow_state", state)
		return record

	def _run_without_old_map(self, mapping):
		name = migration(None, self.new_map, mapping, status="Queued")
		_jobs, errors = run_start(name)
		self.assertEqual(errors, [])
		return self._plm(name)

	def _instance_of(self, record):
		return frappe.db.get_value(
			"BPMN Process Instance", {"context_doctype": DT, "context_docname": record}
		)

	def test_with_no_old_map_a_record_without_an_instance_starts_at_its_mapped_state(self):
		record = self._unstarted(APPROVED)
		plm = self._run_without_old_map(MAPPING)
		# waiting_pr is also Approved, but its open instance leaves it to a run from its old map.
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 1, "Completed"))
		new = frappe.get_doc("BPMN Process Instance", self._instance_of(record))
		self.assertEqual((new.process_model, new.status, new.migrated_from), (self.new_map, "Active", None))
		self.assertEqual(wait_ids(restore_workflow(json.loads(new.workflow_state))), {"Catch_pr"})
		log = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": new.name, "action": ["in", ["Completed", "Migrated"]]},
			fields=["task_name", "action", "data"],
			order_by="creation asc",
		)
		self.assertEqual(
			[(r.task_name, r.action) for r in log], [("Review", "Completed"), ("Migrated", "Migrated")]
		)
		self.assertEqual(json.loads(log[0].data), {"action": "Approve", "migration": plm.name})
		self.assertEqual(frappe.db.get_value(DT, record, "workflow_state"), APPROVED)

	def test_with_no_old_map_a_step_nobody_can_take_is_needs_attention_and_nothing_starts(self):
		disabled = "_plm_edge_disabled@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": disabled, "first_name": "plm", "send_welcome_email": 0, "enabled": 0}
		).insert()
		unassignable = deploy("PLM Edge Unassignable", review_assigned_to(disabled))
		record = self._unstarted(DRAFT)
		name = migration(None, unassignable, [(DRAFT, DRAFT)], status="Queued")
		_jobs, errors = run_start(name)
		self.assertEqual(errors, [])
		rows = [r for r in self._plm(name).error_logs if r.document_name == record]
		self.assertEqual([r.reason for r in rows], ["Needs attention: no assignee"])
		self.assertIn(disabled, rows[0].error_message)
		self.assertIsNone(self._instance_of(record))

	def test_with_no_old_map_a_state_the_new_map_cannot_reach_is_logged_and_nothing_starts(self):
		record = self._unstarted(DONE)
		plm = self._run_without_old_map([(DONE, DONE)])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 0, "Failed"))
		self.assertEqual(
			[(r.document_name, r.reason, r.old_instance) for r in plm.error_logs],
			[(record, "State not reached", None)],
		)
		self.assertIsNone(self._instance_of(record))

	def test_a_record_started_with_no_old_map_moves_again_to_a_newer_map(self):
		record = self._unstarted(APPROVED)
		self._run_without_old_map(MAPPING)
		newer = deploy("PLM Edge Newer", with_changes(OLD, relabel={"Task_review": "Manager Review"}))
		moved, plm, _second = self._move(self._instance_of(record), newer)
		self.assertEqual(self._plm(plm).error_logs, [])
		self.assertTrue(moved)

	def test_with_no_old_map_a_script_sets_the_gateway_value_and_its_writes_and_jobs_are_undone(self):
		def routed(pid):
			script = (
				'<bpmn:scriptTask id="Script_route" name="Route"><bpmn:incoming>Flow_1</bpmn:incoming>'
				"<bpmn:outgoing>Flow_2</bpmn:outgoing><bpmn:script>"
				'frappe.get_doc({"doctype": "Note", "title": "plm fast-forward probe"}).insert()\n'
				'frappe.db.after_commit.add(lambda: frappe.cache.set_value("plm_fast_forward_probe", 1))\n'
				"go_on = True</bpmn:script></bpmn:scriptTask>"
			)
			return definitions(
				pid,
				'<bpmn:startEvent id="Start_1"><bpmn:outgoing>Flow_0</bpmn:outgoing></bpmn:startEvent>'
				+ node("state", "Task_draft", DRAFT, "Flow_0", "Flow_1")
				+ script
				+ '<bpmn:exclusiveGateway id="Gateway_1" default="Flow_skip"><bpmn:incoming>Flow_2</bpmn:incoming>'
				"<bpmn:outgoing>Flow_3</bpmn:outgoing><bpmn:outgoing>Flow_skip</bpmn:outgoing>"
				"</bpmn:exclusiveGateway>"
				+ node("user", "Task_review", "Review", "Flow_3", "Flow_4")
				+ node("state", "Task_approved", APPROVED, "Flow_4", "Flow_5")
				+ '<bpmn:endEvent id="End_1"><bpmn:incoming>Flow_5</bpmn:incoming>'
				"<bpmn:incoming>Flow_skip</bpmn:incoming></bpmn:endEvent>"
				'<bpmn:sequenceFlow id="Flow_0" sourceRef="Start_1" targetRef="Task_draft" />'
				'<bpmn:sequenceFlow id="Flow_1" sourceRef="Task_draft" targetRef="Script_route" />'
				'<bpmn:sequenceFlow id="Flow_2" sourceRef="Script_route" targetRef="Gateway_1" />'
				'<bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Task_review">'
				"<bpmn:conditionExpression>go_on</bpmn:conditionExpression></bpmn:sequenceFlow>"
				'<bpmn:sequenceFlow id="Flow_skip" sourceRef="Gateway_1" targetRef="End_1" />'
				'<bpmn:sequenceFlow id="Flow_4" sourceRef="Task_review" targetRef="Task_approved" />'
				'<bpmn:sequenceFlow id="Flow_5" sourceRef="Task_approved" targetRef="End_1" />',
			)

		record = self._unstarted(APPROVED)
		name = migration(None, deploy("PLM Edge Routed", routed), [(APPROVED, APPROVED)], status="Running")
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", name))
		self.assertTrue(migrate_record(ctx, unstarted_record(DT, record), 1))
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self._instance_of(record), "status"), "Completed"
		)
		self.assertFalse(frappe.db.exists("Note", {"title": "plm fast-forward probe"}))
		frappe.cache.delete_value("plm_fast_forward_probe")
		frappe.db.after_commit.run()
		self.assertIsNone(frappe.cache.get_value("plm_fast_forward_probe"))

	def test_a_run_whose_start_fails_fails_at_once_with_one_error_row(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		frappe.db.savepoint("plm_start_test")
		rollback = frappe.db.rollback
		with (
			patch.object(legacy_migration, "create_batch", side_effect=RuntimeError("no batches today")),
			patch.object(
				frappe.db,
				"rollback",
				side_effect=lambda save_point=None, **kw: rollback(save_point=save_point or "plm_start_test"),
			),
		):
			jobs, _errors = run_start(name, run_jobs=False)
		plm = self._plm(name)
		self.assertEqual(jobs, [])
		self.assertEqual(plm.status, "Failed")
		self.assertEqual(
			[(r.reason, r.document_name, r.old_instance) for r in plm.error_logs], [("Error", None, None)]
		)
		self.assertIn("no batches today", plm.error_logs[0].error_message)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")

	def test_a_stalled_run_that_never_queued_its_batches_gets_one_error_row_and_moves_nothing(self):
		# Running with no batch queued, as a Run Migration step that fails after setting Running leaves it.
		name = migration(self.old_map, self.new_map, MAPPING, status="Running")
		with (
			patch.object(legacy_migration, "is_job_enqueued", return_value=False),
			patch.object(frappe.db, "commit"),
		):
			legacy_migration.fail_stalled_migrations()
		plm = self._plm(name)
		self.assertEqual((plm.status, plm.failed_count), ("Failed", 0))
		self.assertEqual([(r.reason, r.old_instance) for r in plm.error_logs], [("Error", None)])
		self.assertIn("never queued its batches", plm.error_logs[0].error_message)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")

	def _on_one_process(self, *maps):
		"""Put the maps on one Process, as the old and new maps of a process are."""
		process = frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": "PLM Edge Process",
				"process_owner": "Administrator",
				"description": "Test",
			}
		).insert()
		for name in maps:
			frappe.db.set_value("BPMN Process Model", name, "process_name", process.name)

	@staticmethod
	def _record_of(instance):
		return frappe.db.get_value("BPMN Process Instance", instance, "context_docname")

	def test_an_old_map_that_is_not_deployed_is_refused_on_save(self):
		frappe.db.set_value("BPMN Process Model", self.old_map, "serialized_spec", None)
		with self.assertRaisesRegex(frappe.ValidationError, "Leave Old Process Map empty"):
			migration(self.old_map, self.new_map, MAPPING)

	def test_a_run_whose_old_map_was_disabled_after_the_save_fails_with_one_plain_error_row(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		frappe.db.set_value("BPMN Process Model", self.old_map, "serialized_spec", None)
		jobs, _errors = run_start(name, run_jobs=False)
		plm = self._plm(name)
		self.assertEqual((jobs, plm.status), ([], "Failed"))
		self.assertEqual([(r.reason, r.old_instance) for r in plm.error_logs], [("Error", None)])
		self.assertIn("Leave Old Process Map empty", plm.error_logs[0].error_message)
		self.assertNotIn("Traceback", plm.error_logs[0].error_message)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")

	def test_with_no_old_map_a_record_open_on_another_map_of_the_process_is_placed_and_its_instance_retired(
		self,
	):
		self._on_one_process(self.old_map, self.new_map)
		record = self._record_of(self.waiting_review)
		old = frappe.get_doc("BPMN Process Instance", self.waiting_review)
		waiting = next(r for r in old.active_tasks if r.status == "Waiting")
		frappe.db.set_value("BPMN Active Task", waiting.name, "assigned_user", NOBODY)
		add_frappe_assignment(old, NOBODY, "Review")
		with patch("processa.processa_engine.triggers.on_doc_event"):
			on_new_map = old_instance(self.new_map)

		draft = frappe.get_doc(
			"Processa Legacy Migration", migration(None, self.new_map, MAPPING, status="Queued")
		)
		legacy_migration._count_unstarted(draft)
		self.assertEqual({d.old_state: d.record_count for d in draft.state_map}, {DRAFT: 2, APPROVED: 2})
		frappe.delete_doc("Processa Legacy Migration", draft.name, force=True)

		plm = self._run_without_old_map(MAPPING)
		# The four records open on the old map move; the one already open on the new map is left alone.
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (4, 4, "Completed"))
		self.assertEqual(
			frappe.db.count("BPMN Process Instance", {"context_docname": self._record_of(on_new_map)}), 1
		)

		new = frappe.get_doc(
			"BPMN Process Instance",
			{"process_model": self.new_map, "context_doctype": DT, "context_docname": record},
		)
		self.assertEqual((new.status, new.migrated_from), ("Active", None))
		self.assertEqual(wait_ids(restore_workflow(json.loads(new.workflow_state))), {"Task_review"})
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", old.name, "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("BPMN Active Task", waiting.name, "status"), "Cancelled")
		retired = frappe.db.get_value(
			"BPMN Activity Log", {"instance": old.name, "action": "Retired"}, "data"
		)
		self.assertEqual(json.loads(retired), {"replaced_by": new.name})
		self.assertEqual(
			frappe.get_all(
				"ToDo",
				filters={"reference_type": DT, "reference_name": record, "allocated_to": NOBODY},
				pluck="status",
			),
			["Closed"],
		)

	def test_with_no_old_map_a_record_that_cannot_be_placed_keeps_its_open_instance(self):
		self._on_one_process(self.old_map, self.new_map)
		record = self._record_of(self.second_review)
		frappe.db.set_value(DT, record, "workflow_state", DONE)
		plm = self._run_without_old_map([(DONE, DONE)])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 0, "Failed"))
		self.assertEqual(
			[(r.document_name, r.reason) for r in plm.error_logs], [(record, "State not reached")]
		)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")
		self.assertEqual(
			frappe.db.count("BPMN Process Instance", {"context_doctype": DT, "context_docname": record}), 1
		)

	def _returning_map(self, title, actions, script=None):
		if not frappe.db.exists("Workflow State", PENDING):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": PENDING, "style": "Primary"}
			).insert()
		return deploy(title, lambda pid: returning_xml(pid, actions, script))

	def _run_on(self, new_map, mapping):
		name = migration(None, new_map, mapping, status="Queued")
		_jobs, errors = run_start(name)
		self.assertEqual(errors, [])
		return self._plm(name)

	def _walk(self, new_map, state):
		"""fast_forward for a new record in state, which the map's own mapping row maps to itself."""
		record = self._unstarted(state)
		name = migration(None, new_map, [(state, state)], status="Running")
		ctx = build_context(self._plm(name))
		return fast_forward(ctx, unstarted_record(DT, record))

	def _waits_of(self, record):
		workflow_state = frappe.db.get_value("BPMN Process Instance", self._instance_of(record), "workflow_state")
		return wait_ids(restore_workflow(json.loads(workflow_state)))

	def test_with_no_old_map_a_check_that_sends_the_task_back_ends_at_the_next_wait(self):
		new_map = self._returning_map("PLM Edge Sends Back", ["Approve"], script="step_valid = False")
		record = self._unstarted(PENDING)
		plm = self._run_on(new_map, [(PENDING, PENDING)])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 1, "Completed"))
		self.assertEqual(plm.error_logs, [])
		self.assertEqual(self._waits_of(record), {"Task_wait"})
		self.assertEqual(frappe.db.get_value(DT, record, "workflow_state"), PENDING)

	def test_with_no_old_map_a_first_action_that_loops_leaves_the_task_by_the_second(self):
		new_map = self._returning_map("PLM Edge First Loops", ["Retry", "Approve"])
		record = self._unstarted(PENDING)
		plm = self._run_on(new_map, [(PENDING, PENDING)])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 1, "Completed"))
		self.assertEqual(self._waits_of(record), {"Task_wait"})
		self.assertEqual(frappe.db.get_value(DT, record, "workflow_state"), PENDING)

	def test_with_no_old_map_a_record_mapped_to_draft_stops_at_the_draft_task_without_an_action(self):
		new_map = self._returning_map("PLM Edge Stops At Draft", ["Approve"], script="step_valid = False")
		result = self._walk(new_map, DRAFT)
		self.assertEqual(result.steps, [])
		self.assertEqual(result.last_state, DRAFT)
		self.assertEqual(wait_ids(result.wf), {"Task_ask"})

	def test_with_no_old_map_a_state_no_step_reaches_names_the_step_that_came_back_and_its_action(self):
		script = 'frappe.msgprint("Phone number is missing")\nstep_valid = False'
		new_map = self._returning_map("PLM Edge Unreachable", ["Approve"], script=script)
		record = self._unstarted(DONE)
		plm = self._run_on(new_map, [(DONE, DONE)])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (1, 0, "Failed"))
		rows = [r for r in plm.error_logs if r.document_name == record]
		self.assertEqual([r.reason for r in rows], ["State not reached"])
		self.assertIn("came back to Draft after taking the action Approve", rows[0].error_message)
		self.assertIn("Phone number is missing", rows[0].error_message)
		self.assertIsNone(self._instance_of(record))

	def test_with_no_old_map_an_engine_loop_with_no_wait_names_the_step_it_repeats(self):
		record = self._unstarted(DRAFT)
		plm = self._run_on(deploy("PLM Edge Engine Loop", loop_xml), [(DRAFT, DRAFT)])
		rows = [r for r in plm.error_logs if r.document_name == record]
		self.assertEqual([r.reason for r in rows], ["Replay stuck"])
		self.assertIn("without reaching a wait", rows[0].error_message)
		self.assertIn(f"Set {DRAFT}", rows[0].error_message)
		self.assertIsNone(self._instance_of(record))

	def test_with_no_old_map_no_record_takes_the_same_action_on_the_same_step_twice(self):
		sends_back = self._returning_map("PLM Edge Once Back", ["Approve"], script="step_valid = False")
		first_loops = self._returning_map("PLM Edge Once Loops", ["Retry", "Approve"])
		for new_map, expected in ((sends_back, [("Draft", "Approve")]), (first_loops, [("Draft", "Retry")])):
			result = self._walk(new_map, PENDING)
			taken = [(s.name, s.data["action"]) for s in result.steps]
			self.assertEqual(taken, expected)
			self.assertEqual(result.last_state, PENDING)
			self.assertEqual(wait_ids(result.wf), {"Task_wait"})
