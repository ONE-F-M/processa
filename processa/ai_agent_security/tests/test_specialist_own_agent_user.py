# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A coding agent that shared another agent's user gets its own."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_evals.tests.factories import make_agent_configuration
from processa.ai_agent_security import identity
from processa.patches.v1_0 import give_specialists_their_own_agent_user as own_user_patch

AGENTS_PATH = "processa.patches.v1_0.grant_specialists_work_item_read.AGENTS"


def _agent_with_user():
	"""A saved agent holding the user the process would have given it."""
	agent = make_agent_configuration()
	email = identity.ensure_agent_user(agent)
	agent.db_set("agent_user", email, update_modified=False)
	return agent


class TestSpecialistOwnAgentUser(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_an_agent_sharing_another_agents_user_gets_its_own(self):
		first = _agent_with_user()
		second = make_agent_configuration()
		second.db_set("agent_user", first.agent_user, update_modified=False)
		shared = first.agent_user

		with patch(AGENTS_PATH, (second.name,)):
			own_user_patch.execute()

		own = identity.agent_email(second.name)
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", second.name, "agent_user"), own)
		self.assertTrue(frappe.db.exists("User", own))
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", first.name, "agent_user"), shared)
		self.assertTrue(frappe.db.exists("User", shared))

	def test_an_agent_user_no_other_agent_holds_is_not_changed(self):
		agent = make_agent_configuration()
		own = _agent_with_user_of(agent, f"_test_unshared_{frappe.generate_hash(length=6)}@agents.invalid")

		with patch(AGENTS_PATH, (agent.name,)):
			own_user_patch.execute()

		self.assertEqual(frappe.db.get_value("AI Agent Configuration", agent.name, "agent_user"), own)
		self.assertNotEqual(own, identity.agent_email(agent.name))


def _agent_with_user_of(agent, email):
	"""Give *agent* a user that exists but is not the one derived from its name."""
	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.update({"email": email, "first_name": "Unshared", "send_welcome_email": 0})
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
	agent.db_set("agent_user", email, update_modified=False)
	return email
