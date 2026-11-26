# Copyright (c) 2026, one-fm and contributors
"""Library data files run the way import_script runs them, for tests of the functions they hold."""

from functools import cache
from types import ModuleType
from unittest.mock import patch

import frappe

from processa.patches.v1_0 import (
	docu_helpers_move_to_library,
	docu_tools_move_to_library,
	lucrusher_helpers_move_to_library,
	platform_helpers_move_to_libraries,
	prosally_context_move_to_library,
	prosally_ir_move_to_library,
	prosally_layout_move_to_library,
	prosally_map_xml_move_to_library,
	prosally_replies_move_to_library,
	prosally_stage_replies_move_to_library,
)
from processa.patches.v1_0.docu_helpers_move_to_library import uses_library
from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA, LIBRARIES

# (library, data file, moved names, load line) in the order patches.txt runs the patches.
MOVES = (
	(
		docu_helpers_move_to_library.LIBRARY,
		"docu_lib_schema.py",
		docu_helpers_move_to_library.MOVED,
		docu_helpers_move_to_library.LOAD,
	),
	(
		docu_helpers_move_to_library.LIBRARY,
		"docu_lib_schema.py",
		docu_tools_move_to_library.MOVED,
		docu_helpers_move_to_library.LOAD,
	),
	(
		lucrusher_helpers_move_to_library.LIBRARY,
		"lucrusher_lib_codebase.py",
		lucrusher_helpers_move_to_library.MOVED,
		lucrusher_helpers_move_to_library.LOAD,
	),
	*(
		(spec["library"], spec["data_file"], spec["moved"], spec["load"])
		for spec in platform_helpers_move_to_libraries.MOVES
	),
	(
		prosally_replies_move_to_library.LIBRARY,
		"prosally_lib_replies.py",
		prosally_replies_move_to_library.MOVED,
		prosally_replies_move_to_library.LOAD,
	),
	(
		prosally_ir_move_to_library.LIBRARY,
		"prosally_lib_ir.py",
		prosally_ir_move_to_library.MOVED,
		prosally_ir_move_to_library.LOAD,
	),
	(
		prosally_map_xml_move_to_library.LIBRARY,
		"prosally_lib_map_xml.py",
		prosally_map_xml_move_to_library.MOVED,
		prosally_map_xml_move_to_library.LOAD,
	),
	(
		prosally_stage_replies_move_to_library.LIBRARY,
		"prosally_lib_stage_replies.py",
		prosally_stage_replies_move_to_library.MOVED,
		prosally_stage_replies_move_to_library.LOAD,
	),
	(
		prosally_context_move_to_library.LIBRARY,
		"prosally_lib_context.py",
		prosally_context_move_to_library.MOVED,
		prosally_context_move_to_library.LOAD,
	),
	(
		prosally_layout_move_to_library.LIBRARY,
		"prosally_lib_layout.py",
		prosally_layout_move_to_library.MOVED,
		prosally_layout_move_to_library.LOAD,
	),
)
DATA_FILES = {**{library: data_file for library, data_file, _moved, _load in MOVES}, **LIBRARIES}


@cache
def library(data_file: str) -> ModuleType:
	"""The library as a module, so patch.object(library(...), name) reaches the functions that call name."""
	module = ModuleType(data_file.removesuffix(".py"))
	module.frappe = frappe
	code = (DATA / data_file).read_text()
	exec(code, module.__dict__)  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-codeinjection-eval
	return module


def import_script(name: str) -> ModuleType:
	"""What import_script gives a script on the map for the library called name."""
	return library(DATA_FILES[name])


def as_on_site(script: str) -> str:
	"""script with every library patch's import edit applied, as the sites hold it."""
	for _library, _data_file, moved, load in MOVES:
		script = uses_library(script, moved, load)
	return script


def patch_libraries(name: str, new) -> list:
	"""A patch.object of name in every library that defines it, all set to the same new."""
	return [
		patch.object(library(data_file), name, new)
		for data_file in sorted(set(DATA_FILES.values()))
		if name in library(data_file).__dict__
	]
