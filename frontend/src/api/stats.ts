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

export interface OverviewData {
  total_quizzes: number
  total_students: number
  total_practices: number
  today_practices: number
  total_hospitals: number
  total_departments: number
}

export interface StatsTrendsData {
  dates: string[]
  new_practices: number[]
  completed: number[]
  new_students: number[]
}

export interface SystemHealthData {
  db_status: 'ok' | 'error'
  db_ping_ms: number
  active_practice_sessions: number
  pending_import_tasks: number
  audit_logs_24h: number
  slow_request_threshold_ms: number
  server_time: string
}

export const getOverviewStats = async () => {
  const res = await request.get<ApiResponse<OverviewData>>('/stats/overview')
  return res.data.data
}

export const getStatsTrends = async (params?: { days?: number; hospital_id?: number; department_id?: number }) => {
  const res = await request.get<ApiResponse<StatsTrendsData>>('/stats/trends', { params })
  return res.data.data
}

export const getSystemHealthStats = async () => {
  const res = await request.get<ApiResponse<SystemHealthData>>('/stats/system-health')
  return res.data.data
}

export interface StudentStatsItem {
  user_id: number
  username: string
  real_name: string
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  completed_count: number
  in_progress_count: number
  last_practice_time?: string | null
}

export interface QuizStatsItem {
  quiz_id: number
  title: string
  category?: string | null
  scope: 'common' | 'hospital' | 'department'
  hospital_id?: number | null
  hospital_name?: string | null
  department_id?: number | null
  department_name?: string | null
  practice_count: number
}

export interface HospitalCompareItem {
  hospital_id: number
  hospital_code: string
  hospital_name: string
  student_count: number
  hospital_quiz_count: number
  practice_count: number
  completed_count: number
  completion_rate: number
}

export const getStudentStats = async (params?: {
  hospital_id?: number
  department_id?: number
  page?: number
  page_size?: number
}) => {
  const res = await request.get<ApiResponse<PagedData<StudentStatsItem>>>('/stats/students', { params })
  return res.data.data
}

export const getQuizStats = async (params?: {
  hospital_id?: number
  department_id?: number
  page?: number
  page_size?: number
}) => {
  const res = await request.get<ApiResponse<PagedData<QuizStatsItem>>>('/stats/quizzes', { params })
  return res.data.data
}

export const getHospitalCompareStats = async (params?: { page?: number; page_size?: number }) => {
  const res = await request.get<ApiResponse<PagedData<HospitalCompareItem>>>('/stats/hospitals/compare', { params })
  return res.data.data
}

export const addPracticeComment = async (practiceId: number, content: string) => {
  const res = await request.post<ApiResponse<any>>(`/stats/practices/${practiceId}/comment`, { content })
  return res.data.data
}

export interface StudentPracticeItem {
  practice_id: number
  quiz_id: number
  quiz_title: string
  status: string
  started_at: string
  completed_at?: string | null
}

export interface StudentPracticeDetail {
  practice_id: number
  quiz_title: string
  status: string
  dialogues: Array<{
    patient_messages: Array<{ content: string; content_type?: string }>
    standard_answer: { content: string; content_type?: string }
    student_reply?: { content: string; reply_time: string } | null
  }>
  comments: Array<{ comment_id: number; admin_id?: number; admin_name: string; content: string; created_at: string }>
}

export const getStudentPractices = async (userId: number, params?: { page?: number; page_size?: number }) => {
  const res = await request.get<ApiResponse<PagedData<StudentPracticeItem>>>(`/stats/students/${userId}/practices`, {
    params,
  })
  return res.data.data
}

export const getStudentPracticeDetail = async (userId: number, practiceId: number) => {
  const res = await request.get<ApiResponse<StudentPracticeDetail>>(
    `/stats/students/${userId}/practices/${practiceId}`,
  )
  return res.data.data
}

export const updatePracticeComment = async (commentId: number, content: string) => {
  const res = await request.put<ApiResponse<any>>(`/stats/comments/${commentId}`, { content })
  return res.data.data
}

export const deletePracticeComment = async (commentId: number) => {
  const res = await request.delete<ApiResponse<any>>(`/stats/comments/${commentId}`)
  return res.data
}
