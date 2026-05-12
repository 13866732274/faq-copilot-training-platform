import request from './request'

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PagedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface PracticeQuizItem {
  id: number
  title: string
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  chat_type: 'active' | 'passive'
  category?: string | null
  tags?: string | null
  difficulty: number
  message_count: number
  patient_name?: string | null
  counselor_name?: string | null
}

export interface PracticeMessage {
  id: number
  role: string
  content_type: string
  content: string
  sender_name?: string | null
  original_time?: string | null
}

export interface NextData {
  messages: PracticeMessage[]
  need_reply: boolean
  reply_to_message_id?: number | null
  is_last: boolean
}

export interface PracticeHistoryData {
  messages: PracticeMessage[]
}

export interface ReviewDialogue {
  patient_messages: PracticeMessage[]
  standard_answer: PracticeMessage
  standard_answers?: PracticeMessage[]
  student_reply?: { content: string; reply_time: string } | null
}

export interface PracticeAiScoreData {
  practice_id: number
  overall_score: number
  completion_rate: number
  avg_reply_length: number
  empathy_hits: number
  suggestions: string[]
  dimension_scores?: Record<string, number>
  deduction_reasons?: string[]
  llm_audit?: {
    enabled?: boolean
    provider?: string
    model?: string
    status?: string
    latency_ms?: number
    scores?: Record<string, number>
    overall?: number
    deduction_reasons?: string[]
    highlights?: string[]
    summary?: string
    fusion_weights?: { rule: number; llm: number }
    error?: string
    hint?: string
  } | null
}

export interface PracticeDashboardData {
  total_quizzes: number
  completed_quizzes: number
  total_practices: number
  this_week_practices: number
  streak_days: number
  avg_rounds: number
  weekly_heatmap: Array<{ date: string; count: number }>
  recent_practices: Array<{
    practice_id: number
    quiz_id: number
    quiz_title: string
    status: 'in_progress' | 'completed'
    started_at: string
    completed_at?: string | null
  }>
  in_progress_count: number
  last_in_progress?: {
    practice_id: number
    quiz_id: number
    quiz_title: string
    started_at: string
  } | null
}

export interface PracticeFaqMatchedItem {
  cluster_id: number
  title: string
  summary?: string | null
  category?: string | null
  representative_question?: string | null
  best_answer?: string | null
  question_count: number
  answer_count: number
  similarity: number
}

export interface PracticeFaqCopilotData {
  recommended_reply: string
  confidence: number
  matched_faqs: PracticeFaqMatchedItem[]
  latency_ms: number
  quality_mode_requested: PracticeCopilotQualityMode
  quality_mode_effective: Exclude<PracticeCopilotQualityMode, 'auto'>
  quality_route_reason?: string
}

export type PracticeCopilotQualityMode = 'auto' | 'fast' | 'balanced' | 'quality'

export interface PracticeFaqSearchData {
  results: PracticeFaqMatchedItem[]
  latency_ms: number
}

export interface PracticeFaqClusterItem {
  cluster_id: number
  title: string
  category?: string | null
  summary?: string | null
  representative_question?: string | null
  best_answer?: string | null
  question_count: number
  answer_count: number
}

export interface PracticeFaqClusterListData {
  items: PracticeFaqClusterItem[]
  total: number
  page: number
  page_size: number
  categories: string[]
}

export const getAvailablePractices = async (params?: {
  chat_type?: 'active' | 'passive'
  keyword?: string
  category?: string
  tag?: string
  page?: number
  page_size?: number
}) => {
  const res = await request.get<ApiResponse<PagedData<PracticeQuizItem>>>('/practice/available', { params })
  return res.data.data
}

export const getMyPracticeDashboard = async () => {
  const res = await request.get<ApiResponse<PracticeDashboardData>>('/practice/my-dashboard')
  return res.data.data
}

export const startPractice = async (quiz_id: number) => {
  const res = await request.post<ApiResponse<{ practice_id: number }>>('/practice/start', { quiz_id })
  return res.data.data
}

export const startRandomPractice = async (params?: {
  chat_type?: 'active' | 'passive'
  keyword?: string
  category?: string
  tag?: string
}) => {
  const res = await request.post<ApiResponse<{ practice_id: number }>>('/practice/start-random', params || {})
  return res.data.data
}

export const getAvailablePracticeOptions = async (params?: {
  chat_type?: 'active' | 'passive'
  keyword?: string
}) => {
  const res = await request.get<
    ApiResponse<{
      categories: Array<{ name: string; count: number }>
      tags: Array<{ name: string; count: number }>
    }>
  >('/practice/available/options', { params })
  return res.data.data
}

export const nextPractice = async (practiceId: number) => {
  const res = await request.get<ApiResponse<NextData>>(`/practice/${practiceId}/next`)
  return res.data.data
}

export const getPracticeHistory = async (practiceId: number) => {
  const res = await request.get<ApiResponse<PracticeHistoryData>>(`/practice/${practiceId}/history`)
  return res.data.data
}

export const replyPractice = async (practiceId: number, messageId: number, content: string) => {
  const res = await request.post<ApiResponse<any>>(`/practice/${practiceId}/reply`, {
    message_id: messageId,
    content,
  })
  return res.data.data
}

export const completePractice = async (practiceId: number) => {
  const res = await request.post<ApiResponse<any>>(`/practice/${practiceId}/complete`)
  return res.data.data
}

export const reviewPractice = async (practiceId: number) => {
  const res = await request.get<
    ApiResponse<{
      quiz_title: string
      dialogues: ReviewDialogue[]
      comments: Array<{ comment_id: number; admin_name: string; content: string; created_at: string }>
    }>
  >(
    `/practice/${practiceId}/review`,
  )
  return res.data.data
}

export const getPracticeAiScore = async (practiceId: number) => {
  const res = await request.get<ApiResponse<PracticeAiScoreData>>(`/practice/${practiceId}/ai-score`)
  return res.data.data
}

export const practiceFaqCopilot = async (
  query: string,
  quality_mode: PracticeCopilotQualityMode = 'auto',
) => {
  const res = await request.post<ApiResponse<PracticeFaqCopilotData>>('/practice/faq/copilot', { query, quality_mode })
  return res.data.data
}

export const practiceFaqSearch = async (query: string, top_k = 10) => {
  const res = await request.post<ApiResponse<PracticeFaqSearchData>>('/practice/faq/search', { query, top_k })
  return res.data.data
}

export const getPracticeFaqClusters = async (params?: {
  keyword?: string
  category?: string
  page?: number
  page_size?: number
}) => {
  const res = await request.get<ApiResponse<PracticeFaqClusterListData>>('/practice/faq/clusters', { params })
  return res.data.data
}
