# BPMN Service Task Connectors

A **connector** lets a BPMN Service Task call another system's API, such as Google Drive or GitHub, through settings on the task. The person drawing the map picks a connector and an operation and fills in its fields. No script is written in the diagram. It is the `processa` counterpart of Camunda's outbound connectors.

**Connectors are configuration.** A whole connector (its label, canvas icon, operations, the fields each operation shows, which are required, their dropdown choices and conditional visibility, and how the call is made) is set up in the desk UI:

```
BPMN Connector  →  BPMN Connector Operation  →  BPMN Connector Field (child table)
```

A connector that talks plain HTTP/REST needs **no Python at all**. An operation that needs real code (an SDK, a multi-step upload) points at a Python function through its **Handler Path**.

> **New to this?** [WALKTHROUGH.md](WALKTHROUGH.md) builds one field by field, twice: once for an HTTP connector (no code) and once for a Python Handler operation.

## How it runs

```xml
<bpmn:serviceTask spiffworkflow:serviceType="connector"
                  spiffworkflow:connectorId="google_drive"
                  spiffworkflow:operation="createFile"
                  spiffworkflow:connectorParams="{ ...json... }"
                  spiffworkflow:resultVariable="drive_file"
                  spiffworkflow:failOnError="false" />
```

At runtime the engine leaves the Service Task `STARTED`; `_dispatch_service_task` routes `serviceType == "connector"` to `dispatch_connector` (`processa_engine/dispatch/connector.py`), which:

1. checks that the user the instance runs as holds one of the connector's **Allowed Roles** (an empty list allows everyone),
2. resolves the executor for `(connectorId, operation)` (see below),
3. parses `connectorParams` (a JSON object),
4. for every field flagged `expression`, decodes HTML entities and Jinja-renders it against `{doc, instance, frappe, task_data}`,
5. applies each field's configured **Value Transform**, if it declares one,
6. calls the executor with `(params, ctx)`, where `ctx` is `{instance, task, doc, task_data, operation}`,
7. writes its return value to `task.data[resultVariable]`.

Each run also records an outcome (`ok`, `failed`, `not_run` or `not_permitted`) in the task data. Errors are logged and do not stop the process by default. Set `failOnError` to raise the error instead, so the step fails.

### Executor resolution

`_resolve_connector_handler` reads the enabled operation's configuration, in order:

1. the operation's **Handler Path**: a dotted path to `fn(params, ctx)`;
2. execution type **HTTP Request**: `operations/http.execute` (declarative, no Python).

An operation's execution type is its own **Execution Type**, or the connector's when the operation leaves it blank. If neither step applies (for example a Python Handler operation with no Handler Path, a disabled connector or operation, or no configuration row at all), there is no executor. The step then logs an Error Log titled "connector unknown" and moves on, or raises `Unknown connector <id>/<op>` when `failOnError` is set.

## Where each layer lives

| Layer | Where | Purpose |
|---|---|---|
| **Configuration** | `BPMN Connector` / `… Operation` / `… Field` DocTypes | the live definitions: operations, fields, icons, execution |
| **Loader** | `processa_connectors/manifest.py` | projects the DocTypes into manifest dicts (cached); serves the modeler *and* runtime field handling |
| **HTTP executor** | `processa_connectors/operations/http.py` | renders and performs a configured request; maps the response |
| **Python handlers** | `processa_connectors/operations/google_*.py`, `operations/github.py`, `a2a/client_ops.py` | plain functions `fn(params, ctx)` named by an operation's Handler Path |
| **Google clients** | `processa_connectors/google/` | Google API calls the Google handlers use |
| **Seed** | `patches/v1_0/seed_google_connectors.py` (`GOOGLE_CONNECTORS`) and the other `seed_*_connector.py` patches | shipped starting point, imported into the DocTypes |

`validator.py` checks that every operation a modeler can pick resolves to an executor, and that its fields are well-formed. It runs in the test suite and behind **Validate Configuration** on the BPMN Connector form. It also reports every disabled operation as an issue, because a disabled operation has no executor.

## Adding a connector

**REST/HTTP provider: entirely in the desk, no code, no rebuild:**

1. **BPMN Connector**: id, label, icon SVG path + colour, Base URL, Auth Type and the **Secret** itself (or a pointer to a Password field on a settings DocType).
2. **BPMN Connector Operation** per API method: `Method` + `URL Template`, optional Query/Headers/Body templates, and a **Response Map** projecting the response into the output dict.
3. **Fields**: one row per input the modeler should fill in.

Templates are Jinja; field values are exposed as `params`, alongside `doc`, `task_data`, `instance` and `frappe`. Example body: `{"name": "{{ params.filename }}"}`.

**Provider that needs code (an SDK, resumable uploads, several calls in one step):**

