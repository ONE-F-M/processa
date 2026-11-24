# AGENTS.md: the AI agent runtime

Rules for the code that runs AI agents, and for the two editor assistants, Logix and ProsAlly. The runtime lives in this folder, `processa/processa_engine/agent_runtime/`. Agent definitions, configuration and provisioning live in `processa/ai_agent_registry/`, and agent tools in `processa/ai_agent_skills/`. The frontend half of both assistants is in [`frontend/AGENTS.md`](../../../frontend/AGENTS.md).

`processa/agents/` holds only an empty `__init__.py`. Do not put new code there.

## How an agent runs

- An agent is an AI Agent Configuration plus a process map. Its stages are DB Server Scripts called as Agent Tools by an AI Agent Task in that map. Prompts and stage scripts are seeded and changed by patches in `processa/patches/`, not edited in Python files.
- Every chat turn goes through one endpoint, `processa.api.agui.stream_agent_turn`, with the agent's `agent_id` and its fields in the turn `context`. Per-agent context builders (for example `build_prosally_turn_context` in `api/server_scripts.py`) add what a map needs.
- Each stage gets a prompt built from the conversation history. Stages share state within a turn through `turn_state.get_turn` and `update_turn` (this folder), and across turns through `ai_agent_conversations/session_state.py` (the Chat Session State DocType).
- `get_agent_config(agent_id)` in the AI Agent Configuration controller (`ai_agent_registry/doctype/ai_agent_configuration/`) returns an agent's settings and sub-prompt overrides.

## LLM providers

Adapters: `llm_gemini.py` (`GeminiAdapter`), `llm_anthropic.py` (`AnthropicAdapter`), `llm_openai.py` (`OpenAIAdapter`), all behind `BaseLLMAdapter` in `llm_base.py`. The data shapes they and the step loop pass around (`ToolSpec`, `StepResult`, `TurnRecord`, `CompletionResult` and others) are in `llm_types.py`.

`llm_factory.py: get_llm_adapter_from_settings(agent_config)` resolves the adapter:

1. The agent's linked AI Provider and its AI Model. The AI Model holds the key and the API model name. A disabled AI Model is not refused up front: the factory logs an error and builds the adapter with an empty key, so the first model call fails.
2. Otherwise `default_llm_provider` on Processa Settings, with the key and model taken from an enabled AI Model of the matching AI Provider.

To add a provider:

1. Add an adapter class and its branch in `get_llm_adapter()`.
2. Add the provider name to `_NAME_TO_ADAPTER`, `_ADAPTER_TO_NAME` and `_PROVIDER_DEFAULTS` in `llm_factory.py`.
3. Add it to the `default_llm_provider` options on Processa Settings.

## Conversations (`ai_agent_conversations/chat_persistence.py`)

- `Chat Conversation`, `Chat Message` and `Chat Participant` are processa DocTypes.
- Helpers: `create_conversation`, `create_agent_conversation`, `save_user_message`, `save_bot_message`, `load_history` (owner-only), `close_conversation`.
- Per-conversation step state (`get_or_create_state`, `update_state`) lives in the Redis cache under the key `chat_state:<conversation>`, not in a DocType.

## Generated scripts

### Two contracts

The shape a script backs decides how it runs (`shape_kind` in the turn context).

**script_task**: runs inside the SpiffWorkflow engine (`FrappeScriptEngine` in `processa_engine/engine/script_engine.py`), not inside an HTTP request, in one merged exec namespace.

- Injected: `frappe`, `_`, `doc`, `context_doctype`, `context_docname`, `task_data`, `result`, `instance`, `bpmn_id`, `agent_configuration` and `import_script`. Every workflow variable is also injected as a top-level name. Do not redefine any of them.
- Read inputs from `doc` and `task_data`; write outputs to `result`, which the engine merges into the task data for later steps and gateways.
- `frappe.form_dict` is always empty and `frappe.response` is ignored.
- No bare `return`: Server Scripts run as top-level code. Branch with `if`/`else` and abort with `frappe.throw()`.
- The Server Script record's `script_type` (`API`, `DocType Event`, `Scheduler Event`, `Permission Query`) decides how the record is stored, not what is injected.

**agent_tool**: backs a shape inside an AI Agent Task's ad-hoc Tools sub-process, run by `_run_server_script` in `ai_agent_skills/tools/shape_tools.py`, also in one merged exec namespace.

