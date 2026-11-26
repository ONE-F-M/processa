<template>
	<!-- Backend (selector always runs direct_api) -->
	<div class="field-row" v-if="!isSelector">
		<label>Backend</label>
		<select v-model="form.aiBackend">
			<option value="direct_api">Direct API</option>
			<option value="antigravity">Google Antigravity SDK</option>
		</select>
	</div>

	<!-- AI Provider — chosen first, and it narrows the model lists below
               to that provider's models. Read-only;
               a provider that cannot be picked cannot narrow anything. -->
	<div class="field-row">
		<label>AI Provider <span class="hint">(narrows the models below)</span></label>
		<select v-model="form.aiProvider" @change="onProviderChange">
			<option value="">-- Any provider --</option>
			<option v-for="p in providers" :key="p.name" :value="p.name">
				{{ p.provider_name || p.name }}
			</option>
		</select>
		<span class="field-hint"
			>Choosing a provider clears a model that belongs to a different one.</span
		>
	</div>

	<!-- Model — the agent's catalog pick: editable here and
               written back to the linked configuration on Save; the provider
               follows the model automatically. -->
	<div class="field-row">
		<label
			>Model
			<span class="hint"
				>(the agent's catalog pick — saving writes it back; provider follows)</span
			></label
		>
		<select v-model="form.aiModel" @change="onModelChange">
			<option value="">-- Pick a Model --</option>
			<option v-if="unlistedModelLabel(form.aiModel)" :value="form.aiModel">
				{{ unlistedModelLabel(form.aiModel) }}
			</option>
			<option v-for="m in filteredCatalogModels" :key="m.name" :value="m.name">
				{{ modelLabel(m) }}
			</option>
		</select>
	</div>

	<!-- Output variable (selector output is the chosen task, not a variable) -->
	<div class="field-row" v-if="!isSelector">
		<label>Output Variable Name</label>
		<input type="text" v-model="form.aiOutputVariable" placeholder="ai_result" />
	</div>

	<!-- System prompt -->
	<div class="field-row">
		<label
			>System Prompt
			<span class="hint">(Jinja: {{ "{{" }} doc }}, {{ "{{" }} instance }})</span></label
		>
		<textarea v-model="form.aiSystemPrompt" rows="4" />
	</div>

	<!-- User prompt -->
	<div class="field-row">
		<label>User Prompt <span class="hint">(Jinja supported)</span></label>
		<textarea v-model="form.aiUserPrompt" rows="4" />
	</div>

	<!-- Response format (selector responses are tool calls, not text/JSON) -->
	<div class="field-row" v-if="!isSelector">
		<label>Response Format</label>
		<select v-model="form.aiResponseFormat">
			<option value="text">Text</option>
			<option value="json">JSON</option>
		</select>
	</div>

	<!-- Response schema (only when JSON) -->
	<div class="field-row" v-if="!isSelector && form.aiResponseFormat === 'json'">
		<label>Response Schema <span class="hint">(JSON Schema)</span></label>
		<textarea v-model="form.aiResponseSchema" rows="4" placeholder='{"type":"object",...}' />
	</div>

	<div class="field-group-title">Advanced Settings</div>

	<div class="field-row two-col">
		<div>
			<label>Temperature</label>
			<input
				type="number"
				v-model.number="form.aiTemperature"
				min="0"
				max="2"
				step="0.1"
				:disabled="!samplingSupported"
				:class="{ 'field-off': !samplingSupported }"
			/>
		</div>
		<div>
			<label>Top P</label>
			<input
				type="number"
				v-model.number="form.aiTopP"
				min="0"
				max="1"
				step="0.05"
				:disabled="!samplingSupported"
				:class="{ 'field-off': !samplingSupported }"
			/>
		</div>
	</div>
	<span class="field-hint" v-if="!samplingSupported">
		{{ form.aiModel }} does not accept Temperature or Top P, so neither is sent. Tick Support
		Temperature on the AI Model to use them.
	</span>

	<div class="field-row two-col">
		<div>
			<label>Max Tokens</label>
			<input type="number" v-model.number="form.aiMaxTokens" min="1" />
		</div>
		<div>
			<label>Timeout (seconds)</label>
			<input type="number" v-model.number="form.aiTimeout" min="1" />
		</div>
	</div>

	<div v-if="effortSupported" class="field-row two-col">
		<div>
			<label>Effort</label>
			<select v-model="form.aiEffort">
				<option value="">Model Default</option>
				<option v-for="level in EFFORT_LEVELS" :key="level" :value="level">
					{{ level }}
				</option>
			</select>
		</div>
		<div>
			<label>Minimum Tokens When Thinking</label>
			<input v-model.number="form.aiThinkingMinTokens" type="number" min="0" step="1024" />
		</div>
	</div>
	<span v-if="effortSupported" class="field-hint">
		Effort is how hard the model thinks. Thinking counts against Max Tokens, so Max Tokens
		cannot be below the minimum. A minimum of 0 means 8,192.
	</span>
	<span v-if="maxTokensBelowMinimum" class="field-hint">
		Max Tokens ({{ form.aiMaxTokens }}) is below the minimum ({{ thinkingMinimum }}). Raise
		Max Tokens or lower the minimum before saving.
	</span>

	<div v-if="showStageEfforts" class="field-row">
		<label>Stage Effort <span class="hint">(blank uses the Effort above)</span></label>
		<div
			v-for="stage in form.aiStageEfforts"
			:key="stage.sub_agent_id"
			class="field-row two-col"
		>
			<span>{{ stage.sub_agent_name || stage.sub_agent_id }}</span>
			<select v-model="stage.effort">
				<option value="">Agent Effort</option>
				<option v-for="level in EFFORT_LEVELS" :key="level" :value="level">
					{{ level }}
				</option>
			</select>
		</div>
	</div>

	<div class="field-row two-col" v-if="!isSelector">
		<div>
			<label>Run Token Budget <span class="hint">(0 = no budget)</span></label>
			<input type="number" v-model.number="form.aiRunTokenBudget" min="0" step="1000" />
		</div>
		<div>
			<label>Run Cost Budget <span class="hint">(USD, 0 = no budget)</span></label>
			<input type="number" v-model.number="form.aiRunCostBudget" min="0" step="0.1" />
		</div>
	</div>

	<template v-if="form.aiAgentConfig">
		<div class="field-row two-col">
			<div>
				<label>Tool Choice <span class="hint">(first model call only)</span></label>
				<input type="text" v-model.trim="form.aiToolChoice" placeholder="auto" />
			</div>
			<div v-if="!effortSupported">
				<label>Thinking Budget Tokens <span class="hint">(0 = off)</span></label>
				<input
					type="number"
					v-model.number="form.aiThinkingBudgetTokens"
					min="0"
					step="1024"
				/>
			</div>
		</div>
		<span class="field-hint">
			Tool Choice is auto, required, or a tool shape's id, saved on the linked agent.
			<template v-if="!effortSupported">
				A thinking budget is for older models: at least 1,024 and below Max Tokens.
			</template>
		</span>
		<div class="field-row two-col">
			<div>
				<label
					>Terminal Tools
					<span class="hint"
						>(comma-separated; finalize always ends the turn)</span
					></label
				>
				<input type="text" v-model.trim="form.aiTerminalTools" />
			</div>
			<div>
				<label class="checkbox-row">
					<input
						type="checkbox"
						v-model="form.aiParallelToolCalls"
						class="checkbox-input"
					/>
					<span>Parallel Tool Calls</span>
				</label>
			</div>
		</div>
		<div class="field-row" v-if="!isSelector">
			<label>Sandbox</label>
			<label class="checkbox-row">
				<input type="checkbox" v-model="form.aiSandboxUseJob" class="checkbox-input" />
				<span>Use a Cloud Run Job session per Work Item</span>
			</label>
			<label class="checkbox-row">
				<input
					type="checkbox"
					v-model="form.aiSandboxRetryOnTestFailure"
					class="checkbox-input"
				/>
				<span>Retry a failed sandbox dispatch once on test failure</span>
			</label>
			<label class="checkbox-row">
				<input
					type="checkbox"
					v-model="form.aiRequireReproduction"
					class="checkbox-input"
				/>
				<span>Require reproduction before a fix (bug discipline)</span>
			</label>
			<span class="field-hint">
				Saved on the linked agent. With the Job session off, every sandbox call is its own
				request to the shared service.
			</span>
		</div>
	</template>

	<div class="field-row" v-if="!isSelector">
		<label>Max Retries</label>
		<input type="number" v-model.number="form.aiMaxRetries" min="0" max="10" />
	</div>

	<div class="field-row" style="margin-top: 8px" v-if="!isSelector">
		<label class="checkbox-row">
			<input type="checkbox" v-model="form.aiStopOnError" class="checkbox-input" />
			<span>Stop process on error</span>
		</label>
		<span class="field-hint"
			>If checked, the process instance will halt when this AI task fails.</span
		>
	</div>
</template>

<script setup>
import { inject } from "vue";
import { AGENT_CONFIG_KEY } from "@/composables/AgentConfig/useAgentConfigState";

const EFFORT_LEVELS = ["Low", "Medium", "High", "Extra High", "Max"];

const ac = inject(AGENT_CONFIG_KEY);
const {
	providers,
	form,
	isSelector,
	filteredCatalogModels,
	onProviderChange,
	samplingSupported,
	effortSupported,
	thinkingMinimum,
	maxTokensBelowMinimum,
	showStageEfforts,
	onModelChange,
	unlistedModelLabel,
	modelLabel,
} = ac;
</script>

<style scoped src="./AgentConfigRunSettings.css"></style>
