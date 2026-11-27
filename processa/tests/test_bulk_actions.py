# Copyright (c) 2026, one-fm and contributors
"""Unit tests for the list view's bulk actions: which actions a selection offers, and applying one.

Run with:
	bench run-tests --app processa --module processa.tests.test_bulk_actions
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.instances import bulk_actions

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]

COMPLETE_TASK = "processa.processa_engine.instances.bulk_actions.task_actions.complete_task"


def _task(action_names="Approve,Reject", **kwargs):
	"""A Waiting task row as resolve_selection reads it, assigned to the running user by default."""
	row = frappe._dict(
		task_id=kwargs.pop("task_id", f"task-{frappe.generate_hash(length=6)}"),
		task_name="Review",
		task_type="User Task",
		task_actions=json.dumps([{"action": name} for name in action_names.split(",") if name]),
		assigned_user=frappe.session.user,
		assigned_role="",
		other_allowed_users="",
		relieved_user="",
		reliever_user="",
	)
	row.update(kwargs)
	return row


def _instance(name="INST-001", status="Active", engine_in_progress=0):
	return frappe._dict(name=name, status=status, engine_in_progress=engine_in_progress)


def _actions(instances, tasks, user=None, readable=True):
	"""Classify one record the way resolve_selection does, without touching the database for it."""
	waiting = {instances[0].name: tasks} if instances and tasks else {}
	return bulk_actions._record_actions(
		"ToDo", "TODO-001", instances, waiting, user or frappe.session.user, readable
	)


class TestRecordActions(FrappeTestCase):
	"""Why a single record offers an action, or does not."""

	def test_waiting_task_offers_its_actions(self):
		record = _actions([_instance()], [_task()])
		self.assertEqual(sorted(record.actions), ["Approve", "Reject"])
		self.assertIsNone(record.reason)

	def test_unreadable_record_is_blocked(self):
		record = _actions([_instance()], [_task()], readable=False)
		self.assertEqual(record.actions, {})
		self.assertFalse(record.has_instance)
		self.assertEqual(record.reason, "No permission")

	def test_record_without_instance_is_blocked(self):
		record = _actions([], [])
		self.assertFalse(record.has_instance)
		self.assertEqual(record.reason, "No process instance")

	def test_inactive_process_is_blocked(self):
		record = _actions([_instance(status="Completed")], [_task()])
		self.assertTrue(record.has_instance)
		self.assertEqual(record.reason, "Process is not active")

	def test_engine_in_progress_is_blocked(self):
		record = _actions([_instance(engine_in_progress=1)], [_task()])
		self.assertEqual(record.reason, "Already processing")

	def test_instance_without_waiting_task_is_blocked(self):
		record = _actions([_instance()], [])
		self.assertEqual(record.reason, "No waiting task")

	def test_ai_human_task_is_ignored(self):
		record = _actions([_instance()], [_task(task_type="AI Human Task")])
		self.assertEqual(record.reason, "No waiting task")

	def test_two_tasks_offering_one_action_are_ambiguous(self):
		record = _actions([_instance()], [_task("Approve"), _task("Approve")])
		self.assertEqual(record.actions, {})
		self.assertEqual(record.reason, "More than one task offers this action")

	def test_ambiguity_only_drops_the_shared_action(self):
		record = _actions([_instance()], [_task("Approve"), _task("Approve,Reject")])
		self.assertEqual(sorted(record.actions), ["Reject"])

	def test_signature_action_is_excluded_from_bulk(self):
		row = _task("")
		row.task_actions = json.dumps([{"action": "Approve", "requireDigitalSignature": "true"}])
		record = _actions([_instance()], [row])
		self.assertEqual(record.actions, {})
		self.assertEqual(record.reason, "Digital signature required")

	def test_task_assigned_to_someone_else_is_not_offered(self):
		record = _actions(
			[_instance()],
			[_task(assigned_user="assignee@example.com")],
			user="nobody@example.com",
		)
		self.assertEqual(record.actions, {})
		self.assertEqual(record.reason, "Not authorized")


class TestSelectionLimits(FrappeTestCase):
	"""What a selection may contain."""

	def test_empty_selection_throws(self):
		self.assertRaises(frappe.ValidationError, bulk_actions.parse_docnames, "[]")

	def test_oversized_selection_throws(self):
		names = json.dumps([f"DOC-{i}" for i in range(bulk_actions.MAX_DOCUMENTS + 1)])
		self.assertRaises(frappe.ValidationError, bulk_actions.parse_docnames, names)

	def test_duplicate_names_are_collapsed(self):
		self.assertEqual(bulk_actions.parse_docnames('["A", "A", "B"]'), ["A", "B"])


class TestBulkActionContext(FrappeTestCase):
	"""What the whole selection offers, over real documents and instances."""

	def setUp(self):
		self.todos = []
		self.instances = []

	def tearDown(self):
		with patch("frappe.model.document.run_server_script_for_doc_event"):
			for instance in self.instances:
				frappe.delete_doc("BPMN Process Instance", instance, force=True, ignore_permissions=True)
			for todo in self.todos:
				frappe.delete_doc("ToDo", todo, force=True, ignore_permissions=True)

	def _document(self, actions="Approve,Reject", with_instance=True, status="Active"):
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": f"bulk-{frappe.generate_hash(length=6)}",
				"allocated_to": frappe.session.user,
			}
		)
		todo.insert(ignore_permissions=True)
		self.todos.append(todo.name)

		if with_instance:
			instance = frappe.get_doc(
				{
					"doctype": "BPMN Process Instance",
					"process_id": f"bulk-{frappe.generate_hash(length=6)}",
					"status": status,
					"context_doctype": "ToDo",
					"context_docname": todo.name,
					"active_tasks": [
						{
							"task_id": f"task-{frappe.generate_hash(length=6)}",
							"task_name": "Review",
							"task_type": "User Task",
							"status": "Waiting",
							"task_actions": json.dumps(
								[{"action": name} for name in actions.split(",") if name]
							),
							"assigned_user": frappe.session.user,
						}
					],
				}
			)
			instance.flags.ignore_mandatory = True
			# A site that keeps Server Scripts switched off cannot run the doc events an insert fires.
			with patch("frappe.model.document.run_server_script_for_doc_event"):
				instance.insert(ignore_permissions=True, ignore_mandatory=True)
			self.instances.append(instance.name)

		return todo.name

	def test_only_actions_every_record_offers_are_returned(self):
		both = self._document("Approve,Reject")
		approve_only = self._document("Approve")

		context = bulk_actions.get_bulk_action_context("ToDo", json.dumps([both, approve_only]))

		self.assertEqual(context["actions"], ["Approve"])
		self.assertEqual(context["with_instance"], 2)
		self.assertEqual(context["eligible"], 2)

	def test_mixed_selection_offers_nothing(self):
		with_instance = self._document("Approve")
		without_instance = self._document(with_instance=False)

		context = bulk_actions.get_bulk_action_context("ToDo", json.dumps([with_instance, without_instance]))

		self.assertTrue(context["mixed"])
		self.assertEqual(context["actions"], [])
		self.assertEqual(context["blocked"][without_instance], "No process instance")

	def test_selection_without_any_instance_is_not_mixed(self):
		plain = self._document(with_instance=False)

		context = bulk_actions.get_bulk_action_context("ToDo", json.dumps([plain]))

		self.assertFalse(context["mixed"])
		self.assertEqual(context["without_instance"], 1)
		self.assertEqual(context["actions"], [])

	def test_blocked_record_is_named_with_its_reason(self):
		live = self._document("Approve")
		done = self._document("Approve", status="Completed")

		context = bulk_actions.get_bulk_action_context("ToDo", json.dumps([live, done]))

		self.assertEqual(context["actions"], [])
		self.assertEqual(context["eligible"], 1)
		self.assertEqual(context["blocked"][done], "Process is not active")


class TestRunBulkTaskAction(FrappeTestCase):
	"""The loop: every record is attempted, and one failure does not undo the others."""

	def _selection(self, records):
		return patch.object(bulk_actions, "resolve_selection", return_value=records)

	def test_every_record_is_completed_and_reported(self):
		selection = {
			"DOC-1": frappe._dict(actions={"Approve": ("INST-1", "task-1")}, reason=None),
			"DOC-2": frappe._dict(actions={"Approve": ("INST-2", "task-2")}, reason=None),
		}
		with self._selection(selection), patch(COMPLETE_TASK) as complete, patch.object(frappe.db, "commit"):
			summary = bulk_actions.run_bulk_task_action("ToDo", ["DOC-1", "DOC-2"], "Approve")

		self.assertEqual(summary["succeeded"], ["DOC-1", "DOC-2"])
		self.assertEqual(summary["failed"], [])
		self.assertEqual(complete.call_count, 2)
		complete.assert_called_with("INST-2", "task-2", {"action": "Approve"})

	def test_a_failure_does_not_stop_the_rest(self):
		selection = {
			"DOC-1": frappe._dict(actions={"Approve": ("INST-1", "task-1")}, reason=None),
			"DOC-2": frappe._dict(actions={"Approve": ("INST-2", "task-2")}, reason=None),
		}
		with (
			self._selection(selection),
			patch(COMPLETE_TASK, side_effect=[frappe.ValidationError("Not allowed"), None]),
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch.object(frappe, "log_error"),
		):
			summary = bulk_actions.run_bulk_task_action("ToDo", ["DOC-1", "DOC-2"], "Approve")

		self.assertEqual(summary["succeeded"], ["DOC-2"])
		self.assertEqual(summary["failed"][0]["docname"], "DOC-1")
		self.assertIn("Not allowed", summary["failed"][0]["reason"])

	def test_a_record_without_the_action_is_skipped_with_its_reason(self):
		selection = {
			"DOC-1": frappe._dict(actions={"Approve": ("INST-1", "task-1")}, reason=None),
			"DOC-2": frappe._dict(actions={}, reason="Not authorized"),
		}
		with self._selection(selection), patch(COMPLETE_TASK) as complete, patch.object(frappe.db, "commit"):
			summary = bulk_actions.run_bulk_task_action("ToDo", ["DOC-1", "DOC-2"], "Approve")

		self.assertEqual(complete.call_count, 1)
		self.assertEqual(summary["skipped"], [{"docname": "DOC-2", "reason": "Not authorized"}])

	def test_the_comment_reaches_the_task(self):
		selection = {"DOC-1": frappe._dict(actions={"Approve": ("INST-1", "task-1")}, reason=None)}
		with self._selection(selection), patch(COMPLETE_TASK) as complete, patch.object(frappe.db, "commit"):
			bulk_actions.run_bulk_task_action("ToDo", ["DOC-1"], "Approve", comment="looks fine")

		complete.assert_called_once_with("INST-1", "task-1", {"action": "Approve", "comment": "looks fine"})


class TestBulkActionDispatch(FrappeTestCase):
	"""A small selection runs in the request; a larger one goes to a worker."""

	def test_action_is_required(self):
		self.assertRaises(frappe.ValidationError, bulk_actions.bulk_task_action, "ToDo", '["A"]', "")

	def test_small_selection_runs_inline(self):
		names = json.dumps([f"DOC-{i}" for i in range(bulk_actions.INLINE_LIMIT - 1)])
		with patch.object(bulk_actions, "run_bulk_task_action", return_value={"total": 19}) as run:
			result = bulk_actions.bulk_task_action("ToDo", names, "Approve")

		self.assertEqual(result["mode"], "sync")
		run.assert_called_once()

	def test_large_selection_is_enqueued(self):
		names = json.dumps([f"DOC-{i}" for i in range(bulk_actions.INLINE_LIMIT)])
		job = MagicMock(id="job-1")
		with patch.object(frappe, "enqueue", return_value=job) as enqueue, patch.object(frappe, "msgprint"):
			result = bulk_actions.bulk_task_action("ToDo", names, "Approve")

		self.assertEqual(result["mode"], "async")
		self.assertEqual(result["job_id"], "job-1")
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		self.assertEqual(len(enqueue.call_args.kwargs["names"]), bulk_actions.INLINE_LIMIT)
