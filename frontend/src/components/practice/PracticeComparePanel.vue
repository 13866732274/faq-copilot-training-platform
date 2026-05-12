<script setup lang="ts">
import { computed, ref } from 'vue'
import MessageContent from '../chat/MessageContent.vue'

type CompareMessage = {
  id?: number
  role?: string
  sender_name?: string | null
  content_type?: string | null
  content: string
  original_time?: string | null
}

type CompareRound = {
  patient_messages: CompareMessage[]
  standard_answer: CompareMessage
  standard_answers?: CompareMessage[]
  student_reply?: { content: string; reply_time?: string } | null
}

const props = withDefaults(
  defineProps<{
    dialogues: CompareRound[]
    emptyText?: string
  }>(),
  {
    emptyText: '暂无对比数据',
  },
)

const showOriginal = ref(false)

const originalTimeline = computed(() => {
  const result: Array<CompareMessage & { key: string }> = []
  props.dialogues.forEach((round, roundIndex) => {
    round.patient_messages.forEach((msg, msgIndex) =>
      result.push({
        ...msg,
        key: `p-${roundIndex}-${msgIndex}`,
        role: msg.role || 'patient',
        sender_name: msg.sender_name || '患者',
      }),
    )
    const answers = round.standard_answers?.length ? round.standard_answers : [round.standard_answer]
    answers.forEach((ans, ansIndex) => {
      result.push({
        ...ans,
        key: `c-${roundIndex}-${ansIndex}`,
        role: ans.role || 'counselor',
        sender_name: ans.sender_name || '咨询师',
      })
    })
  })
  return result
})
</script>

