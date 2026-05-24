<script setup lang="ts">
import { FileSpreadsheet, Upload, Download, Play, RotateCcw, Check, ArrowRight } from "lucide-vue-next";
import { ref } from "vue";
import { getApiBase, getToken } from "../api";

// 状态
const step = ref(1);
const file = ref<File | null>(null);
const uploading = ref(false);
const generating = ref(false);

// 解析结果
interface ColumnInfo {
  index: number;
  header: string;
  field_id: string | null;
  confidence: number;
  generator: string | null;
}

interface Relationship {
  type: string;
  parent_col: number;
  child_col: number;
  description: string;
}

interface ParseResult {
  file_id: string;
  filename: string;
  headers: string[];
  columns: ColumnInfo[];
  header_row: number;
  relationships: Relationship[];
  sample_data: string[][];
}

interface GenerateResult {
  filename: string;
  download_url: string;
  total_rows: number;
  groups: number;
  rows_per_group: number;
  preview: string[][];
}

const parseResult = ref<ParseResult | null>(null);
const generateResult = ref<GenerateResult | null>(null);
const count = ref(30);

// 字段显示名称
const fieldNames: Record<string, string> = {
  name: "姓名", phone: "手机号", username: "账号", password: "密码",
  id_card: "身份证", email: "邮箱", school: "学校", college: "学院",
  major: "专业", class_name: "班级", student_no: "学号", gender: "性别",
  group_no: "组号", seat_number: "座位号", position: "岗位",
  exam_no: "准考证号", enrollment_year: "入学年份", education: "学历",
  is_coop: "是否共建", score: "分数", address: "地址", remark: "备注"
};

function getFieldDisplayName(fieldId: string): string {
  return fieldNames[fieldId] || fieldId;
}

// 触发文件选择
function triggerFileInput() {
  document.getElementById("file-input")?.click();
}

// 处理文件选择
function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files?.[0]) {
    uploadFile(input.files[0]);
  }
}

// 处理拖拽
function handleDrop(e: DragEvent) {
  e.preventDefault();
  if (e.dataTransfer?.files[0]) {
    uploadFile(e.dataTransfer.files[0]);
  }
}

