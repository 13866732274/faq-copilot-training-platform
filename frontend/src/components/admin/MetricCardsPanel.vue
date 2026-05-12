<script setup lang="ts">
import { onBeforeUnmount, ref, watch, type Component } from 'vue'

type MetricTone = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export interface MetricCardItem {
  key: string
  label: string
  value: number | string
  hint?: string
  tone?: MetricTone
  icon?: Component
}

const props = withDefaults(
  defineProps<{
    items: MetricCardItem[]
    loading?: boolean
    refreshTick?: number
  }>(),
  {
    loading: false,
    refreshTick: 0,
  },
)

const toneClass = (tone?: MetricTone) => `tone-${tone || 'primary'}`
const refreshAnimating = ref(false)
let refreshTimer: ReturnType<typeof window.setTimeout> | null = null

watch(
  () => props.refreshTick,
  () => {
    refreshAnimating.value = true
    if (refreshTimer) window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => {
      refreshAnimating.value = false
      refreshTimer = null
    }, 720)
  },
)

onBeforeUnmount(() => {
  if (!refreshTimer) return
  window.clearTimeout(refreshTimer)
  refreshTimer = null
})
</script>

<template>
  <el-row :gutter="12" class="metric-grid" :class="{ 'refresh-animating': refreshAnimating }">
    <el-col v-for="item in props.items" :key="item.key" :xs="24" :sm="12" :md="8" :lg="8" :xl="4">
      <el-card shadow="never" class="metric-card" :class="[toneClass(item.tone), { loading: props.loading }]">
        <el-skeleton v-if="props.loading" animated>
          <template #template>
            <div class="metric-skeleton">
              <el-skeleton-item variant="text" style="width: 45%; height: 16px" />
              <el-skeleton-item variant="text" style="width: 62%; height: 34px; margin-top: 12px" />
              <el-skeleton-item variant="text" style="width: 72%; height: 14px; margin-top: 10px" />
            </div>
          </template>
        </el-skeleton>
        <div v-else class="metric-content">
          <div class="metric-head">
            <span class="metric-label">{{ item.label }}</span>
            <el-icon v-if="item.icon" class="metric-icon"><component :is="item.icon" /></el-icon>
          </div>
          <div class="metric-value">{{ item.value }}</div>
          <div class="metric-hint">{{ item.hint || ' ' }}</div>
        </div>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
.metric-grid {
  margin-bottom: 12px;
}

.metric-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  transition: transform 0.2s ease, box-shadow 0.22s ease, border-color 0.2s ease;
}

.metric-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 24px -20px rgb(0 0 0 / 20%);
}

.metric-card.loading {
  min-height: 132px;
}

.metric-card::after {
  content: '';
  position: absolute;
  right: -24px;
  top: -24px;
  width: 82px;
  height: 82px;
  border-radius: 999px;
  opacity: 0.14;
  background: var(--metric-accent, var(--el-color-primary));
}

.metric-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.metric-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.metric-icon {
  font-size: 16px;
  color: var(--metric-accent, var(--el-color-primary));
}

.metric-value {
  margin-top: 8px;
  font-size: 30px;
  line-height: 1.1;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: var(--el-text-color-primary);
}

.metric-skeleton {
  min-height: 100px;
}

.metric-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.metric-card.tone-primary {
  --metric-accent: var(--el-color-primary);
}

.metric-card.tone-success {
  --metric-accent: var(--el-color-success);
}

.metric-card.tone-warning {
  --metric-accent: var(--el-color-warning);
}

.metric-card.tone-info {
  --metric-accent: var(--el-color-info);
}

.metric-card.tone-danger {
  --metric-accent: var(--el-color-danger);
}

.refresh-animating .metric-content {
  animation: metricPulse 0.7s ease;
}

@keyframes metricPulse {
  0% {
    filter: saturate(1);
  }
  45% {
    filter: saturate(1.22);
    transform: translateY(-1px);
  }
  100% {
    filter: saturate(1);
    transform: translateY(0);
  }
}
</style>
