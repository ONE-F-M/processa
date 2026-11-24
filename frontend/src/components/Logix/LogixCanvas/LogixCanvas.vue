<template>
	<div class="lc-root">

		<!-- LEFT: chat; script changes arrive as onefm.script_diff cards handled in onLogixCardAction. -->
		<div v-if="!props.readonly" class="lc-chat-panel">
			<AgentChatPanel
				agent-id="logix_agent"
				variant="docked"
				layout="conversation"
				:apply-targets="['apply-script', 'run-test']"
				:context="logixTurnContext"
				:cards="cardRegistry"
				@card-action="onLogixCardAction"
			/>
		</div>

		<!-- ── CENTER: Code Editor Panel ────────────────────────────── -->
		<div class="lc-editor-panel">

			<!-- File bar -->
			<div class="lc-file-bar">
				<div class="lc-file-name-area">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
					</svg>
					<span v-if="!isEditingName" class="lc-filename" @dblclick="!props.readonly && startEditName()" :title="props.readonly ? 'Read-only' : 'Double-click to rename'">
						{{ canvasScriptName || 'Untitled' }}
					</span>
					<input
						v-else
						ref="nameInputEl"
						v-model="canvasScriptName"
						class="lc-name-input"
						placeholder="Script name..."
						@blur="stopEditName"
						@keydown.enter="stopEditName"
						@keydown.escape="stopEditName"
					/>
				</div>
				<div class="lc-file-actions">
					<!-- Save status -->
					<span v-if="isSaving" class="lc-save-status lc-autosaving">
						<span class="lc-spinner-sm"></span> Saving…
					</span>
					<span v-else-if="saveProblem" class="lc-save-status lc-unsaved lc-save-error" :title="saveProblem">● {{ saveProblem }}</span>
					<span v-else-if="isDirty && !isSaved" class="lc-save-status lc-unsaved">● Unsaved</span>
					<span v-else-if="isSaved" class="lc-save-status lc-saved">✓ Saved</span>

					<span
						v-if="flagged.length"
						class="lc-save-status lc-lint-status"
						:title="flaggedTitle"
					>{{ flagged.length }} needs approval</span>

					<div v-if="isLoadingScript" class="lc-loading-indicator">
						<div class="lc-spinner-sm"></div>
						Loading...
					</div>

					<!-- Folder / Script Browser button -->
					<div class="lc-script-browser-wrap">
						<button
							class="lc-file-btn"
							:class="{ 'lc-file-btn--active': showScriptBrowser }"
							@click="toggleScriptBrowser"
							title="Browse server scripts"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
								<path stroke-linecap="round" stroke-linejoin="round" d="M3 7a2 2 0 012-2h3.5L10 7h9a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
							</svg>
						</button>
						<!-- Script browser dropdown -->
						<div v-if="showScriptBrowser" class="lc-script-dropdown">
							<div class="lc-script-dropdown-header">
								<span>Server Scripts</span>
								<div v-if="loadingScriptBrowser" class="lc-spinner-sm"></div>
							</div>
							<div class="lc-script-dropdown-search">
								<input
									v-model="scriptBrowserSearch"
									type="text"
									placeholder="Search scripts..."
									class="lc-script-search-input"
									@click.stop
								/>
							</div>
							<div class="lc-script-dropdown-list">
								<div v-if="loadingScriptBrowser && !filteredScriptBrowserList.length" class="lc-script-dropdown-empty">Loading…</div>
								<div v-else-if="filteredScriptBrowserList.length === 0" class="lc-script-dropdown-empty">No scripts found</div>
								<div
									v-for="s in filteredScriptBrowserList"
									:key="s.name"
									class="lc-script-dropdown-item"
									:class="{ 'lc-script-dropdown-item--active': s.name === canvasScriptName }"
									@click="linkExistingScript(s.name)"
								>
									<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="12" height="12" class="lc-script-item-icon">
										<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
									</svg>
									<div class="lc-script-item-info">
										<div class="lc-script-item-name">{{ s.name }}</div>
										<div class="lc-script-item-type">{{ s.script_type }}</div>
									</div>
									<svg v-if="s.name === canvasScriptName" viewBox="0 0 24 24" fill="currentColor" width="12" height="12" class="lc-script-item-check">
										<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
									</svg>
								</div>
							</div>
						</div>
					</div>

					<button class="lc-file-btn" @click="copyCanvas" title="Copy script">
						<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
							<path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
						</svg>
						Copy
					</button>
					<Button
						size="sm"
						:variant="showSecurity ? 'outline' : 'ghost'"
						label="Security"
						@click="showSecurity = !showSecurity; showVersionHistory = false"
					/>
					<button
						class="lc-file-btn"
						:class="{ 'lc-file-btn--active': showVersionHistory }"
						title="Version History"
						@click="showVersionHistory = !showVersionHistory; showSecurity = false"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
							<circle cx="12" cy="12" r="10"/>
							<polyline points="12 6 12 12 16 14"/>
						</svg>
					</button>
				</div>
			</div>

			<!-- Backdrop to close dropdowns when clicking outside -->
			<div v-if="showDoctypeDropdown || showModuleDropdown || showScriptBrowser" class="lc-dropdown-backdrop" @click="showDoctypeDropdown = false; showModuleDropdown = false; showScriptBrowser = false"></div>

			<!-- Script Settings Panel -->
			<div class="lc-settings-panel">
					<div class="lc-settings-grid">
						<div v-if="flagged.length" class="lc-settings-field"><label class="lc-settings-label">Approval</label><div class="lc-settings-input">{{ approvalLabel }}</div></div>
						<div v-if="flagged.length" class="lc-settings-field"><label class="lc-settings-label">Deploy</label><div class="lc-settings-input">{{ approvalState }}</div></div>
						<!-- Script Type -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Script Type</label>
							<select v-model="scriptMeta.script_type" class="lc-settings-select" disabled>
								<option value="API">API</option>
							</select>
						</div>

						<!-- Module -->
						<div class="lc-settings-field">
							<label class="lc-settings-label">Module</label>
							<div class="lc-settings-dropdown-wrap">
								<input
									v-model="moduleSearch"
									type="text"
									:placeholder="scriptMeta.module || 'Search Module...'"
									class="lc-settings-input"
									@focus="showModuleDropdown = true; showDoctypeDropdown = false; moduleSearch = ''"
								/>
								<div v-if="showModuleDropdown && filteredModuleOptions.length > 0" class="lc-settings-dropdown">
									<div v-for="m in filteredModuleOptions" :key="m" @mousedown.prevent="scriptMeta.module = m; moduleSearch = m; showModuleDropdown = false" class="lc-settings-dropdown-item">{{ m }}</div>
								</div>
							</div>
						</div>

						<!-- DocType (for DocType Event / Permission Query) -->
						<template v-if="['DocType Event', 'Permission Query'].includes(scriptMeta.script_type)">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Reference DocType</label>
								<div class="lc-settings-dropdown-wrap">
									<input
										v-model="doctypeSearch"
										type="text"
										:placeholder="scriptMeta.reference_doctype || 'Search DocType...'"
										class="lc-settings-input"
										@focus="showDoctypeDropdown = true; showModuleDropdown = false; doctypeSearch = ''"
									/>
									<div v-if="showDoctypeDropdown && filteredDoctypeOptions.length > 0" class="lc-settings-dropdown">
										<div v-for="dt in filteredDoctypeOptions" :key="dt" @mousedown.prevent="scriptMeta.reference_doctype = dt; doctypeSearch = dt; showDoctypeDropdown = false" class="lc-settings-dropdown-item">{{ dt }}</div>
									</div>
								</div>
							</div>
							<div v-if="scriptMeta.script_type === 'DocType Event'" class="lc-settings-field">
								<label class="lc-settings-label">DocType Event</label>
								<select v-model="scriptMeta.doctype_event" class="lc-settings-select">
									<option value="">Select event...</option>
									<option v-for="e in DOCTYPE_EVENTS" :key="e" :value="e">{{ e }}</option>
								</select>
							</div>
						</template>

						<!-- API fields -->
						<template v-if="scriptMeta.script_type === 'API'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">API Method</label>
								<input v-model="scriptMeta.api_method" type="text" placeholder="e.g. my_api" class="lc-settings-input" />
							</div>
							<div class="lc-settings-field lc-settings-field--inline">
								<label class="lc-settings-label">Allow Guest</label>
								<input type="checkbox" v-model="scriptMeta.allow_guest" class="lc-settings-checkbox" />
							</div>
						</template>

						<!-- Scheduler Event fields -->
						<template v-if="scriptMeta.script_type === 'Scheduler Event'">
							<div class="lc-settings-field">
								<label class="lc-settings-label">Event Frequency</label>
								<select v-model="scriptMeta.event_frequency" class="lc-settings-select">
									<option value="">Select frequency...</option>
									<option v-for="f in EVENT_FREQUENCIES" :key="f" :value="f">{{ f }}</option>
								</select>
							</div>
							<div v-if="scriptMeta.event_frequency === 'Cron'" class="lc-settings-field">
								<label class="lc-settings-label">Cron Format</label>
								<input v-model="scriptMeta.cron_format" type="text" placeholder="*/5 * * * *" class="lc-settings-input" />
							</div>
						</template>
					</div>
			</div>

			<div v-if="flagged.length" class="lc-lint-banner">
				<div class="lc-lint-banner-head">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
					</svg>
					{{ bannerText }}
				</div>
				<ul class="lc-lint-list">
					<li v-for="(line, i) in flaggedLines" :key="i">{{ line }}</li>
				</ul>
			</div>

			<ScriptNamesHint class="mx-3 my-2" />

			<!-- Code area with syntax highlighting -->
			<div class="lc-code-area">
				<CodeMirrorEditor
					v-model="canvasCode"
					language="python"
					placeholder="# Script will appear here after chatting with Logix or loading an existing script..."
					:read-only="props.readonly"
					@change="onCodeInput"
				/>
			</div>

		</div>

		<LogixSecurityPanel
			v-if="showSecurity"
			v-bind="securityPanel"
			@close="showSecurity = false"
			@request="onRequestApproval"
		/>
		<!-- ── RIGHT: Version History Panel ──────────────────── -->
		<Transition name="lc-slide-in">
			<div v-if="showVersionHistory" class="lc-version-panel">
				<div class="lc-version-panel-header">
					<span>Version History</span>
					<button class="lc-ver-refresh-btn" @click="fetchVersionHistory" :disabled="loadingVersions" title="Refresh">
						<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13" :class="{ 'lc-spin': loadingVersions }">
							<path d="M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
						</svg>
					</button>
				</div>

				<div v-if="loadingVersions" class="lc-version-empty">
					<div class="lc-ver-spinner"></div>
					<p>Loading history…</p>
				</div>
				<div v-else-if="!canvasScriptName" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No script linked.</p>
					<p class="lc-version-empty-sub">Save the script first.</p>
				</div>
				<div v-else-if="versions.length === 0" class="lc-version-empty">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="28" height="28">
						<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
					</svg>
					<p>No history yet.</p>
					<p class="lc-version-empty-sub">Save changes to start tracking versions.</p>
				</div>

				<div v-for="(v, idx) in versions" :key="v.version_name" class="lc-version-item" :class="{ 'lc-version-active': v.is_current }">
					<div class="lc-version-top">
						<div class="lc-version-top-left">
							<span class="lc-version-num">V{{ versions.length - idx }}</span>
							<span v-if="v.is_current" class="lc-active-badge">Current</span>
						</div>
						<span class="lc-version-time">{{ formatCreation(v.creation) }}</span>
					</div>
					<div class="lc-version-author">{{ v.author }}</div>
					<div class="lc-version-desc">{{ v.description }}</div>
					<div class="lc-version-links">
						<button v-if="!v.is_current" class="lc-ver-link" @click="toggleDiff(v)">[View Diff]</button>
						<button v-if="!v.is_current" class="lc-ver-link" @click="restoreVersion(v)">[Restore]</button>
					</div>
					<!-- Inline diff -->
					<div v-if="diffVersion?.version_name === v.version_name && versionDiffRows.length" class="lc-inline-diff">
						<div class="lc-inline-diff-header">
							<span>V{{ versions.length - idx }}</span>
							<span>Current</span>
						</div>
						<div class="lc-inline-diff-body">
							<div v-for="(row, ri) in versionDiffRows" :key="ri" class="lc-diff-row">
								<pre :class="['lc-diff-cell', diffCellClass(row, 'left')]">{{ row.left ?? '' }}</pre>
								<pre :class="['lc-diff-cell', diffCellClass(row, 'right')]">{{ row.right ?? '' }}</pre>
							</div>
						</div>
					</div>
				</div>
			</div>
		</Transition>
	</div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from "vue";
