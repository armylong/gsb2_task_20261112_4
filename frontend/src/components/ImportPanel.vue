<template>
  <div>
    <el-alert type="info" :closable="false" class="section-block"
      title="同一文件重复上传会按内容哈希自动识别并复用原批次, 不会重复入库, 保证重复导入幂等。" />

    <el-card class="section-block">
      <template #header>上传数据文件（CSV / JSON）</template>
      <el-form inline>
        <el-form-item label="来源标识">
          <el-input v-model="sourceLabel" placeholder="如 CRM / ERP" style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-upload :show-file-list="false" :before-upload="handleUpload" accept=".csv,.json">
            <el-button type="primary">选择文件并上传</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="section-block">
      <template #header>已导入批次</template>
      <el-table :data="batches" size="small" stripe @row-click="selectBatch"
        :row-class-name="rowClass" highlight-current-row>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="source_label" label="来源" width="100" />
        <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="file_format" label="格式" width="80" />
        <el-table-column prop="row_count" label="数据行数" width="90" />
        <el-table-column label="内容哈希(前12位)" width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.content_hash.slice(0, 12) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="current" class="section-block">
      <template #header>
        原始数据预览 — {{ current.file_name }}
        <el-tag size="small" class="ml8">前 8 行</el-tag>
        <el-tag size="small" type="success" class="ml8">
          字段 {{ current.columns.length }} 个 · 共 {{ current.total_rows }} 行
        </el-tag>
      </template>
      <el-table :data="previewRows" size="small" border max-height="360">
        <el-table-column label="原始行号" width="90" fixed>
          <template #default="{ row }">
            <span class="mono">{{ row.row_no }}</span>
          </template>
        </el-table-column>
        <el-table-column v-for="col in current.columns" :key="col" :label="col" min-width="130">
          <template #default="{ row }">
            <span v-if="row.data[col] === null || row.data[col] === ''" class="null-cell">
              {{ row.data[col] === null ? 'null' : '空串' }}
            </span>
            <span v-else>{{ row.data[col] }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="actions">
        <el-button type="primary" @click="goRule">去配置清洗规则 →</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const emit = defineEmits(['go-rule'])

const sourceLabel = ref('CRM')
const batches = ref([])
const current = ref(null)
const previewRows = ref([])

async function loadBatches() {
  batches.value = await api.get('/imports')
}

async function handleUpload(file) {
  if (!sourceLabel.value.trim()) {
    ElMessage.warning('请先填写来源标识')
    return false
  }
  const form = new FormData()
  form.append('source_label', sourceLabel.value.trim())
  form.append('file', file)
  try {
    const result = await api.post('/imports/upload', form)
    ElMessage.success(result.reused ? '文件已存在, 复用原批次(幂等)' : '上传成功')
    await loadBatches()
    showBatch(result.batch)
    previewRows.value = result.preview_rows
  } catch (err) {
    ElMessage.error(err.message)
  }
  return false
}

async function selectBatch(row) {
  const detail = await api.get(`/imports/${row.id}`)
  showBatch(detail.batch)
  previewRows.value = detail.preview_rows
}

function showBatch(batch) {
  current.value = batch
}

function goRule() {
  emit('go-rule')
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : ''
}

function rowClass({ row }) {
  return current.value?.id === row.id ? 'current-row' : ''
}

onMounted(loadBatches)
</script>

<style scoped>
.ml8 { margin-left: 8px; }
.null-cell { color: #909399; font-style: italic; }
.actions { margin-top: 12px; text-align: right; }
</style>
