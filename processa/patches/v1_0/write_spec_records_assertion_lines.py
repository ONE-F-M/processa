"""Write Spec records the assertion lines of the spec it wrote, so Run Specs can check them.

Run Specs compares the lines in the turn state's spec_assertions with the hashes Submit Assertions approved. Nothing wrote
spec_assertions, so on a site that took Write Spec from add_testing_agent_sandbox_tools every run_specs call stopped at "No spec was
written: call write_spec first." and every criterion ended as "Could not test". A script that already records them is left alone."""

import frappe

from processa.patches.v1_0.add_testing_agent_sandbox_tools import RECORD_ASSERTIONS

NAME = "Sandbox Tool: Write Spec"


def execute():
	script = frappe.db.get_value("Server Script", NAME, "script")
	if not script or "spec_assertions" in script:
		return
	frappe.db.set_value("Server Script", NAME, "script", script.rstrip("\n") + "\n" + RECORD_ASSERTIONS)