1. Write a function `fn(params, ctx)` that returns a JSON-safe dict, for example in `processa_connectors/operations/<provider>.py`. Put the provider's API calls in their own module (the Google ones are in `processa_connectors/google/`). Wrap calls that may hit rate limits in `processa_connectors/retry.call_with_retry`.
2. On the operation, set **Execution Type** to **Python Handler** and **Handler Path** to the function's dotted path, such as `processa.processa_connectors.operations.google_drive.create_file`.

Either way the modeler panel and the canvas icon follow automatically, with no engine or frontend change.

### Field schema

| DocType field | Manifest key | Notes |
|---|---|---|
| Field Name | `name` | key inside `connectorParams` |
| Label / Type / Required | `label` / `type` / `required` | type ∈ String, Text, Dropdown, Boolean, Hidden: the widget, nothing more. Required adds a `*` to the field's label in the panel; the executors do not check it. |
| Expression | `expression` | on (default): Jinja-rendered at runtime |
| Default Value | `default` | |
| **Value Transform** | *(server-side)* | dotted path to `fn(value) -> value`, run after rendering |
| Choices | `choices` | `Label\|value` per line |
| **Choices From** | `dynamicChoices` | dotted path to `fn(**context) -> [{label, value}]` |
| Only Show When / Operator / Value | `condition` | `equals` or `one of`; the literal `operation` tests the selected operation |
| Help Text | `help` | shown under the field |

### Value Transform: provider quirks without provider code

Nothing in the generic layer knows about any provider. Input clean-up is a field-level **Value Transform**: a dotted path to `fn(value) -> value` applied after the expression renders. The Google connectors point their file and folder fields at `processa.processa_connectors.google.common.normalize_drive_id`, which is why you can paste either a Drive share link or a bare id. That behaviour is configuration, not a special field type. A transform that raises is logged and the original value is used, so a bad transform does not fail the task.

### Choices From: dependent dropdowns

Set a field's **Choices From** to a dotted path returning `[{label, value}]`. The panel calls `processa.api.connectors.get_connector_field_choices` with the connector, operation and field (never the path, which the server reads from the configuration), plus the sibling field values as `context`. The function receives the ones it declares as keyword arguments. So `list_file_choices(folder=None)` gets whatever the modeler put in the `folder` field, and the dropdown lists that folder's contents.

Both paths are checked as importable and callable when the operation is saved, and neither is included in the manifest served to the browser.

### Canvas icon

`Icon SVG Path` is the `d` attribute of one path on a **24×24 viewBox** (paste from any icon set), with `Icon Colour` as a hex value. The Service Task shows it in place of the gear; connectors with no icon get the default teal plug. The form renders a live preview, and the diagram picks it up on the next load, with no rebuild.

## Letting the Connector Agent build one

A connector is configuration, which means an agent can author it. The **Connector Agent** (`agent_id` `connector_agent`) is a *background* agent: an orchestrator delegates a work order to it over A2A and it builds the connector on its own.

```
orchestrator's ad-hoc sub-process
  └─ Service Task  serviceType=connector  connectorId=a2a
                   operation=delegate_to_local_agent
                   connectorParams={"agent": "Connector Agent",
                                    "instruction": "<what to build, in words>"}
```

The `delegate_to_local_agent` operation (`a2a/client_ops.py`) creates an A2A Task, which starts the agent's own A2A-startable map. Its answer comes back on the task's `result`, and the connector rows appear in the desk.

The work order is plain English. It may name an **OpenAPI/Swagger URL**, a **documentation page**, an example **curl**, or simply describe the API; the agent uses whichever it is given.

The agent's configuration is seeded by `patches/v1_0/seed_connector_agent_config.py`, including its `connector_writer` sub-prompt. Its map and its tool scripts are not in this repository: they are Server Scripts brought in by export and import. The only tool code in Python is `fetch_url` in `operations/http.py`, a size-capped, timed fetch that refuses internal hosts and allows `http` and `https`. `processa/tests/test_connector_agent.py` loads the helpers back out of the installed Server Scripts and tests them, including `TestReviewerImporterAgreement`, which checks that the agent's review step and the importer accept the same manifest shape.

`get_execution_spec(..., allow_disabled=True)` lets authoring test a connector it wrote disabled. It bypasses only the connector's **Enabled** flag; the operation itself must still be enabled.

Note that `seed.import_manifest` always saves a connector as enabled. A draft is kept disabled only because the agent's own write script switches it off.

## Portability

Connectors move between sites as **data**, not patches:

- `processa.api.connectors.export_connector(connector_id)` returns a JSON manifest (also the **Export JSON** button on the form). Secrets never travel, only the settings DocType and fieldname that say where to read them.
- `processa.processa_connectors.seed.import_manifest(manifest, overwrite=False)` creates or updates a connector.

