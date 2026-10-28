# 链证 AI 软件依赖风险工作台

一个可本地运行的 GraphRAG 应用原型。导入 CycloneDX JSON，匹配 OSV 已知漏洞，查看从项目根节点进入组件的多条路径，以原文证据回答问题，并比较修复前后的实际依赖清单。

当前版本 v0.3。提供 DeepSeek 官方 API 设置与真实连接验证、带原文摘录校验的模型解释、多轮追问和参赛演示流程。模型是否已实际连接，以运行时状态和真实验收记录为准；代码接入与模拟测试不等于已完成真实模型验收。

## 当前已经实现

- CycloneDX 1.4–1.7 JSON 导入、5 MB 大小限制、组件身份归一化及数据质量提示。
- 每个 `bom-ref` 独立保存；同版本在不同位置的出现不会被合并。
- 真实 OSV 查询冻结快照、手动在线扫描、分页处理、精确包版本缓存；未查询和失败均不视为无漏洞。
- 完整可达性计算、受限代表路径展示、交互式 SVG 图谱及节点原始 JSON 定位。
- 图事实与 BM25 公告检索、可配置的真实 Embedding 检索与 RRF 融合。
- 无密钥即可使用的证据模板解释；可选兼容 `chat/completions` 协议的模型辅助解释。
- 引用定位、引用编号存在性检查、问题记录、JSON 报告和原始 SBOM 下载。
- Markdown 与纯文本项目文档导入，绑定快照、包名、来源版本及可选目标版本，引用定位到原始行列。
- 文档原文预览与移出检索库；重新扫描不删除项目文档，历史问答保留当时引用。
- 最近 20 条问答可从界面恢复；切换快照或风险时，过期响应不会覆盖当前选择。
- 快照比较，区分已消除、仍保留、新增，以及覆盖不足时的“未观察到”。
- 本机模型设置，最小真实 API 请求验证，保留返回模型、请求 ID、耗时与 token 用量；API 密钥不会回传页面。
- 模型解释逐项引用证据并提供原文摘录；不存在的编号、无法核对的摘录和范围外版本会触发本地回退。
- 多轮追问显式引用上一条回答，仅在同一快照及检索模式内继承目标版本，每轮重新检索证据。
- 分步演示控制条与可打印 HTML 报告，区分真实模型结果、本地解释与历史回放。

本版将方案中的 React 与 Neo4j 暂时替换为无构建依赖的原生 JavaScript 和 SQLite 存储的图结构，方便先跑通核心闭环。依赖关系由程序计算，文本解释与模型接口独立，后续可替换前端和图数据库。

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

## 三分钟演示

1. 选择“初始快照”，点选 `GHSA-29mw-wpgm-hmr9`，查看两条 lodash 引入路径。
2. 点击“这个漏洞从哪里来”，打开证据原文，核对版本和查询时间。
3. 切换“文本 RAG 对照”，观察其不会输出结构化路径判断。本功能只是对照入口，尚未构成正式评测。
4. 进入“快照对比”，先比较初始与“仅升级报表路径”：目标漏洞仍保留。
5. 将修复后切换为“两条路径均已升级”：冻结查询记录中的公告已无匹配位置。
6. 点击“导入 SBOM”，上传自有清单。没有本地精确版本记录的组件显示“未扫描”，点击“在线更新 OSV”后才发起查询。

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

优先打开 `http://127.0.0.1:8765/?setup=model`，选择 DeepSeek 官方，保持 `https://api.deepseek.com` 和 `deepseek-flash`，在本机窗口填写自己的 API 密钥并点击“测试并保存”。该操作会发起一次真实、最小 JSON 请求；验证成功才会记录成功状态。密钥不要发到聊天、普通问答框或版本库。

Windows 下记住的密钥使用当前账户 DPAPI 加密；Linux/Docker 下保存为权限受限的本机文件。不记住时只保留到进程结束。模型配置位于 `data/model-settings.json`，不进入源码包或 Docker 构建上下文；API 的 GET 响应不包含密钥。更换账户或操作系统时需要重新填写。

未连接模型时默认本地证据解释；通过连接验证后默认启用模型辅助解释，也可以手动取消。问题范围仍由当前选中公告与版本约束限定，多漏洞问题需要拆分。模型解释不能覆盖结构化影响判断，未知的兼容性和实际可利用性仍保留未知。