import CodeMirrorEditor from "@/components/Editor/CodeMirrorEditor/CodeMirrorEditor.vue";
import ScriptNamesHint from "@/components/Editor/ScriptNamesHint/ScriptNamesHint.vue";
import { Button, frappeRequest } from "frappe-ui";
import { useLogixTestRun } from "@/composables/Logix/useLogixTestRun.js";
import { useLogixScriptSecurity } from "@/composables/Logix/useLogixScriptSecurity.js";
import LogixSecurityPanel from "@/components/Logix/LogixSecurityPanel/LogixSecurityPanel.vue";
// The chat half is the shared AgentChatPanel; onefm.script_diff and onefm.test_cases cards act on the editor.
import AgentChatPanel from "@/components/Chat/AgentChatPanel/AgentChatPanel.vue";
import { cardRegistry } from "@/utils/cardRegistry";
import { saveStatusLabel } from "@/utils/logixSaveStatus";

const props = defineProps({
	element:        { type: Object,  default: null },
	scriptType:     { type: String,  default: "bpmn:script" },
	currentScript:  { type: String,  default: "" },
	eventBus:       { type: Object,  default: null },
	processContext: { type: Object,  default: null },
	// True when launched from a read-only process map — the script shows in
	// a read-only CodeMirror editor and no edits are saved.
	readonly:       { type: Boolean, default: false },
});

