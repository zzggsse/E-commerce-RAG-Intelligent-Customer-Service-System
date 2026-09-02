# 电商 RAG 智能客服系统

基于 **Milvus 向量库 + BGE 嵌入 + 大模型（RAG）** 的电商智能客服系统。
**默认不内置任何知识库数据**，首次启动是一个空库；你可以一键造测试数据，也可以直接上传自己的资料（Word / PDF / CSV / TXT 等）。

- 后端（FastAPI）：`http://127.0.0.1:8001`
- 前端（Vite/React）：`http://localhost:5174`
- 接口文档（Swagger）：`http://127.0.0.1:8001/docs`

---

## 一、这个项目解决什么问题

电商售前售后客服常见痛点：

- **重复咨询占用人力**：发货进度、退换货、保修、发票这类重复问题每天被问几十上百次，回答口径还不统一。
- **知识分散难检索**：商品资料、物流规则、售后政策散落在 Word / PDF / Excel / FAQ 里，客服翻文档效率低。
- **大模型直接答会“幻觉”**：空口编造保修政策、价格、发货时效，风险高、不专业。
- **无法按商品与上下文精确作答**：追问“它怎么退”时，模型不知道“它”是哪件商品；同名商品也常常答串。
- **缺自动兜底**：用户已生气、触发敏感词、或库里根本没答案时，仍需人工介入，但没有自动机制。
- **缺观测**：答得准不准、转人工多不多、延时高不高，都无从量化。

本项目用 **RAG（检索增强生成）** 把企业文档向量化存进 Milvus，客服提问时**只基于你自己的资料回答**：
检索不到或分数过低就自动转人工，负面情绪 / 敏感词提前兜底，并提供知识库管理与观测统计面板。

---

## 二、主要功能

| 能力 | 说明 |
| --- | --- |
| 智能客服对话 | 基于知识库回答，返回“答案 + 是否转人工 + 命中来源” |
| 历史上下文扩写 | 追问/碎片句先合并最近一次提问再检索（“它怎么退”→ 继承前文商品） |
| 歧义澄清 | 同时命中“苹果”与“苹果手机”等并列商品时，给数字选项让用户确认 |
| 多轮购物推荐 | 问“推荐哪款耳机”→ 先问更看重降噪/续航/价格/…→ 按选项推荐对应商品 |
| 语音输入 | 输入框话筒：可走后端 ASR 接口（`.env` 配 `ASR_API_KEY`）或浏览器内置识别，语音转文字进输入框 |
| 商品自动识别 | 问题自带商品名（“xx耳机售后多久”）自动锁定商品；追问不丢主语 |
| 负面情绪识别 | 用规则打分提前识别抱怨/投诉/催单/情绪激动，**不等检索**直接转人工 |
| 敏感词拦截 | 命中身份证、验证码赌博等直接拦截并转人工，不进入检索与生成 |
| 防幻觉 | 检索分数低于阈值时不喂大模型、直接转人工；大模型自评兜底 |
| 知识库管理 | 多格式上传、列表、按关键词/文档类型检索、删除、内容指纹自动替换更新 |
| 品牌自动识别 | 上传含“品牌：XXX”的资料自动识别品牌，客服标题随之改为“品牌名 · 智能客服” |
| 观测统计 | 今日 / 近 7 天：问答量、转人工率、知识库未命中、平均延迟、转人工原因 Top |

---

## 三、安装

### 环境要求

- **Windows 10/11** + 已启动的 **Docker Desktop**（用于 Milvus 向量库）。没有 Docker 时可在配置里把 `VECTOR_BACKEND` 改为 `local` 用内存库演示。
- **Python 3.10 / 3.11 / 3.12**（3.13+ 缺少部分依赖预编译包，安装会失败）。
- **Node.js**（用于前端）。
- 一个 **OpenAI 兼容的大模型 API Key**（DeepSeek / 火山方舟 / 通义 / 智谱 / OpenAI 均可）。

### 安装步骤

1. 双击 `start.bat`。首次运行会自动：检查 Docker → 启动并等待 Milvus 就绪 → 创建 `.venv` 并安装依赖（约 3-8 分钟）→ 初始化一个**空知识库**。
2. 若首次自动生成了 `.env`，按提示打开填写 `LLM_API_KEY`，保存后重新运行 `start.bat`。
3. 另开一个终端启动前端：
   ```bash
   cd frontend
   npm install      # 首次
   npm run dev      # 默认 5174 端口，已把 /api 代理到 127.0.0.1:8001
   ```
4. 浏览器打开 `http://localhost:5174`。

> **端口注意**：本项目后端固定在 **8001**（`start.bat` / `frontend/vite.config.js` / `settings.py` 里 `API_PORT=8001`）。不要改到 8000——8000 常被其它程序占用导致起不来。

---

## 四、使用

### 1. 配置大模型 Key（必填）

