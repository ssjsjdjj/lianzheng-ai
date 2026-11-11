# 链证 AI 软件依赖风险工作台

一个可本地运行的 GraphRAG 应用原型。导入 CycloneDX JSON 或 npm package-lock v2/v3，匹配 OSV 已知漏洞，查看从项目根节点进入组件的多条路径，以原文证据回答问题，再登记修复任务并使用新的实际依赖清单复核。

当前版本 v0.6。新增真实锁文件导入、逐条人工证据复核、带版本防覆盖的修复任务单，以及本应用聊天调用限制。优先提供 OpenAI / GPT 官方 Responses API 接入，保留 DeepSeek 与兼容接口。本轮 v0.6.0 真实 GPT 问答与引用验收通过 3/3，独立于合成评测和公开项目导入检查统计；这不是回答准确率或业务上线证明。详情见 [验证记录](VALIDATION.md)。

### v0.6 工作流程

- 导入 `package-lock.json` v2/v3，按安装位置和可确定的依赖查找关系生成清单。保留同包不同位置、精确版本和依赖类别，缺失关系保留覆盖提示；不安装依赖、不执行脚本、不联网推断缺失边。
- 在模型回答中逐条核对“结论—原句—支持范围”，人工标注支持、部分支持、证据不足或来源冲突并保存备注。默认待人工复核，不使用模型自动语义分数；内容指纹和记录版本防止旧标注套用到变化后的结论。
- 从当前风险创建修复任务，记录负责人、候选边界、人工检查项和审计。更新任务或提交新清单复核必须携带最新 `revision`，拒绝过时界面覆盖；清单复核通过不代表业务测试通过、全部漏洞消除或可以上线。
- “用量与限制”记录本版启用后的聊天请求，包含连接测试和失败请求；设置每日次数及可选金额阈值。未知费用保留预留，不视为零；本地阈值不是账户账单上限，不涵盖独立 Embedding 和其他应用。
- HTML 及 JSON 报告保留人工复核和任务结果，明确区分当时的清单复核凭据、人工勾选记录与待完成事项。

### 证据导航与离线对照

- 系统先在完整候选证据内按问题词项排序片段，再限制发送给 GPT 的输入长度；每份证据最多 4 条原句，保留 Unicode 起止位置并回核原文。它是词项相关性选择，不是语义蕴含判定。
- 回答中的“路径 1 / 路径 2”可切到图谱，单独高亮节点与依赖边；支持返回问答、恢复全部路径。切换快照会清除旧高亮。
- “查看原文”自动展开证据并高亮对应原句；重复句按原始位置定位，历史回放也可使用。图引用可直接跳到对应路径。
- 首页“打开离线对比评测”展示固定样本、指标定义与失败记录。60 个检索问题 + 60 个长文档片段问题，按 6 个合成项目划分 dev/test；三种检索和两种片段策略共 300 条运行记录。不是 300 个独立问题，也不是模型正确率。

复现开发集：`python scripts/benchmark.py --split dev --output evaluation/reproduced-dev.json`。冻结测试集使用 `--split test`；不要根据其结果调参再称作未见测试集。完整报告：[HTML](evaluation/benchmark-results.html)、[JSON](evaluation/benchmark-results.json)、[样本与标注](evaluation/benchmark-fixture.json)。TF-IDF 只是词项向量基线，真实语义 embedding 对比未运行。

## 当前已经实现