const emit = defineEmits(["close", "script-saved", "back"]);

// ── Canvas state ──────────────────────────────────────────────────────
const canvasScriptName = ref(props.currentScript || "");
const savedScriptName  = ref(props.currentScript || ""); // tracks the name currently in the DB
const canvasCode       = ref("");
const isEditingName    = ref(false);
const nameInputEl      = ref(null);
const isDirty          = ref(false);
const isSaving         = ref(false);
const isSaved          = ref(false);
const isLoadingScript  = ref(false);
const saveError        = ref(""); // the last save request's error, shown in the status area
// Read-only shows at once; the other reasons only once the user has changed something.
const saveProblem = computed(() => (props.readonly || isDirty.value)
	? saveStatusLabel({ readonly: props.readonly, name: canvasScriptName.value, error: saveError.value })
	: "");

// ── Script security: the lint of the open script on its script task ───
const { lint, requesting, requestError, runLint, requestApproval } = useLogixScriptSecurity();
const showSecurity = ref(false);
const flagged = computed(() => (lint.value?.findings || []).filter((f) => !f.approved));
const flaggedTitle = computed(() => flagged.value.map((f) => f.message).join("\n"));
const flaggedLines = computed(() => flagged.value.map(({ line, name, message, category, sanctioned_alternative: alt }) => ["Syntax error", "Script import"].includes(category) ? `Line ${line}: ${message}. Fix it: it cannot be approved.` : alt ? `Line ${line}: ${message}. Use ${alt.charAt(0).toLowerCase()}${alt.slice(1).replace(/\.?$/, ".")} To keep ${name}, request approval in Security.` : `Line ${line}: ${message}. Request approval in Security.`));
const securityPanel = computed(() => ({ lint: lint.value, scriptLabel: savedScriptName.value, saved: Boolean(savedScriptName.value), dirty: isDirty.value && !isSaved.value, readonly: props.readonly, requesting: requesting.value, error: requestError.value }));
const approvalLabel = computed(() => (lint.value?.open_request && lint.value?.latest_request?.status) || "Needs approval");
const bannerText = computed(() => flagged.value.some((f) => ["Syntax error", "Script import"].includes(f.category)) ? "This script has an error to fix. An error cannot be approved." : `${flagged.value.length} item${flagged.value.length > 1 ? "s need" : " needs"} approval before this map can be deployed. Saving is allowed.`);
const approvalState = computed(() => lint.value?.open_request ? `Blocked: ${lint.value.open_request} open` : "Blocked");
const lintNow = () => runLint({ code: canvasCode.value || "", scriptName: savedScriptName.value, processContext: props.processContext });
let lintTimer = null;
watch(canvasCode, () => {
	if (lintTimer) clearTimeout(lintTimer);
	lintTimer = setTimeout(lintNow, 400);
});

