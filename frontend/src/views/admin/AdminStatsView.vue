<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Document, OfficeBuilding, TrendCharts, UserFilled } from '@element-plus/icons-vue'
import {
  getHospitalCompareStats,
  getQuizStats,
  getStudentPracticeDetail,
  getStudentPractices,
  getStudentStats,
  type HospitalCompareItem,
  type QuizStatsItem,
  type StudentPracticeDetail,
  type StudentPracticeItem,
  type StudentStatsItem,
} from '../../api/stats'
import { getHospitals, type HospitalItem } from '../../api/hospital'
import { getDepartments, type DepartmentItem } from '../../api/department'
import { useUserStore } from '../../stores/user'
import MessageContent from '../../components/chat/MessageContent.vue'
import MetricCardsPanel, { type MetricCardItem } from '../../components/admin/MetricCardsPanel.vue'
import AdminTableSkeleton from '../../components/admin/AdminTableSkeleton.vue'
import {
  DRAWER_DESKTOP_SIZE,
  UI_TEXT,
  buildPositionText,
  createDebouncedFn,
  getDrawerSize,
} from '../../composables/useUiStandards'

const userStore = useUserStore()
const loadingStudents = ref(false)
const loadingQuizzes = ref(false)
const loadingCompare = ref(false)
const students = ref<StudentStatsItem[]>([])
const quizzes = ref<QuizStatsItem[]>([])
const hospitalCompare = ref<HospitalCompareItem[]>([])
const hospitals = ref<HospitalItem[]>([])
const departments = ref<DepartmentItem[]>([])
const isSuperAdmin = ref(false)
const selectedHospitalId = ref<number | undefined>(undefined)
const selectedDepartmentId = ref<number | undefined>(undefined)
const isMobile = ref(false)
type StatsTabKey = 'student' | 'quiz' | 'compare'
const activeTab = ref<StatsTabKey>('student')
const studentPager = reactive({ page: 1, page_size: 10, total: 0 })
const quizPager = reactive({ page: 1, page_size: 10, total: 0 })
const comparePager = reactive({ page: 1, page_size: 10, total: 0 })

const studentDrawerVisible = ref(false)
const studentDrawerLoading = ref(false)
const selectedStudent = ref<StudentStatsItem | null>(null)
const studentPractices = ref<StudentPracticeItem[]>([])
const studentPracticePager = reactive({ page: 1, page_size: 10, total: 0 })
const selectedPracticeId = ref<number | null>(null)
const selectedPracticeDetail = ref<StudentPracticeDetail | null>(null)
const practiceDetailLoading = ref(false)
const statsRefreshTick = ref(0)
const metricLoading = computed(
  () => loadingStudents.value || loadingQuizzes.value || loadingCompare.value,
)

const departmentOptionsByHospital = computed(() => {
  if (!selectedHospitalId.value) return departments.value
  return departments.value.filter((d) => d.hospital_id === selectedHospitalId.value)
})

const currentQuizPracticeTotal = computed(() =>
  quizzes.value.reduce((sum, item) => sum + (item.practice_count || 0), 0),
)
const currentHospitalCompletedTotal = computed(() =>
  hospitalCompare.value.reduce((sum, item) => sum + (item.completed_count || 0), 0),
)
const metricItems = computed<MetricCardItem[]>(() => [
  {
    key: 'student_total',
    label: '咨询员人数（筛选后）',
    value: studentPager.total,
    hint: '当前条件下的咨询员规模',
    tone: 'info',
    icon: UserFilled,
  },
  {
    key: 'quiz_total',
    label: '案例总数（筛选后）',
    value: quizPager.total,
    hint: '当前条件下的案例范围',
    tone: 'primary',
    icon: Document,
  },
  {
    key: 'hospital_total',
    label: '医院维度记录',
    value: comparePager.total,
    hint: '医院对比统计条目数',
    tone: 'warning',
    icon: OfficeBuilding,
  },
  {
    key: 'quiz_practice_total',
    label: '当前页训练次数',
    value: currentQuizPracticeTotal.value,
    hint: '案例排行页当前页合计',
    tone: 'success',
    icon: DataAnalysis,
  },
  {
    key: 'hospital_completed_total',
    label: '当前页完成次数',
    value: currentHospitalCompletedTotal.value,
    hint: '医院对比页当前页合计',
    tone: 'danger',
    icon: TrendCharts,
  },
])
const statsTabOptions = computed<Array<{ key: StatsTabKey; label: string; hint: string; total: number }>>(() => [
  { key: 'student', label: '咨询员训练统计', hint: '咨询员训练概览', total: studentPager.total },
  { key: 'quiz', label: '案例训练排行', hint: '案例热度排行', total: quizPager.total },
  { key: 'compare', label: '医院对比', hint: '跨院数据对比', total: comparePager.total },
])

