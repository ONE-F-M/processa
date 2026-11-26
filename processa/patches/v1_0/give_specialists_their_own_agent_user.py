"""Give each coding agent a user of its own where it shares another agent's.

On the BA site the Dev Agent's agent_user was another agent's user, so the
roles its tools ran with were that agent's, not the Dev Agent's. For each of the
four coding agents, if its agent_user is set, is not the address derived from
its own name, and is also held by another AI Agent Configuration, it is pointed
at its own user. The configuration that still holds the old user then has its
roles synced again, so that user matches its own configuration.

Every other agent_user is left alone, including addresses on the old .invalid
domain: an agent's address is stamped on everything it has written.
"""

import frappe

from processa.ai_agent_security import identity
from processa.patches.v1_0 import grant_specialists_work_item_read

DOCTYPE = "AI Agent Configuration"


def execute():
	for name in grant_specialists_work_item_read.AGENTS:
		if not frappe.db.exists(DOCTYPE, name):
			continue
		doc = frappe.get_doc(DOCTYPE, name)
		old_user = doc.get("agent_user")
		if not old_user or old_user == identity.agent_email(name):
			continue
		others = frappe.get_all(
			DOCTYPE,
			filters={"agent_user": old_user, "name": ["!=", name]},
			pluck="name",
			order_by="name asc",
		)
		if not others:
			continue

		doc.db_set("agent_user", None, update_modified=False)
		email = identity.ensure_agent_user(doc)
		if not email:
			# Could not provision: put back what was there rather than leave it empty.
			doc.db_set("agent_user", old_user, update_modified=False)
			continue
		doc.db_set("agent_user", email, update_modified=False)

		# The old user is still the other configuration's: bring its roles back
		# to what that configuration names.
		identity.ensure_agent_user(frappe.get_doc(DOCTYPE, others[0]))
