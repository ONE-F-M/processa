<template>
	<!-- Phases like CLARIFY or NO_MATCH carry no panel, no stage action and no
	     next step — their whole answer is the reply text, so the card renders
	     nothing rather than an empty shell above it. -->
	<CardShell v-if="view.hasContent" :title="view.title">
		<LuCrusherResultBody :value="value" :busy="busy" capped @action="(...a) => $emit('action', ...a)" />
		<template v-if="view.panel" #expanded>
			<LuCrusherResultBody :value="value" :busy="busy" readonly />
		</template>
	</CardShell>
</template>
<script setup>
// LuCrusherResultCard = CardShell[LuCrusherResultBody] over the
// six panels lumina.js rendered by hand for onefm.lucrusher_result: process
// matches, a parsed Lucidchart document, a codebase scan, the topology
// proposal, the migration task list and the ProsAlly prompts. Which panel
// shows is decided by the payload's `intent`, exactly as
// handle_lucrusher_result decided it — see luCrusherView.js.
//
// Every button except Copy prompt is a QUICK-SEND: the panel sends a literal
// sentence as the user's message. LuCrusher reads the sentences as intent, so
// they must not be paraphrased.
import { computed } from "vue";
import CardShell from "../../Primitives/CardShell/CardShell.vue";
import LuCrusherResultBody from "../LuCrusherResultBody/LuCrusherResultBody.vue";
import { deriveLuCrusherView } from "@/utils/luCrusherView";

const props = defineProps({
	value: { type: Object, required: true },
	busy: { type: Boolean, default: false },
});
defineEmits(["action"]);

const view = computed(() => deriveLuCrusherView(props.value));
</script>