复制 `.env.example` 为 `.env`，至少填写 `LLM_API_KEY`。不填也能启动，但只会返回“命中原文”，无法自然对话。

```bash
LLM_API_KEY=你的key
LLM_BASE_URL=https://api.deepseek.com/v1        # 兼容任何 OpenAI 格式后端
LLM_MODEL=deepseek-chat
```

### 2. 给知识库放数据（二选一）

**方式 A：一键造测试数据（推荐先跑通）**
双击 `generate_test_data.bat`，或执行：
```bash
.venv\Scripts\python.exe -m scripts.generate_test_data
```
它会清空当前知识库 → 在 `data/` 生成 6 份示例文档（2 件商品与物流/售后 FAQ/退换货/投诉处理 4 篇资料）→ 向量化并倒入 Milvus。

**方式 B：上传你自己的真实资料**
打开前端 `http://localhost:5174` → 「知识库管理」页 → 点击上传：

- 支持格式：`.md` `.markdown` `.txt` `.pdf` `.docx` `.csv` `.tsv`，可多选。
- 「文档类型」是**自由文本**，随便填（商品、售后、物流、退换货、发票、运费险、会员……不限于预置项）。
- 「商品编号」可选；商品资料建议填写，追问时系统可据此自动锁定该商品。
- 上传会自动识别/替换重复内容；含「品牌：XXX」的资料会自动识别品牌并更新客服标题。

### 3. 使用客服对话

前端左侧「客服对话」直接提问即可，支持多轮追问、商品推荐引导、歧义确认。系统答不上来时自动给出转人工提示。

### 4. 更新知识库

有两种方式，推荐都在「知识库管理」页完成：

- **整档替换**：在文档列表找到该文件 → 删除 → 重新上传同名新文件；系统按内容指纹去重，相同内容不会重复入库。
- **同名自动替换**：上传同名（或内容高度相似）的新文件，系统自动识别并替换覆盖旧内容，无需手动先删。
- 已上线的活动规则（如双十一）结束后，删除对应文档或上传覆盖版本即可让知识库随之更新。

### 5. 转人工接入

系统不会自己“呼叫”真人客服，而是把转人工事件作为接口信号暴露给业务方，由你的客服系统消费：

- 前端对话中命中转人工时，消息会标记「转人工」，并显示触发的**原因**（如“负面情绪:投诉”“知识库无答案”）。
- 后端 `/rag/chat` 返回结构里的 `need_human=true` + `human_reason` 即转人工信号：
  - 可对接企业微信/工单/坐席系统的 Webhook，收到 `need_human=true` 时自动创建工单或转给在线坐席；
  - 命中负面情绪、敏感词、重复质问、知识库无答案等场景都会给出对应 `human_reason`，便于区分拦截优先级。
- 相关话术可在 `settings.py` 的「转人工与风控」段修改：`NEGATIVE_REPLY`、`SENSITIVE_REPLY`、`NO_ANSWER_REPLY`、`REPEAT_QUESTION_LIMIT`。

### 6. 观测统计

前端左侧「观测统计」面板，有“今日 / 近 7 天”切换，展示：`总问答量`、`转人工率`、`知识库未命中`、`平均延迟`、`转人工原因 Top`。全部按真实会话日志统计，可点「清空」复位。

---

## 五、输入 / 输出示例

### 1. 前端对话（命中知识库）

> **用户**：星野T5耳机支持主动降噪吗？
> **客服**：支持的，星野T5耳机采用混合主动降噪，深度约 -45dB，并支持通透模式……
> 底部显示来源文档与相关度；`need_human=false`，不转人工。

### 2. API 对话请求与响应

```
curl -X POST http://127.0.0.1:8001/rag/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"user_001","query":"星野T5耳机续航多久"}'
```

```json
{
  "answer": "星野T5耳机单次续航约 8 小时，搭配充电仓总续航约 30 小时。",
  "need_human": false,
  "human_reason": "",
  "session_id": "user_001",
  "goods_id": "G10086",
  "kb_hit": true,
  "kind": "",
  "top_score": 0.86,
  "latency_ms": 620,
  "sources": ["goods/G10086/星野T5耳机.md"],
  "references": [
    {
      "source": "goods/G10086/星野T5耳机.md",
      "doc_type": "goods",
      "goods_id": "G10086",
      "rerank_score": 0.86,
      "preview": "星野T5耳机单次续航约 8 小时……"
    }
  ]
}
```

### 3. 转人工示例

> **用户**：快递太慢了，我要投诉！
> **客服**：理解您的心情，这件事情我已为您转接人工客服，尽快为您处理。
> 返回：`need_human=true`，`human_reason="负面情绪:投诉"`。

> **用户**：这个保修政策是什么（知识库里没有）
> **客服**：该问题暂未找到对应资料，请转人工客服为您核实，感谢理解～
> 返回：`need_human=true`，`human_reason="知识库无答案"`，`kb_hit=false`。

