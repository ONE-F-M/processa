"""ProsAlly's classify, confirm, generate and modify steps send the files attached to the turn with each model call.

Build Context keeps the turn's files in the turn store; each step passes them to complete_sub_prompt.
Edits each script in place once; one whose anchor moved is logged and left as it is.
"""

import frappe

from processa.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

FILES = 'files=turn.get("files"))'

SCRIPTS = {
	"ProsAlly%Build Context": (
		(
			'    "user_text": task_data.get("user_text", "") or "",\n',
			'    "user_text": task_data.get("user_text", "") or "",\n    "files": task_data.get("files") or [],\n',
		),
	),
	"ProsAlly%Tool Classify Intent": (
		(
			'complete_sub_prompt(_cfg, "intent_classifier", prompt, system=_system)',
			'complete_sub_prompt(_cfg, "intent_classifier", prompt, system=_system, ' + FILES,
		),
	),
	"ProsAlly%Tool Confirm": (
		(
			'complete_sub_prompt(prosally_config(), "confirmer", prompt)',
			'complete_sub_prompt(prosally_config(), "confirmer", prompt, ' + FILES,
		),
	),
	"ProsAlly%Tool Generate Process": (
		(
			'complete_sub_prompt(_cfg, "process_generator", prompt, system=_system, max_tokens=_max_tokens)',
			'complete_sub_prompt(_cfg, "process_generator", prompt, system=_system, max_tokens=_max_tokens, '
			+ FILES,
		),
		(
			'complete_sub_prompt(_cfg, "process_generator", _outline_prompt, system=_system, max_tokens=4096)',
			'complete_sub_prompt(_cfg, "process_generator", _outline_prompt, system=_system, max_tokens=4096, '
			+ FILES,
		),
		(
			'complete_sub_prompt(_cfg, "process_generator", _phase_prompt, system=_system, max_tokens=_max_tokens)',
			'complete_sub_prompt(_cfg, "process_generator", _phase_prompt, system=_system, max_tokens=_max_tokens, '
			+ FILES,
		),
	),
	"ProsAlly%Tool Modify Process": (
		(
			'complete_sub_prompt(_cfg, "modifier", prompt, system=_system, max_tokens=_max_tokens)',
			'complete_sub_prompt(_cfg, "modifier", prompt, system=_system, max_tokens=_max_tokens, ' + FILES,
		),
	),
}


def execute():
	for pattern, edits in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Server Script", name)
		script = doc.script
		for anchor, replacement in edits:
			script = apply_edit(script, anchor, replacement)
			if script is None:
				frappe.log_error(
					title="prosally_steps_see_attached_files: anchor not found",
					message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
				)
				break
		if script and script != doc.script:
			doc.script = script
			doc.save(ignore_permissions=True)
