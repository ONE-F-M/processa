# Copyright (c) 2026, one-fm and contributors
"""A new attempt of a delegation takes its state from the new attempt, not from the last one's suspended run."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.a2a import execute, task_store
from processa.tests.test_agent_callback import _a_process_model


class TestRetryAttemptState(FrappeTestCase):
	def setUp(self):
		self.process_model = _a_process_model()
		self.task = frappe.get_doc(
			{"doctype": "A2A Task", "direction": "Internal", "state": "working"}
		).insert(ignore_permissions=True)
		self.first = self._instance()
		self.task.db_set("instance", self.first.name, update_modified=False)

	def tearDown(self):
		frappe.db.rollback()

	def _instance(self, status="Active"):
		return frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": self.process_model,
				"status": status,
				"context_doctype": "A2A Task",
				"context_docname": self.task.name,
			}
		).insert(ignore_permissions=True)

	def _suspended_run(self, instance):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": instance.name,
				"process_model": self.process_model,
				"bpmn_id": "work",
				"element_type": "task",
				"status": "Suspended",
				"started_at": frappe.utils.now_datetime(),
				"pending_human_task": "h-first",
			}
		).insert(ignore_permissions=True)

	def _refresh(self):
		self.task.reload()
		with patch.object(frappe, "enqueue", lambda *a, **k: None):
			task_store.refresh_state(self.task)
		self.task.reload()

	def _start_another_attempt(self):
		started = {}

		def start(doc, model_name):
			started["instance"] = self._instance()

		with patch("processa.processa_engine.triggers._maybe_start_instance", side_effect=start):
			name = execute._start_another_attempt(self.task, self.process_model)
		self.task.db_set("instance", name, update_modified=False)
		return started["instance"]

	def test_a_first_attempt_that_suspends_reads_as_input_required(self):
		run = self._suspended_run(self.first)
		self._refresh()
		self.assertEqual(self.task.state, "input-required")
		self.assertEqual(self.task.agent_run, run.name)

	def test_a_new_attempt_clears_the_last_attempts_run(self):
		self._suspended_run(self.first)
		self._refresh()
		self._start_another_attempt()
		self.task.reload()
		self.assertFalse(self.task.agent_run)
		self.assertFalse(self.task.pending_human_task)

	def test_a_new_attempt_that_is_running_reads_as_working(self):
		self._suspended_run(self.first)
		self._refresh()
		self._start_another_attempt()
		self._refresh()
		self.assertEqual(self.task.state, "working")

	def test_a_new_attempt_that_errors_reads_as_failed(self):
		self._suspended_run(self.first)
		self._refresh()
		second = self._start_another_attempt()
		second.db_set("status", "Errored", update_modified=False)
		self._refresh()
		self.assertEqual(self.task.state, "failed")

	def test_a_new_attempt_that_suspends_points_at_its_own_run(self):
		self._suspended_run(self.first)
		self._refresh()
		second = self._start_another_attempt()
		run = self._suspended_run(second)
		self._refresh()
		self.assertEqual(self.task.state, "input-required")
		self.assertEqual(self.task.agent_run, run.name)