<template>
  <div class="compare-panel">
    <div class="panel-actions">
      <el-button @click="showOriginal = !showOriginal">
        {{ showOriginal ? '收起完整原始对话' : '查看完整原始对话' }}
      </el-button>
    </div>

    <el-alert
      type="success"
      :closable="false"
      show-icon
      title="本套作答已结束。你可以对照“我的回复区”和“答案区”，也可展开查看完整原始对话。"
      style="margin-bottom: 12px"
    />

    <el-empty v-if="!dialogues.length" :description="emptyText" />

    <el-card v-if="showOriginal" shadow="never" class="original-wrap">
      <template #header><strong>原始对话（完整）</strong></template>
      <el-empty v-if="!originalTimeline.length" description="暂无原始消息" />
      <div
        v-for="(msg, idx) in originalTimeline"
        :key="`${msg.key}-${idx}`"
        class="origin-line"
        :class="msg.role"
      >
        <div class="origin-meta">
          <el-tag size="small" :type="msg.role === 'patient' ? 'info' : 'success'">
            {{ msg.role === 'patient' ? '患者' : '咨询师' }}
          </el-tag>
          <span class="origin-name">{{ msg.sender_name }}</span>
          <span v-if="msg.original_time" class="origin-time">{{ msg.original_time }}</span>
        </div>
        <div class="origin-content">
          <MessageContent :content-type="msg.content_type || 'text'" :content="msg.content" />
        </div>
      </div>
    </el-card>

    <div v-for="(round, index) in dialogues" :key="index" class="round">
      <h4>第 {{ index + 1 }} 轮对话</h4>
      <div class="patient-line" v-for="(m, i) in round.patient_messages" :key="i">
        患者：<MessageContent :content-type="m.content_type || 'text'" :content="m.content" />
      </div>
      <div class="compare">
        <div class="col mine">
          <div class="head">我的回复</div>
          <div>{{ round.student_reply?.content || '（未作答）' }}</div>
        </div>
        <div class="col std">
          <div class="head">答案区（标准答案）</div>
          <div
            v-for="(ans, ansIdx) in round.standard_answers?.length ? round.standard_answers : [round.standard_answer]"
            :key="ansIdx"
            class="answer-line"
          >
            <div class="answer-label">A{{ ansIdx + 1 }}</div>
            <MessageContent :content-type="ans.content_type || 'text'" :content="ans.content" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.compare-panel {
  --cmp-round-bg: color-mix(in srgb, var(--ui-surface-1, var(--el-bg-color)) 96%, #fff 4%);
  --cmp-round-border: var(--ui-border-soft, var(--el-border-color));
  --cmp-round-shadow: 0 10px 24px -20px rgb(0 0 0 / 26%);
  --cmp-patient-text: var(--el-text-color-primary);
  --cmp-mine-bg: linear-gradient(
    145deg,
    color-mix(in srgb, var(--el-color-warning-light-9) 82%, var(--el-bg-color) 18%) 0%,
    color-mix(in srgb, var(--el-color-warning-light-8) 46%, var(--el-bg-color) 54%) 100%
  );
  --cmp-mine-border: color-mix(in srgb, var(--el-color-warning-light-5) 56%, var(--el-border-color) 44%);
  --cmp-std-bg: linear-gradient(
    145deg,
    color-mix(in srgb, var(--el-color-primary-light-9) 86%, var(--el-bg-color) 14%) 0%,
    color-mix(in srgb, var(--el-color-primary-light-8) 44%, var(--el-bg-color) 56%) 100%
  );
  --cmp-std-border: color-mix(in srgb, var(--el-color-primary-light-5) 55%, var(--el-border-color) 45%);
  --cmp-head-text: var(--el-text-color-primary);
  --cmp-answer-line-bg: rgb(255 255 255 / 46%);
  --cmp-answer-line-border: color-mix(in srgb, var(--el-color-primary-light-5) 48%, var(--el-border-color) 52%);
  --cmp-answer-label-bg: #ecf5ff;
  --cmp-answer-label-color: #2475d4;
  --cmp-answer-label-border: #d3e8ff;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.original-wrap {
  margin-bottom: 14px;
}

.origin-line {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 8px;
}

.origin-line.patient {
  background: var(--el-fill-color-lighter);
}

.origin-line.counselor {
  background: color-mix(in srgb, var(--el-color-success-light-9) 65%, var(--el-bg-color) 35%);
}

.origin-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.origin-name,
.origin-time {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.round {
  border: 1px solid var(--cmp-round-border);
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 14px;
  background: var(--cmp-round-bg);
  box-shadow: var(--cmp-round-shadow);
}

.round h4 {
  color: var(--el-text-color-primary);
}

.patient-line {
  color: var(--cmp-patient-text);
  margin-bottom: 4px;
  line-height: 1.6;
  word-break: break-all;
}

.compare {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.col {
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 10px;
  word-break: break-all;
}

.std {
  background: var(--cmp-std-bg);
  border-color: var(--cmp-std-border);
}

.mine {
  background: var(--cmp-mine-bg);
  border-color: var(--cmp-mine-border);
}

.head {
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--cmp-head-text);
}

.answer-line + .answer-line {
  margin-top: 6px;
}

.answer-line {
  border: 1px solid var(--cmp-answer-line-border);
  background: var(--cmp-answer-line-bg);
  border-radius: 8px;
  padding: 8px 10px;
}

.answer-label {
  display: inline-block;
  font-size: 12px;
  color: var(--cmp-answer-label-color);
  background: var(--cmp-answer-label-bg);
  border: 1px solid var(--cmp-answer-label-border);
  border-radius: 10px;
  padding: 1px 8px;
  margin-bottom: 4px;
}

:global(.dark) .compare-panel .round {
  --cmp-round-bg: linear-gradient(160deg, rgb(26 30 37 / 92%) 0%, rgb(18 22 28 / 94%) 100%);
  --cmp-round-border: #3d4a5d;
  --cmp-round-shadow: 0 14px 28px -20px rgb(0 0 0 / 58%);
  --cmp-patient-text: #ecf1f8;
  --cmp-mine-bg: linear-gradient(145deg, rgb(64 55 33 / 88%) 0%, rgb(43 36 24 / 90%) 100%);
  --cmp-mine-border: #655a3f;
  --cmp-std-bg: linear-gradient(145deg, rgb(34 54 78 / 90%) 0%, rgb(24 40 60 / 92%) 100%);
  --cmp-std-border: #4a6b95;
  --cmp-head-text: #f4f8ff;
  --cmp-answer-line-bg: rgb(223 246 255 / 8%);
  --cmp-answer-line-border: #4e6f9b;
  --cmp-answer-label-bg: #173b60;
  --cmp-answer-label-color: #b8ddff;
  --cmp-answer-label-border: #2f5f93;
}

:global(.dark) .compare-panel .patient-line {
  color: var(--cmp-patient-text);
}

:global(.dark) .compare-panel .origin-line.patient {
  background: #242a32;
  border-color: #3f4654;
}

:global(.dark) .compare-panel .origin-line.counselor {
  background: #1f3228;
  border-color: #355347;
}

:global(.dark) .compare-panel .std {
  background: var(--cmp-std-bg);
}

:global(.dark) .compare-panel .mine {
  background: var(--cmp-mine-bg);
}

:global(.dark) .compare-panel .head {
  color: var(--cmp-head-text);
}

:global(.dark) .compare-panel .origin-name,
:global(.dark) .compare-panel .origin-time {
  color: #c8ced8;
}

@media (max-width: 768px) {
  .panel-actions {
    justify-content: flex-start;
  }

  .compare {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .round {
    padding: 10px;
  }
}
</style>