模型辅助解释使用可配置的兼容接口。PowerShell 示例：

```powershell
$env:LZ_LLM_BASE_URL = 'https://your-provider.example/v1'
$env:LZ_LLM_API_KEY = 'your-key'
$env:LZ_LLM_MODEL = 'your-model'
# 可选：配置真实语义向量召回
$env:LZ_EMBEDDING_BASE_URL = 'https://your-provider.example/v1'
$env:LZ_EMBEDDING_API_KEY = 'your-key'
$env:LZ_EMBEDDING_MODEL = 'your-embedding-model'
.\start.ps1
```

Base URL 应指向 API 前缀，不包含 `/chat/completions` 或 `/embeddings`。v0.3 的模型设置支持读取项目根目录 `.env` 中的 `LZ_LLM_*` 或 `DEEPSEEK_API_KEY`；本机设置优先于系统环境，系统环境优先于该文件。向量配置仍从进程环境读取。Docker Compose 也可将项目 `.env` 的变量传入容器。

Embedding 必须返回 `data: [{index, embedding}]`。应用的模型解释要求 JSON claims，每项有正文、真实证据 ID 及可核对的短原文摘录；DeepSeek 调用显式启用 JSON 输出并关闭思考模式，使用有限的输出 token 预算。格式、引用或摘录校验失败时回退本地结果，不自动重复收费请求；有返回的用量元数据仍尽量保留。

连接成功之后运行 `.\.venv\Scripts\python.exe scripts/verify_live_model.py`，完成三轮真实问答验收；结果保存到 `evaluation/live-model-results.json`。该脚本只接受 DeepSeek 官方端点，不接受本地模拟服务冒充真实 DeepSeek。实际完成情况见运行结果，不以单元测试或浏览器模拟服务记录替代。

v0.2 修复了纯语义召回被零关键词得分过滤的问题，缓存会去重并校验向量索引、维度和有限数值。候选超过 80 个片段时，向量精排覆盖 BM25 前 80 个，其余仍参与关键词排序；界面回答会提示此限制。文本 RAG 对照的模型上下文不包含图路径和图统计，但仍共享版本身份过滤。

引用编号和摘录存在性校验不能证明语义蕴含，模型解释需要人工核对。真实模型模式中，已计算的代表依赖路径也会以图证据形式引用，并带原始 JSON 位置；文本对照模式不接收这些图证据。外部服务只接收当前问题所需的证据、有限的同范围历史问题与版本信息，不接收 API 密钥正文或其他项目历史。

参赛演示操作、真实验收命令和失败处理见 [DEMO_GUIDE.md](DEMO_GUIDE.md)。界面可载入专用演示资料，逐步执行图谱、模型问答、迁移追问和两种修复对比，再导出不含密钥的 HTML 报告。

## 架构与目录

```text
浏览器界面
  └─ FastAPI
      ├─ CycloneDX 解析 → 组件出现位置与依赖边 → 完整可达性与代表路径
      ├─ OSV 冻结/在线查询 → 精确版本匹配与来源记录
      ├─ 图事实与版本过滤 → BM25 / 可选 Embedding → 公告与项目文档证据
      ├─ 证据模板 / 可选模型解释 → 引用检查 → 问答记录
      └─ SQLite → 快照、查询缓存、公告、版本文档库、问答历史
```

```text
lianzheng/domain.py       清单解析 身份规则 可达性与路径
lianzheng/osv.py          OSV 查询 分页 缓存 公告证据
lianzheng/retrieval.py    BM25 可选向量融合与模型适配器
lianzheng/knowledge.py    精确版本文档绑定 原文分块与行列定位
lianzheng/providers.py    DeepSeek 与兼容协议调用及脱敏错误处理
lianzheng/settings.py     本机配置 连接验证 密钥保存
lianzheng/reports.py      可打印的证据与演示报告
lianzheng/service.py      导入 分析 问答 对比业务逻辑
lianzheng/store.py        SQLite 持久化
lianzheng/app.py          API 静态页面与本地写入保护
static/                  响应式交互界面
fixtures/                三份演示清单与真实公告冻结记录
tests/                   核心逻辑和 API 回归测试
scripts/evaluate.py      小型功能验收报告
```

