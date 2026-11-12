<template>
  <el-container class="app-shell">
    <el-header class="app-header">
      <div class="title">本地数据清洗对账工具</div>
      <el-tag size="small" type="info">Vue3 + FastAPI + SQLite · 本地运行</el-tag>
    </el-header>
    <el-main>
      <el-tabs v-model="activeTab" type="border-card">
        <el-tab-pane label="① 导入预览" name="import">
          <import-panel @go-rule="activeTab = 'rule'" />
        </el-tab-pane>
        <el-tab-pane label="② 规则配置" name="rule">
          <rule-panel @go-run="activeTab = 'run'" />
        </el-tab-pane>
        <el-tab-pane label="③ 处理进度与清洗结果" name="run">
          <run-panel @go-recon="activeTab = 'recon'" />
        </el-tab-pane>
        <el-tab-pane label="④ 对账差异" name="recon">
          <recon-panel />
        </el-tab-pane>
      </el-tabs>
    </el-main>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'
import ImportPanel from './components/ImportPanel.vue'
import RulePanel from './components/RulePanel.vue'
import RunPanel from './components/RunPanel.vue'
import ReconPanel from './components/ReconPanel.vue'

const activeTab = ref('import')
</script>

<style>
body {
  margin: 0;
  background: #f5f7fa;
  font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
.app-header {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #1f2d3d;
  color: #fff;
}
.app-header .title {
  font-size: 18px;
  font-weight: 600;
}
.app-shell {
  min-height: 100vh;
}
.section-block {
  margin-bottom: 20px;
}
.mono {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
}
</style>