- CycloneDX 1.4–1.7 JSON 导入、5 MB 大小限制、组件身份归一化及数据质量提示。
- npm package-lock v2/v3 导入、原始锁文件保留与下载、可追溯的安装位置与依赖解析提示。
- 每个 `bom-ref` 独立保存；同版本在不同位置的出现不会被合并。
- 真实 OSV 查询冻结快照、手动在线扫描、分页处理、精确包版本缓存；未查询和失败均不视为无漏洞。
- 完整可达性计算、受限代表路径展示、交互式 SVG 图谱及节点原始 JSON 定位。
- 图事实与 BM25 公告检索、可配置的真实 Embedding 检索与 RRF 融合。
- 无密钥即可使用的证据模板解释；GPT 官方模式使用 Responses API，DeepSeek 与其他兼容模式使用 `chat/completions`。
- 引用定位、引用编号存在性检查、问题记录、JSON 报告和原始 SBOM 下载。
- Markdown 与纯文本项目文档导入，绑定快照、包名、来源版本及可选目标版本，引用定位到原始行列。
- 文档原文预览与移出检索库；重新扫描不删除项目文档，历史问答保留当时引用。
- 最近 20 条问答可从界面恢复；切换快照或风险时，过期响应不会覆盖当前选择。
- 快照比较，区分已消除、仍保留、新增，以及覆盖不足时的“未观察到”。
- 本机模型设置，最小真实 API 请求验证，保留返回模型、请求 ID、耗时与 token 用量；API 密钥不会回传页面。
- OpenAI 官方模式默认候选 `gpt-6-luna`，使用严格 JSON Schema、`store:false` 和有界输出；实际模型权限以 API 账户与连接验证为准。
- 模型解释逐项引用证据并提供原文摘录；不存在的编号、无法核对的摘录和范围外版本会触发本地回退。
- GPT 从系统生成的原文片段目录中选择引用 ID，由服务器回填原句与来源，减少模型改写引文的错误；语义支持仍需人工复核。
- 模型输入的序列化消息总量最多 48,000 个 UTF-8 字节，不等同于 token 数；缩短或省略证据时保留完整本地原文和预算记录。
- 多轮追问显式引用上一条回答，仅在同一快照及检索模式内继承目标版本，每轮重新检索证据。
- 问答显示处理流程与实际等待时长；“停止等待”只停止浏览器等待，服务端仍可能继续处理和计费。
- 分步演示控制条、准备状态、本次模型回答计数与可打印 HTML 报告，区分模型返回、本地解释与历史回放；无密钥也可演示本地证据和修复对比。

本版将方案中的 React 与 Neo4j 暂时替换为无构建依赖的原生 JavaScript 和 SQLite 存储的图结构，方便先跑通核心闭环。依赖关系由程序计算，文本解释与模型接口独立，后续可替换前端和图数据库。

## 公开真实项目输入

仓库附带两个公开项目固定提交中的原始锁文件及许可证：`ietf-tools/datatracker`（提交 `dd2518248e4b32a9c814e9346d9451e9f76d1e75`，BSD-3-Clause）和 `mermaid-js/mermaid-cli`（提交 `1423a0d7967d275a9d360ba0617f569550827c8b`，MIT）。来源链接、文件 SHA-256 和许可证记录见 [来源清单](fixtures/public-projects/sources.json)。

两个输入均为 v3，当前导入器检查结果均为 `supported-incomplete`，保留覆盖不完整提示；缺少可定位的可选或 peer 依赖时不补造边。此结果仅说明冻结输入的导入兼容性，没有执行安装、构建、漏洞查询、运行时检测或模型问答，不属于客户试用或生产安全效果证明。[检查结果](evaluation/public-project-results.json)

离线复现：`python scripts/verify_public_projects.py --require-supported`。它核对随仓库保存的来源清单和文件哈希，不联网重新验证上游，也不执行依赖脚本。导入器目前不支持 v1、workspace/link、git/file 安装来源；别名必须具有明确且相符的 `npm:` 声明与实际包身份。不能由锁文件单独证明 semver 约束满足或运行环境实际安装状态。

## 快速启动

需要 Python 3.11 或以上。默认仅监听本机 `127.0.0.1`，首次安装依赖需要联网。

Windows PowerShell，在项目目录执行：

```powershell
.\start.ps1
```

若当前 PowerShell 执行策略阻止脚本，可使用以下手动命令，无需修改系统执行策略：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn lianzheng.app:app --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765>。交互式 API 文档位于 <http://127.0.0.1:8765/docs>；其 Swagger 资源需要联网，离线可直接读取 `/openapi.json`，应用主界面没有 CDN 依赖。

