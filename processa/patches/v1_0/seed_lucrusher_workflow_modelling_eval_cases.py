"""LuCrusher Baseline gains two modelling cases: Approve and Accept on one document are one workflow, and a
stop that one path sends to another path of the same process is a signal event, never a script task.
Idempotent by suite and case title.
"""

from processa.patches.v1_0.seed_lucrusher_eval_suite import (
	IN_ORDER,
	LUCID_DOC_ID,
	PARSED_DOC,
	judge_rubric,
	tool_call,
	turn_state,
)
from processa.patches.v1_0.seed_lucrusher_prosally_grounding_eval_cases import READ_THEN_DRAFT
from processa.patches.v1_0.seed_lucrusher_skill_eval_cases import NO_REFETCH, seed_cases
from processa.patches.v1_0.seed_lucrusher_skills import PROSALLY_SKILL, TOPOLOGY_SKILL

CLIENT_EVENT_SUMMARY = """I've successfully read the Lucidchart document "Client Event".
It contains 1 page(s).

### Page: Client Event
  Shapes: 9  |  Connections: 9
  Swimlanes/Roles: Operations Supervisor, Project Manager, Operations Manager
  Start/End events: Event requested, Event active, Event rejected
  Process steps (4):
    \u2022 Operations Supervisor creates the Client Event
    \u2022 Project Manager approves the Client Event
    \u2022 Operations Manager accepts the Client Event
    \u2022 Event schedules are generated
  Decision points (2):
    \u25c7 Approved?
    \u25c7 Accepted?"""

CHECK_SUMMARY = """I've successfully read the Lucidchart document "Pre-Employment Check".
It contains 1 page(s).

### Page: Pre-Employment Check
  Shapes: 10  |  Connections: 11
  Swimlanes/Roles: Recruiter, Medical Officer, PRO
  Start/End events: Check requested, Candidate cleared, Check cancelled
  Process steps (5):
    \u2022 Recruiter opens the pre-employment check
    \u2022 Medical Officer books the medical examination
    \u2022 PRO prepares the visa documents
    \u2022 Medical Officer records the medical result
    \u2022 PRO submits the documents to the ministry
  Decision points (1):
    \u25c7 Medical result fit?
  Text annotations / instructions (1):
    \u270e Document preparation runs at the same time as the medical examination. The moment the medical result is Unfit, the PRO stops preparing the documents and the check is cancelled."""


# A signal throw and a signal catch or boundary in the drafted blocks, and no ScriptTask line that carries the signal.
SIGNAL_DRAWN = (
	r"(?is)^(?=.*IntermediateThrowEvent[^\\]{0,120}signal)"
	r"(?=.*(?:IntermediateCatchEvent|Boundary\w*)[^\\]{0,120}signal)"
	r"(?!.*ScriptTask[^\\]{0,120}signal)"
)


def _context(user_text: str, bot_text: str, state: dict, summary: str) -> dict:
	"""The two messages before the turn, and the migration state and fetched document where Build Context reads them."""
	return {
		"conversation_messages": [
			{"message_type": "User", "text": user_text},
			{"message_type": "Bot", "text": bot_text},
		],
		"session_state": {
			**{key: value for key, value in state.items() if value is not None},
			f"lucid_doc:{LUCID_DOC_ID}": {**PARSED_DOC, "summary": summary},
		},
	}


def _approve_accept_case() -> dict:
	state = turn_state(
		"CODEBASE_SCAN_RESULT",
		confirmed_process={"name": "Client Event", "process_name": "Client Event"},
		document={"document_id": LUCID_DOC_ID, "title": "Client Event", "page_count": 1},
		codebase_scan={"apps_scanned": ["one_fm"], "matched_doctypes": ["Client Event"]},
	)
	context = _context(
		"scan the codebase for Client Event",
		"The scan found the Client Event DocType.",
		state,
		CLIENT_EVENT_SUMMARY,
	)
	return {
		"title": "Approve and Accept on one Client Event are one workflow, not two processes",
		"skill": TOPOLOGY_SKILL,
		"prompt": "analyse the topology for this process",
		"context": context,
		"calls": [tool_call(1, "finalize", "intent", "equals", "TOPOLOGY_PROPOSAL")],
		"assertions": [
			IN_ORDER,
			NO_REFETCH,
			judge_rubric(
				"The topology proposes ONE process for the Client Event in which creating, approving and "
				"accepting the Client Event are steps or workflow states of that one process. Approve and "
				"Accept are NOT proposed as separate processes, and no process is split off only because "
				"a different role approves or accepts the same document."
			),
		],
	}


def _signal_case() -> dict:
	state = turn_state(
		"MIGRATION_TASKS_CONFIRMED",
		confirmed_process={"name": "Pre Employment Check", "process_name": "Pre Employment Check"},
		document={"document_id": LUCID_DOC_ID, "title": "Pre-Employment Check", "page_count": 1},
		codebase_scan={"apps_scanned": ["one_fm"], "matched_doctypes": ["Pre Employment Check"]},
		topology={"total_processes": 1, "processes": [{"process_name": "Run Pre-Employment Check"}]},
		migration_tasks={
			"processes": [
				{
					"process_name": "Run Pre-Employment Check",
					"tasks": [
						{
							"category": "PROCESS MAP",
							"task": "Build the Run Pre-Employment Check map",
							"references": ["code"],
						}
					],
				}
			]
		},
	)
	context = _context(
		"approved", "Migration tasks confirmed. Next I can write the ProsAlly prompts.", state, CHECK_SUMMARY
	)
	return {
		"title": "A stop sent from the medical path to the document path is a signal event, not a script task",
		"skill": PROSALLY_SKILL,
		"prompt": "now write the ProsAlly prompts",
		"context": context,
		"calls": [*READ_THEN_DRAFT, tool_call(2, "finalize", "prosally_prompts", "regex", SIGNAL_DRAWN)],
		"assertions": [IN_ORDER],
	}


CASES = [_approve_accept_case(), _signal_case()]


def execute():
	seed_cases(CASES)