const studentScopeText = (row: StudentStatsItem) => `${row.hospital_name || '-'} / ${row.department_name || '-'}`

const quizSourceText = (row: QuizStatsItem) => {
  if (row.scope === 'common') return '通用案例库'
  if (row.scope === 'department') return `科室专属${row.department_name ? `（${row.department_name}）` : ''}`
  return `医院专属${row.hospital_name ? `（${row.hospital_name}）` : ''}`
}

const practiceStatusText = (status: string) => {
  if (status === 'completed') return '已完成'
  if (status === 'in_progress') return '进行中'
  return status
}

const currentStudentIndex = computed(() => {
  if (!selectedStudent.value) return -1
  return students.value.findIndex((s) => s.user_id === selectedStudent.value?.user_id)
})
const currentStudentGlobalIndex = computed(() => {
  if (currentStudentIndex.value < 0) return -1
  return (studentPager.page - 1) * studentPager.page_size + currentStudentIndex.value
})

const canViewStudentPrev = computed(() => currentStudentGlobalIndex.value > 0)
const canViewStudentNext = computed(() => {
  return currentStudentGlobalIndex.value >= 0 && currentStudentGlobalIndex.value < studentPager.total - 1
})
const studentPositionText = computed(() => buildPositionText(currentStudentGlobalIndex.value, studentPager.total))

const buildScopeParams = () => ({
  hospital_id: selectedHospitalId.value,
  department_id: selectedDepartmentId.value,
})

const loadStudents = async () => {
  loadingStudents.value = true
  try {
    const data = await getStudentStats({
      ...buildScopeParams(),
      page: studentPager.page,
      page_size: studentPager.page_size,
    })
    students.value = data.items
    studentPager.total = data.total
  } finally {
    loadingStudents.value = false
  }
}

const loadQuizzes = async () => {
  loadingQuizzes.value = true
  try {
    const data = await getQuizStats({
      ...buildScopeParams(),
      page: quizPager.page,
      page_size: quizPager.page_size,
    })
    quizzes.value = data.items
    quizPager.total = data.total
  } finally {
    loadingQuizzes.value = false
  }
}

const loadHospitalCompare = async () => {
  loadingCompare.value = true
  try {
    const data = await getHospitalCompareStats({
      page: comparePager.page,
      page_size: comparePager.page_size,
    })
    hospitalCompare.value = data.items
    comparePager.total = data.total
  } finally {
    loadingCompare.value = false
  }
}

const load = async () => {
  try {
    await Promise.all([loadStudents(), loadQuizzes(), loadHospitalCompare()])
    statsRefreshTick.value += 1
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取统计失败')
  }
}

const refreshStats = async () => {
  triggerFilterRefresh.cancel()
  studentPager.page = 1
  quizPager.page = 1
  comparePager.page = 1
  await load()
}

const triggerFilterRefresh = createDebouncedFn(() => {
  refreshStats()
}, 300)