The shipped Google connectors are defined in `GOOGLE_CONNECTORS` in `patches/v1_0/seed_google_connectors.py`. That patch calls `seed.import_manifest` for each one, and the app's `after_install` hook calls `seed.import_seed_manifests`, which does the same. Neither overwrites a connector that already exists, so a site's own edits survive a re-run.

## Shipped connectors

| Connector | Operations | Seeded by |
|---|---|---|
| `google_drive` | copyFile, downloadText, createFile, updateFileContent, setPermissions, listFiles, revokePermissions, deleteFile, setContentRestriction | `seed_google_connectors.py`; setContentRestriction by `add_drive_content_restriction_operation.py` |
| `google_docs` | createDocument, insertText, appendText, fillTemplate, fillBrandedTemplate, replaceAllText, getText | `seed_google_connectors.py` |
| `google_sheets` | createSpreadsheet, getValues, updateValues, appendValues, clearValues, addSheet | `seed_google_connectors.py` |
| `google_slides` | createPresentation, replaceAllText, createSlide, duplicateSlide, getText, fillBrandedDeck | `seed_google_connectors.py` |
| `a2a` | delegate_to_local_agent, delegate_task | `seed_a2a_connector.py` |
| `github`, `github_video_upload`, `url_liveness_check` | see their patches | `seed_github_connector.py`, `seed_github_video_upload_connector.py`, `seed_url_liveness_connector.py` |

All four Google connectors use execution type **HTTP Request**. They have 28 operations: 17 are plain HTTP calls and 11 set **Python Handler** with an explicit Handler Path. `GOOGLE_CONNECTORS` holds 27 of them; `setContentRestriction` is added only by the `add_drive_content_restriction_operation` patch, so a fresh install, where patches are marked as already run, does not get it.

## Credentials

Every connector keeps its credential **on the connector**: an encrypted `Password` field in its Auth section (`Credential Source = On this connector`). The value goes to Frappe's `__Auth` store, not the DocType column, and appears in neither the manifest served to the browser nor an export; only the *fact* that a credential is expected travels.

The Auth section shows only when the connector's execution type is **HTTP Request**.

**Google.** Each Google connector is seeded with Auth Type **Service Account JSON** and `Credential Source = On this connector`. Paste the whole JSON key file Google issued into **Secret**. `Secret` is a 10,000-character field because a service-account key is about 2.3 kB and Frappe's Password control otherwise caps input at 140.

- **HTTP operations** (17 of 28): the HTTP executor reads the key with the connector's Credential Source, exchanges it for an access token using the connector's **Scopes**, and caches the token.
- **Python Handler operations** (11 of 28): `google.common.load_service_account_info` reads the named connector's Secret. If that Secret is empty, it falls back to the `google_drive` connector's Secret. It ignores Credential Source. There is no `site_config.json` or file fallback. With no key at all, it raises an error naming the connector to fix.

All business config (destination **folders**, files, templates) is entered **on the connector element**, never in settings.

Set `Credential Source = From a settings DocType` instead when several connectors share one key. For Bearer Token, API Key Header, API Key Query Param, Basic and GitHub App JSON, the target must be a `Password` field, and a plain `Data` field is refused on save. That check does not apply to Service Account JSON.

**Google needs a Shared Drive.** A service account has no My Drive quota, so anything that creates a file (`createFile`, `createDocument`, `createPresentation`, `createSpreadsheet`) must target a folder in a Shared Drive the service account belongs to, which is why all four take a **Folder**.

**`deleteFile` moves the file to the trash.** It sends `PATCH files/<id>` with `{"trashed": true}`; there is no option to delete permanently.

## Outbound-request safety

The HTTP executor refuses non-`http(s)` schemes, and refuses hosts resolving to loopback / link-local / private / reserved addresses unless the connector ticks **Allow Internal Hosts**; otherwise a connector could be used to send requests into the server's own network. Responses above 2 MB are rejected rather than written into task data. HTTP 429, 500, 502, 503 and 504 are retried with backoff via `processa_connectors/retry.call_with_retry`.

## Expression gotcha

Jinja here behaves as it does everywhere else in Frappe, which means a **field that is set but empty renders as the literal string `None`**: `{"note": "{{ doc.note }}"}` sends `"note": "None"` when `note` is unset. Guard it in the template: `{{ doc.note or "" }}`.

An **unknown name** is different: Frappe renders it as the debug text `{{ no such element: … }}`, which would corrupt a URL or body, so the HTTP executor blanks those. Field values rendered from `connectorParams` are not blanked: a typo'd name there reaches the provider as that literal text.

## Not done

- Reconcile manifests against Google's live API discovery documents.
- BPMN Error boundary-event mapping for `failOnError`.
- Render an empty value as an empty string instead of `None` in both rendering paths (see the gotcha above). This would change the behaviour of shipped connectors.
