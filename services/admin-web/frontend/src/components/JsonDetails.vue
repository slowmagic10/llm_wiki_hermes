<script setup lang="ts">
import { pretty } from '../api'
defineProps<{ value: unknown; title?: string }>()
</script>
<template><details class="json-details"><summary>{{ title || '调试详情' }}</summary><pre>{{ pretty(value) }}</pre></details></template>
