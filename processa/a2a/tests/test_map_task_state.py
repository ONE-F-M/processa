# Copyright (c) 2026, one-fm and contributors
"""A task that started a map takes its state from the map's instance, not from the last AI run it pointed at."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from processa.a2a import task_store


def a_task(**over):
	return SimpleNamespace(
		**{"state": "working", "agent_run": None, "instance": None, "conversation": None, "status_message": None, **over}
	)


class TestMapTaskState(unittest.TestCase):
	def _states_set(self, task, run_status=None, instance_status=None):
		"""What refresh_state would write for this task, given the status of its run and of its instance."""

		def get_value(doctype, name, fields=None, as_dict=False):
			if doctype == "AI Agent Run":
				return SimpleNamespace(status=run_status, pending_human_task=None)
			return instance_status

		with (
			patch.object(task_store.frappe, "db", new=MagicMock()) as db,
			patch.object(task_store, "get_suspended_run", return_value=None),
			patch.object(task_store, "_latest_bot_reply", return_value=""),
			patch.object(task_store, "_set_state") as set_state,
		):
			db.get_value.side_effect = get_value
			task_store.refresh_state(task)
		return [call.args[1] for call in set_state.call_args_list]

	def test_a_failed_ai_step_does_not_fail_a_map_that_is_still_running(self):
		# The Sonnet step errors and the map retries on Opus: the instance is still Active.
		task = a_task(instance="inst-1", agent_run="sonnet-run")
		self.assertEqual(self._states_set(task, run_status="Error", instance_status="Active"), ["working"])

	def test_the_task_fails_when_the_instance_itself_fails(self):
		task = a_task(instance="inst-1", agent_run="sonnet-run")
		self.assertEqual(self._states_set(task, run_status="Error", instance_status="Errored"), ["failed"])

	def test_the_task_completes_when_the_map_completes_whatever_an_earlier_step_did(self):
		task = a_task(instance="inst-1", agent_run="sonnet-run")
		self.assertEqual(self._states_set(task, run_status="Error", instance_status="Completed"), ["completed"])

	def test_a_chat_task_still_takes_its_state_from_its_run(self):
		# A chat turn has a conversation, and its instance stays Active across turns.
		task = a_task(instance="inst-1", agent_run="run-1", conversation="conv-1")
		self.assertEqual(self._states_set(task, run_status="Error", instance_status="Active"), ["failed"])

	def test_a_task_with_only_a_run_takes_its_state_from_it(self):
		self.assertEqual(self._states_set(a_task(agent_run="run-1"), run_status="Success"), ["completed"])

	def test_a_finished_task_is_left_alone(self):
		task = a_task(state="completed", instance="inst-1", agent_run="run-1")
		self.assertEqual(self._states_set(task, run_status="Error", instance_status="Errored"), [])
