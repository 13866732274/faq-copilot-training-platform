import { getToken } from '../utils/auth'
import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

// ─── Types ────────────────────────────────────────────────────────

export interface FaqClusterItem {
  id: number
  title: string
  summary: string | null
  category: string | null
  tags: string | null
  representative_question: string | null
  best_answer: string | null
  question_count: number
  answer_count: number
  is_active: boolean
  is_locked: boolean
  created_at: string | null
  updated_at: string | null
}

export interface FaqQuestionItem {
  id: number
  content: string
  quiz_id: number | null
  is_representative: boolean
  similarity_score: number
  source_context: string | null
}

export interface FaqAnswerItem {
  id: number
  content: string
  quiz_id: number | null
  quality_score: number
  is_best: boolean
  upvotes: number
  source_context: string | null
}

export interface FaqTaskItem {
  id: number
  retry_from_task_id: number | null
  heartbeat_timeout_minutes: number
  heartbeat_timeout_source_code: string
  heartbeat_timeout_source_label: string
  status: string
  total_quizzes: number
  total_messages: number
  extracted_pairs: number
  clusters_created: number
  clusters_updated: number
  error_message: string | null
  failure_reason_code: string | null
  failure_reason_label: string | null
  stage_durations_json: string | null
  started_at: string | null
  stage_changed_at: string | null
  finished_at: string | null
  created_at: string | null
}

export interface EtaBenchmarkItem {
  avg_seconds: number
  avg_per_quiz: number
  sample_count: number
}

export interface EtaBenchmarksData {
  benchmarks: Record<string, EtaBenchmarkItem> | null
  sample_count: number
}

export interface FaqTaskFailureStatItem {
  code: string
  label: string
  count: number
  latest_task_id: number
  latest_at: string | null
  sample_error: string | null
}

export interface FaqTaskFailureStatsData {
  days: number
  total_failed: number
  items: FaqTaskFailureStatItem[]
}

export interface FaqCategoryCount {
  name: string
  count: number
}

export interface FaqClusterListData {
  items: FaqClusterItem[]
  total: number
  page: number
  page_size: number
  categories: FaqCategoryCount[]
}

export interface FaqClusterDetailData {
  cluster: FaqClusterItem
  questions: FaqQuestionItem[]
  answers: FaqAnswerItem[]
}

export interface FaqSearchResult {
  cluster_id: number
  title: string
  summary: string | null
  category: string | null
  representative_question: string | null
  best_answer: string | null
  question_count: number
  answer_count: number
  similarity: number
}

export interface FaqCopilotData {
  recommended_reply: string
  confidence: number
  sources: string[]
  note: string
  matched_faqs: FaqSearchResult[]
  quality_mode_requested?: CopilotQualityMode
  quality_mode_effective?: Exclude<CopilotQualityMode, 'auto'>
  quality_route_reason?: string
}

export interface FaqStatsData {
  total_clusters: number
  active_clusters: number
  total_questions: number
  total_answers: number
  copilot_today: {
    date_bj: string
    total_calls: number
    avg_latency_ms: number
    quality_hit_calls: number
    quality_hit_rate: number
    failed_calls: number
    failure_rate: number
  }
  copilot_7d_trend: Array<{
    date_bj: string
    calls: number
    avg_latency_ms: number
    failure_rate: number
  }>
  categories: FaqCategoryCount[]
  recent_tasks: Array<{
    id: number
    status: string
    clusters_created: number
    extracted_pairs: number
    created_at: string | null
  }>
}

export interface CopilotPanelData {
  panel_id: number
  query: string
  candidates: string[]
  matched_faqs: FaqSearchResult[]
  confidence: number
  quality_mode_requested: CopilotQualityMode
  quality_mode_effective: Exclude<CopilotQualityMode, 'auto'>
  quality_route_reason: string
  latency_ms: number
}

export interface CopilotEfficiency7dData {
  window_days: number
  total_feedback: number
  accepted: number
  edited: number
  rejected: number
  accept_rate: number
  avg_first_response_ms: number
  avg_session_duration_ms: number
  baseline_first_response_ms: number
  labor_reduction_pct: number
  trend: Array<{
    date_bj: string
    accepted: number
    edited: number
    rejected: number
    total: number
    accept_rate: number
  }>
}