const onHospitalFilterChange = () => {
  selectedDepartmentId.value = undefined
}

const onStudentPageChange = () => loadStudents()
const onQuizPageChange = () => loadQuizzes()
const onComparePageChange = () => loadHospitalCompare()
const onStudentPracticePageChange = () => loadStudentPractices()

const loadHospitals = async () => {
  try {
    hospitals.value = await getHospitals({ active_only: true })
  } catch {
    hospitals.value = []
  }
}

const loadDepartments = async () => {
  try {
    departments.value = await getDepartments({ active_only: true })
  } catch {
    departments.value = []
  }
}

const openStudentDrawer = async (row: StudentStatsItem) => {
  selectedStudent.value = row
  studentDrawerVisible.value = true
  selectedPracticeId.value = null
  selectedPracticeDetail.value = null
  studentPracticePager.page = 1
  await loadStudentPractices()
}

const loadStudentPractices = async () => {
  if (!selectedStudent.value) return
  studentDrawerLoading.value = true
  try {
    const data = await getStudentPractices(selectedStudent.value.user_id, {
      page: studentPracticePager.page,
      page_size: studentPracticePager.page_size,
    })
    studentPractices.value = data.items
    studentPracticePager.total = data.total
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取咨询员训练记录失败')
  } finally {
    studentDrawerLoading.value = false
  }
}

const loadStudentPracticeDetail = async (practiceId: number) => {
  if (!selectedStudent.value) return
  selectedPracticeId.value = practiceId
  practiceDetailLoading.value = true
  try {
    selectedPracticeDetail.value = await getStudentPracticeDetail(selectedStudent.value.user_id, practiceId)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '获取训练详情失败')
  } finally {
    practiceDetailLoading.value = false
  }
}

const openStudentByGlobalIndex = async (globalIndex: number) => {
  if (globalIndex < 0 || globalIndex >= studentPager.total) return
  const targetPage = Math.floor(globalIndex / studentPager.page_size) + 1
  const targetIndexInPage = globalIndex % studentPager.page_size
  if (targetPage !== studentPager.page) {
    studentPager.page = targetPage
    await loadStudents()
  }
  const target = students.value[targetIndexInPage]
  if (!target) return
  await openStudentDrawer(target)
}

const viewPrevStudent = async () => {
  if (!canViewStudentPrev.value || studentDrawerLoading.value) return
  await openStudentByGlobalIndex(currentStudentGlobalIndex.value - 1)
}

const viewNextStudent = async () => {
  if (!canViewStudentNext.value || studentDrawerLoading.value) return
  await openStudentByGlobalIndex(currentStudentGlobalIndex.value + 1)
}

const updateViewport = () => {
  isMobile.value = window.innerWidth < 992
}

onMounted(() => {
  isSuperAdmin.value = userStore.user?.role === 'super_admin'
  if (!isSuperAdmin.value) {
    selectedHospitalId.value = userStore.user?.hospital_id || undefined
    selectedDepartmentId.value = userStore.user?.department_id || undefined
  }
  updateViewport()
  window.addEventListener('resize', updateViewport)
  Promise.all([loadHospitals(), loadDepartments()]).then(load)
})

onBeforeUnmount(() => {
  triggerFilterRefresh.cancel()
  window.removeEventListener('resize', updateViewport)
})

