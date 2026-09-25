<template>
  <section class="page" data-module="chemical">
    <header class="page-head">
      <div>
        <h2>药剂出入管理</h2>
        <p class="page-desc">维护药剂单据，围绕单据编号、药剂名称、规格型号、出入数量做登记、筛选与状态流转；结存随确认出入库自动重算。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记药剂单据</button>
        <button class="btn" type="button" @click="exportRows">导出药剂出入清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="actionMessage" :class="actionOk ? 'notice-text' : 'error-text'" class="action-notice">
      {{ actionMessage }}
    </div>

    <p v-if="loading" class="state-text">正在加载药剂出入数据…</p>

    <template v-else>
      <table v-if="rows.length" class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td v-for="column in columns" :key="column">
              {{ formatCell(column, row[column]) }}
            </td>
            <td class="row-actions">
              <template v-if="allowedActions(String(row.status)).length">
                <button
                  v-for="action in allowedActions(String(row.status))"
                  :key="action"
                  class="link"
                  type="button"
                  :disabled="busyId === row.id"
                  @click="runAction(action, row)"
                >
                  {{ busyId === row.id ? '提交中…' : action }}
                </button>
              </template>
              <span v-else class="muted-text">终态单据，无可用动作</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else-if="loadFailed" class="state-box">
        <p class="error-text">药剂单据列表读取失败，当前展示的不是最新结存。</p>
        <button class="btn primary" type="button" @click="reload">重试加载</button>
      </div>
      <div v-else class="state-box">
        <p class="state-text">暂无符合条件的药剂出入单据{{ hasFilters ? '，可调整筛选条件或' : '，可' }}登记新单据。</p>
      </div>
    </template>

    <footer class="page-foot">
      <span>共 {{ total }} 条药剂出入记录</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stats = { pending_audit: number; consumed: number; low_stock: number }

const ENDPOINT = '/api/chemical'
const columns = ["单据编号", "药剂名称", "规格型号", "出入类型", "出入数量", "结存数量", "供应商", "经办人员", "状态"]
const statuses = ["待审核", "已审核", "已出入库", "已作废"]
// 与后端状态机保持一致：只暴露当前状态允许的动作，既保留全部既有审核动作，
// 又从界面上杜绝「确认出入库」重复提交。
const ACTION_MAP: Record<string, string[]> = {
  '待审核': ["审核单据", "作废单据"],
  '已审核': ["确认出入库", "作废单据"],
  '已出入库': ["作废单据"],
  '已作废': [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '待审核单据', value: 0 },
  { label: '累计出库量', value: 0 },
  { label: '结存偏低药剂', value: 0 },
])
const filters = ref<Record<string, string>>({})
const filterFields = ["单据编号", "药剂名称", "规格型号"]

const loading = ref(false)
const loadFailed = ref(false)
const busyId = ref<number | null>(null)
const actionMessage = ref('')
const actionOk = ref(false)
const hasFilters = computed(() =>
  Object.values(filters.value).some((value) => String(value ?? '').trim() !== '')
)

function allowedActions(status: string): string[] {
  return ACTION_MAP[status] ?? []
}

function formatCell(column: string, value: unknown): string {
  if (column === '状态') return String(value ?? '—')
  if (value === null || value === undefined || value === '') {
    // 作废单据的结存由后端置空：明确告诉用户它不参与结存，而不是显示 0 误导。
    return column === '结存数量' ? '不计入结存' : '—'
  }
  return String(value)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  actionOk.value = false
  actionMessage.value = '药剂单据登记入口尚未接入审批流，请通过后端接口登记后再执行审核动作'
}

async function runAction(action: string, row: Row) {
  // 前端再拦一次重复提交：上一个动作未返回前不允许对同一行再次提交。
  if (busyId.value !== null) return
  actionMessage.value = ''
  busyId.value = Number(row.id)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    // HTTP 200 但业务未生效（重复提交、已作废、状态不允许）时，按失败提示处理，
    // 不再当作成功刷新，避免误以为结存又算了一次。
    if (!response.ok || !payload || payload.ok === false) {
      actionOk.value = false
      actionMessage.value = payload?.message || '药剂出入动作未生效，请稍后重试'
      return
    }
    actionOk.value = true
    actionMessage.value = payload.message || '操作成功，结存已刷新'
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    actionOk.value = false
    actionMessage.value = error instanceof Error ? error.message : '药剂出入操作失败，结存未变更，可重试该动作'
  } finally {
    busyId.value = null
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = (await response.json()) as Stats
    stats.value = [
      { label: '待审核单据', value: data.pending_audit },
      { label: '累计出库量', value: data.consumed },
      { label: '结存偏低药剂', value: data.low_stock },
    ]
  } catch {
    // 卡片统计失败不阻塞列表，保留上一次数值，列表自身的错误仍会单独提示。
  }
}

async function reload() {
  loading.value = true
  loadFailed.value = false
  const params = new URLSearchParams()
  // 后端只支持一个关键字（对编号/名称/规格做模糊匹配），取第一个非空检索框。
  const keyword = ['单据编号', '药剂名称', '规格型号']
    .map((key) => String(filters.value[key] ?? '').trim())
    .find(Boolean)
  if (keyword) {
    params.set('keyword', keyword)
  }
  const statusText = String(filters.value.status ?? '').trim()
  if (statusText) {
    params.set('status', statusText)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}`)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 无数据时正常落入空态分支并给出说明，不算失败、不弹错误。
  } catch (error) {
    loadFailed.value = true
    rows.value = []
    total.value = 0
    const detail = error instanceof Error ? error.message : '网络异常'
    actionOk.value = false
    actionMessage.value = `药剂单据列表读取失败（${detail}），请检查后端服务后点击“重试加载”`
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
