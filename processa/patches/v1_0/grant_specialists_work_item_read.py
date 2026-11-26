"""Give the Dev, Frontend, Mobile App and Connector agents the Developer role and a user of their own, so read_work_item can read the Work Item they work on."""

import frappe

from processa.ai_agent_security import identity

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent", "Connector Agent")
ROLE = "Developer"


def execute():
	if not frappe.db.exists("Role", ROLE):
		return
	for agent in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", agent):
			continue
		doc = frappe.get_doc("AI Agent Configuration", agent)
		if ROLE not in {row.role for row in doc.get("agent_roles") or []}:
			doc.append("agent_roles", {"role": ROLE})
			doc.save(ignore_permissions=True)
		email = identity.ensure_agent_user(doc)
		if email and doc.get("agent_user") != email:
			doc.db_set("agent_user", email, update_modified=False)