watch([selectedHospitalId, selectedDepartmentId], () => {
  triggerFilterRefresh()
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="admin-card-header">
        <strong class="admin-card-title">统计面板</strong>
      </div>
    </template>
    <MetricCardsPanel :items="metricItems" :loading="metricLoading" :refresh-tick="statsRefreshTick" />
    <div class="admin-toolbar">
      <el-select
        v-model="selectedHospitalId"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="按医院查看"
        style="width: 220px"
        @change="onHospitalFilterChange"
      >
        <el-option v-for="h in hospitals" :key="h.id" :label="h.name" :value="h.id" />
      </el-select>
      <el-select
        v-model="selectedDepartmentId"
        :disabled="!isSuperAdmin"
        clearable
        placeholder="按科室查看"
        style="width: 220px"
      >
        <el-option v-for="d in departmentOptionsByHospital" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-button type="primary" @click="refreshStats">刷新统计</el-button>
    </div>

    <div class="stats-switcher-wrap">
      <div class="stats-switcher" role="tablist" aria-label="统计维度切换">
        <button
          v-for="item in statsTabOptions"
          :key="item.key"
          type="button"
          role="tab"
          class="stats-switch-item"
          :class="{ active: activeTab === item.key }"
          :aria-selected="activeTab === item.key"
          @click="activeTab = item.key"
        >
          <span class="stats-switch-label">{{ item.label }}</span>
          <span class="stats-switch-hint">{{ item.hint }}</span>
          <el-tag size="small" effect="plain" :type="activeTab === item.key ? 'success' : 'info'">{{ item.total }}</el-tag>
        </button>
      </div>
    </div>

    <transition name="stats-panel-fade" mode="out-in">
      <div v-if="activeTab === 'student'" :key="activeTab" class="stats-panel">
        <template v-if="!isMobile && loadingStudents">
          <AdminTableSkeleton :is-mobile="false" :rows="8" />
        </template>
        <template v-else-if="!isMobile && students.length">
          <el-table class="admin-list-table" :data="students" border stripe>
            <el-table-column prop="real_name" label="姓名" width="120" />
            <el-table-column prop="username" label="用户名" width="120" />
            <el-table-column label="所属范围" min-width="200">
              <template #default="{ row }">{{ studentScopeText(row) }}</template>
            </el-table-column>
            <el-table-column prop="completed_count" label="已完成" width="100" />
            <el-table-column prop="in_progress_count" label="进行中" width="100" />
            <el-table-column prop="last_practice_time" label="最后练习时间" min-width="180" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="openStudentDrawer(row)">查看详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <template v-else-if="!isMobile">
          <el-empty
            class="admin-empty stats-empty"
            description="暂无咨询员统计数据，可调整筛选条件后重试"
            :image-size="96"
          />
        </template>
        <div v-else class="mobile-list">
          <template v-if="loadingStudents">
            <AdminTableSkeleton :is-mobile="true" :mobile-rows="3" />
          </template>
          <el-empty
            v-else-if="!students.length"
            class="admin-empty stats-empty"
            description="暂无咨询员统计数据，可调整筛选条件后重试"
            :image-size="90"
          />
          <el-card v-for="row in students" :key="row.user_id" class="mobile-item" shadow="never">
            <div class="mobile-title-row">
              <strong>{{ row.real_name }}</strong>
              <span class="meta">@{{ row.username }}</span>
            </div>
            <div class="meta">所属范围：{{ studentScopeText(row) }}</div>
            <div class="meta">已完成：{{ row.completed_count }} | 进行中：{{ row.in_progress_count }}</div>
            <div class="meta">最后练习：{{ row.last_practice_time || '-' }}</div>
            <div class="actions">
              <el-button link type="primary" @click="openStudentDrawer(row)">查看详情</el-button>
            </div>
          </el-card>
        </div>
        <div class="admin-pager">
          <el-pagination
            v-model:current-page="studentPager.page"
            v-model:page-size="studentPager.page_size"
            :page-sizes="[10, 20, 50, 100]"
            :layout="isMobile ? 'sizes, prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
            :small="isMobile"
            :total="studentPager.total"
            @size-change="onStudentPageChange"
            @current-change="onStudentPageChange"
          />
        </div>
      </div>

      <div v-else-if="activeTab === 'quiz'" :key="activeTab" class="stats-panel">
        <template v-if="!isMobile && loadingQuizzes">
          <AdminTableSkeleton :is-mobile="false" :rows="8" />
        </template>
        <template v-else-if="!isMobile && quizzes.length">
          <el-table class="admin-list-table" :data="quizzes" border stripe>
            <el-table-column prop="quiz_id" label="编号" width="90" />
            <el-table-column prop="title" label="案例标题" min-width="260" />
            <el-table-column label="案例库来源" width="200">
              <template #default="{ row }">{{ quizSourceText(row) }}</template>
            </el-table-column>
            <el-table-column prop="practice_count" label="训练次数" width="120" />
          </el-table>
        </template>
        <template v-else-if="!isMobile">
          <el-empty
            class="admin-empty stats-empty"
            description="暂无案例排行数据，可调整筛选条件后重试"
            :image-size="96"
          />
        </template>
        <div v-else class="mobile-list">
          <template v-if="loadingQuizzes">
            <AdminTableSkeleton :is-mobile="true" :mobile-rows="3" />
          </template>
          <el-empty
            v-else-if="!quizzes.length"
            class="admin-empty stats-empty"
            description="暂无案例排行数据，可调整筛选条件后重试"
            :image-size="90"
          />
          <el-card v-for="row in quizzes" :key="row.quiz_id" class="mobile-item" shadow="never">
            <div class="mobile-title-row">
              <strong>{{ row.title }}</strong>
              <el-tag size="small" type="info">编号 {{ row.quiz_id }}</el-tag>
            </div>
            <div class="meta">来源：{{ quizSourceText(row) }}</div>
            <div class="meta">训练次数：{{ row.practice_count }}</div>
          </el-card>
        </div>
        <div class="admin-pager">
          <el-pagination
            v-model:current-page="quizPager.page"
            v-model:page-size="quizPager.page_size"
            :page-sizes="[10, 20, 50, 100]"
            :layout="isMobile ? 'sizes, prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
            :small="isMobile"
            :total="quizPager.total"
            @size-change="onQuizPageChange"
            @current-change="onQuizPageChange"
          />
        </div>
      </div>

      <div v-else :key="activeTab" class="stats-panel">
        <template v-if="!isMobile && loadingCompare">
          <AdminTableSkeleton :is-mobile="false" :rows="8" />
        </template>
        <template v-else-if="!isMobile && hospitalCompare.length">
          <el-table class="admin-list-table" :data="hospitalCompare" border stripe>
            <el-table-column prop="hospital_name" label="医院" min-width="160" />
            <el-table-column prop="student_count" label="咨询员数" width="100" />
            <el-table-column prop="hospital_quiz_count" label="专属案例数" width="110" />
            <el-table-column prop="practice_count" label="训练次数" width="110" />
            <el-table-column prop="completed_count" label="完成次数" width="110" />
            <el-table-column label="完成率" width="110">
              <template #default="{ row }">{{ row.completion_rate }}%</template>
            </el-table-column>
          </el-table>
        </template>
        <template v-else-if="!isMobile">
          <el-empty
            class="admin-empty stats-empty"
            description="暂无医院对比数据，可调整筛选条件后重试"
            :image-size="96"
          />
        </template>
        <div v-else class="mobile-list">
          <template v-if="loadingCompare">
            <AdminTableSkeleton :is-mobile="true" :mobile-rows="3" />
          </template>
          <el-empty
            v-else-if="!hospitalCompare.length"
            class="admin-empty stats-empty"
            description="暂无医院对比数据，可调整筛选条件后重试"
            :image-size="90"
          />
          <el-card v-for="row in hospitalCompare" :key="row.hospital_id" class="mobile-item" shadow="never">
            <div class="mobile-title-row">
              <strong>{{ row.hospital_name }}</strong>
              <el-tag size="small" type="info">{{ row.completion_rate }}%</el-tag>
            </div>
            <div class="meta">咨询员：{{ row.student_count }} | 专属案例：{{ row.hospital_quiz_count }}</div>
            <div class="meta">练习：{{ row.practice_count }} | 完成：{{ row.completed_count }}</div>
          </el-card>
        </div>
        <div class="admin-pager">
          <el-pagination
            v-model:current-page="comparePager.page"
            v-model:page-size="comparePager.page_size"
            :page-sizes="[10, 20, 50, 100]"
            :layout="isMobile ? 'sizes, prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
            :small="isMobile"
            :total="comparePager.total"
            @size-change="onComparePageChange"
            @current-change="onComparePageChange"
          />
        </div>
      </div>
    </transition>

    <el-drawer
      v-model="studentDrawerVisible"
      class="admin-smooth-drawer"
      :size="getDrawerSize(isMobile, DRAWER_DESKTOP_SIZE.detail)"
      direction="rtl"
      :with-header="false"
    >
      <div class="drawer-body admin-drawer-body" v-loading="studentDrawerLoading">
        <div v-if="selectedStudent" class="drawer-title admin-drawer-header">
          <strong>
            咨询员详情 - {{ selectedStudent.real_name }}
            <span v-if="studentPositionText">（{{ studentPositionText }}）</span>
          </strong>
          <div class="drawer-actions admin-drawer-actions">
            <el-button :disabled="!canViewStudentPrev || studentDrawerLoading" @click="viewPrevStudent">上一位</el-button>
            <el-button :disabled="!canViewStudentNext || studentDrawerLoading" @click="viewNextStudent">下一位</el-button>
            <el-button link type="primary" @click="studentDrawerVisible = false">{{ UI_TEXT.close }}</el-button>
          </div>
        </div>

        <el-descriptions v-if="selectedStudent" :column="isMobile ? 1 : 2" border>
          <el-descriptions-item label="姓名">{{ selectedStudent.real_name }}</el-descriptions-item>
          <el-descriptions-item label="用户名">{{ selectedStudent.username }}</el-descriptions-item>
          <el-descriptions-item label="所属范围">{{ studentScopeText(selectedStudent) }}</el-descriptions-item>
          <el-descriptions-item label="最后练习">{{ selectedStudent.last_practice_time || '-' }}</el-descriptions-item>
          <el-descriptions-item label="已完成">{{ selectedStudent.completed_count }}</el-descriptions-item>
          <el-descriptions-item label="进行中">{{ selectedStudent.in_progress_count }}</el-descriptions-item>
        </el-descriptions>

        <el-card shadow="never" class="section-card">
          <template #header>
            <div class="admin-card-header">
              <strong class="admin-card-title">训练记录</strong>
            </div>
          </template>
          <el-empty v-if="!studentPractices.length && !studentDrawerLoading" class="admin-empty" description="暂无训练记录" />
          <el-table v-else-if="!isMobile" :data="studentPractices" border stripe>
            <el-table-column prop="practice_id" label="训练编号" width="100" />
            <el-table-column prop="quiz_title" label="案例标题" min-width="240" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">{{ practiceStatusText(row.status) }}</template>
            </el-table-column>
            <el-table-column prop="started_at" label="开始时间" width="180" />
            <el-table-column prop="completed_at" label="完成时间" width="180" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button link type="primary" @click="loadStudentPracticeDetail(row.practice_id)">查看对话</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="mobile-list">
            <el-card v-for="row in studentPractices" :key="row.practice_id" class="mobile-item" shadow="never">
              <div class="mobile-title-row">
                <strong>{{ row.quiz_title }}</strong>
                <el-tag size="small" :type="row.status === 'completed' ? 'success' : 'warning'">
                  {{ practiceStatusText(row.status) }}
                </el-tag>
              </div>
              <div class="meta">开始：{{ row.started_at }}</div>
              <div class="meta">完成：{{ row.completed_at || '-' }}</div>
              <div class="actions">
                <el-button link type="primary" @click="loadStudentPracticeDetail(row.practice_id)">查看对话</el-button>
              </div>
            </el-card>
          </div>

          <div class="admin-pager">
            <el-pagination
              v-model:current-page="studentPracticePager.page"
              v-model:page-size="studentPracticePager.page_size"
              :page-sizes="[10, 20, 50, 100]"
              :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
              :small="isMobile"
              :total="studentPracticePager.total"
              @size-change="onStudentPracticePageChange"
              @current-change="onStudentPracticePageChange"
            />
          </div>
        </el-card>

        <el-card shadow="never" class="section-card" v-loading="practiceDetailLoading">
          <template #header>
            <div class="admin-card-header">
              <strong class="admin-card-title">对话详情</strong>
            </div>
          </template>
          <el-empty v-if="!selectedPracticeDetail" class="admin-empty" description="请选择一条训练记录查看对话" />
          <template v-else>
            <div v-for="(round, idx) in selectedPracticeDetail.dialogues" :key="idx" class="round">
              <h4>第 {{ idx + 1 }} 轮</h4>
              <div v-for="(m, i) in round.patient_messages" :key="i">
                患者：<MessageContent :content-type="m.content_type || 'text'" :content="m.content" />
              </div>
              <div class="compare">
                <div class="col std">
                  <div class="head">标准答案</div>
                  <div>{{ round.standard_answer.content }}</div>
                </div>
                <div class="col stu">
                  <div class="head">咨询员回复</div>
                  <div>{{ round.student_reply?.content || '（未作答）' }}</div>
                </div>
              </div>
            </div>
          </template>
        </el-card>
      </div>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.stats-switcher-wrap {
  margin-bottom: 12px;
  overflow-x: auto;
}

.stats-switcher {
  display: inline-flex;
  gap: 8px;
  padding: 6px;
  border: 1px solid var(--ui-border-soft);
  border-radius: 14px;
  background:
    radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--el-color-primary-light-9) 42%, transparent 58%), transparent 42%),
    var(--ui-surface-1);
}

