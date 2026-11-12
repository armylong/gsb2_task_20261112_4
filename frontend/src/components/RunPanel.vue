<template>
  <div>
    <el-card class="section-block">
      <template #header>发起清洗（全量重算，重复运行结果不会累加）</template>
      <el-form inline>
        <el-form-item label="规则版本">
          <el-select v-model="selectedRuleId" style="width: 320px" placeholder="选择已保存的规则版本">
            <el-option v-for="r in versions" :key="r.id"
              :label="`#${r.id} ${r.name} v${r.version}${r.note ? ' · ' + r.note : ''}`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!selectedRuleId" @click="startRun">运行清洗</el-button>
          <el-button @click="loadRuns">刷新列表</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="section-block">
      <template #header>清洗任务列表</template>
      <el-table :data="runs" size="small" stripe highlight-current-row @row-click="selectRun">
        <el-table-column prop="id" label="Run" width="70" />
        <el-table-column prop="rule_version" label="规则版本" width="90" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="200">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :status="row.status === 'failed' ? 'exception' : ''" />
          </template>
        </el-table-column>
        <el-table-column prop="message" label="消息" min-width="140" show-overflow-tooltip />
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <template v-if="detail">
      <el-card class="section-block">
        <template #header>
          Run #{{ detail.id }} 统计
          <el-button size="small" type="success" style="float: right"
            :disabled="detail.status !== 'completed'" @click="exportRun">导出清洗结果 CSV</el-button>
          <el-button size="small" style="float: right; margin-right: 8px"
            :disabled="detail.status !== 'completed'" @click="emit('go-recon')">去对账 →</el-button>
        </template>
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="原始总行数">{{ detail.stats.total_rows }}</el-descriptions-item>
          <el-descriptions-item label="有效行">{{ detail.stats.valid_rows }}</el-descriptions-item>
          <el-descriptions-item label="无效行">{{ detail.stats.invalid_rows }}</el-descriptions-item>
          <el-descriptions-item label="去重丢弃">{{ detail.stats.dropped_duplicates }}</el-descriptions-item>
          <el-descriptions-item label="最终保留">
            <b>{{ detail.stats.kept_rows }}</b>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="section-block">
        <template #header>
          清洗后记录（含来源追溯：来源文件 + 原始行号）
          <el-radio-group v-model="recordFilter" size="small" style="margin-left: 12px">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="s in sourceLabels" :key="s" :value="s">{{ s }}</el-radio-button>
          </el-radio-group>
        </template>
        <el-table :data="filteredRecords" size="small" border max-height="380">
          <el-table-column label="追溯来源" width="240" fixed>
            <template #default="{ row }">
              <div>{{ row.source_label }}</div>
              <div class="mono small">{{ row.source_file }} : 第 {{ row.source_row }} 行</div>
            </template>
          </el-table-column>
          <el-table-column v-for="t in targetFields" :key="t" :label="t" min-width="120">
            <template #default="{ row }">{{ row.data[t] ?? '—' }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-row :gutter="12">
        <el-col :span="12">
          <el-card class="section-block">
            <template #header>
              <el-tag type="danger" size="small">无效行 {{ detail.invalid_rows.length }}</el-tag>
            </template>
            <el-table :data="detail.invalid_rows" size="small" max-height="260">
              <el-table-column label="来源" width="90">
                <template #default="{ row }">{{ row.source_label }}</template>
              </el-table-column>
              <el-table-column prop="source_row" label="原始行号" width="90" />
              <el-table-column label="错误原因" min-width="220">
                <template #default="{ row }">{{ row.errors.join('；') }}</template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card class="section-block">
            <template #header>
              <el-tag type="warning" size="small">去重丢弃 {{ detail.dropped_duplicates.length }}</el-tag>
            </template>
            <el-table :data="detail.dropped_duplicates" size="small" max-height="260">
              <el-table-column prop="dedupe_key" label="去重键" width="130" />
              <el-table-column prop="dropped_row" label="丢弃行" width="80" />
              <el-table-column prop="kept_row" label="保留行" width="80" />
              <el-table-column prop="reason" label="原因" min-width="160" />
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="section-block">
        <template #header>规则版本差异对比（改规则重跑后，对比前后两个 Run）</template>
        <el-form inline>
          <el-form-item label="基准 Run">
            <el-select v-model="diffBase" style="width: 140px">
              <el-option v-for="r in runs" :key="r.id" :label="`Run #${r.id} (v${r.rule_version})`"
                :value="r.id" :disabled="r.status !== 'completed'" />
            </el-select>
          </el-form-item>
          <el-form-item label="对比 Run">
            <el-select v-model="diffTarget" style="width: 140px">
              <el-option v-for="r in runs" :key="r.id" :label="`Run #${r.id} (v${r.rule_version})`"
                :value="r.id" :disabled="r.status !== 'completed'" />
            </el-select>
          </el-form-item>
          <el-button type="primary" :disabled="!diffBase || !diffTarget" @click="runDiff">对比</el-button>
        </el-form>
        <template v-if="diffResult">
          <el-descriptions :column="5" border size="small" class="section-block">
            <el-descriptions-item label="基准条数">{{ diffResult.summary.base_count }}</el-descriptions-item>
            <el-descriptions-item label="对比条数">{{ diffResult.summary.target_count }}</el-descriptions-item>
            <el-descriptions-item label="新增">
              <el-tag type="success">{{ diffResult.summary.added }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="删除">
              <el-tag type="danger">{{ diffResult.summary.removed }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="字段变化">
              <el-tag type="warning">{{ diffResult.summary.changed }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <el-table v-if="diffResult.changed.length" :data="diffResult.changed" size="small" border
            max-height="260">
            <el-table-column prop="source_label" label="来源" width="90" />
            <el-table-column prop="dedupe_key" label="业务键" width="130" />
            <el-table-column label="字段级变化" min-width="300">
              <template #default="{ row }">
                <div v-for="d in row.field_diffs" :key="d.field" class="diff-line">
                  <el-tag size="small">{{ d.field_label }}</el-tag>
                  <span class="mono old-val">{{ d.before ?? '∅' }}</span>
                  →
                  <span class="mono new-val">{{ d.after ?? '∅' }}</span>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const emit = defineEmits(['go-recon'])

const versions = ref([])
const runs = ref([])
const selectedRuleId = ref(null)
const detail = ref(null)
const recordFilter = ref('all')
const diffBase = ref(null)
const diffTarget = ref(null)
const diffResult = ref(null)
const targetFields = ref([])
let timer = null

const sourceLabels = computed(() => [...new Set(detail.value?.records.map((r) => r.source_label) || [])])
const filteredRecords = computed(() => {
  if (!detail.value) return []
  return recordFilter.value === 'all'
    ? detail.value.records
    : detail.value.records.filter((r) => r.source_label === recordFilter.value)
})

function statusType(status) {
  return { completed: 'success', running: 'warning', failed: 'danger', pending: 'info' }[status] || 'info'
}
function statusText(status) {
  return { completed: '完成', running: '运行中', failed: '失败', pending: '排队中' }[status] || status
}

async function startRun() {
  const run = await api.post('/runs', { rule_version_id: selectedRuleId.value })
  ElMessage.success(`Run #${run.id} 已开始`)
  await loadRuns()
  await selectRun(run)
}

async function loadRuns() {
  runs.value = await api.get('/runs')
}

async function selectRun(runRow) {
  detail.value = await api.get(`/runs/${runRow.id}`)
  diffResult.value = null
}

async function runDiff() {
  diffResult.value = await api.get(`/runs/diff/${diffBase.value}/${diffTarget.value}`)
}

async function exportRun() {
  const result = await api.post(`/exports/run/${detail.value.id}`)
  window.open(result.download_url, '_blank')
  ElMessage.success(`已导出 ${result.row_count} 条`)
}

onMounted(async () => {
  const meta = await api.get('/meta')
  targetFields.value = Object.keys(meta.target_schema)
  versions.value = await api.get('/rules')
  await loadRuns()
  // 轮询运行中的任务进度
  timer = setInterval(async () => {
    const busy = runs.value.some((r) => ['pending', 'running'].includes(r.status))
    if (busy) {
      await loadRuns()
      if (detail.value && ['pending', 'running'].includes(detail.value.status)) {
        detail.value = await api.get(`/runs/${detail.value.id}`)
      }
    }
  }, 1500)
})

onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.small { font-size: 12px; color: #606266; }
.diff-line { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.old-val { color: #f56c6c; }
.new-val { color: #67c23a; }
</style>
