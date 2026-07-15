<script setup lang="ts">
defineProps<{ label: string; value: string | number; hint?: string; state?: string }>()
</script>
<template>
  <article class="metric-card" :class="state ? 'tone-' + state : ''">
    <div class="metric-card__label">{{ label }}</div>
    <div class="metric-card__value">{{ value ?? '-' }}</div>
    <div class="metric-card__hint">{{ hint || ' ' }}</div>
  </article>
</template>