async function onRequestApproval(reason) {
	const scriptName = savedScriptName.value;
	if (await requestApproval({ scriptName, processContext: props.processContext, reason })) await lintNow();
}

// ── Auto-save ─────────────────────────────────────────────────────────
let autoSaveTimer = null;
let isInitializing = false;

// ── Script metadata ───────────────────────────────────────────────────
const scriptMeta = ref({
	script_type: "API",
	reference_doctype: "",
	doctype_event: "",
	api_method: "",
	allow_guest: false,
	event_frequency: "",
	cron_format: "",
	module: "",
});
const doctypeOptions = ref([]);
const moduleOptions  = ref([]);
const showDoctypeDropdown = ref(false);
const showModuleDropdown  = ref(false);
const doctypeSearch  = ref("");
const moduleSearch   = ref("");
const filteredDoctypeOptions = computed(() => {
	const q = doctypeSearch.value.toLowerCase();
	return q ? doctypeOptions.value.filter((d) => d.toLowerCase().includes(q)) : doctypeOptions.value;
});
const filteredModuleOptions = computed(() => {
	const q = moduleSearch.value.toLowerCase();
	return q ? moduleOptions.value.filter((m) => m.toLowerCase().includes(q)) : moduleOptions.value;
});

const DOCTYPE_EVENTS = [
	"Before Insert", "Before Validate", "Before Save", "After Insert",
	"After Save", "Before Rename", "After Rename", "Before Submit",
	"After Submit", "Before Cancel", "After Cancel", "Before Delete",
	"After Delete", "Before Save (Submitted Document)",
	"After Save (Submitted Document)", "Before Print", "On Payment Authorization",
];
const EVENT_FREQUENCIES = [
	"All", "Hourly", "Daily", "Weekly", "Monthly", "Yearly",
	"Hourly Long", "Daily Long", "Weekly Long", "Monthly Long", "Cron",
];

