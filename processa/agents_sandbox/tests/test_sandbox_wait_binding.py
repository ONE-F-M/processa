# Copyright (c) 2026, one-fm and contributors
"""An agent bound to a sandbox run that already settled is resumed by the binding, exactly once."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import agent_callback as cb
from processa.processa_engine.runtime.remote_waits import bind_agent_sandbox_wait
from processa.tests.test_agent_callback import _a_process_model

WF_TASK_ID = "wf-task-binding"
TASK = SimpleNamespace(id=WF_TASK_ID, task_spec=SimpleNamespace(bpmn_id="work", name="work"))


class TestSandboxWaitBinding(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_model": _a_process_model()}
		).insert(ignore_permissions=True)
		self.agent_run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": self.instance.name,
				"process_model": self.instance.process_model,
				"bpmn_id": "work",
				"element_type": "task",
				"status": "Suspended",
				"started_at": frappe.utils.now_datetime(),
				"checkpoint": json.dumps({"wf_task_id": WF_TASK_ID}),
			}
		).insert(ignore_permissions=True)
		self.jobs = []

	def _run(self, state, *, retry_of=None, action="prepare_site"):
		run = frappe.get_doc(
			{
				"doctype": "Agent Sandbox Run",
				"state": state,
				"target_app": "processa",
				"git_branch": "version-15",
				"work_item_description": "a binding test",
				"retry_of": retry_of,
			}
		).insert(ignore_permissions=True)
		run.db_set("request_payload", frappe.as_json({"action": action}), update_modified=False)
		return run

	def _bind(self, run_name):
		marker = {"agent_sandbox_run": run_name, "run": self.agent_run.name}
		with patch.object(frappe, "enqueue", lambda *a, **k: self.jobs.append(k)):
			bind_agent_sandbox_wait(self.instance, TASK, marker)

	def _resumed_with(self, run_name):
		return [
			j for j in self.jobs if j.get("job_id") == f"bpmn-ai-{self.instance.name}-devagentres-{run_name}"
		]

	def test_a_run_that_settled_before_the_binding_resumes_the_agent(self):
		run = self._run("completed")
		self._bind(run.name)
		self.assertEqual(len(self._resumed_with(run.name)), 1)
		self.assertEqual(self._resumed_with(run.name)[0]["kind"], "human_resume")
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "resume_enqueued"), 1)

	def test_a_run_still_in_flight_is_left_to_its_callback(self):
		run = self._run("running")
		self._bind(run.name)
		self.assertEqual(self.jobs, [])
		self.assertEqual(
			frappe.db.get_value("Agent Sandbox Run", run.name, "caller_agent_run"), self.agent_run.name
		)

	def test_a_run_already_resumed_is_not_resumed_again(self):
		run = self._run("completed")
		run.db_set("resume_enqueued", 1, update_modified=False)
		self._bind(run.name)
		self.assertEqual(self.jobs, [])

	def test_a_retry_in_flight_gets_the_caller_and_the_first_failure_is_not_given(self):
		original = self._run("failed")
		retry = self._run("running", retry_of=original.name)
		self._bind(original.name)
		self.assertEqual(self.jobs, [])
		self.assertEqual(
			frappe.db.get_value("Agent Sandbox Run", retry.name, "caller_agent_run"), self.agent_run.name
		)
		self.assertEqual(
			frappe.db.get_value("Agent Sandbox Run", retry.name, "caller_wf_task_id"), WF_TASK_ID
		)

	def test_a_retry_that_already_finished_resumes_with_the_retry(self):
		original = self._run("failed")
		retry = self._run("completed", retry_of=original.name)
		self._bind(original.name)
		self.assertEqual(len(self._resumed_with(retry.name)), 1)
		self.assertEqual(self._resumed_with(original.name), [])

	def test_a_failure_with_a_delayed_retry_scheduled_waits_for_the_retry(self):
		run = self._run("failed")
		with (
			patch("processa.agents_sandbox.sandbox.ops.retry_eligible", return_value=True),
			patch("processa.agents_sandbox.sandbox.supervisor.next_step", return_value={"delay": 30}),
		):
			self._bind(run.name)
		self.assertEqual(self.jobs, [])

	def test_a_failure_that_is_not_retried_resumes_with_the_failure(self):
		run = self._run("failed")
		with patch("processa.agents_sandbox.sandbox.ops.retry_eligible", return_value=False):
			self._bind(run.name)
		self.assertEqual(len(self._resumed_with(run.name)), 1)

	def test_a_result_after_the_binding_resumes_once_through_the_callback(self):
		run = self._run("running")
		stale = frappe.get_doc("Agent Sandbox Run", run.name)
		self._bind(run.name)
		with patch.object(frappe, "enqueue", lambda *a, **k: self.jobs.append(k)):
			cb._settle(stale, {"status": "prepared"})
		self.assertEqual(len(self._resumed_with(run.name)), 1)
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "resume_enqueued"), 1)