- Injected: the calling model's arguments as top-level names (declared by `spiffworkflow:aiToolParams`), plus `frappe`, `_`, `doc`, `context_doctype`, `context_docname`, `task_data` (the calling task's variables with the model's arguments on top), `result`, `instance`, `bpmn_id`, `ai_agent_config`, `shape_config` and `import_script`.
- The script runs as the agent's own user with permissions on, when the agent has one. `frappe.flags.requesting_user` holds the person who started the chat.
- Report expected failures as `result["error"] = "..."` so the model can recover; do not raise.
- `result` must be a flat, JSON-serializable dict.
- The turn-state bridge (`get_turn(context_docname)`, `update_turn(...)`) is the right way to reach per-turn state; keep those thin wrappers.

### Security validator (`processa/ai_agent_security/code_checks/script_validator.py`)

`validate_script(code)` gates every generated script and returns `{"valid": bool, "violations": [...], "findings": [...]}`. Each finding is `{rule, line, code, category, name}`.

- One AST pass finds every import, builtin call, Frappe function, dunder or object-graph attribute, write to the request session, permission keyword (such as `ignore_permissions=`), `def`, `lambda`, `class`, `while` and very large multiplication. Each is sorted into a Script Import Category. An import of a module in no category is Unlisted.
- A regular expression also flags destructive `frappe.db.sql` (DROP, TRUNCATE, ALTER, CREATE TABLE).
- No name is banned outright. A finding goes away when its category is Allowed by Default or an approval for the script covers it. Two findings can never be approved: a syntax error, and an `import_script` call without the script name in quotes.
- A rejected script is regenerated with its violations fed back into the writer prompt. The violation list is logged with `frappe.log_error` and never shown to the user.
- Never log a full generated script at INFO level.

## Logix

Logix writes and fixes Server Scripts for Script Tasks and Agent Tools in the editor. `AGENT_ID = "logix_agent"`.

- Stages: an intent classifier routes to a clarifier (asks one question, writes no code), a script writer (`script_task`), a tool writer (`agent_tool`), or a debugger. A reviewer checks the writer's output, then `validate_script` gates it. The stage names and the classifier's outputs live in DB Server Scripts and patches, not in Python.
- Debug path: `ai_agent_registry/definitions/logix/helpers.py:debug_inputs` puts `script_text` (a pasted script, else the linked script's code) and `last_error` on the turn. `last_error` is a pasted traceback, else the newest Error Log titled `BPMN ScriptTask: "<script>" execution failed` or `Logix check: "<script>" failed`. The `debug_script` tool returns an explanation and a fixed script; the reviewer judges only the unified diff, and `validate_script` gates the fix. A passing fix replies as a MODIFY with the diff; a failing one explains the issues and offers no code.
- Sub-prompt keys on the AI Agent Configuration: `intent_classifier`, `clarifier`, `script_writer`, `script_reviewer`, `test_writer`, `tool_writer`, `script_debugger`.
- Read tools in `ai_agent_registry/definitions/logix/tools.py` and `definitions/shared/tools.py` (for example `get_server_script_content`, `get_server_script_meta`, `list_api_server_scripts`, `get_doctype_fields`) return strings and never raise: the `tool_envelope` decorator in `definitions/shared/helpers.py` logs the error and returns the error value.
- Script endpoints in `api/server_scripts.py`: `create_server_script` (upsert), `update_server_script`, `check_server_script_exists`. They check Server Script permission or the System Manager role before writing.

## ProsAlly

ProsAlly generates, redraws and modifies BPMN diagrams from natural language. `agent_id = "prosally_agent"`.

- It never changes a diagram without the user's confirmation. A confirmed action comes back as `confirmed_action`, which must be one of the known action intents before anything acts on it.
- `current_xml` (the canvas the panel sends with every turn) is untrusted input; never execute it.
- The stages are DB Server Scripts driven by the ProsAlly process map. They import Python helpers from `ai_agent_registry/definitions/prosally/` (`tools_pipeline.py`, `tools_lint.py`, `tools_links.py`, `tools_review.py`, `tools_subprocess.py` and others). `compile_ir` in `tools_pipeline.py` turns the model's intermediate representation into BPMN XML.
- Generated XML must satisfy the error-level bpmnlint rules in `frontend/src/bpmn/lint/bpmnlintrc.js`: one start event and one end event, every element connected, and a BPMNShape or BPMNEdge for every element. Existing element ids are never renamed in a modify, and new elements get unique ids.
- Positions are placeholders; the frontend lays the diagram out (see `frontend/AGENTS.md`).
