# 本地数据清洗对账工具

把两份字段命名、日期格式、金额写法、空值记号都不一致的业务数据（CSV + JSON），
通过可视化配置整理成统一格式，先预览清洗结果，确认后再合并、对账并导出。

技术栈：**Vue 3 + Element Plus / FastAPI + SQLAlchemy / SQLite**，纯本地运行，不依赖 Docker。

## 目录结构

```
repo/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── parsers.py      # CSV/JSON 解析（行号约定见下）
│   │   ├── transform.py    # 映射/类型转换/派生表达式/必填校验/去重
│   │   ├── reconcile.py    # 两来源对账
│   │   ├── jobs.py         # 后台清洗与对账任务（全量重算）
│   │   ├── services.py     # 导出、规则版本间 diff
│   │   └── routers/        # API 路由
│   ├── tests/              # pytest 端到端测试
│   └── requirements.txt
├── frontend/               # Vue3 前端（四个标签页）
├── demo_data/              # 演示数据（验收用）
│   ├── source_a_crm.csv    # 来源 A：中文表头、斜杠日期、两位小数、空串/横杠空值
│   └── source_b_erp.json   # 来源 B：驼峰字段、ISO 日期、整数/字符串金额、null 空值
├── run_dev.sh              # 开发模式（前后端两个端口，热更新）
└── run_local.sh            # 单端口模式（构建后由 FastAPI 托管）
```

## 快速开始

### 方式一：开发模式（推荐验收时使用）

```bash
./run_dev.sh
# 前端 http://127.0.0.1:5173 ，后端 API 文档 http://127.0.0.1:8000/docs
```

### 方式二：单端口模式

```bash
./run_local.sh
# 浏览器打开 http://127.0.0.1:8000
```

### 运行测试

```bash
cd backend
.venv/bin/python -m pytest -q
```

## 验收操作路径（基于 demo_data）

1. **导入预览**：分别上传 `source_a_crm.csv`（来源标识填 `CRM`）和
   `source_b_erp.json`（来源标识填 `ERP`）。再传一次同一文件，会提示
   「复用原批次（幂等）」，批次列表不新增。
2. **规则配置**：为两个来源各选批次，点「应用智能映射建议」补全映射；
   派生字段建议配置：
   - CRM：`full_name = ${姓氏}${名字}`
   - ERP：`full_name = ${firstName} ${lastName}`
   - 值映射：CRM 状态（已完成→completed 等）、ERP 状态（COMPLETED→completed 等）、
     ERP 渠道（online→线上 等）
   - CRM 去重选「保留第一条」；ERP 选「按字段优先级」，优先级字段填 `dataTier`、值越大越优先
   - 必填：`biz_no, amount, order_date`
3. 点「试清洗预览」确认结果（每边 11 条保留、1 条无效、1 条去重丢弃），
   再「保存为新版本」。
4. **处理进度**：运行清洗，进度条轮询；结果含来源文件与原始行号追溯。
   重复运行同一规则，合并条数保持 22 条不变（幂等）。
5. 修改规则再保存会生成 v2，重跑后在「规则版本差异对比」里选两个 Run，
   可看到字段级 before/after 差异。
6. **对账差异**：选 Run、两个来源，对比 `amount/order_date/channel/status`。
   演示数据预期：8 条完全匹配、2 条字段不一致（BIZ-1005 金额、BIZ-1006 日期）、
   各 1 条单边记录（BIZ-1011 仅 CRM、BIZ-1012 仅 ERP）。
7. 清洗结果与对账差异均可导出 CSV（含追溯列），文件落在 `backend/workdata/exports/`。

## 关键设计说明

### 幂等性（要求 4）

- 导入时对文件字节算 SHA-256，同内容文件重复上传直接返回原批次，不重复入库。
- 清洗 Run 是**全量重算**：先删除该 Run 的旧合并记录再写入，结果只取决于
  「规则版本 + 批次内容」，与运行次数无关；Run 之间数据隔离，不会越跑越多。
- 对账 Job 同理，每次重算覆盖自己的差异条目。

### 来源追溯（要求 2）

每条合并记录持久化 `source_label / source_file / source_row / batch_id / dedupe_key`。
- CSV 的 `source_row` 是含表头的物理行号（首条数据 = 2），与 Excel 看到的一致；
- JSON 的 `source_row` 是 `records` 数组中的序号（从 1 开始）。
- 对账差异条目同样带两侧的文件名和行号，可直接定位源头。

### 去重（要求 3）

去重只在**同一来源内部**按去重键执行，跨来源的同键记录保留给对账环节。
- `keep_first`：保留原始行号最小的一条；
- `priority`：按指定字段排序（支持目标字段或来源原始字段，如 `dataTier`），
  值越大/越小可选，同值按行号保证结果稳定。

### 派生字段（要求 1）

不使用 `eval`，内置安全表达式解析器，支持：

- 模板：`${姓氏}${名字}`
- 函数：`concat(...)`、`coalesce(...)`、`upper(...)`、`lower(...)`、`trim(...)`
- 字符串字面量：`concat(${a}, " ", ${b})`

### 类型转换与空值

- 金额：整数、两位小数字符串、千分位都可解析，统一保留两位小数；
- 日期：支持 ISO 8601（含带时间的）、`2026/10/01`、`20261001` 等，
  非法日期（如 `2026-02-30`）转成无效行而不是静默吞掉；
- 空值记号可配置（默认 `- -- null NULL 空串 None N/A`），命中即按 null 处理。

### 规则版本与 diff（要求 5）

每次保存规则生成一条不可变快照（同名规则版本号自增），Run 绑定具体版本。
两个 Run 之间按 `(来源, 去重键)` 对比，输出新增 / 删除 / 字段级变化三类差异。

## 数据存放

SQLite 数据库与导出文件默认在 `backend/workdata/`（已在 .gitignore 中），
可用环境变量 `RECON_WORK_DIR` 改位置；删掉该目录即可完全重置。
