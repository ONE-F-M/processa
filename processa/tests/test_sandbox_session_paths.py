# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The three endpoints a sandbox session calls keep their dotted paths and stay guest-callable over POST only."""

import frappe
from frappe.tests.utils import FrappeTestCase

ENDPOINTS = ("register", "next_command", "post_result")


class TestSandboxSessionPaths(FrappeTestCase):
	def test_sandbox_session_endpoints_are_guest_post_only(self):
		for name in ENDPOINTS:
			path = f"processa.api.sandbox_session.{name}"
			with self.subTest(endpoint=path):
				func = frappe.get_attr(path)
				self.assertIn(func, frappe.whitelisted, f"{path} is not whitelisted")
				self.assertIn(func, frappe.guest_methods, f"{path} is not allow_guest")
				methods = frappe.allowed_http_methods_for_whitelisted_func.get(func)
				self.assertEqual([m.upper() for m in methods or []], ["POST"], f"{path} must allow only POST")
