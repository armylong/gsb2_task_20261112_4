<template>
  <div>
    <el-card class="section-block">
      <template #header>发起对账</template>
      <el-form inline>
        <el-form-item label="基于 Run">
          <el-select v-model="runId" style="width: 260px" placeholder="选择已完成的清洗任务"
            @change="syncLabels">
            <el-option v-for="r in runs" :key="r.id"
              :label="`Run #${r.id}（v${r.rule_version}，${r.stats?.kept_rows ?? 0} 条）`"
              :value="r.id" :disabled="r.status !== 'completed'" />
          </el-select>
        </el-form-item>
        <el-form-item label="左来源">
          <el-select v-model="leftLabel" style="width: 140px">
            <el-option v-for="s in labels" :key="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="右来源">
          <el-select v-model="rightLabel" style="width: 140px">
            <el-option v-for="s in labels" :key="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="对账键">
          <el-input v-model="keyField" style="width: 130px" />
        </el-form-item>
        <el-form-item label="金额容差">
          <el-input-number v-model="tolerance" :min="0" :step="0.01" :precision="2" style="width: 130px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!canStart" @click="startRecon">开始对账</el-button>
        </el-form-item>
      </el-form>
      <el-checkbox-group v-model="compareFields">
        <el-checkbox v-for="f in comparableFields" :key="f" :value="f">
          对比 {{ fieldLabels[f] || f }}
        </el-checkbox>
      </el-checkbox-group>
    </el-card>

    <el-card class="section-block">
      <template #header>对账任务</template>
      <el-table :data="jobs" size="small" stripe highlight-current-row @row-click="selectJob">
        <el-table-column prop="id" label="Job" width="70" />
        <el-table-column prop="run_id" label="Run" width="70" />
        <el-table-column label="对账来源" width="200">
          <template #default="{ row }">{{ row.left_label }} ↔ {{ row.right_label }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'completed' ? 'success' : 'warning'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" />
          </template>
        </el-table-column>
        <el-table-column label="差异数" width="90">
          <template #default="{ row }">{{ row.stats?.total_diff_entries ?? 0 }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <template v-if="currentJob">
      <el-card class="section-block">
        <template #header>
          对账结果统计
          <el-button size="small" type="success" style="float: right"
            :disabled="currentJob.status !== 'completed'" @click="exportRecon">导出差异 CSV</el-button>
        </template>
        <el-descriptions :column="5" border size="small">
          <el-descriptions-item label="完全匹配">{{ currentJob.stats.matched }}</el-descriptions-item>
          <el-descriptions-item label="字段不一致">
            <el-tag type="warning">{{ currentJob.stats.field_mismatch }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="仅左存在">
            <el-tag type="danger">{{ currentJob.stats.only_left }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="仅右存在">
            <el-tag type="danger">{{ currentJob.stats.only_right }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="差异条目合计">
            <b>{{ currentJob.stats.total_diff_entries }}</b>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card>
        <template #header>差异明细（可按类型筛选，每条差异都能看到来源文件与行号）</template>
        <el-radio-group v-model="typeFilter" size="small" class="section-block">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="field_mismatch">字段不一致</el-radio-button>
          <el-radio-button value="only_left">仅左存在</el-radio-button>
          <el-radio-button value="only_right">仅右存在</el-radio-button>
        </el-radio-group>
        <el-table :data="filteredEntries" size="small" border max-height="420">
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag :type="entryType(row.match_type)" size="small">
                {{ typeLabel(row.match_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="key_value" label="业务键" width="130" />
          <el-table-column label="差异字段" min-width="220">
            <template #default="{ row }">
              <div v-for="d in row.diffs" :key="d.field" class="diff-line">
                <el-tag size="small">{{ d.field_label || d.field }}</el-tag>
                <span class="mono old-val">{{ d.left ?? '∅' }}</span>
                <span>vs</span>
                <span class="mono new-val">{{ d.right ?? '∅' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="左侧来源追溯" width="210">
            <template #default="{ row }">
              <div v-if="row.left_file" class="mono small">
                {{ row.left_file }}:{{ row.left_row }}
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="右侧来源追溯" width="210">
            <template #default="{ row }">
              <div v-if="row.right_file" class="mono small">
                {{ row.right_file }}:{{ row.right_row }}
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const runs = ref([])
const jobs = ref([])
const runId = ref(null)
const leftLabel = ref('')
const rightLabel = ref('')
const keyField = ref('biz_no')
const tolerance = ref(0)
const compareFields = ref(['amount', 'order_date', 'channel', 'status'])
const comparableFields = ['amount', 'order_date', 'channel', 'status', 'full_name']
const fieldLabels = {
  biz_no: '业务编号', full_name: '客户全名', amount: '订单金额',
  order_date: '下单日期', channel: '渠道', status: '单据状态',
}
const currentJob = ref(null)
const entries = ref([])
const typeFilter = ref('all')
let timer = null

const labels = computed(() => {
  const run = runs.value.find((r) => r.id === runId.value)
  if (!run) return []
  // 来源标签从已有对账任务不可得, 用 run 详情获取
  return run._labels || []
})
const canStart = computed(() => runId.value && leftLabel.value && rightLabel.value
  && leftLabel.value !== rightLabel.value && compareFields.value.length)
const filteredEntries = computed(() => typeFilter.value === 'all'
  ? entries.value
  : entries.value.filter((e) => e.match_type === typeFilter.value))

function typeLabel(type) {
  return { field_mismatch: '字段不一致', only_left: '仅左存在', only_right: '仅右存在' }[type]
}
function entryType(type) {
  return { field_mismatch: 'warning', only_left: 'danger', only_right: 'danger' }[type] || 'info'
}

async function syncLabels() {
  if (!runId.value) return
  const detail = await api.get(`/runs/${runId.value}`)
  const run = runs.value.find((r) => r.id === runId.value)
  if (run) run._labels = [...new Set(detail.records.map((r) => r.source_label))]
  if (!labels.value.includes(leftLabel.value)) leftLabel.value = labels.value[0] || ''
  if (!labels.value.includes(rightLabel.value)) {
    rightLabel.value = labels.value[1] || labels.value[0] || ''
  }
}

async function startRecon() {
  const job = await api.post('/recon', {
    run_id: runId.value,
    left_label: leftLabel.value,
    right_label: rightLabel.value,
    key_field: keyField.value,
    compare_fields: compareFields.value,
    amount_tolerance: tolerance.value,
  })
  ElMessage.success(`对账 Job #${job.id} 已开始`)
  await loadJobs()
  await selectJob(job)
}

async function loadJobs() {
  jobs.value = await api.get('/recon')
}

async function selectJob(jobRow) {
  currentJob.value = await api.get(`/recon/${jobRow.id}`)
  if (currentJob.value.status === 'completed') {
    entries.value = await api.get(`/recon/${jobRow.id}/entries`)
  } else {
    entries.value = []
  }
}

async function exportRecon() {
  const result = await api.post(`/exports/recon/${currentJob.value.id}`)
  window.open(result.download_url, '_blank')
  ElMessage.success(`已导出 ${result.row_count} 条差异`)
}

onMounted(async () => {
  runs.value = await api.get('/runs')
  await loadJobs()
  timer = setInterval(async () => {
    const busy = jobs.value.some((j) => ['pending', 'running'].includes(j.status))
    if (busy) {
      await loadJobs()
      if (currentJob.value && ['pending', 'running'].includes(currentJob.value.status)) {
        await selectJob(currentJob.value)
      }
    }
  }, 1500)
})

onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.small { font-size: 12px; }
.muted { color: #c0c4cc; }
.diff-line { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.old-val { color: #f56c6c; }
.new-val { color: #67c23a; }
</style>