## API

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 健康、模型配置状态、公告快照时间 |
| GET | `/api/model/settings` | 脱敏模型状态与最近连接验证 |
| POST | `/api/model/connect` | 最小真实请求验证并保存本机模型配置 |
| GET | `/api/snapshots` | 快照列表 |
| POST | `/api/snapshots` | 导入 `{bom, project, label}` 或原始 CycloneDX 对象 |
| GET | `/api/snapshots/{id}?focus={vulnerability}` | 图、风险、证据和数据质量 |
| POST | `/api/snapshots/{id}/scan` | `{live: true}` 在线更新；false 使用冻结或缓存 |
| POST | `/api/snapshots/{id}/ask` | `{question, focus, mode: graph/text, use_model, parent_id?}` |
| GET | `/api/snapshots/{id}/history` | 最近 20 条问答 |
| GET | `/api/snapshots/{id}/documents` | 已导入文档的摘要与适用范围 |
| POST | `/api/snapshots/{id}/documents` | 导入 `{title,package,version,target_version?,kind,text,url?}` |
| GET | `/api/snapshots/{id}/documents/{document_id}` | 原文、元数据与分块 |
| DELETE | `/api/snapshots/{id}/documents/{document_id}` | 从该快照后续检索中移除 |
| GET | `/api/compare?before={id}&after={id}` | 同项目两份快照对比 |
| GET | `/api/snapshots/{id}/bom` | 导出原始清单 |
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

目前的小型功能集用演示数据验收，不能作为独立准确率基准，也不能据此宣称 GraphRAG 优于文本 RAG。方案中的 100 题独立测试集、用户任务耗时试验和商业验证仍需后续建设。


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

## GitHub 持续检查

仓库的 GitHub Actions 会在推送、拉取请求和手动触发时，使用 Python 3.12 执行单元测试及固定演示集功能检查。功能报告作为 `local-functional-checks` 构件保存 7 天。该流程不需要配置 API 密钥，模型相关测试使用模拟服务，不能替代 DeepSeek 官方真实问答验收。

本机 `.env` 及其变体、数据库、模型配置、浏览器测试结果和真实模型验收明细均已加入忽略规则；`.env.example` 可随源码提交。真实模型接入状态仍以本机验收记录为准。

## 已知边界与下一步

- 当前仅支持有精确 npm purl 的组件，执行必要的结构校验，没有实现 CycloneDX 全量 JSON Schema 校验。必须声明根节点；缺少依赖列表会产生覆盖警告。
- 默认显示最多 5 条代表路径、最多 12 跳，枚举有资源上限；完整可达性独立计算。图形最多显示 40 个节点，优先展示选中路径并提示截断；邻接索引避免反复扫描全部边。
- 项目文档支持精确来源版本与目标版本，不解释版本范围；尚未实现 PDF、网页抓取和文档真实性校验。不能保证候选升级兼容、依赖解析成功或可上线。
- 同项目身份目前以项目名称关联；组件变化仅对同名、同 `bom-ref` 做确定比较，不猜测跨生成器的组件位置映射。
- 当前比较是所选公告查询快照下的观察结果。两侧公告获取时间不一致时，消失项保守标记为“未观察到”，不归因为代码升级；正式实验需要冻结统一的公告数据集。
- 单次在线扫描最多 100 个精确包版本；真实网络请求可能耗时，原型没有生产任务队列或并发扫描调度。
- 只有本机单用户模式，无登录与多租户隔离，不应直接暴露公网。默认不开启任意文档 URL 抓取，也不执行上传文件中的代码。
- 真实模型验收需要本机有效 API 密钥和可用余额；没有通过验收时不宣称已完成真实接入或可无条件现场演示。后续还需独立评测集、扫描任务进度与真实用户试用，再扩展持久化向量库、Neo4j、团队权限与 CI 集成。

## 公开来源

- [CycloneDX 数据模型](https://cyclonedx.org/specification/overview/)
- [OSV 查询 API](https://google.github.io/osv.dev/post-v1-query/)
- [OSV 数据来源与许可说明](https://google.github.io/osv.dev/data/)
- [OSV-Scanner](https://github.com/google/osv-scanner)
- [DeepSeek 首次调用与当前模型](https://api-docs.deepseek.com/)
- [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)

公告冻结内容应保留原始署名与来源；对外打包、再分发或商业使用前需按各原始数据源核对许可。
