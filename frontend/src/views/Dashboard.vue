<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常；数据口径与各模块列表一致。</p>
      </div>
      <button v-if="loadFailed" class="btn primary" type="button" @click="loadOverview">重试加载</button>
    </header>

    <p v-if="loading" class="state-text">正在加载运营概览…</p>

    <div v-else-if="loadFailed" class="state-box">
      <p class="error-text">运营概览读取失败，以下数字不是最新数据，请检查后端服务后重试。</p>
    </div>

    <template v-else>
      <div class="stat-row">
        <article v-for="card in cards" :key="card.label" class="stat-card">
          <span class="stat-label">{{ card.label }}</span>
          <strong class="stat-value">{{ card.value }}</strong>
        </article>
      </div>
      <table v-if="moduleRows.length" class="data-table">
        <thead>
          <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in moduleRows" :key="row.name">
            <td>{{ row.name }}</td>
            <td>{{ row.created }}</td>
            <td>{{ row.pending }}</td>
            <td>{{ row.abnormal }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="state-box">
        <p class="state-text">暂无任何业务模块数据，可先到各业务页面登记单据。</p>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const loading = ref(false)
const loadFailed = ref(false)

async function loadOverview() {
  loading.value = true
  loadFailed.value = false
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards ?? []
    moduleRows.value = payload.modules ?? []
  } catch {
    // 失败时明确说明并重试，不再用一组假的 0 数据冒充真实概览。
    loadFailed.value = true
    cards.value = []
    moduleRows.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
</script>
