<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常；数据与各业务列表同源。</p>
      </div>
      <button class="btn" type="button" :disabled="loading" @click="loadOverview">
        {{ loading ? '刷新中…' : '刷新概览' }}
      </button>
    </header>
    <p v-if="errorMessage" class="error-text">
      {{ errorMessage }}
      <button class="link" type="button" @click="loadOverview">重试</button>
    </p>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
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
        <tr v-if="!loading && !errorMessage && !moduleRows.length">
          <td colspan="4" class="empty-state">暂无运营数据</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const loading = ref(false)
const errorMessage = ref('')

async function loadOverview() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await request('/api/overview')
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}，概览数据未更新`)
    }
    const payload = (await response.json()) as Overview
    cards.value = payload.cards ?? []
    moduleRows.value = payload.modules ?? []
  } catch (error) {
    // 失败时明确说明并保留重试入口，不再用一份虚构数据冒充真实概览。
    cards.value = []
    moduleRows.value = []
    errorMessage.value = `${error instanceof Error ? error.message : '运营概览读取失败'}，请稍后重试`
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
</script>