async function loadDoctypeOptions() {
	if (doctypeOptions.value.length) return;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: { doctype: "DocType", fields: JSON.stringify(["name"]), limit_page_length: 0, order_by: "name asc" },
		});
		doctypeOptions.value = (rows || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load DocTypes", e); }
}
async function loadModuleOptions() {
	if (moduleOptions.value.length) return;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: { doctype: "Module Def", fields: JSON.stringify(["name"]), limit_page_length: 0, order_by: "name asc" },
		});
		moduleOptions.value = (rows || []).map((x) => x.name);
	} catch (e) { console.error("Failed to load Modules", e); }
}

// ── Version history ───────────────────────────────────────────────────
const showVersionHistory = ref(false);
const versions           = ref([]);
const loadingVersions    = ref(false);
const diffVersion        = ref(null);
const versionDiffRows    = ref([]);

// ── Script browser ────────────────────────────────────────────────────
const showScriptBrowser    = ref(false);
const scriptBrowserList    = ref([]);
const loadingScriptBrowser = ref(false);
const scriptBrowserSearch  = ref("");

const filteredScriptBrowserList = computed(() => {
	const q = scriptBrowserSearch.value.toLowerCase();
	return q ? scriptBrowserList.value.filter(s => s.name.toLowerCase().includes(q) || (s.script_type || "").toLowerCase().includes(q)) : scriptBrowserList.value;
});

