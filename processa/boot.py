# Copyright (c) 2026, one-fm and contributors
"""What the desk needs to know at boot.

The ONE AI bundle's version, the Processa-controlled DocTypes and the DocTypes with a cancellation map.
The desk loads the bundle by a bare path through ``frappe.require``, so the version
keeps the 12h Cache-Control on /assets from pinning a browser to an old build.
"""

import os

import frappe

from processa.processa_engine.instances.listing import get_cancellation_maps, get_processa_controlled_doctypes

BUNDLE = ("public", "one_ai", "one-ai.iife.js")


def boot_session(bootinfo):
	bootinfo.one_ai_asset_version = asset_version()
	bootinfo.processa_doctypes = get_processa_controlled_doctypes()
	bootinfo.processa_cancellation_doctypes = sorted(get_cancellation_maps())


def asset_version() -> str:
	"""The bundle's mtime, matching www/one_ai/index.py.

	A missing bundle falls back to the site's build version rather than raising:
	the desk must boot on a site where the chat was never built.
	"""
	try:
		return str(int(os.path.getmtime(frappe.get_app_path("processa", *BUNDLE))))
	except OSError:
		return frappe.utils.get_build_version()
