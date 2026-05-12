<script setup lang="ts">
import { computed } from 'vue'
import { ref } from 'vue'

const props = defineProps<{
  contentType: string
  content: string
}>()

const previewVisible = ref(false)
const audioStatus = ref<'idle' | 'playing' | 'paused' | 'ended'>('idle')
const mediaBaseUrl = (import.meta.env.VITE_MEDIA_BASE_URL || '').replace(/\/$/, '')
const isLikelyMediaUrl = (value: string) => {
  if (!value) return false
  const v = value.trim().toLowerCase()
  if (!v) return false
  if (v.startsWith('http://') || v.startsWith('https://') || v.startsWith('/')) return true
  return (
    v.includes('/uploads/') ||
    v.includes('.png') ||
    v.includes('.jpg') ||
    v.includes('.jpeg') ||
    v.includes('.gif') ||
    v.includes('.webp') ||
    v.includes('.bmp') ||
    v.includes('.mp3') ||
    v.includes('.wav') ||
    v.includes('.amr') ||
    v.includes('.aac') ||
    v.includes('.m4a') ||
    v.includes('.ogg') ||
    v.includes('.opus')
  )
}

const mediaUrl = computed(() => {
  const content = props.content || ''
  if (!content) return ''
  if (!isLikelyMediaUrl(content)) return ''
  if (content.startsWith('http://') || content.startsWith('https://')) return content
  if (content.startsWith('/')) return mediaBaseUrl ? `${mediaBaseUrl}${content}` : content
  if (content.includes('/uploads/')) {
    const normalized = content.replace(/^\/+/, '')
    return mediaBaseUrl ? `${mediaBaseUrl}/${normalized}` : `/${normalized}`
  }
  return content
})

const hasImageUrl = computed(() => props.contentType === 'image' && !!mediaUrl.value)
const hasAudioUrl = computed(() => props.contentType === 'audio' && !!mediaUrl.value)
</script>

<template>
  <template v-if="contentType === 'image'">
    <div v-if="hasImageUrl" class="img-wrap" @click="previewVisible = true">
      <img :src="mediaUrl" alt="图片消息" />
    </div>
    <div v-else class="media-placeholder image">
      <div class="media-placeholder-title">图片消息</div>
      <div class="media-placeholder-tip">{{ content || '未导出原图链接' }}</div>
    </div>
    <el-dialog v-model="previewVisible" title="图片预览" width="60%">
      <div class="preview-box">
        <img :src="mediaUrl" alt="图片预览" class="preview-img" />
      </div>
    </el-dialog>
  </template>
  <template v-else-if="contentType === 'audio'">
    <div class="audio-wrap">
      <audio
        v-if="hasAudioUrl"
        :src="mediaUrl"
        controls
        preload="none"
        @play="audioStatus = 'playing'"
        @pause="audioStatus = 'paused'"
        @ended="audioStatus = 'ended'"
      />
      <div v-else class="media-placeholder audio">
        <div class="media-placeholder-title">语音消息</div>
        <div class="media-placeholder-tip">{{ content || '未导出音频链接' }}</div>
      </div>
      <div v-if="hasAudioUrl" class="audio-status">
        {{
          audioStatus === 'playing'
            ? '播放中'
            : audioStatus === 'paused'
              ? '已暂停'
              : audioStatus === 'ended'
                ? '已播放完成'
                : '待播放'
        }}
      </div>
    </div>
  </template>
  <template v-else>
    <span>{{ content }}</span>
  </template>
</template>

<style scoped>
.img-wrap {
  cursor: zoom-in;
}
.img-wrap img {
  max-width: 220px;
  max-height: 220px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
}
.preview-box {
  display: flex;
  justify-content: center;
}
.preview-img {
  max-width: 100%;
  max-height: 70vh;
  border-radius: 6px;
}
.audio-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.audio-status {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.media-placeholder {
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--el-fill-color-lighter);
  min-width: 170px;
}

.media-placeholder-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.media-placeholder-tip {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