---

## 六、技术设计：向量化 / 切片 / 检索 / 重排为何自研而不用 LangChain

- 本项目在这四个环节直接使用底层引擎：`sentence-transformers`（`BGE`）做向量与本地重排、`pymilvus` 做 Milvus 检索和元数据过滤，而不是把它们包在 LangChain 里。
- 原因：LangChain 只是“包一层”，不会让效果更好；本项目把复杂度集中在真正影响体验的地方——**防幻觉阈值（低分不喂大模型、直接转人工）、商品元数据过滤、歧义澄清**，这些用 LangChain 反而要外包才能保住。
- 详细逐项对比见 `docs/项目功能与技术点.md` 的「#10 技术选型：LangChain 与自研直连的对比」。

### 会话主链路

商品识别 / 上下文扩写 → 风控（敏感词、负面情绪）→ 向量检索 + 元数据过滤 → 重排 → 阈值熔断 → 喂大模型生成 → 转人工判定 → 统计入库。

---

## 七、接口速查

| 接口 | 方法 | 入参 | 说明 |
| --- | --- | --- | --- |
| `/rag/chat` | POST | `session_id`、`query`、`goods_id?` | 智能客服对话（含转人工信号） |
| `/document/upload` | POST | `files[]`、`doc_type`、`goods_id?`、`category?`、`replace` | 上传入库，自动去重/替换 |
| `/document/sources` | GET | - | 列出知识库所有文档 |
| `/document/search` | POST | `keyword`、`goods_id?`、`doc_type?` | 关键词检索（可叠加文档类型过滤） |
| `/document/delete` | POST | `source`、`goods_id?`、`doc_type?` | 按来源删除文档切片 |
| `/document/ingest_dir` | POST | `path?` | 批量导入 `data/` 目录 |
| `/config/brand` | GET/POST | `brand_name` | 读取/设置客服品牌 |
| `/stat/get` | GET | `days` | 观测统计（今日/近 7 天） |
| `/stat/clear` | POST | - | 清空观测统计 |
| `/session/list` `/session/detail` `/session/clear` | GET/GET/POST | `session_id?` | 会话管理 |
| `/health` | GET | - | 健康检查 |

---

## 八、常用配置（`settings.py` / `.env`）

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` `LLM_MODEL` `LLM_BASE_URL` | DeepSeek `deepseek-chat` | 对话大模型（任意 OpenAI 兼容后端） |
| `EMBEDDING_MODEL` | 本地 `models/bge-large-zh-v1.5` | 向量模型 |
| `EMBEDDING_DEVICE` | `cpu` | 有 GPU 改 `cuda` |
| `VECTOR_BACKEND` | `milvus` | 没 Docker 改 `local`（内存向量库） |
| `RERANK_BACKEND` | `none` | `local` / `dashscope` / `none`（关重排用向量分） |
| `VECTOR_TOP_K` / `RERANK_TOP_N` | `7` / `3` | 召回 / 进 Prompt 条数 |
| `RERANK_SCORE_THRESHOLD` | `0.30` | 低于此分截断低相关片段 |
| `NO_ANSWER_THRESHOLD` | `0.35` | 低于此分直接转人工（防幻觉） |
| `REPEAT_QUESTION_LIMIT` | `3` | 重复问相似问题达到次数即转人工 |
| `SESSION_MAX_TURNS` | `3` | 会话上下文轮数 |
| `DATA_DIR` | `./data` | 知识库目录 |
| `API_PORT` | `8001` | 后端端口 |
| `ASR_ENABLED` `ASR_API_KEY` `ASR_BASE_URL` `ASR_MODEL` | `false` / - / OpenAI / `whisper-1` | 语音输入走后端 `/asr` 接口（不配则用浏览器识别） |

改完切片/检索配置后需重建知识库：`.venv\Scripts\python.exe -m scripts.rebuild_kb`。

---

## 九、常见问题

- **Milvus 起不来？** 确认 Docker Desktop 已启动、`19530` 端口没被占；看日志 `docker compose logs milvus`（首次 1-2 分钟）。
- **端口 8001 被占？** 找到占用者停掉，或在 `settings.py` + `frontend/vite.config.js` 里统一改端口。**别用 8000**。
- **知识库片段数显示不对？** 删除后 Milvus 的 `num_entities` 会短暂滞后；系统按实际行数统计，随后自动修正。
- **上传带“品牌：”的文件没改标题？** 只有当前还没设品牌时才会自动识别；也可在「知识库管理」页手动保存品牌。
- **没有知识库数据，问什么都不懂？** 先跑 `generate_test_data.bat`，或在页面上传真实资料。
- **问“推荐哪款耳机”不直接答？** 这是有意设计：先让你选择更看重的方面（降噪/续航/价格/…），再按选项精准推荐，避免答非所问。
