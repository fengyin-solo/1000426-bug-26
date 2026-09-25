<template>
  <section class="page" data-module="chemical">
    <header class="page-head">
      <div>
        <h2>药剂出入管理</h2>
        <p class="page-desc">
          维护药剂单据，围绕单据编号、药剂名称、出入数量做登记、筛选与状态流转；
          结存在确认出入库后按药剂滚动更新，作废单据自动冲回，重复提交不会多算。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="busyId !== null" @click="openCreate">登记药剂单据</button>
        <button class="btn" type="button" :disabled="loading" @click="exportRows">导出药剂出入清单</button>
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
        <span>单据状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit" :disabled="loading">查询</button>
      <button class="btn ghost" type="button" :disabled="loading" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="listError" class="error-text">
      {{ listError }}
      <button class="link" type="button" @click="reload">重试</button>
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="busyId === row.id"
              @click="runAction(action, row)"
            >
              {{ busyId === row.id && busyAction === action ? '处理中…' : action }}
            </button>
          </td>
        </tr>
        <tr v-if="!loading && !listError && !rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            {{ hasFilter ? '当前筛选条件下没有药剂单据，可重置条件或登记新单据' : '暂无药剂出入数据，可先登记药剂单据' }}
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条药剂出入记录</span>
      <span v-if="actionMessage" :class="actionOk ? 'ok-text' : 'error-text'">{{ actionMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="closeCreate">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记药剂单据</h3>
        <p class="page-desc">出入数量为正数表示入库，为负数表示出库；登记后需经审核、确认出入库才会计入结存。</p>
        <label v-for="field in createFields" :key="field" class="filter-item modal-field">
          <span>{{ field }}</span>
          <input
            v-model="createForm[field]"
            :placeholder="field === '出入数量' ? '如 100（入库）或 -20（出库）' : `请输入${field}`"
          />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" :disabled="creating" @click="closeCreate">取消</button>
          <button class="btn primary" type="submit" :disabled="creating">{{ creating ? '提交中…' : '提交登记' }}</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatItem = { label: string; value: number }

const ENDPOINT = '/api/chemical'
const columns = ["单据编号", "药剂名称", "规格型号", "出入数量", "结存数量", "供应商", "经办人员", "单据状态"]
const actions = ["审核单据", "确认出入库", "作废单据"]
const statuses = ["待审核", "已审核", "已出入库", "已作废"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatItem[]>([
  { label: '待审核单据', value: 0 },
  { label: '累计药剂出库', value: 0 },
  { label: '结存偏低药剂', value: 0 },
])
const loading = ref(false)
const listError = ref('')
const actionMessage = ref('')
const actionOk = ref(false)
const filters = reactive<Record<string, string>>({})
const statusFilter = ref('')
const filterFields = columns.slice(0, 3)

const busyId = ref<number | null>(null)
const busyAction = ref('')

const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const createFields = ["单据编号", "药剂名称", "规格型号", "出入数量", "供应商", "经办人员"]
const createForm = reactive<Record<string, string>>(Object.fromEntries(createFields.map((field) => [field, ''])))

const hasFilter = computed(() =>
  Object.values(filters).some((value) => value.trim() !== '') || statusFilter.value !== '',
)

function resetFilters() {
  for (const field of Object.keys(filters)) {
    filters[field] = ''
  }
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  for (const field of createFields) {
    createForm[field] = ''
  }
  createError.value = ''
  showCreate.value = true
}

function closeCreate() {
  if (creating.value) return
  showCreate.value = false
}

async function readMessage(response: Response, fallback: string) {
  try {
    const payload = await response.json()
    return payload?.message ?? payload?.detail ?? fallback
  } catch {
    return fallback
  }
}

async function submitCreate() {
  createError.value = ''
  creating.value = true
  try {
    const values = Object.fromEntries(
      Object.entries(createForm).map(([key, value]) => [key, value.trim()]),
    )
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '药剂单据登记失败，请稍后重试')
    }
    showCreate.value = false
    actionOk.value = true
    actionMessage.value = payload.message || '药剂单据已登记，等待审核'
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '药剂单据登记失败，请稍后重试'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  // 同一行动作串行，避免连点导致重复提交；服务端也会按状态机拦截。
  if (busyId.value !== null) return
  actionMessage.value = ''
  listError.value = ''
  busyId.value = Number(row.id)
  busyAction.value = action
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '药剂出入动作未生效，请稍后重试')
    }
    actionOk.value = true
    actionMessage.value = payload.message
    await reload()
  } catch (error) {
    actionOk.value = false
    actionMessage.value = error instanceof Error ? error.message : '药剂出入操作失败，请稍后重试'
  } finally {
    busyId.value = null
    busyAction.value = ''
  }
}

async function reload() {
  loading.value = true
  listError.value = ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim()) params.set(key, value.trim())
  }
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  try {
    const response = await request(`${ENDPOINT}${query ? `?${query}` : ''}`)
    if (!response.ok) {
      throw new Error(await readMessage(response, '药剂单据列表读取失败'))
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    // 读取失败时保留上次列表，并给出说明与重试入口，而不是静默回到空数据。
    listError.value = `${error instanceof Error ? error.message : '药剂单据列表读取失败'}，可点击重试`
  } finally {
    loading.value = false
  }
  // 卡片与列表分别请求，但共用同一结存口径；卡片失败不影响列表使用。
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      const payload = await response.json()
      stats.value = [
        { label: '待审核单据', value: Number(payload['待审核单据'] ?? 0) },
        { label: '累计药剂出库', value: Number(payload['累计药剂出库'] ?? 0) },
        { label: '结存偏低药剂', value: Number(payload['结存偏低药剂'] ?? 0) },
      ]
    }
  } catch {
    /* 统计卡片失败时保留上次数值，列表仍可正常操作 */
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 420px;
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
}
.modal-card h3 {
  margin: 0 0 6px;
}
.modal-field {
  margin: 8px 0;
}
.modal-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.ok-text {
  color: #067647;
}
.link:disabled {
  color: var(--muted);
  cursor: not-allowed;
}
</style>
