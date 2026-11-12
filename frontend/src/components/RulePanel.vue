<template>
  <div>
    <el-card class="section-block">
      <template #header>规则草稿</template>
      <el-form inline>
        <el-form-item label="规则名称">
          <el-input v-model="ruleName" style="width: 200px" />
        </el-form-item>
        <el-form-item label="版本备注">
          <el-input v-model="ruleNote" placeholder="本次改了什么" style="width: 260px" />
        </el-form-item>
        <el-form-item>
          <el-button @click="addSource">+ 添加来源</el-button>
          <el-button type="warning" :loading="previewing" @click="preview">试清洗预览</el-button>
          <el-button type="primary" @click="saveRule">保存为新版本</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-for="(source, idx) in sources" :key="idx" class="section-block" shadow="never">
      <template #header>
        来源 {{ idx + 1 }}：
        <el-input v-model="source.source_label" size="small" style="width: 140px" />
        <el-select v-model="source.batch_id" size="small" style="width: 320px; margin-left: 8px"
          @change="(val) => onBatchChange(source, val)">
          <el-option v-for="b in batches" :key="b.id"
            :label="`#${b.id} ${b.source_label} · ${b.file_name}（${b.row_count}行）`" :value="b.id" />
        </el-select>
        <el-button size="small" text type="primary" @click="applySuggestion(source)">
          应用智能映射建议
        </el-button>
        <el-button size="small" text type="danger" @click="sources.splice(idx, 1)">删除来源</el-button>
      </template>

      <el-divider content-position="left">字段映射与类型转换（目标字段类型固定）</el-divider>
      <el-table :data="mappingRows(source)" size="small" border>
        <el-table-column label="统一目标字段" width="150">
          <template #default="{ row }">
            {{ row.target }}
            <el-tag size="small" type="info">{{ targetTypes[row.target] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源字段" min-width="220">
          <template #default="{ row }">
            <el-select v-model="source.field_mappings[row.target]" clearable size="small"
              placeholder="不映射" style="width: 100%">
              <el-option v-for="col in batchColumns(source.batch_id)" :key="col"
                :label="col" :value="col" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="值映射（可选，原始值 → 统一值）" min-width="280">
          <template #default="{ row }">
            <div v-for="(v, k) in source.value_maps[row.target]" :key="k" class="map-row">
              <el-input :model-value="k" size="small" style="width: 120px"
                placeholder="原始值" disabled />
              <span>→</span>
              <el-input v-model="source.value_maps[row.target][k]" size="small"
                style="width: 120px" placeholder="统一值" />
              <el-button size="small" text type="danger"
                @click="removeValueMap(source, row.target, k)">删</el-button>
            </div>
            <el-button size="small" text @click="addValueMap(source, row.target)">+ 添加值映射</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider content-position="left">派生字段（表达式，如 ${姓氏}${名字} 或 concat(${a}, " ", ${b})）</el-divider>
      <div v-for="(expr, target) in source.derived_fields" :key="target" class="map-row">
        <el-select :model-value="target" size="small" style="width: 160px"
          @change="(val) => changeDerivedTarget(source, target, val)">
          <el-option v-for="t in targetFields" :key="t" :label="t" :value="t" />
        </el-select>
        <el-input v-model="source.derived_fields[target]" size="small" style="width: 420px"
          placeholder='${字段名} 或 concat(upper(${x}), ${y})' />
        <el-button size="small" text type="danger"
          @click="delete source.derived_fields[target]">删除</el-button>
      </div>
      <el-button size="small" text @click="addDerived(source)">+ 添加派生字段</el-button>

      <el-divider content-position="left">空值记号、必填与去重</el-divider>
      <el-form label-width="110px" size="small">
        <el-form-item label="空值记号">
          <el-input :model-value="nullTokensText(source)" style="width: 420px"
            @input="(v) => setNullTokens(source, v)" />
          <span class="hint">逗号分隔，命中的值一律按 null 处理</span>
        </el-form-item>
        <el-form-item label="必填字段">
          <el-checkbox-group v-model="source.required_fields">
            <el-checkbox v-for="t in targetFields" :key="t" :value="t">{{ t }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="去重键">
          <el-select v-model="source.dedupe_key" clearable style="width: 200px">
            <el-option label="biz_no（业务编号）" value="biz_no" />
          </el-select>
        </el-form-item>
        <el-form-item label="重复处理方式">
          <el-radio-group v-model="source.dedupe_strategy">
            <el-radio value="keep_first">保留第一条（按原始行号）</el-radio>
            <el-radio value="priority">按字段优先级保留</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="source.dedupe_strategy === 'priority'" label="优先级字段">
          <el-select v-model="source.priority_field" clearable style="width: 260px"
            placeholder="可取目标字段或来源原始字段，如 dataTier">
            <el-option v-for="col in batchColumns(source.batch_id)" :key="col"
              :label="`${col}（来源原始字段）`" :value="col" />
            <el-option v-for="t in targetFields" :key="t" :label="`${t}（目标字段）`" :value="t" />
          </el-select>
          <el-checkbox v-model="source.priority_desc">值越大越优先</el-checkbox>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="previewData" class="section-block">
      <template #header>
        试清洗结果（未保存）：保留 {{ previewData.total_kept }} 条 ·
        无效 {{ previewData.total_invalid }} 条 ·
        去重丢弃 {{ previewData.total_dropped }} 条
      </template>
      <el-tabs>
        <el-tab-pane v-for="ps in previewData.per_source" :key="ps.source_label"
          :label="`${ps.source_label}（${ps.stats.kept_rows}）`">
          <el-table :data="ps.records" size="small" border max-height="320">
            <el-table-column label="来源行" width="90">
              <template #default="{ row }">
                <span class="mono">{{ ps.source_file }}:{{ row.source_row }}</span>
              </template>
            </el-table-column>
            <el-table-column v-for="t in targetFields" :key="t" :label="t" min-width="120">
              <template #default="{ row }">{{ row.data[t] ?? '—' }}</template>
            </el-table-column>
          </el-table>
          <div v-if="ps.invalid_rows.length" class="problem-block">
            <el-tag type="danger">无效行 {{ ps.invalid_rows.length }}</el-tag>
            <el-table :data="ps.invalid_rows" size="small" max-height="200">
              <el-table-column prop="source_row" label="行号" width="80" />
              <el-table-column label="错误原因" min-width="240">
                <template #default="{ row }">{{ row.errors.join('；') }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div v-if="ps.dropped_duplicates.length" class="problem-block">
            <el-tag type="warning">去重丢弃 {{ ps.dropped_duplicates.length }}</el-tag>
            <el-table :data="ps.dropped_duplicates" size="small" max-height="200">
              <el-table-column prop="dedupe_key" label="去重键" width="140" />
              <el-table-column prop="dropped_row" label="丢弃行" width="90" />
              <el-table-column prop="kept_row" label="保留行" width="90" />
              <el-table-column prop="reason" label="原因" min-width="200" />
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
      <div class="actions">
        <el-button type="primary" @click="saveRule">确认无误，保存为新版本 →</el-button>
      </div>
    </el-card>

    <el-card>
      <template #header>历史规则版本（改规则会产生新版本，可对比两次清洗结果）</template>
      <el-table :data="versions" size="small" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" width="140" />
        <el-table-column prop="version" label="版本号" width="80" />
        <el-table-column prop="note" label="备注" min-width="200" />
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" text @click="loadVersion(row)">载入</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const emit = defineEmits(['go-run'])

const batches = ref([])
const versions = ref([])
const sources = ref([])
const ruleName = ref('演示规则')
const ruleNote = ref('')
const previewData = ref(null)
const previewing = ref(false)
const targetFields = ref([])
const targetTypes = ref({})

function emptySource() {
  return {
    source_label: '',
    batch_id: null,
    field_mappings: {},
    null_tokens: ['-', '--', 'null', 'NULL', '', 'None'],
    value_maps: {},
    derived_fields: {},
    dedupe_key: 'biz_no',
    dedupe_strategy: 'keep_first',
    priority_field: null,
    priority_desc: true,
    required_fields: ['biz_no', 'amount', 'order_date'],
  }
}

function addSource() {
  sources.value.push(emptySource())
}

function mappingRows(source) {
  return targetFields.value.map((target) => ({ target, source }))
}

function batchColumns(batchId) {
  return batches.value.find((b) => b.id === batchId)?.columns || []
}

function nullTokensText(source) {
  return source.null_tokens.join(', ')
}

function addValueMap(source, target) {
  if (!source.value_maps[target]) source.value_maps[target] = {}
  const map = source.value_maps[target]
  ElMessageBox.prompt('输入原始值（命中后映射到目标值）', '添加值映射').then(({ value }) => {
    if (value) map[value] = value
  }).catch(() => {})
}

function removeValueMap(source, target, key) {
  delete source.value_maps[target][key]
}

function addDerived(source) {
  const used = new Set(Object.keys(source.derived_fields))
  const target = targetFields.value.find((t) => !used.has(t))
  if (!target) {
    ElMessage.warning('所有目标字段都已配置派生规则')
    return
  }
  source.derived_fields[target] = ''
}

function changeDerivedTarget(source, oldKey, newKey) {
  if (oldKey === newKey) return
  if (newKey in source.derived_fields) {
    ElMessage.warning(`字段 ${newKey} 已存在派生规则`)
    return
  }
  const expr = source.derived_fields[oldKey]
  delete source.derived_fields[oldKey]
  source.derived_fields[newKey] = expr
}

function setNullTokens(source, text) {
  source.null_tokens = text.split(',').map((s) => s.trim()).filter(Boolean)
}

async function onBatchChange(source, batchId) {
  const batch = batches.value.find((b) => b.id === batchId)
  if (batch && !source.source_label) source.source_label = batch.source_label
}

async function applySuggestion(source) {
  if (!source.batch_id) {
    ElMessage.warning('请先选择导入批次')
    return
  }
  const result = await api.get(`/imports/${source.batch_id}/suggest`)
  Object.assign(source.field_mappings, result.suggested_mappings)
  ElMessage.success(`已建议 ${Object.keys(result.suggested_mappings).length} 个映射`)
}

function buildPayload() {
  return {
    name: ruleName.value.trim(),
    note: ruleNote.value.trim() || null,
    config: { sources: sources.value },
  }
}

async function preview() {
  if (!sources.value.length) return ElMessage.warning('请先添加来源')
  previewing.value = true
  try {
    previewData.value = await api.post('/rules/preview', buildPayload())
  } catch (err) {
    ElMessage.error(err.message)
  } finally {
    previewing.value = false
  }
}

async function saveRule() {
  if (!ruleName.value.trim()) return ElMessage.warning('请填写规则名称')
  try {
    const saved = await api.post('/rules', buildPayload())
    ElMessage.success(`已保存为 v${saved.version}`)
    ruleNote.value = ''
    previewData.value = null
    await loadVersions()
    ElMessageBox.confirm('规则已保存，是否立即运行清洗？', '下一步', {
      confirmButtonText: '去运行',
      cancelButtonText: '留在本页',
    }).then(() => emit('go-run')).catch(() => {})
  } catch (err) {
    ElMessage.error(err.message)
  }
}

async function loadVersion(version) {
  sources.value = version.config.sources.map((s) => ({ ...emptySource(), ...s }))
  ruleName.value = version.name
  ruleNote.value = `基于 v${version.version} 修改`
  previewData.value = null
  ElMessage.success(`已载入 v${version.version}，修改后保存将生成新版本`)
}

async function loadVersions() {
  versions.value = await api.get('/rules')
}

onMounted(async () => {
  const meta = await api.get('/meta')
  targetFields.value = Object.keys(meta.target_schema)
  targetTypes.value = meta.target_types
  batches.value = await api.get('/imports')
  await loadVersions()
  if (!sources.value.length) addSource()
})
</script>

<style scoped>
.map-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.hint {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
.problem-block {
  margin-top: 10px;
}
.actions {
  margin-top: 12px;
  text-align: right;
}
</style>