// 上传文件
async function uploadFile(selectedFile: File) {
  file.value = selectedFile;
  uploading.value = true;

  const formData = new FormData();
  formData.append("file", selectedFile);

  try {
    const res = await fetch(`${getApiBase()}/api/v1/template/upload`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${getToken()}` },
      body: formData
    });
    const data = await res.json();

    if (data.success) {
      parseResult.value = data;
      step.value = 2;
    } else {
      alert(data.error || "上传失败");
      file.value = null;
    }
  } catch (err) {
    alert("上传失败: " + (err instanceof Error ? err.message : "未知错误"));
    file.value = null;
  } finally {
    uploading.value = false;
  }
}

// 生成数据
async function handleGenerate() {
  if (!parseResult.value || !count.value) return;
  generating.value = true;

  try {
    const res = await fetch(`${getApiBase()}/api/v1/template/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${getToken()}`
      },
      body: JSON.stringify({
        file_id: parseResult.value.file_id,
        count: count.value
      })
    });
    const data = await res.json();

    if (data.success) {
      generateResult.value = data;
      step.value = 3;
    } else {
      alert(data.error || "生成失败");
    }
  } catch (err) {
    alert("生成失败: " + (err instanceof Error ? err.message : "未知错误"));
  } finally {
    generating.value = false;
  }
}

// 下载文件
function downloadFile() {
  if (generateResult.value) {
    window.open(generateResult.value.download_url, "_blank");
  }
}

// 重置
function resetAll() {
  file.value = null;
  parseResult.value = null;
  generateResult.value = null;
  count.value = 30;
  step.value = 1;
}
</script>

<template>
  <section class="content-stack">
    <!-- 步骤指示器 -->
    <div class="steps-bar">
      <div class="step-item" :class="{ active: step >= 1, done: step > 1 }">
        <div class="step-num">{{ step > 1 ? "✓" : "1" }}</div>
        <span>上传模板</span>
      </div>
      <div class="step-line" :class="{ active: step > 1 }"></div>
      <div class="step-item" :class="{ active: step >= 2, done: step > 2 }">
        <div class="step-num">{{ step > 2 ? "✓" : "2" }}</div>
        <span>确认映射</span>
      </div>
      <div class="step-line" :class="{ active: step > 2 }"></div>
      <div class="step-item" :class="{ active: step >= 3 }">
        <div class="step-num">3</div>
        <span>生成下载</span>
      </div>
    </div>

    <!-- 步骤1: 上传模板 -->
    <section v-if="step === 1" class="panel">
      <div class="panel-heading">
        <h2><FileSpreadsheet :size="18" /> 上传Excel模板</h2>
      </div>

      <div
        class="upload-zone"
        :class="{ 'has-file': file }"
        @click="triggerFileInput"
        @dragover.prevent
        @drop="handleDrop"
      >
        <Upload :size="40" />
        <p v-if="!file">点击或拖拽文件到此处上传</p>
        <p v-else>{{ file.name }}</p>
        <span class="hint">支持任意格式的 .xlsx, .xls 文件</span>
      </div>

      <input id="file-input" type="file" accept=".xlsx,.xls" hidden @change="handleFileSelect" />

      <div v-if="uploading" class="loading-row">正在智能分析模板...</div>
    </section>

    <!-- 步骤2: 确认映射 -->
    <section v-if="step === 2 && parseResult" class="panel">
      <div class="panel-heading">
        <h2>智能识别结果</h2>
        <span>表头行: 第{{ parseResult.header_row }}行 | {{ parseResult.headers.length }} 列</span>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>列名</th>
              <th>识别字段</th>
              <th>置信度</th>
              <th>生成器</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="col in parseResult.columns" :key="col.index">
              <td>{{ col.header || "(空)" }}</td>
              <td>
                <span v-if="col.field_id" class="tag tag-blue">
                  {{ getFieldDisplayName(col.field_id) }}
                </span>
                <span v-else class="tag tag-gray">未识别</span>
              </td>
              <td>
                <span v-if="col.field_id" :class="col.confidence >= 80 ? 'text-green' : 'text-yellow'">
                  {{ col.confidence }}%
                </span>
                <span v-else class="text-muted">-</span>
              </td>
              <td>
                <code v-if="col.generator" class="generator-code">{{ col.generator }}</code>
                <span v-else class="text-muted">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 关系推断 -->
      <div v-if="parseResult.relationships.length > 0" class="relations-section">
        <h3>推断的列间关系</h3>
        <div class="relation-tags">
          <span v-for="rel in parseResult.relationships" :key="rel.description" class="tag tag-red">
            {{ rel.description }}
          </span>
        </div>
      </div>

      <!-- 样本数据 -->
      <div v-if="parseResult.sample_data.length > 0" class="sample-section">
        <h3>原始数据预览</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th v-for="h in parseResult.headers" :key="h">{{ h || "-" }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in parseResult.sample_data" :key="idx">
                <td v-for="(cell, ci) in row" :key="ci">{{ cell || "-" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 数量设置 -->
      <div class="count-section">
        <h3>设置生成数量</h3>
        <div class="count-input-group">
          <label>生成</label>
          <input v-model.number="count" type="number" min="1" max="10000" />
          <span>行</span>
        </div>
        <div class="quick-counts">
          <button @click="count = 10">10行</button>
          <button @click="count = 30">30行</button>
          <button @click="count = 50">50行</button>
          <button @click="count = 100">100行</button>
        </div>
      </div>

      <div class="action-bar">
        <button class="btn btn-secondary" @click="resetAll">
          <RotateCcw :size="16" /> 重新选择
        </button>
        <button class="btn btn-primary" :disabled="generating" @click="handleGenerate">
          <Play :size="16" />
          {{ generating ? "生成中..." : "开始生成" }}
        </button>
      </div>
    </section>

    <!-- 步骤3: 生成结果 -->
    <section v-if="step === 3 && generateResult" class="panel result-panel">
      <div class="panel-heading">
        <h2><Check :size="18" /> 生成成功</h2>
      </div>

      <div class="result-stats">
        <div class="stat-card">
          <div class="stat-value">{{ generateResult.total_rows }}</div>
          <div class="stat-label">生成行数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ parseResult?.headers.length || 0 }}</div>
          <div class="stat-label">列数</div>
        </div>
      </div>

      <button class="btn btn-download" @click="downloadFile">
        <Download :size="18" /> 下载Excel文件
      </button>

      <!-- 预览 -->
      <div v-if="generateResult.preview.length > 0" class="sample-section">
        <h3>生成数据预览（前5行）</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th v-for="h in parseResult?.headers" :key="h">{{ h || "-" }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, idx) in generateResult.preview" :key="idx">
                <td v-for="(cell, ci) in row" :key="ci">{{ cell || "-" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="action-bar">
        <button class="btn btn-secondary" @click="resetAll">
          <RotateCcw :size="16" /> 重新开始
        </button>
      </div>
    </section>
  </section>
</template>

<style scoped>
/* 步骤指示器 */
.steps-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 20px;
  background: var(--panel-bg, #fff);
  border-radius: 10px;
  margin-bottom: 16px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #999;
  font-size: 14px;
}

.step-item.active {
  color: #667eea;
  font-weight: 500;
}

.step-item.done {
  color: #52c41a;
}

.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #eee;
  color: #999;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}

.step-item.active .step-num {
  background: #667eea;
  color: #fff;
}

.step-item.done .step-num {
  background: #52c41a;
  color: #fff;
}

.step-line {
  width: 40px;
  height: 2px;
  background: #eee;
  margin: 0 12px;
}

.step-line.active {
  background: #52c41a;
}

/* 上传区域 */
.upload-zone {
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  color: #666;
}

.upload-zone:hover {
  border-color: #667eea;
  background: #f8f9ff;
}

.upload-zone.has-file {
  border-color: #52c41a;
  background: #f6ffed;
}

.upload-zone p {
  margin: 12px 0 4px;
  font-size: 15px;
}

.upload-zone .hint {
  font-size: 12px;
  color: #999;
}

/* 标签 */
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.tag-blue { background: #e6f7ff; color: #1890ff; }
.tag-gray { background: #f5f5f5; color: #999; }
.tag-red { background: #fff1f0; color: #ff4d4f; }

.text-green { color: #52c41a; font-weight: 500; }
.text-yellow { color: #faad14; font-weight: 500; }
.text-muted { color: #ccc; }

.generator-code {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  color: #666;
}

/* 关系区域 */
.relations-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #eee;
}

.relations-section h3 {
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

.relation-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 样本数据 */
.sample-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #eee;
}

.sample-section h3 {
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

/* 数量设置 */
.count-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #eee;
}

.count-section h3 {
  font-size: 14px;
  color: #666;
  margin-bottom: 12px;
}

.count-input-group {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}

.count-input-group input {
  width: 100px;
  height: 36px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  text-align: center;
  font-size: 16px;
  font-weight: 500;
}

.quick-counts {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.quick-counts button {
  flex: 1;
  height: 32px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-counts button:hover {
  border-color: #667eea;
  color: #667eea;
}

/* 操作按钮 */
.action-bar {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #eee;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  flex: 1;
}

.btn-primary:hover { opacity: 0.9; }
.btn-primary:disabled { background: #ccc; cursor: not-allowed; }

.btn-secondary {
  background: #f5f5f5;
  color: #666;
}

.btn-secondary:hover { background: #eee; }

.btn-download {
  width: 100%;
  height: 48px;
  background: #52c41a;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s;
}

.btn-download:hover { background: #389e0d; }

/* 结果面板 */
.result-panel {
  border: 2px solid #52c41a;
}

.result-stats {
  display: flex;
  gap: 16px;
  margin: 16px 0;
}

.stat-card {
  flex: 1;
  background: #f6ffed;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #52c41a;
}

.stat-label {
  font-size: 13px;
  color: #666;
  margin-top: 4px;
}
</style>
