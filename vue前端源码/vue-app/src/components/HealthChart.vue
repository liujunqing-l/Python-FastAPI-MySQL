<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { formatDate } from '../services/healthApi.js'
import { healthMetricValue } from '../services/presentation.js'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  metric: { type: String, required: true },
  title: { type: String, required: true },
  unit: { type: String, default: '' },
  color: { type: String, default: '#2dd4bf' },
  height: { type: Number, default: 250 },
})

const chartEl = ref(null)
let chart

const aliases = computed(() => {
  const map = {
    body_temperature: ['body_temperature', 'temperature'],
    wrist_temperature: ['wrist_temperature'],
    heart_rate: ['heart_rate'],
    blood_oxygen: ['blood_oxygen', 'spo2'],
    steps: ['steps', 'step_count'],
  }
  return map[props.metric] || [props.metric]
})

function timestamp(row) {
  return row?.collected_at || row?.device_time || row?.received_at || row?.measured_at || null
}

function render() {
  if (!chart || !chartEl.value) return
  const points = props.rows
    .map((row) => {
      const rawValue = healthMetricValue(row, props.metric, aliases.value)
      return { time: timestamp(row), value: rawValue === null ? null : Number(rawValue) }
    })
    .filter((point) => point.time && point.value !== null && Number.isFinite(point.value))
    .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())

  chart.setOption({
    animation: false,
    color: [props.color],
    grid: { left: 46, right: 18, top: 24, bottom: 42 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => `${value}${props.unit ? ` ${props.unit}` : ''}`,
      axisPointer: { type: 'line' },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((point) => formatDate(point.time)),
      axisLabel: { color: '#91a6c2', hideOverlap: true, fontSize: 10 },
      axisLine: { lineStyle: { color: '#2b4362' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      name: props.unit,
      nameTextStyle: { color: '#91a6c2' },
      axisLabel: { color: '#91a6c2', fontSize: 10 },
      splitLine: { lineStyle: { color: '#213650' } },
    },
    series: [{
      name: props.title,
      type: 'line',
      data: points.map((point) => point.value),
      smooth: false,
      connectNulls: false,
      showSymbol: points.length <= 40,
      symbolSize: 6,
      lineStyle: { width: 2 },
      areaStyle: { color: `${props.color}18` },
    }],
    graphic: points.length ? [] : [{
      type: 'text',
      left: 'center',
      top: 'middle',
      style: { text: '暂无测量数据', fill: '#91a6c2', fontSize: 13 },
    }],
  }, true)
}

function resize() { chart?.resize() }

onMounted(async () => {
  await nextTick()
  chart = echarts.init(chartEl.value)
  render()
  window.addEventListener('resize', resize)
})
watch(() => [props.rows, props.metric, props.color], render, { deep: true })
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="health-chart">
    <header class="health-chart__header">
      <h3>{{ title }}</h3>
      <span v-if="unit">单位：{{ unit }}</span>
    </header>
    <div ref="chartEl" class="health-chart__canvas" :style="{ height: `${height}px` }" />
  </section>
</template>

<style scoped>
.health-chart { min-width: 0; padding: 16px; background: #101d31; border: 1px solid #2b4362; border-radius: 8px; }
.health-chart__header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.health-chart__header h3 { margin: 0; color: #e9f1ff; font-size: 15px; font-weight: 600; }
.health-chart__header span { color: #91a6c2; font-size: 12px; }
.health-chart__canvas { width: 100%; min-height: 180px; }
</style>
