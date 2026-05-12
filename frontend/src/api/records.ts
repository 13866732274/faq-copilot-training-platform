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

export interface RecordListItem {
  practice_id: number
  quiz_id: number
  quiz_title: string
  status: string
  started_at: string
  completed_at?: string | null
}

export interface RecordDetailData {
  practice_id: number
  quiz_title: string
  status: string
  dialogues: Array<{
    patient_messages: Array<{ content: string; content_type?: string }>
    standard_answer: { content: string; content_type?: string }
    standard_answers?: Array<{ content: string; content_type?: string; role?: string; sender_name?: string }>
    student_reply?: { content: string; reply_time: string } | null
  }>
  comments: Array<{ comment_id: number; admin_id?: number; admin_name: string; content: string; created_at: string }>
}

export const getMyRecords = async (params?: { page?: number; page_size?: number }) => {
  const res = await request.get<ApiResponse<PagedData<RecordListItem>>>('/records/my', { params })
  return res.data.data
}

export const getMyRecordDetail = async (practiceId: number) => {
  const res = await request.get<ApiResponse<RecordDetailData>>(`/records/my/${practiceId}`)
  return res.data.data
}