macOS 或 Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn lianzheng.app:app --host 127.0.0.1 --port 8765
```

Docker 可选：

```bash
docker compose up --build
```

SQLite 数据保存在 `data/lianzheng.sqlite3`；Docker 使用命名卷。请在服务停止后备份数据库。`requirements-lock.txt` 保存本次验证的完整 Python 依赖版本；复现环境可安装该文件。

## 三至五分钟演示

1. 选择“初始快照”，点选 `GHSA-29mw-wpgm-hmr9`，查看两条 lodash 引入路径。
2. 点击“这个漏洞从哪里来”，打开证据原文，核对版本和查询时间。
3. 切换“文本 RAG 对照”，观察其不会输出结构化路径判断。本功能只是对照入口，尚未构成正式评测。
4. 进入“快照对比”，先比较初始与“仅升级报表路径”：目标漏洞仍保留。
5. 将修复后切换为“两条路径均已升级”：冻结查询记录中的公告已无匹配位置。
6. 在“修复任务”中从当前公告建单，登记负责人及检查步骤，分别提交部分修复和完整修复快照，核对任务结果与凭据。随后可导入自有 SBOM 或 `package-lock.json`；没有本地精确版本记录的组件显示“未扫描”，点击“在线更新 OSV”后才发起查询。

演示中的业务组件 `@demo/report-kit`、`@demo/export-kit` 与拓扑是人为构造的，不能当成真实用户项目。`fixtures/osv-cache.json` 是开发时真实取得的 OSV 响应，包含来源与获取时间；公开 npm registry 的 latest 查询仅用于生成演示版本，不会在运行时自动决定升级目标。

4.17.21 在所保存的 OSV 数据中仍有其他漏洞记录，系统不会把针对某个公告的修复等同于全部风险消除。所有“无匹配”表述仅针对选中的清单和数据快照。

## 文档与迁移要求演示

1. 选择“初始快照”，进入“项目文档”并点击“导入文档”。
2. 选择 `lodash @ 4.17.20`，目标版本填写 `4.18.1`；上传 `fixtures/migration-demo.md` 并保存。
3. 回到证据问答，提问“升级到 4.18.1 有哪些迁移检查要求”，查看项目文档、原始行号与公告引用。
4. 将目标版本改问为 `4.17.21`，这份声明适用 `4.18.1` 的迁移文档不会进入回答。
5. 在“问答记录”恢复较早的回答；移除文档后，后续检索不再使用它，历史回答仍保留原始引用。

该样例是人为编写的项目流程示例，不是官方迁移文档。真实项目应导入获授权的文档，并自行核对适用范围和内容真实性。系统不自动抓取来源链接，不把导入者声明当成兼容性保证。

文档输入仅接受 UTF-8 Markdown 或纯文本，正文最多 200000 字符。当前快照最多 50 份文档、2000 个片段；单份文档最多 300 个片段。导入完全相同的内容与元数据不会重复建库。文档按标题分块，超长行也保留可复核的行列位置。

## 模型与向量服务

优先打开 `http://127.0.0.1:8765/?setup=model`，选择“OpenAI / GPT 官方”，使用 `https://api.openai.com/v1` 和默认候选模型 `gpt-6-luna`，在本机窗口填写自己的 OpenAI API Key，点击“测试并保存”。可以改填 API 账户可用的其他模型。连接验证会发起一次最小 API 请求，成功后才记录验证状态；它只验证连接，不代表实际问答已经验收。密钥不要发到聊天、普通问答框或版本库。

已有 ChatGPT Pro 的用户，可先按 [OpenAI 官方 API credits 领取说明](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)检查资格、关联自己的 API 组织并领取额度，再在 API 平台创建项目使用的 API Key。会员登录不会自动连接到本项目，额度是否到账及剩余金额以官方账单页为准。

DeepSeek 仍可在同一设置窗口选择“DeepSeek 官方”，使用 `https://api.deepseek.com` 和 `deepseek-flash`；其他服务选择对应兼容模式。更换服务商或端点后需要填写相应密钥并重新验证。

Windows 下记住的密钥使用当前账户 DPAPI 加密；Linux/Docker 下保存为权限受限的本机文件。不记住时只保留到进程结束。模型配置位于 `data/model-settings.json`，不进入源码包或 Docker 构建上下文；API 的 GET 响应不包含密钥。更换账户或操作系统时需要重新填写。

未连接模型时默认本地证据解释；通过连接验证后默认启用模型辅助解释，也可以手动取消。问题范围仍由当前选中公告与版本约束限定，多漏洞问题需要拆分。模型解释不能覆盖结构化影响判断，未知的兼容性和实际可利用性仍保留未知。

