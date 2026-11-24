# Copyright (c) 2026, one-fm and contributors
"""Records that change while a migration runs, a record moved twice, runs whose jobs or checks fail,
and runs with no old map, which start records that no instance runs."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.doctype.processa_legacy_migration import legacy_migration
from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_move import (
	migrate_record,
	unstarted_record,
)
from processa.processa_engine.doctype.processa_legacy_migration.legacy_migration_replay import (
	build_context,
	wait_ids,
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

	def test_with_no_old_map_a_script_sets_the_gateway_value_and_its_writes_are_undone(self):
		def routed(pid):
			script = (
				'<bpmn:scriptTask id="Script_route" name="Route"><bpmn:incoming>Flow_1</bpmn:incoming>'
				"<bpmn:outgoing>Flow_2</bpmn:outgoing><bpmn:script>"
				'frappe.get_doc({"doctype": "Note", "title": "plm fast-forward probe"}).insert()\n'
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
