<script setup lang="ts">
import GlobalNoticeBar from './components/common/GlobalNoticeBar.vue'
</script>

<template>
  <GlobalNoticeBar />
  <router-view v-slot="{ Component, route }">
    <transition name="scene-fade" mode="out-in" appear>
      <div :key="route.fullPath" class="app-scene">
        <component :is="Component" />
      </div>
    </transition>
  </router-view>
</template>