// ─── API Calls ────────────────────────────────────────────────────

export async function startFaqProcessing(quizIds?: number[]): Promise<{ task_id: number; status: string }> {
  const resp = await request.post<ApiResponse<{ task_id: number; status: string }>>('/faq/process', quizIds ? { quiz_ids: quizIds } : {})
  return resp.data.data
}

export async function startFaqIncremental(): Promise<{
  task_id: number
  status: string
  new_quiz_count?: number
  skipped_reason?: string
}> {
  const resp = await request.post<ApiResponse<{
    task_id: number
    status: string
    new_quiz_count?: number
    skipped_reason?: string
  }>>('/faq/process-incremental')
  return resp.data.data
}

export async function listFaqTasks(page = 1, pageSize = 20): Promise<{ items: FaqTaskItem[]; total: number }> {
  const resp = await request.get<ApiResponse<{ items: FaqTaskItem[]; total: number }>>('/faq/tasks', { params: { page, page_size: pageSize } })
  return resp.data.data
}

export async function getFaqTask(taskId: number): Promise<FaqTaskItem> {
  const resp = await request.get<ApiResponse<FaqTaskItem>>(`/faq/tasks/${taskId}`)
  return resp.data.data
}

export async function retryFaqTask(taskId: number): Promise<{ task_id: number; status: string; retry_from_task_id: number }> {
  const resp = await request.post<ApiResponse<{ task_id: number; status: string; retry_from_task_id: number }>>(`/faq/tasks/${taskId}/retry`)
  return resp.data.data
}

export async function deleteFaqTask(taskId: number): Promise<void> {
  await request.delete(`/faq/tasks/${taskId}`)
}

export async function batchDeleteFaqTasks(ids: number[]): Promise<{ deleted: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number }>>('/faq/tasks/batch-delete', { ids })
  return resp.data.data
}

export async function clearFaqTaskHistory(keepDays: number): Promise<{ deleted: number; keep_days: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number; keep_days: number }>>('/faq/tasks/clear-history', { keep_days: keepDays })
  return resp.data.data
}

export async function getFaqTaskFailureStats(days = 30): Promise<FaqTaskFailureStatsData> {
  const resp = await request.get<ApiResponse<FaqTaskFailureStatsData>>('/faq/tasks/failure-stats', { params: { days } })
  return resp.data.data
}

export async function getFaqTaskEtaBenchmarks(): Promise<EtaBenchmarksData> {
  const resp = await request.get<ApiResponse<EtaBenchmarksData>>('/faq/tasks/eta-benchmarks')
  return resp.data.data
}

export async function listFaqClusters(params: {
  page?: number
  page_size?: number
  category?: string
  keyword?: string
  is_active?: boolean
} = {}): Promise<FaqClusterListData> {
  const resp = await request.get<ApiResponse<FaqClusterListData>>('/faq/clusters', { params })
  return resp.data.data
}

export async function getFaqClusterDetail(clusterId: number): Promise<FaqClusterDetailData> {
  const resp = await request.get<ApiResponse<FaqClusterDetailData>>(`/faq/clusters/${clusterId}`)
  return resp.data.data
}

export async function updateFaqCluster(clusterId: number, payload: Partial<FaqClusterItem>): Promise<void> {
  await request.put(`/faq/clusters/${clusterId}`, payload)
}

export async function deleteFaqCluster(clusterId: number): Promise<void> {
  await request.delete(`/faq/clusters/${clusterId}`)
}

export async function mergeFaqClusters(clusterIds: number[], title?: string): Promise<{ target_id: number }> {
  const resp = await request.post<ApiResponse<{ target_id: number }>>('/faq/clusters/merge', { cluster_ids: clusterIds, title })
  return resp.data.data
}

export async function toggleBestAnswer(answerId: number): Promise<{ is_best: boolean }> {
  const resp = await request.post<ApiResponse<{ is_best: boolean }>>(`/faq/answers/${answerId}/best`)
  return resp.data.data
}

export async function upvoteAnswer(answerId: number): Promise<{ upvotes: number }> {
  const resp = await request.post<ApiResponse<{ upvotes: number }>>(`/faq/answers/${answerId}/upvote`)
  return resp.data.data
}

