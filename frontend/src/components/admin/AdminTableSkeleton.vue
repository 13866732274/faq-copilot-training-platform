<script setup lang="ts">
withDefaults(
  defineProps<{
    rows?: number
    mobileRows?: number
    isMobile?: boolean
  }>(),
  {
    rows: 8,
    mobileRows: 3,
    isMobile: false,
  },
)
</script>

<template>
  <div class="admin-table-skeleton">
    <template v-if="!isMobile">
      <el-skeleton class="table-skeleton" animated :rows="rows" />
    </template>
    <div v-else class="mobile-skeleton-list">
      <el-skeleton v-for="idx in mobileRows" :key="idx" animated :rows="3" />
    </div>
  </div>
</template>

<style scoped>
.table-skeleton {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 14px 12px;
  background: var(--el-bg-color);
}

.mobile-skeleton-list {
  display: grid;
  gap: 10px;
}
</style>