GPT 官方模式使用 `POST /v1/responses`，设置 `store:false`、严格 JSON Schema 和默认 `max_output_tokens=2400`。`gpt-6-luna` 默认使用 `reasoning.effort=none`；已识别的 GPT-6 Astra / GPT-6.1 Sol 使用 `low`，不发送不适用的 `temperature`。`store:false` 是本次 Responses 请求的存储设置，不改变服务商适用的数据政策。GPT 返回正文和 `quote_ids`，Schema 将可选 ID 限制在本轮原文目录内；服务器回填来源与原句后，仍检查引用、摘录和版本范围。目录每份证据最多取 4 个连续原文片段、每段最多 200 字符，也计入输入预算；目录不保证覆盖全文。

环境变量也可用于配置。PowerShell 示例：

```powershell
$env:LZ_LLM_PROVIDER = 'openai'
$env:LZ_LLM_BASE_URL = 'https://api.openai.com/v1'
$env:OPENAI_API_KEY = 'your-openai-api-key'
$env:LZ_LLM_MODEL = 'gpt-6-luna'
# 可选：配置真实语义向量召回
$env:LZ_EMBEDDING_BASE_URL = 'https://your-provider.example/v1'
$env:LZ_EMBEDDING_API_KEY = 'your-key'
$env:LZ_EMBEDDING_MODEL = 'your-embedding-model'
.\start.ps1
```

DeepSeek 可改为 `LZ_LLM_PROVIDER=deepseek`、`LZ_LLM_BASE_URL=https://api.deepseek.com`、`LZ_LLM_MODEL=deepseek-flash`，并设置 `DEEPSEEK_API_KEY`；通用 `LZ_LLM_API_KEY` 如已设置，会优先用于所选端点，应核对其所属服务商。

Base URL 应指向 API 前缀，不包含 `/responses`、`/chat/completions` 或 `/embeddings`。模型设置支持读取项目根目录 `.env` 中的 `LZ_LLM_*`、`OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`；本机设置优先于系统环境，系统环境优先于该文件。向量配置仍从进程环境读取。Docker Compose 也可将项目 `.env` 的变量传入容器。

Embedding 必须返回 `data: [{index, embedding}]`。应用的模型解释要求 JSON claims，每项有正文、真实证据 ID 及可核对的短原文摘录；DeepSeek 调用显式启用 JSON 输出、关闭思考模式，默认输出预算为 2400 tokens。单次问答最多发起一次聊天模型请求，不自动重复失败请求；格式、引用或摘录校验失败时回退本地结果，已发生的调用仍可能计费，返回的用量元数据会尽量保留。

模型消息的序列化 UTF-8 总量受 48,000 字节预算约束。系统缩短证据片段、减少上文或省略候选证据，并记录 `model_budget`；仍超过预算时不发起模型调用。这个限制不是 48,000 tokens，也不保证固定费用。模型只能引用本次实际收到的片段，完整原文仍留在本地引用区。

界面和报告展示实际返回的 token 用量，仅在模型、服务档位和计费用量字段都已知时给出费用估算；缺失信息显示“未提供”，不当成零费用。估算以服务商实际账单为准，可能不含税费或地区附加项。“停止等待”只停止浏览器等待，服务端可能继续完成请求并产生费用；稍后可刷新问答记录。历史回放展示当时的回答与用量，不重新调用模型。

本版聊天用量账本从 v0.6 启用后开始记录，按 UTC 日期统计。连接测试、失败请求、被引用校验拒绝的模型返回均计入请求次数；被守卫拦截而未发出的请求不计为新调用。金额阈值采用已知费用估算或保守预留；当前仅为官方 `gpt-6-luna` 默认档位提供预留，无法预估的模型在开启金额阈值时会被阻止。任何未知、未预留的历史费用都会阻止后续受金额阈值约束的请求。它不控制独立 Embedding、在线漏洞查询或其他应用，也不是供应商账单硬上限。

未完成请求不会仅因等待较久、换日或重启而自动释放。若进程意外中断遗留 `in_flight` 票据，系统会保留其预算占用并阻止后续聊天调用，需要先核对供应商请求状态和本地记录，由维护者确认处理。没有增加自动重试。

