<script setup lang="ts">
import { computed } from 'vue'
import { tone } from '../api'
const props = defineProps<{ status?: string | boolean; label?: string }>()
const kind = computed(() => tone(props.status))
const text = computed(() => props.label || String(props.status ?? 'unknown'))
</script>
<template><span class="status-badge" :class="'is-' + kind"><i></i>{{ text }}</span></template>
