# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly Libraries box gets 'ProsAlly: Lib Layout', and the scripts load the layout helpers from it.

The library runs the node pipeline through subprocess and draws with networkx, so each task that loads it, and the
library task, gets an Approved request shipped by the patch. A second run changes nothing.
"""

from processa.patches.v1_0 import prosally_replies_move_to_library

LIBRARY = "ProsAlly: Lib Layout"
LOAD = f'_layout_lib = import_script("{LIBRARY}")'
MOVED = ("compile_ir", "layout_note", "relayout", "relayout_output", "diagram_edit_output")
APPROVED_TASKS = ("classify_intent", "generate_process", "modify_process", "lib_layout")
REASON = (
	"ProsAlly layout helpers moved into the map's library; they run the node pipeline through subprocess."
)


def execute():
	prosally_replies_move_to_library.execute(
		LIBRARY, "prosally_lib_layout.py", MOVED, LOAD, APPROVED_TASKS, REASON
	)