连接成功之后运行 `.\.venv\Scripts\python.exe scripts/verify_live_model.py`，完成三轮真实问答验收；结果保存到 `evaluation/live-model-results.json`，旧报告归档在本机 `evaluation/live-model-history/`，失败请求的可用用量也保留。该脚本会调用 API，只接受已验证的 OpenAI 或 DeepSeek 官方端点，拒绝把本地或兼容模拟服务当成官方验收。本轮 v0.6.0 的三轮 GPT 验收通过 3/3；计费用量明细不全，不能精确计价，保守预算占用并非实际账单。详情见 [VALIDATION.md](VALIDATION.md)；源码不附带密钥或私有真实问答明细，其他机器需要自行配置。

v0.2 修复了纯语义召回被零关键词得分过滤的问题，缓存会去重并校验向量索引、维度和有限数值。候选超过 80 个片段时，向量精排覆盖 BM25 前 80 个，其余仍参与关键词排序；界面回答会提示此限制。文本 RAG 对照的模型上下文不包含图路径和图统计，但仍共享版本身份过滤。

引用编号和摘录存在性校验不能证明语义蕴含，模型解释需要人工核对。真实模型模式中，已计算的代表依赖路径也会以图证据形式引用，并带原始 JSON 位置；文本对照模式不接收这些图证据。外部服务只接收当前问题所需的证据、有限的同范围历史问题与版本信息，不接收 API 密钥正文或其他项目历史。

参赛演示操作、真实验收命令和失败处理见 [DEMO_GUIDE.md](DEMO_GUIDE.md)。界面可载入专用演示资料，逐步执行图谱、模型问答、迁移追问和两种修复对比，再导出不含密钥的 HTML 报告。

## 架构与目录

```text
浏览器界面
  └─ FastAPI
      ├─ CycloneDX / npm 锁文件解析 → 组件出现位置与依赖边 → 完整可达性与代表路径
      ├─ OSV 冻结/在线查询 → 精确版本匹配与来源记录
      ├─ 图事实与版本过滤 → BM25 / 可选 Embedding → 公告与项目文档证据
      ├─ 证据模板 / 可选模型解释 → 引用检查 → 问答记录 → 人工支持范围复核
      ├─ 修复任务 → 带版本的人工更新 → 新清单复核凭据
      └─ SQLite → 快照、查询缓存、文档与问答、复核记录、任务审计、聊天用量账本
```

```text
lianzheng/domain.py       清单解析 身份规则 可达性与路径
lianzheng/lockfiles.py    npm 锁文件安装位置与依赖关系解析
lianzheng/osv.py          OSV 查询 分页 缓存 公告证据
lianzheng/retrieval.py    BM25 可选向量融合与模型适配器
lianzheng/knowledge.py    精确版本文档绑定 原文分块与行列定位
lianzheng/providers.py    OpenAI Responses / DeepSeek / 兼容协议及脱敏错误处理
lianzheng/budget.py       模型输入字节预算 片段取舍与预算记录
lianzheng/call_control.py 聊天调用次数 金额预留 并发与重复请求守卫
lianzheng/claim_review.py 人工证据支持范围 内容指纹 复核审计
lianzheng/remediation.py  修复任务 记录版本 新清单复核凭据
lianzheng/settings.py     本机配置 连接验证 密钥保存
lianzheng/reports.py      可打印的证据与演示报告
lianzheng/service.py      导入 分析 问答 对比业务逻辑
lianzheng/store.py        SQLite 持久化
lianzheng/app.py          API 静态页面与本地写入保护
static/                  响应式交互界面
fixtures/                三份演示清单与真实公告冻结记录
tests/                   核心逻辑和 API 回归测试
scripts/evaluate.py      小型功能验收报告
scripts/verify_public_projects.py 公开固定版本锁文件结构检查
```