async function toggleScriptBrowser() {
	showScriptBrowser.value = !showScriptBrowser.value;
	if (showScriptBrowser.value && !scriptBrowserList.value.length) {
		await fetchScriptBrowserList();
	}
}

async function fetchScriptBrowserList() {
	loadingScriptBrowser.value = true;
	try {
		const rows = await frappeRequest({
			url: "/api/method/frappe.client.get_list",
			params: {
				doctype: "Server Script",
				fields: JSON.stringify(["name", "script_type"]),
				limit_page_length: 0,
				order_by: "modified desc",
			},
		});
		scriptBrowserList.value = rows || [];
	} catch (e) {
		console.error("Failed to load script list:", e);
	} finally {
		loadingScriptBrowser.value = false;
	}
}

async function linkExistingScript(name) {
	showScriptBrowser.value = false;
	isInitializing = true;
	try {
		canvasScriptName.value = name;
		savedScriptName.value  = name;
		isLoadingScript.value  = true;
		const msg = await frappeRequest({
			url: "/api/method/frappe.client.get",
			params: { doctype: "Server Script", name },
		});
		canvasCode.value = msg?.script || "";
		scriptMeta.value = {
			script_type:       "API",
			reference_doctype: msg?.reference_doctype || "",
			doctype_event:     msg?.doctype_event || "",
			api_method:        msg?.api_method || "",
			allow_guest:       !!msg?.allow_guest,
			event_frequency:   msg?.event_frequency || "",
			cron_format:       msg?.cron_format || "",
			module:            msg?.module || "",
		};
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     name,
			});
		}
		isDirty.value = false;
		isSaved.value = false;
		await fetchVersionHistory();
	} catch (e) {
		console.error("Failed to link script:", e);
	} finally {
		isLoadingScript.value = false;
		isInitializing = false;
	}
}

// ── Chat wiring ───────────────────────────────────────────
// The shared AgentChatPanel owns transcript/composer/lifecycle; this host
// owns what card actions mean.

const logixTurnContext = computed(() => ({
	element_name: elementLabel.value || canvasScriptName.value || "",
	// The launch paths differ: the properties-panel launcher loads the script
	// into canvas state without setting the prop — the canvas's own state is
	// the truth (fixed after a live turn where the map couldn't see the
	// script and asked the user to paste it).
	current_script: savedScriptName.value || canvasScriptName.value || props.currentScript || "",
	process_context: props.processContext || null,
}));

async function onLogixCardAction({ name, action, value, payload }) {
	if (name === "onefm.test_cases" && action === "run-test") {
		await runTestCase(payload);
		return;
	}
	if (name !== "onefm.script_diff" || action !== "apply-script") return;
	const code = value.modified_script || "";
	if (!code) return;
	// Set the canvas, mark dirty, and save through the one path that owns
	// naming, linking and version history.
	if (value.mode === "CREATE" && value.suggested_name && !canvasScriptName.value) {
		canvasScriptName.value = value.suggested_name;
	}
	canvasCode.value = code;
	isDirty.value = true;
	isSaved.value = false;
	await saveScript();
}

// The TestCaseCard renders and requests; the host owns the linked-script name, so it starts the run.
async function runTestCase(payload) {
	const report = payload && typeof payload.onResult === "function" ? payload.onResult : () => {};
	if (!savedScriptName.value) {
		report({ passed: false, summary: "Save the script first — there is nothing to run yet." });
		return;
	}
	report(
		await useLogixTestRun({
			scriptName: savedScriptName.value,
			inputs: payload.inputs,
			processContext: props.processContext,
		}),
	);
}

// ── Element label ─────────────────────────────────────────────────────
const elementLabel = computed(() => {
	if (!props.element) return "";
	const bo = props.element.businessObject;
	return bo?.name || props.element.id || "";
});