export async function faqSearch(query: string, topK = 10): Promise<{ results: FaqSearchResult[]; query: string }> {
  const resp = await request.post<ApiResponse<{ results: FaqSearchResult[]; query: string }>>('/faq/search', { query, top_k: topK })
  return resp.data.data
}

export type CopilotQualityMode = 'auto' | 'fast' | 'balanced' | 'quality'

export async function faqCopilot(query: string, qualityMode: CopilotQualityMode = 'auto'): Promise<FaqCopilotData> {
  const resp = await request.post<ApiResponse<FaqCopilotData>>('/faq/copilot', { query, quality_mode: qualityMode })
  return resp.data.data
}

export async function faqCopilotPanel(
  query: string,
  qualityMode: CopilotQualityMode = 'auto',
  conversationId?: string,
  channel = 'console',
): Promise<CopilotPanelData> {
  const resp = await request.post<ApiResponse<CopilotPanelData>>('/faq/copilot/panel', {
    query,
    quality_mode: qualityMode,
    conversation_id: conversationId,
    channel,
  })
  return resp.data.data
}

export async function submitCopilotFeedback(payload: {
  panel_id: number
  action: 'accepted' | 'edited' | 'rejected'
  conversation_id?: string
  channel?: string
  candidate_index?: number
  final_reply?: string
  first_response_ms?: number
  session_duration_ms?: number
  message_count?: number
}): Promise<void> {
  await request.post('/faq/copilot/feedback', payload)
}

export interface CopilotStreamCallbacks {
  onFaqs: (faqs: FaqSearchResult[]) => void
  onToken: (token: string) => void
  onDone: (latencyMs: number, requestedMode?: CopilotQualityMode, effectiveMode?: Exclude<CopilotQualityMode, 'auto'>, reason?: string) => void
  onError: (err: string) => void
}

export async function faqCopilotStream(
  query: string,
  callbacks: CopilotStreamCallbacks,
  qualityMode: CopilotQualityMode = 'auto',
): Promise<void> {
  const token = getToken()
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const resp = await fetch(`${baseURL}/faq/copilot/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ query, quality_mode: qualityMode }),
  })

  if (!resp.ok || !resp.body) {
    if (resp.status === 401) {
      callbacks.onError('登录已过期，请重新登录')
      window.location.href = '/login'
    } else {
      callbacks.onError(`请求失败 (${resp.status})`)
    }
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const msg = JSON.parse(line.slice(6))
        if (msg.type === 'faqs') callbacks.onFaqs(msg.matched_faqs || [])
        else if (msg.type === 'token') callbacks.onToken(msg.content || '')
        else if (msg.type === 'done') callbacks.onDone(
          msg.latency_ms || 0,
          msg.quality_mode_requested,
          msg.quality_mode_effective,
          msg.quality_route_reason,
        )
      } catch { /* skip malformed lines */ }
    }
  }
}

export async function getFaqStats(): Promise<FaqStatsData> {
  const resp = await request.get<ApiResponse<FaqStatsData>>('/faq/stats')
  return resp.data.data
}

export async function getCopilotEfficiency7d(): Promise<CopilotEfficiency7dData> {
  const resp = await request.get<ApiResponse<CopilotEfficiency7dData>>('/faq/copilot/efficiency-7d')
  return resp.data.data
}

export interface FaqDataQuality {
  conversations: { total: number; active: number; avg_messages: number }
  messages: {
    total: number
    patient: number
    counselor: number
    text: number
    image: number
    audio: number
    patient_ratio: number
    text_ratio: number
  }
  faq: { clusters: number; locked: number; coverage_pct: number }
  health_score: number
  warnings: string[]
}

export async function getFaqDataQuality(): Promise<FaqDataQuality> {
  const resp = await request.get<ApiResponse<FaqDataQuality>>('/faq/data-quality')
  return resp.data.data
}

export async function deleteFaqCopilotLog(logId: number): Promise<void> {
  await request.delete(`/faq/copilot/logs/${logId}`)
}

export async function batchDeleteFaqCopilotLogs(ids: number[]): Promise<{ deleted: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number }>>('/faq/copilot/logs/batch-delete', { ids })
  return resp.data.data
}

export async function clearFaqCopilotLogs(): Promise<{ deleted: number }> {
  const resp = await request.post<ApiResponse<{ deleted: number }>>('/faq/copilot/logs/clear')
  return resp.data.data
}