## API

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 健康、模型配置状态、公告快照时间 |
| GET | `/api/model/settings` | 脱敏模型状态与最近连接验证 |
| POST | `/api/model/connect` | 最小真实请求验证并保存本机模型配置 |
| GET | `/api/model/usage` | 本版聊天用量、保守预留与跨日未完成请求 |
| PUT | `/api/model/usage/policy` | 更新每日聊天次数及可选金额阈值 |
| GET | `/api/snapshots` | 快照列表 |
| POST | `/api/snapshots` | 导入 `{bom, project, label}`；`bom` 可为 CycloneDX 或 package-lock v2/v3 |
| GET | `/api/snapshots/{id}?focus={vulnerability}` | 图、风险、证据和数据质量 |
| POST | `/api/snapshots/{id}/scan` | `{live: true}` 在线更新；false 使用冻结或缓存 |
| POST | `/api/snapshots/{id}/ask` | `{question, focus, mode: graph/text, use_model, parent_id?}` |
| GET | `/api/snapshots/{id}/history` | 最近 20 条问答 |
| GET | `/api/snapshots/{id}/history/{answer_id}/reviews` | 逐条原文匹配与人工支持范围记录 |
| PUT | `/api/snapshots/{id}/history/{answer_id}/reviews/{claim_index}` | 保存人工状态与备注，必须携带内容 `fingerprint` 和最新 `revision` |
| GET / POST | `/api/snapshots/{id}/tasks` | 列出或从当前公告创建修复任务 |
| GET / PATCH | `/api/tasks/{task_id}` | 读取或更新任务；更新必须携带最新 `revision` |
| POST | `/api/tasks/{task_id}/verify` | 使用 `after_snapshot_id` 与最新 `revision` 提交新清单复核 |
| GET | `/api/tasks/{task_id}/report` | 导出任务与当时的清单复核凭据 |
| GET | `/api/snapshots/{id}/documents` | 已导入文档的摘要与适用范围 |
| POST | `/api/snapshots/{id}/documents` | 导入 `{title,package,version,target_version?,kind,text,url?}` |
| GET | `/api/snapshots/{id}/documents/{document_id}` | 原文、元数据与分块 |
| DELETE | `/api/snapshots/{id}/documents/{document_id}` | 从该快照后续检索中移除 |
| GET | `/api/compare?before={id}&after={id}` | 同项目两份快照对比 |
| GET | `/api/snapshots/{id}/bom` | 导出原始清单 |
| GET | `/api/snapshots/{id}/lockfile` | 下载该快照保留的原始锁文件；非锁文件快照不适用 |
| GET | `/api/snapshots/{id}/report?format=json/html` | 导出分析与问答 JSON 或可打印 HTML |
| POST | `/api/demo/prepare` | 幂等准备专用演示文档与快照 |
| GET | `/api/demo/report` | 演示对比与实际问答报告 |

## 测试与验收

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/evaluate.py
```

测试覆盖多路径与部分修复、深路径和环、悬空依赖、版本身份冲突、未知项、OSV 分页与失败、模型虚构引用、API 文件导入与同源保护等。功能验收结果保存到 `evaluation/smoke-results.json`。

固定演示功能集和合成对照评测不能作为真实业务准确率基准，也不能据此宣称 GraphRAG 优于文本 RAG。公开锁文件检查仅验证导入结构；本轮三次真实模型请求只验证固定问答流程与引用约束。独立专家标注的真实问题集、用户任务耗时试验和商业验证仍需后续建设。

v0.6 浏览器人工交互验收通过 15/15，覆盖任务与人工复核保存、双标签页冲突、快照隔离、用量设置、真实锁文件导入、大列表展开和移动布局；主工作区只回放已有 GPT 回答，未新增模型调用。工作流检查使用独立数据库，人工复核夹具明确标识。逐项观察与边界见 [验收记录](evaluation/ui-v06-checks.json)，这不是自动浏览器测试或语义准确率成绩。

浏览器检查可选安装 Node.js 与 Playwright 后运行，先保持应用服务在运行：

```bash
npm install
# Windows 默认使用已安装的 Microsoft Edge；其他系统先安装 Chromium
npx playwright install chromium
npm run test:browser
```

`LZ_TEST_URL` 可指向独立测试服务地址；`LZ_TEST_IMPORT=1` 会额外上传一份样例清单，建议对独立测试数据库启用。截图保存在 `test-results`。此脚本依赖内置冻结演示集，不应使用它评估实时漏洞数据的准确率。

新增 `npm run test:knowledge` 覆盖文档导入、版本隔离、原文定位、历史回放、过期响应保护与移除。该脚本默认请求 `http://127.0.0.1:8766`，需要先在独立数据库上启动服务；它会导入并移除一份测试文档。PowerShell 示例：

```powershell
$env:LZ_DATABASE = Join-Path $env:TEMP 'lianzheng-ui-test.sqlite3'
.\.venv\Scripts\python.exe -m uvicorn lianzheng.app:app --host 127.0.0.1 --port 8766
# 在另一个终端执行 npm run test:knowledge
```