// ── Lifecycle ─────────────────────────────────────────────────────────
onMounted(async () => {
	loadDoctypeOptions();
	loadModuleOptions();
	await initCanvas();
});

async function initCanvas() {
	isInitializing = true;
	try {
		if (props.currentScript) {
			canvasScriptName.value = props.currentScript;
			savedScriptName.value  = props.currentScript;
			isLoadingScript.value  = true;
			try {
				const msg = await frappeRequest({
					url: "/api/method/frappe.client.get",
					params: { doctype: "Server Script", name: props.currentScript },
				});
				canvasCode.value = msg?.script || "";
				scriptMeta.value = {
					script_type:       "API",
					reference_doctype: msg?.reference_doctype || "",
					doctype_event:     msg?.doctype_event || "",
					api_method:        msg?.api_method || "",
					allow_guest:       !!msg?.allow_guest,
					event_frequency:   msg?.event_frequency || "",
					cron_format:       msg?.cron_format || "",
					module:            msg?.module || "",
				};
			} catch (e) {
				console.error("Failed to load script:", e);
			} finally {
				isLoadingScript.value = false;
			}
			await fetchVersionHistory();
		} else {
			// Auto-set display name from the BPMN element label; savedScriptName stays ""
			// until the first successful auto-save confirms it exists in the DB.
			canvasScriptName.value = elementLabel.value || "";
			savedScriptName.value  = "";
			canvasCode.value = "";
		}
	} finally {
		isInitializing = false;
	}
}

// ── Code editor helpers ───────────────────────────────────────────────
function onCodeInput() {
	isDirty.value = true;
	isSaved.value = false;
	scheduleAutoSave();
}

// syncScroll removed — CodeMirror handles scroll sync natively

function startEditName() {
	isEditingName.value = true;
	nextTick(() => {
		nameInputEl.value?.select();
	});
}

async function stopEditName() {
	isEditingName.value = false;
	const newName = canvasScriptName.value.trim();
	if (newName && newName !== savedScriptName.value) {
		// New name — ensure it doesn't collide with an unrelated existing script
		await ensureUniqueName();
	}
	scheduleAutoSave();
}

async function copyCanvas() {
	try { await navigator.clipboard.writeText(canvasCode.value); } catch { /* fallback */ }
}

// ── Version history (real API) ───────────────────────────────────────
async function fetchVersionHistory() {
	if (!canvasScriptName.value) { versions.value = []; return; }
	loadingVersions.value = true;
	try {
		const data = await frappeRequest({
			url: "/api/method/processa.api.versions.get_script_version_history",
			params: { script_name: canvasScriptName.value },
		});
		versions.value = data || [];
	} catch (e) {
		console.error("Failed to fetch version history:", e);
		versions.value = [];
	} finally {
		loadingVersions.value = false;
	}
}

function formatCreation(creation) {
	if (!creation) return "";
	try {
		return new Date(creation).toLocaleString(undefined, {
			month: "short", day: "numeric",
			hour: "2-digit", minute: "2-digit"
		});
	} catch { return creation; }
}

function toggleDiff(version) {
	if (diffVersion.value?.version_name === version.version_name) {
		diffVersion.value = null;
		versionDiffRows.value = [];
		return;
	}
	diffVersion.value = version;
	const oldLines = (version.script || "").split("\n");
	const newLines = (canvasCode.value || "").split("\n");
	const rows = [];
	const maxLen = Math.max(oldLines.length, newLines.length);
	for (let i = 0; i < maxLen; i++) {
		const l = oldLines[i] ?? null;
		const r = newLines[i] ?? null;
		if (l === r) rows.push({ type: "unchanged", left: l, right: r });
		else if (l === null) rows.push({ type: "added", left: null, right: r });
		else if (r === null) rows.push({ type: "deleted", left: l, right: null });
		else rows.push({ type: "changed", left: l, right: r });
	}
	versionDiffRows.value = rows;
}

