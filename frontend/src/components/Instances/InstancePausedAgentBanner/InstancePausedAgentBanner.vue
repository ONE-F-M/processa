<template>
	<div
		v-for="agent in rows"
		:key="agent.agent_run"
		class="flex flex-wrap items-start gap-3 bg-amber-50 border border-amber-200 text-amber-800 text-sm px-4 py-2.5 mx-4 mt-2 rounded-lg"
	>
		<Icon
			icon="lucide:pause-circle"
			class="w-4 h-4 mt-0.5 text-amber-600 shrink-0"
		/>
		<div class="flex-1 min-w-0 break-words">
			<p>
				<span class="font-semibold">AI agent paused</span>
				<span class="text-amber-700"> - waiting for {{ agent.waitText }} since {{ agent.since }}</span>
			</p>
			<p
				v-if="agent.stuck"
				class="mt-0.5"
			>
				The answer arrived at {{ agent.answered }} but the agent was not woken.
			</p>
		</div>
		<Button
			v-if="agent.stuck && canManage"
			variant="solid"
			size="sm"
			:loading="resuming === agent.agent_run"
			:disabled="Boolean(resuming)"
			@click="resume(agent)"
		>
			Resume agent
		</Button>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { Button } from "frappe-ui"
import { Icon } from "@iconify/vue"
import { useCurrentUser } from "@/composables/useCurrentUser"
import { useInstanceControl } from "@/composables/useInstanceControl"

// One row per agent suspended on a sandbox run or a delegation; agents waiting for a person have their own banner.
const props = defineProps({
	instanceName: { type: String, required: true },
	agents: { type: Array, default: () => [] },
})
const emit = defineEmits(["changed", "notice"])

const { currentRoles } = useCurrentUser()
const { runControl } = useInstanceControl()
const resuming = ref("")

const canManage = computed(() => currentRoles.value.some((r) => r === "System Manager" || r === "Process Owner"))

const rows = computed(() =>
	props.agents.map((agent) => ({
		...agent,
		waitText: agent.waits_on === "a2a" ? `another agent (${agent.wait_label})` : agent.wait_label,
		since: timeOf(agent.suspended_at),
		answered: timeOf(agent.answered_at),
	})),
)

function timeOf(value) {
	return value ? String(value).slice(11, 16) : ""
}

async function resume(agent) {
	resuming.value = agent.agent_run
	try {
		await runControl("resume_suspended_agent", props.instanceName, "", { agent_run: agent.agent_run })
		emit("changed")
	} catch (e) {
		emit("notice", e.message)
	} finally {
		resuming.value = ""
	}
}
</script>

<style scoped></style>
