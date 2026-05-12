import request from './request'

export interface MessageItem {
  sequence: number
  role: string
  content_type: string
  content: string
  sender_name: string
  original_time?: string | null
}

export interface UploadPreviewData {
  preview_id: string
  source_file: string
  patient_name?: string | null
  counselor_name?: string | null
  message_count: number
  messages: MessageItem[]
}

export interface ConfirmPayload {
  preview_id: string
  title: string
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type: 'active' | 'passive'
  category?: string
  difficulty: number
  tags?: string
  description?: string
}

export interface UpdateQuizPayload {
  title: string
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type: 'active' | 'passive'
  category?: string
  difficulty: number
  tags?: string
  description?: string
  patient_name?: string
  counselor_name?: string
}

export interface QuizMetaOptionItem {
  name: string
  count: number
}

export interface QuizMetaOptionsData {
  categories: QuizMetaOptionItem[]
  tags: QuizMetaOptionItem[]
}

export interface BatchQuizMetaUpdatePayload {
  quiz_ids?: number[]
  keyword?: string
  scope?: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type?: 'active' | 'passive'
  set_category?: string
  clear_category?: boolean
  add_tags?: string[]
  remove_tags?: string[]
  replace_tags?: string[]
  clear_tags?: boolean
}

export interface QuizMetaOperateFilters {
  scope?: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type?: 'active' | 'passive'
}

export interface BatchReparsePayload {
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type?: 'active' | 'passive'
  limit?: number
  only_legacy_or_empty_hash?: boolean
}

export interface BatchReparseResult {
  matched: number
  processed: number
  updated: number
  skipped: number
  failed: number
  detail: Array<Record<string, any>>
}

export interface BatchReparseEstimateResult {
  matched: number
  limit: number
  only_legacy_or_empty_hash: boolean
}

export interface QuizListItem {
  id: number
  title: string
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  chat_type: 'active' | 'passive'
  category?: string | null
  difficulty: number
  tags?: string | null
  patient_name?: string | null
  counselor_name?: string | null
  message_count: number
  is_active: boolean
  is_deleted?: boolean
  created_at: string
}

export interface QuizDetailData extends QuizListItem {
  description?: string | null
  source_file?: string | null
  versions?: Array<{
    id: number
    version_no: number
    source_file?: string | null
    message_count: number
    created_by?: number | null
    created_at: string
  }>
  messages: MessageItem[]
}

interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export const uploadQuizHtml = async (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  const res = await request.post<ApiResponse<UploadPreviewData>>('/quizzes/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data.data
}

export const confirmQuizImport = async (payload: ConfirmPayload) => {
  const res = await request.post<ApiResponse<{ quiz_id: number; title: string; message_count: number }>>(
    '/quizzes/confirm',
    payload,
  )
  return res.data.data
}

export const confirmQuizNewVersion = async (quizId: number, payload: ConfirmPayload) => {
  const res = await request.post<ApiResponse<{ quiz_id: number; title: string; message_count: number }>>(
    `/quizzes/${quizId}/versions/confirm`,
    payload,
  )
  return res.data.data
}

export const batchReparseQuizzes = async (payload: BatchReparsePayload) => {
  const res = await request.post<ApiResponse<BatchReparseResult>>('/quizzes/reparse/batch', payload)
  return res.data.data
}

export const estimateBatchReparseQuizzes = async (payload: BatchReparsePayload) => {
  const res = await request.post<ApiResponse<BatchReparseEstimateResult>>('/quizzes/reparse/batch/estimate', payload)
  return res.data.data
}

export const getQuizList = async (params: {
  page: number
  page_size: number
  keyword?: string
  scope?: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type?: 'active' | 'passive'
  deleted_only?: boolean
  include_deleted?: boolean
}) => {
  const res = await request.get<
    ApiResponse<{ items: QuizListItem[]; total: number; page: number; page_size: number }>
  >('/quizzes', { params })
  return res.data.data
}

export const getQuizDetail = async (id: number) => {
  const res = await request.get<ApiResponse<QuizDetailData>>(`/quizzes/${id}`)
  return res.data.data
}

export const softDeleteQuiz = async (id: number) => {
  const res = await request.delete<ApiResponse<null>>(`/quizzes/${id}`)
  return res.data
}

export const hardDeleteQuiz = async (id: number) => {
  const res = await request.delete<ApiResponse<null>>(`/quizzes/${id}`, {
    params: { hard: true },
  })
  return res.data
}

export const restoreQuiz = async (id: number) => {
  const res = await request.post<ApiResponse<null>>(`/quizzes/${id}/restore`)
  return res.data
}

export const updateQuiz = async (id: number, payload: UpdateQuizPayload) => {
  const res = await request.put<ApiResponse<{ quiz_id: number; title: string }>>(`/quizzes/${id}`, payload)
  return res.data.data
}

export const getQuizMetaOptions = async (params?: {
  scope?: 'common' | 'hospital' | 'department'
  hospital_id?: number
  department_id?: number
  chat_type?: 'active' | 'passive'
}) => {
  const res = await request.get<ApiResponse<QuizMetaOptionsData>>('/quizzes/meta/options', { params })
  return res.data.data
}

export const batchUpdateQuizMeta = async (payload: BatchQuizMetaUpdatePayload) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/batch/meta/update', payload)
  return res.data.data
}

export const renameQuizCategory = async (
  payload: QuizMetaOperateFilters & { old_name: string; new_name: string },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/category/rename', payload)
  return res.data.data
}

export const mergeQuizCategories = async (
  payload: QuizMetaOperateFilters & { source_names: string[]; target_name: string },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/category/merge', payload)
  return res.data.data
}

export const deleteQuizCategories = async (
  payload: QuizMetaOperateFilters & { names: string[] },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/category/delete', payload)
  return res.data.data
}

export const renameQuizTag = async (
  payload: QuizMetaOperateFilters & { old_name: string; new_name: string },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/tag/rename', payload)
  return res.data.data
}

export const mergeQuizTags = async (
  payload: QuizMetaOperateFilters & { source_names: string[]; target_name: string },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/tag/merge', payload)
  return res.data.data
}

export const deleteQuizTags = async (
  payload: QuizMetaOperateFilters & { names: string[] },
) => {
  const res = await request.post<ApiResponse<{ matched: number; updated: number }>>('/quizzes/meta/tag/delete', payload)
  return res.data.data
}