function diffCellClass(row, side) {
	if (row.type === "hunk")      return "lc-sdiff-hunk";
	if (row.type === "unchanged") return "";
	if (row.type === "deleted")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-empty";
	if (row.type === "added")     return side === "right" ? "lc-sdiff-add"  : "lc-sdiff-empty";
	if (row.type === "changed")   return side === "left"  ? "lc-sdiff-del"  : "lc-sdiff-add";
	return "";
}

async function restoreVersion(version) {
	canvasCode.value  = version.script || "";
	isDirty.value     = true;
	isSaved.value     = false;
	diffVersion.value = null;
	scheduleAutoSave();
}

// ── Auto-save scheduler ───────────────────────────────────────────────
function scheduleAutoSave() {
	if (isInitializing) return;
	// Read-only viewing (locked map): never persist edits, even if the
	// CodeMirror's own readOnly state is briefly out of sync.
	if (props.readonly) return;
	if (autoSaveTimer) clearTimeout(autoSaveTimer);
	autoSaveTimer = setTimeout(() => { saveScript(); }, 1500);
}

// Watch metadata changes and auto-save
watch(scriptMeta, () => { scheduleAutoSave(); }, { deep: true });

// ── Unique name helper ────────────────────────────────────────────────
async function ensureUniqueName() {
	const base = canvasScriptName.value.trim();
	if (!base) return;
	let name = base;
	let counter = 1;
	while (true) {
		try {
			// A name that matches the currently saved script is always fine (it's ours)
			if (name === savedScriptName.value) break;
			const d = await frappeRequest({
				url: "/api/method/processa.api.server_scripts.check_server_script_exists",
				params: { script_name: name },
			});
			if (!d?.exists) break;
			name = `${base} ${counter++}`;
		} catch { break; }
	}
	canvasScriptName.value = name;
}

// ── Save script ───────────────────────────────────────────────────────
async function saveScript() {
	if (props.readonly) return; // view-only: never persist edits
	const name = canvasScriptName.value.trim();
	if (!name) return; // silently wait — user hasn't named the script yet

	isSaving.value = true;
	try {
		// If the script was previously saved under a different name, rename it first
		if (savedScriptName.value && savedScriptName.value !== name) {
			await frappeRequest({
				url: "/api/method/frappe.client.rename_doc",
				method: "POST",
				params: { doctype: "Server Script", name: savedScriptName.value, new_name: name },
			});
			savedScriptName.value = name;
		}

		// Upsert with the (possibly renamed) name
		const meta = scriptMeta.value;
		const data = await frappeRequest({
			url: "/api/method/processa.api.server_scripts.create_server_script",
			method: "POST",
			params: {
				script_name:       name,
				script_type:       "API",
				script:            canvasCode.value,
				reference_doctype: meta.reference_doctype || undefined,
				doctype_event:     meta.doctype_event || undefined,
				api_method:        meta.api_method || undefined,
				allow_guest:       meta.allow_guest ? 1 : 0,
				event_frequency:   meta.event_frequency || undefined,
				cron_format:       meta.cron_format || undefined,
				module:            meta.module || undefined,
			},
		});
		const scriptName = data?.name || name;
		canvasScriptName.value = scriptName;
		savedScriptName.value  = scriptName;

		// Fire BPMN event to link the script to the element
		if (props.eventBus && props.element) {
			props.eventBus.fire("spiff.script.update", {
				element:    props.element,
				scriptType: props.scriptType,
				script:     scriptName,
			});
		}

		saveError.value = "";
		isDirty.value = false;
		isSaved.value = true;
		setTimeout(() => { isSaved.value = false; }, 3000);

		emit("script-saved", scriptName);
		await fetchVersionHistory();
	} catch (err) {
		console.error("Auto-save failed:", err);
		saveError.value = err?.messages?.[0] || err?.message || "Auto-save failed";
	} finally {
		isSaving.value = false;
	}
}

// Conversation lifecycle (create / resume / end-on-unmount) is owned by the
// shared AgentChatPanel — no chat teardown left to do here.
</script>

<style scoped src="./LogixCanvas.css"></style>
