<template>
	<button
		title="Comment Tool"
		:class="[
			'p-1.5 flex items-center justify-center rounded transition-colors',
			active
				? 'bg-blue-100 text-blue-700 shadow-sm'
				: 'hover:bg-gray-100 text-gray-700',
		]"
		@click="$emit('click')"
	>
		<Icon icon="lucide:message-square" class="w-4 h-4" />
	</button>
</template>

<script setup>
import { Icon } from "@iconify/vue";

defineProps({
	active: {
		type: Boolean,
		default: false,
	},
});

defineEmits(["click"]);
</script>
