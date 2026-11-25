# Copyright (c) 2026, one-fm and contributors
"""The instance page names what a suspended agent waits on, and resumes it when that answer arrived unseen."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from processa.api import instances
from processa.tests.test_agent_callback import _a_process_model

EMPLOYEE = "resume-agent-employee@example.com"


class TestResumeSuspendedAgent(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_model": _a_process_model(), "status": "Active"}
		).insert(ignore_permissions=True)
		self.jobs = []

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _agent(self, deferred=None, minutes_ago=5):
		suspension = {"deferred_wait": deferred} if deferred else {}
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": self.instance.name,
				"process_model": self.instance.process_model,
				"bpmn_id": "test_sonnet",
				"element_type": "task",
				"status": "Suspended",
				"started_at": now_datetime(),
				"suspended_at": add_to_date(now_datetime(), minutes=-minutes_ago),
				"checkpoint": json.dumps({"wf_task_id": "wf-1", "suspension": suspension}),
			}
		).insert(ignore_permissions=True)

	def _sandbox_wait(self, state, minutes_ago=5, retry_of=None):
		run = frappe.get_doc(
			{
				"doctype": "Agent Sandbox Run",
				"state": state,
				"action": "checkout_pr_head",
				"target_app": "processa",
				"git_branch": "version-15",
				"work_item_description": "a resume test",
				"caller_instance": self.instance.name,
				"retry_of": retry_of,
			}
		).insert(ignore_permissions=True)
		run.db_set(
			{
				"request_payload": frappe.as_json({"action": "checkout_pr_head"}),
				"completed_at": add_to_date(now_datetime(), minutes=-minutes_ago)
				if state != "running"
				else None,
			},
			update_modified=False,
		)
		agent = self._agent({"run": run.name, "label": "checkout_pr_head for processa@version-15 (session)"})
		run.db_set("caller_agent_run", agent.name, update_modified=False)
		return agent, run

	def _a2a_wait(self, state):
		task = frappe.get_doc(
			{
				"doctype": "A2A Task",
				"direction": "Internal",
				"state": state,
				"caller_instance": self.instance.name,
			}
		).insert(ignore_permissions=True)
		task.db_set("completed_at", add_to_date(now_datetime(), minutes=-5), update_modified=False)
		agent = self._agent({"a2a_task": task.name, "label": "Ask the Dev Agent"})
		task.db_set("caller_agent_run", agent.name, update_modified=False)
		return agent, task

	def _listed(self, agent):
		return next(
			r for r in instances.get_suspended_ai_tasks(self.instance.name) if r["agent_run"] == agent.name
		)

	def _resume(self, agent):
		with patch.object(frappe, "enqueue", lambda *a, **k: self.jobs.append(k)):
			return instances.resume_suspended_agent(self.instance.name, agent.name)

	def test_a_sandbox_answer_that_arrived_unseen_is_listed_as_stuck(self):
		agent, run = self._sandbox_wait("completed")
		row = self._listed(agent)
		self.assertEqual(row["waits_on"], "agent_sandbox")
		self.assertEqual(row["wait_name"], run.name)
		self.assertTrue(row["answered_at"])
		self.assertTrue(row["stuck"])

	def test_an_answer_younger_than_a_minute_is_not_stuck(self):
		agent, _ = self._sandbox_wait("completed", minutes_ago=0)
		self.assertFalse(self._listed(agent)["stuck"])

	def test_a_sandbox_run_still_in_flight_is_not_stuck(self):
		agent, _ = self._sandbox_wait("running")
		row = self._listed(agent)
		self.assertEqual(row["wait_state"], "running")
		self.assertFalse(row["answered_at"])
		self.assertFalse(row["stuck"])

	def test_a_finished_delegation_is_listed_as_stuck(self):
		agent, task = self._a2a_wait("completed")
		row = self._listed(agent)
		self.assertEqual(row["waits_on"], "a2a")
		self.assertEqual(row["wait_name"], task.name)
		self.assertTrue(row["stuck"])

	def test_an_agent_waiting_for_a_person_is_never_stuck(self):
		agent = self._agent()
		row = self._listed(agent)
		self.assertEqual(row["waits_on"], "human")
		self.assertFalse(row["stuck"])

	def test_resume_hands_the_sandbox_result_to_the_agent_and_logs_who_did_it(self):
		agent, run = self._sandbox_wait("completed")
		result = self._resume(agent)
		self.assertEqual(result["resumed_with"], run.name)
		self.assertEqual(
			[j["job_id"] for j in self.jobs], [f"bpmn-ai-{self.instance.name}-devagentres-{run.name}"]
		)
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "resume_enqueued"), 1)
		self.assertTrue(
			frappe.db.exists(
				"BPMN Activity Log",
				{"instance": self.instance.name, "action": "Resumed", "user": "Administrator"},
			)
		)

	def test_resume_hands_the_delegated_answer_to_the_agent(self):
		agent, task = self._a2a_wait("completed")
		self._resume(agent)
		self.assertEqual(
			[j["job_id"] for j in self.jobs], [f"bpmn-ai-{self.instance.name}-a2ares-{task.name}"]
		)

	def test_resume_is_refused_while_the_answer_has_not_arrived(self):
		agent, _ = self._sandbox_wait("running")
		with self.assertRaises(frappe.ValidationError):
			self._resume(agent)
		self.assertEqual(self.jobs, [])

	def test_resume_is_refused_while_a_delayed_retry_is_scheduled(self):
		agent, _ = self._sandbox_wait("failed")
		with (
			patch("processa.agents_sandbox.sandbox.ops.retry_eligible", return_value=True),
			patch("processa.agents_sandbox.sandbox.supervisor.next_step", return_value={"delay": 30}),
		):
			self.assertFalse(self._listed(agent)["stuck"])
			with self.assertRaises(frappe.ValidationError):
				self._resume(agent)
		self.assertEqual(self.jobs, [])

	def test_resume_is_refused_for_an_agent_of_another_instance(self):
		agent, _ = self._sandbox_wait("completed")
		other = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_model": _a_process_model(), "status": "Active"}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			with patch.object(frappe, "enqueue", lambda *a, **k: self.jobs.append(k)):
				instances.resume_suspended_agent(other.name, agent.name)
		self.assertEqual(self.jobs, [])

	def test_resume_is_refused_without_a_recovery_role(self):
		agent, _ = self._sandbox_wait("completed")
		if not frappe.db.exists("User", EMPLOYEE):
			frappe.get_doc(
				{"doctype": "User", "email": EMPLOYEE, "first_name": "Resume", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(EMPLOYEE)
		with self.assertRaises(frappe.PermissionError):
			self._resume(agent)
		frappe.set_user("Administrator")
		self.assertEqual(self.jobs, [])
