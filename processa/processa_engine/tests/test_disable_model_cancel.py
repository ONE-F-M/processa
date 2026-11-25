# Copyright (c) 2026, one-fm and contributors
"""Switching a map off can cancel its Active instances, in a background job, without touching other maps."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.deploy import disable_process_model
from processa.processa_engine.compiler.lifecycle import cancel_running_instances
from processa.processa_engine.tests.test_instance_control import _instance
from processa.tests.test_timer_sweep import TIMER_XML

JOB = "processa.processa_engine.compiler.lifecycle.cancel_running_instances"


def _started(xml=TIMER_XML):
	instance = _instance(xml)
	instance.start()
	return instance


def _another_on_same_model(instance):
	other = frappe.get_doc({"doctype": "BPMN Process Instance", "process_model": instance.process_model}).insert()
	other.start()
	return other


def _status(instance):
	return frappe.db.get_value("BPMN Process Instance", instance.name, "status")


def _active_count(model_name):
	return frappe.db.count("BPMN Process Instance", {"process_model": model_name, "status": "Active"})


def _reason(model_name):
	return f"Process map {model_name} was switched off."


class TestDisableModelCancel(FrappeTestCase):
	def setUp(self):
		# Keep the fixtures and the cancelling inside the test transaction.
		commit = patch.object(frappe.db, "commit")
		self.commit = commit.start()
		self.addCleanup(commit.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _disable(self, model_name, **kwargs):
		with patch.object(frappe, "enqueue") as enqueue:
			result = disable_process_model(model_name, **kwargs)
		return result, enqueue

	def test_disable_with_cancel_leaves_no_active_instance_and_records_the_reason(self):
		first = _started()
		second = _another_on_same_model(first)
		model_name = first.process_model
		self.assertEqual(_active_count(model_name), 2)

		result, enqueue = self._disable(model_name, cancel_running=1)

		self.assertTrue(result["cancelling"])
		self.assertEqual(result["running_instances"], 2)
		enqueue.assert_called_once_with(JOB, queue="long", model_name=model_name, reason=_reason(model_name))

		cancel_running_instances(model_name=model_name, reason=_reason(model_name))

		self.assertEqual(_active_count(model_name), 0)
		for instance in (first, second):
			self.assertEqual(_status(instance), "Cancelled")
			log = frappe.get_all(
				"BPMN Activity Log",
				filters={"instance": instance.name, "action": "Cancelled"},
				fields=["data"],
			)
			self.assertEqual(len(log), 1)
			self.assertIn(_reason(model_name), log[0].data)
		self.assertTrue(self.commit.called)

	def test_an_active_instance_of_another_model_is_untouched(self):
		target = _started()
		other = _started()
		self.assertNotEqual(target.process_model, other.process_model)

		_, enqueue = self._disable(target.process_model, cancel_running=1)
		cancel_running_instances(**{k: v for k, v in enqueue.call_args.kwargs.items() if k != "queue"})

		self.assertEqual(_status(target), "Cancelled")
		self.assertEqual(_status(other), "Active")
		self.assertEqual(frappe.db.get_value("BPMN Process Model", other.process_model, "is_active"), 1)

	def test_disable_without_cancel_leaves_instances_active(self):
		instance = _started()

		result, enqueue = self._disable(instance.process_model)

		self.assertNotIn("cancelling", result)
		self.assertEqual(result["running_instances"], 1)
		enqueue.assert_not_called()
		self.assertEqual(frappe.db.get_value("BPMN Process Model", instance.process_model, "is_active"), 0)
		self.assertEqual(_status(instance), "Active")

	def test_an_already_inactive_model_with_cancel_cancels_its_active_instances(self):
		instance = _started()
		model_name = instance.process_model
		self._disable(model_name)
		self.assertEqual(_status(instance), "Active")

		result, enqueue = self._disable(model_name, cancel_running=1)

		self.assertEqual(
			result, {"success": True, "model": model_name, "running_instances": 1, "cancelling": True}
		)
		enqueue.assert_called_once_with(JOB, queue="long", model_name=model_name, reason=_reason(model_name))
		cancel_running_instances(model_name=model_name, reason=_reason(model_name))
		self.assertEqual(_status(instance), "Cancelled")

	def test_an_already_inactive_model_without_cancel_is_still_refused(self):
		instance = _started()
		self._disable(instance.process_model)

		with self.assertRaises(frappe.ValidationError):
			self._disable(instance.process_model)

	def test_a_user_without_a_recovery_role_cannot_cancel(self):
		instance = _started()
		frappe.set_user("Guest")

		with patch.object(frappe, "enqueue") as enqueue:
			with self.assertRaises(frappe.PermissionError):
				disable_process_model(instance.process_model, cancel_running=1)

		frappe.set_user("Administrator")
		enqueue.assert_not_called()
		self.assertEqual(frappe.db.get_value("BPMN Process Model", instance.process_model, "is_active"), 1)
		self.assertEqual(_status(instance), "Active")
