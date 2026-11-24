# Creating a Connector - step by step

Two walkthroughs, both done from the Frappe desk:

- **[Walkthrough A - HTTP connector](#walkthrough-a---http-connector-no-code)** - a REST/HTTP provider. **No code at all**: the credential lives on the connector, encrypted.
- **[Walkthrough B - Python Handler operation](#walkthrough-b---python-handler-operation)** - for calls an HTTP template can't express (SDK uploads, several calls in one step). One Python function per operation; everything else is still the desk.

The field names below match the desk forms. The hostnames, ids and results are examples. Reference: [README.md](README.md).

---

## Before you start

**Where the three DocTypes live** - search the awesomebar for:

| DocType | Holds |
|---|---|
| **BPMN Connector** | the provider: id, label, canvas icon, base URL, auth, execution type |
| **BPMN Connector Operation** | one row per API method, plus the fields the modeler fills in |
| **BPMN Connector Field** | a child table inside the Operation - not opened directly |

You need the **System Manager** role: it is the only role with access to these DocTypes.

**How the pieces relate.** One Connector has many Operations; each Operation has
many Fields. The modeler picks Connector → Operation, then fills in that
operation's Fields.

```
BPMN Connector "helpdesk"
├── Operation "createTicket"   → Fields: subject, priority, team
└── Operation "closeTicket"    → Fields: ticket, reason
```

---

## Walkthrough A - HTTP connector (no code)

We will build a `helpdesk` connector with a `createTicket` operation that POSTs to
`https://api.example.com/v2/tickets` with an API key.

### Step 1 - create the Connector

**BPMN Connector** → **Add BPMN Connector**:

| Field | Value | Why |
|---|---|---|
| Connector ID | `helpdesk` | Goes into the BPMN XML verbatim. Lowercase/underscores, starts with a letter - enforced on save. |
| Label | `Helpdesk` | What the modeler sees in the Connector dropdown |
| Enabled | ✅ | Unticking hides it from the modeler *and* refuses to dispatch |
| Description | `Raise and close helpdesk tickets.` | Optional |

**Canvas Icon** section - what the Service Task shows instead of the gear:

| Field | Value |
|---|---|
| Icon SVG Path | `M12 2 2 22h20z` (the `d` of one path on a **24×24 viewBox** - paste from any icon set, e.g. an MDI icon) |
| Icon Colour | `#8b5cf6` |
| Icon Label | `Helpdesk` |

A live preview renders beside the fields as you type. Paste **path data only** -
a full `<svg>` element is rejected. Leave blank for the default teal plug.

**Execution** section:

| Field | Value | Why |
|---|---|---|
| Execution Type | `HTTP Request` | This is the no-code path |
| Base URL | `https://api.example.com/v2` | Each operation's URL is relative to this |
| Request Timeout (s) | `20` | |
| Allow Internal Hosts | ❌ leave off | Off = loopback/private addresses are refused, so a connector can't be aimed at internal infrastructure. Only tick for a deliberate internal integration. |

**Authentication** section:

| Field | Value | Why |
|---|---|---|
| Auth Type | `API Key Header` | |
| Credential Source | `On this connector` | The default - the key lives here |
| Secret | *paste the API key* | A Password field: stored encrypted, never exported, never sent to the browser |
| API Key Header Name | `X-Api-Key` | |

Auth Type options: `None`, `Bearer Token`, `API Key Header`, `API Key Query
Param`, `Basic` (secret holds `user:password`), `Service Account JSON` (a Google
key; the executor exchanges it for an access token using the connector's
**Scopes**) and `GitHub App JSON`.

The Authentication section is shown only when the connector's Execution Type is
`HTTP Request`.

> **Verified:** the Secret column in the database holds `******************` - the
> real value goes to Frappe's encrypted `__Auth` store and is decrypted only at
> call time. It does not appear in the document, in `get_all(fields=["*"])`, in the
> manifest sent to the modeler, or in an export.

#### Sharing one credential across connectors

Switch **Credential Source** to `From a settings DocType` when several connectors
use the *same* key, so rotating it is one edit instead of several. (The shipped
Google connectors do not do this: each holds its own key on the connector.) Then:

| Field | Value |
|---|---|
| Secret Settings DocType | `Processa Settings` |
| Secret Fieldname | `helpdesk_api_key` |

That field must be a **Password** field - a plain Data field is rejected on save,
because it would store the secret unencrypted. (This check covers every Auth Type
except `Service Account JSON`.) To add one without code: **Customize
Form** → *Enter Form Type* `Processa Settings` → **Add Row** with Type `Password` →
**Update**, then fill it in on Processa Settings.

**Save.**

### Step 2 - create the Operation

From the connector, use the **Operations** button (or **BPMN Connector
Operation** → **Add**):

| Field | Value | Why |
|---|---|---|
| Connector | `helpdesk` | |
| Operation ID | `createTicket` | Goes into the BPMN XML verbatim |
| Label | `Create ticket` | Shown in the Operation dropdown |
| Enabled | ✅ | |
| Sort Order | `1` | Position in the dropdown |
| API Method | `POST /tickets` | Documentation only |

**Execution Type**: leave **blank** - it inherits `HTTP Request` from the connector.

**HTTP Request** section - this is where the call is described:

| Field | Value |
|---|---|
| Method | `POST` |
| URL Template | `/tickets` |
| Query Parameters (JSON) | `{"notify": "true"}` |
| Headers (JSON) | `{"X-Requested-By": "{{ instance.name }}"}` |

**Request Body** section:

| Field | Value |
|---|---|
| Content Type | `application/json` |
| Body Template | `{"subject": "{{ params.subject }}", "priority": "{{ params.priority }}"}` |

**Response Mapping** section - projects the provider's response into the workflow:

| Field | Value |
|---|---|
| Response Map (JSON) | `{"ticketId": "data.id", "link": "data.links[0].href"}` |

Dotted paths, with `[0]` for list indices. A path that isn't in the response
yields `None` rather than an error. Leave blank to get the whole response.

**Documented Output** (optional, shown to modelers):
`{"ticketId": "New ticket id", "link": "Ticket URL"}`

### Step 3 - add the Fields

Still on the Operation, in the **Fields Shown In The Modeler** table. Each row
becomes one input in the properties panel, in this order.

**Row 1 - a required text input:**

| Column | Value |
|---|---|
| Field Name | `subject` |
| Label | `Subject` |
| Type | `String` |
| Required | ✅ |
| Expression | ✅ |
| Help Text | `Shown to the agent who picks the ticket up` |

**Row 2 - a dropdown with a default:**

| Column | Value |
|---|---|
| Field Name | `priority` |
| Label | `Priority` |
| Type | `Dropdown` |
| Required | ✅ |
| Default Value | `low` |
| Choices | `High\|high`<br>`Low\|low` - one per line, `Label\|value` |

**Row 3 - a field that only appears when it's relevant:**

| Column | Value |
|---|---|
| Field Name | `team` |
| Label | `Team` |
| Type | `String` |
| Only Show When Field | `priority` |
| Operator | `equals` |
| Value | `high` |

**Save.** Field Name must match what the Body Template reads
(`{{ params.subject }}` ↔ `subject`).

#### The field columns

| Column | Effect |
|---|---|
| **Type** | The widget: `String` (one line), `Text` (multi-line), `Dropdown`, `Boolean` (checkbox), `Hidden` |
| **Required** | Panel marks the label with `*`. Nothing checks it at runtime: neither the dispatcher nor the HTTP executor refuses a missing value |
| **Expression** | On (default) = the value is Jinja-rendered at runtime. Turn **off** for a literal that must not be interpreted |
| **Default Value** | Pre-filled in the panel |
| **Choices** / **Choices From** | Static list, or a live list (see [Optional extras](#optional-extras)) |
| **Only Show When / Operator / Value** | `equals`, or `one of` with a comma-separated list. Use the literal `operation` to test the chosen operation |
| **Value Transform** | Normalise what the modeler typed (see [Optional extras](#optional-extras)) |

#### What Jinja can see

In URL / Query / Headers / Body templates:

| Name | Is |
|---|---|
| `params` | this operation's field values - `{{ params.subject }}` |
| `doc` | the context document the process is running on - `{{ doc.customer_name }}` |
| `task_data` | workflow variables, including earlier connectors' output - `{{ task_data.ticket.ticketId }}` |
| `instance` | the BPMN Process Instance - `{{ instance.name }}` |
| `frappe` | e.g. `{{ frappe.utils.nowdate() }}` |

> **Gotcha:** an unset field renders as the literal string `None`. Write
> `{{ doc.note or "" }}` when empty should mean empty.

### Step 4 - check it

Saving the operation already refuses the common mistakes: an HTTP operation with
no URL Template or Method, a dropdown with no choices, a condition that points at
a field that doesn't exist, and a Handler Path or Value Transform that cannot be
imported.

Then, on the connector, click **Validate Configuration**. It checks every
operation of the connector, including that each one resolves to an executor. You
want *"No issues found."* A disabled operation is always reported, because it has
no executor.

### Step 5 - use it in a diagram

1. Open the modeler (**/processa**), drop a **Service Task**.
2. Properties panel → **Service Type**: `Connector`.
3. **Connector**: `Helpdesk` → **Operation**: `Create ticket`.
4. Your three fields appear. Fill them in - values can be Jinja:
   - Subject: `Printer on fire - {{ doc.name }}`
   - Priority: `High` (Team then appears)
5. **Output variable**: `ticket` - the result lands in `task_data.ticket`.
6. **Fail workflow on error**: tick to raise the error so the step fails; leave
   off to log and continue.
7. Save. The task now shows your icon instead of the gear.

Downstream tasks and gateways read `{{ task_data.ticket.ticketId }}`.

### What happens at runtime

For the configuration above, with `subject` = `Printer on fire` and
`priority` = `high`, the executor sends:

```
POST https://api.example.com/v2/tickets?notify=true
X-Api-Key: <the Secret stored on the connector>
X-Requested-By: <instance name>
Content-Type: application/json

{"subject": "Printer on fire", "priority": "high"}
```

and given `{"data": {"id": "TK-42", "links": [{"href": "https://help/TK-42"}]}}`
writes into task data:

```json
{"ticketId": "TK-42", "link": "https://help/TK-42"}
```

No Python was written at any point.

---

## Walkthrough B - Python Handler operation

Use this only when an HTTP template genuinely can't express the call: resumable
uploads, SDK-only APIs, several calls in one step. Of the 28 shipped Google
operations, 11 work this way (for example `google_drive` → `createFile`); the
other 17 are plain HTTP operations.

**Be clear about the split:** the *connector definition* is still 100% desk -
icon, operations, fields, required flags, choices, conditions. The only code is
one function per operation. If you can do it over HTTP, use Walkthrough A.

Execution Type can be set on the connector or on each operation. An operation
with a blank Execution Type inherits the connector's. The usual pattern is to
keep the connector on `HTTP Request`, so its Authentication section (and Secret)
stays available, and set `Python Handler` only on the operations that need code.

### Step 1 - write the handler

One function per operation, signature `handler(params, ctx) -> dict`:

```python
# apps/your_app/your_app/connectors/acme_ops.py
import frappe


def create_invoice(params, ctx):
    """params: the resolved field values. ctx: {instance, task, doc, task_data, operation}."""
    from acme_sdk import AcmeClient          # the SDK that forced this route

    token = frappe.get_doc("BPMN Connector", "acme").get_password("auth_secret")
    client = AcmeClient(token=token)
    invoice = client.invoices.create(
        customer=params["customer"],
        amount=float(params.get("amount") or 0),
    )
    return {"invoiceId": invoice.id, "url": invoice.public_url}
```

Rules that matter:

- **Return a JSON-safe dict.** It is stored in `task.data[resultVariable]`, on the instance.
- **Raise on failure.** `dispatch_connector` decides what to do based on the
  element's `failOnError`; don't swallow errors.
- **Read only from `params`**, so the modeler stays in control.
- Keep credentials out of the code. Read them from a Password field: the
  connector's own **Secret** (`auth_secret`, as above), or a shared one on a
  settings DocType. The dispatcher does not pass the secret to a Python handler.

`bench restart` after adding the file.

### Step 2 - create the Connector

Same as Walkthrough A Step 1. Keep **Execution Type** = `HTTP Request` if you
want to store the credential in the connector's **Secret** (the Authentication
section is hidden for `Python Handler`). Base URL and Timeout are used only by
HTTP operations and can stay blank if every operation is a Python Handler.

Icon, label and description work identically.

### Step 3 - create the Operation, pointing at the function

| Field | Value |
|---|---|
| Connector | `acme` |
| Operation ID | `createInvoice` |
| Label | `Create invoice` |
| Execution Type | `Python Handler` |
| **Handler Path** | `your_app.connectors.acme_ops.create_invoice` |

The Handler Path is the dotted import path of the function, starting from the
Python package (for processa: `processa.processa_connectors.operations.google_drive.create_file`).
It is **checked on save**: an unimportable path is rejected there and then,
rather than inside a running workflow. A Python Handler operation saved with no
Handler Path shows an orange warning, and it has no executor until you set one.

The HTTP Request / Response Mapping sections are ignored for this route; your
function returns the dict directly.

### Step 4 - add the Fields

Identical to Walkthrough A Step 3. The Field Names become the `params` keys your
function reads - `params["customer"]` needs a field named `customer`.

### Step 5 - Validate, then use it

Same as Walkthrough A Steps 4-5. **Validate Configuration** confirms the handler
resolves. From the modeler's side the two kinds of operation look the same.

---

## Optional extras

Both need a dotted path to a Python function, so they are the two places a *new*
connector might touch code. Neither is required, and both are validated importable
and callable on save.

### Value Transform - normalise what the modeler typed

A field-level dotted path to `fn(value) -> value`, applied **after** the
expression renders and **before** the executor runs. This is how the Google
connectors accept either a Drive share link or a bare id:

| Column | Value |
|---|---|
| Field Name | `folder` |
| Value Transform | `processa.processa_connectors.google.common.normalize_drive_id` |

The modeler pastes
`https://drive.google.com/drive/folders/FOLDER_ABC123`; the handler receives
`FOLDER_ABC123`. A transform that raises is logged and the original value used,
so a bad transform degrades rather than failing the task.

For an HTTP connector you can usually skip this and use a Jinja filter in the
template instead.

### Choices From - a dropdown filled from the provider

A field-level dotted path to `fn(**context) -> [{label, value}]`:

| Column | Value |
|---|---|
| Field Name | `file` |
| Type | `Dropdown` |
| Choices From | `processa.processa_connectors.operations.google_drive.list_file_choices` |

The panel sends the sibling field values as context, and your function receives
the ones it declares. So `list_file_choices(folder=None)` gets whatever the
modeler put in the `folder` field, and the dropdown lists that folder's contents -
a dependent dropdown.

The path is read from the configuration, never from the browser.

---

## Moving a connector between sites

Connectors travel as **data**, not patches:

- **Export JSON** on the connector form → the full manifest, execution config
  included. Secrets never travel, only the settings DocType and fieldname that say
  where to read them.
- `processa.processa_connectors.seed.import_manifest(manifest, overwrite=False)`, from
  bench console, creates or updates. Without `overwrite` an existing connector is left untouched.

So: build once in a test site, export, import into production, and re-enter only
the secret.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Connector missing from the modeler dropdown | `Enabled` unticked, your roles are not in the connector's **Allowed Roles**, or the panel cached an older fetch - reload the modeler |
| Operation missing | Operation `Enabled` unticked, or it belongs to another connector |
| Fields don't appear | An operation isn't selected, or every field is hidden by a condition |
| `None` inside a URL or body | An unset field - use `{{ doc.field or "" }}` |
| Task silently does nothing | `Fail workflow on error` is off and the call failed - check **Error Log** |
| Error Log titled `connector unknown`, or the error `Unknown connector <id>/<op>` when Fail workflow on error is on | Connector or operation disabled, a Python Handler operation with no Handler Path, or the id in the XML no longer matches |
| Error Log titled `connector not permitted` | The user the instance runs as has none of the connector's **Allowed Roles** |
| Auth header absent | Auth Type set but the Secret is empty - the executor errors rather than calling unauthenticated |
| `no secret was found at …` | Credential Source points at a settings DocType whose field is blank, or the on-connector Secret was never filled in |
| Host refused | The URL resolves to a private/loopback address; tick **Allow Internal Hosts** only if that is intended |
| Dropdown empty | The Choices From function raised or returned nothing - check **Error Log** |