`npm run test:models` 使用 `tests/mock_provider.py` 的本地协议模拟服务验证模型设置、密钥不回显、原文校验、多轮上下文、演示流程及回退。先在独立终端运行 `.\.venv\Scripts\python.exe tests/mock_provider.py`，并将应用指向独立测试数据库和 8766 端口。该流程不是大模型实测，不应对外展示为 DeepSeek 真实验收。真实验收只运行 `scripts/verify_live_model.py` 并保留实际报告。

`npm run test:gpt` 通过浏览器路由模拟 OpenAI 配置、模型返回和用量元数据，验证 GPT 预设、费用与未知值、输入预算、停止等待、本地演示和移动布局。它不访问 OpenAI，不需要 API Key，也不代表真实 GPT 推理或账户额度验收。使用独立应用数据库运行，结果和截图保存在 `test-results`。各版本已完成的检查及待验收事项见 [VALIDATION.md](VALIDATION.md)。

## GitHub 持续检查

仓库的 GitHub Actions 会在推送、拉取请求和手动触发时，使用 Python 3.12 执行单元测试、固定演示集功能检查和离线开发集对照。检查报告作为 `local-functional-checks` 构件保存 7 天。该流程不需要配置 API 密钥，模型相关测试使用模拟服务，不能替代 OpenAI / DeepSeek 官方真实问答验收。

本机 `.env` 及其变体、数据库、模型配置、浏览器测试结果和真实模型验收明细均已加入忽略规则；`.env.example` 可随源码提交。真实模型接入状态仍以本机验收记录为准。

## 已知边界与下一步

- 当前仅支持有精确 npm purl 的组件，执行必要的结构校验，没有实现 CycloneDX 全量 JSON Schema 校验。必须声明根节点；缺少依赖列表会产生覆盖警告。
- 锁文件仅支持 npm v2/v3 的明确安装位置与可确定关系；workspace/link、git/file 来源或无法核实的别名会被拒绝。缺失依赖声明不补造关系，保留结构覆盖提示；锁文件不证明实际安装和 semver 兼容。
- 默认显示最多 5 条代表路径、最多 12 跳，枚举有资源上限；完整可达性独立计算。图形最多显示 40 个节点，优先展示选中路径并提示截断；邻接索引避免反复扫描全部边。
- 项目文档支持精确来源版本与目标版本，不解释版本范围；尚未实现 PDF、网页抓取和文档真实性校验。不能保证候选升级兼容、依赖解析成功或可上线。
- 同项目身份目前以项目名称关联；组件变化仅对同名、同 `bom-ref` 做确定比较，不猜测跨生成器的组件位置映射。
- 当前比较是所选公告查询快照下的观察结果。两侧公告获取时间不一致时，消失项保守标记为“未观察到”，不归因为代码升级；正式实验需要冻结统一的公告数据集。
- 单次在线扫描最多 100 个精确包版本；真实网络请求可能耗时，原型没有生产任务队列或并发扫描调度。
- 只有本机单用户模式，无登录与多租户隔离，不应直接暴露公网。默认不开启任意文档 URL 抓取，也不执行上传文件中的代码。
- 人工复核没有独立专家身份认证；任务检查项也是使用者自填记录。任务版本与内容指纹用于防覆盖，不能替代证据真实性、实际构建或业务验收。
- 真实模型验收需要本机有效 API 密钥和可用余额；没有通过验收时不宣称已完成真实接入或可无条件现场演示。后续还需独立评测集、扫描任务进度与真实用户试用，再扩展持久化向量库、Neo4j、团队权限与 CI 集成。

## 公开来源

- [CycloneDX 数据模型](https://cyclonedx.org/specification/overview/)
- [OSV 查询 API](https://google.github.io/osv.dev/post-v1-query/)
- [OSV 数据来源与许可说明](https://google.github.io/osv.dev/data/)
- [OSV-Scanner](https://github.com/google/osv-scanner)
- [OpenAI API credits 领取说明](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
- [OpenAI 模型与迁移说明](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI 结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)
- [DeepSeek 首次调用与当前模型](https://api-docs.deepseek.com/)
- [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)

公告冻结内容应保留原始署名与来源；对外打包、再分发或商业使用前需按各原始数据源核对许可。