.stats-switch-item {
  min-width: 180px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
  color: var(--el-text-color-regular);
  padding: 8px 10px;
  display: grid;
  justify-items: flex-start;
  gap: 4px;
  transition: all 0.24s ease;
}

.stats-switch-item:hover {
  border-color: color-mix(in srgb, var(--el-color-primary) 32%, transparent 68%);
  transform: translateY(-1px);
}

.stats-switch-item.active {
  border-color: color-mix(in srgb, var(--el-color-primary) 32%, transparent 68%);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 72%, transparent 28%);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--el-color-primary) 18%, transparent 82%),
    0 8px 18px color-mix(in srgb, var(--el-color-primary) 14%, transparent 86%);
}

.stats-switch-label {
  font-size: 14px;
  font-weight: 700;
}

.stats-switch-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.stats-panel {
  animation: statsPanelIn 220ms ease;
}

@keyframes statsPanelIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.stats-panel-fade-enter-active,
.stats-panel-fade-leave-active {
  transition: opacity 0.18s ease;
}

.stats-panel-fade-enter-from,
.stats-panel-fade-leave-to {
  opacity: 0;
}

.mobile-list {
  display: grid;
  gap: 10px;
}

.mobile-item {
  border: 1px solid var(--el-border-color-light);
}

.mobile-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.meta {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.section-card {
  margin-top: 12px;
}

.stats-empty {
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
  background: var(--el-fill-color-light);
  margin-top: 4px;
}

.round {
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--el-border-color);
}

.compare {
  margin-top: 8px;
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr 1fr;
}

.col {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 8px;
}

.col .head {
  font-weight: 600;
  margin-bottom: 4px;
}

@media (max-width: 768px) {
  .stats-switcher {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
    min-width: 620px;
  }
  .stats-switch-item {
    min-width: 0;
    padding: 8px;
  }
  .stats-switch-label {
    font-size: 13px;
  }
  .compare {
    grid-template-columns: 1fr;
  }
}
</style>
