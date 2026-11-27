# ZYourRoad

基于 DeepSeek Harness（DSH）、OpenStreetMap（OSM）和确定性路网算法的城市旅游路径规划 Agent。
项目将大模型的需求理解与工具编排能力，与可验证的离线地图数据、NetworkX 最短路径算法、
开放/闭环行程访问顺序优化（Open/Closed-loop TSP）、距离/时间双代价口径及交互式地图可视化结合。

## 当前已实现方案

### Agent与工具编排

- 使用官方 `deepseek-harness-sdk` 驱动DeepSeek模型和DSH Runtime。
- 通过DSH MCP Client启动项目自己的Python MCP Server。
- Agent负责理解自然语言约束、筛选POI、组织游览顺序并解释结果。
- 距离、坐标和路线均由确定性GIS工具产生，不由模型编造。
- 最终路线通过专用发布工具一次提交，探索性调用不会污染地图。
- 工具调用参数、完整结果和失败信息保存为可审计JSONL；不展示模型隐藏思维链。

当前MCP工具：

- `geocode_location`：地名搜索与WGS84坐标解析。
- `search_tourism_pois`：按景点、公园、历史、博物馆、酒店等类别检索POI。
- `prepare_osm_region`：准备或读取指定小区域的路网与POI缓存。
- `plan_walking_route`：计算单段真实路线，可选 `weight=length/time` 和出行方式。
- `optimize_itinerary_order`：在真实路网上比较当前顺序、最近邻、2-opt 和
  Held-Karp，返回可发布的确定性顺序；支持距离/时间两种权重和开放/闭环两种模型。
- `publish_tourism_itinerary`：发布最终地点顺序、多段路线和换乘断点；
  应传入与顺序优化相同的 `weight`，保证排序口径和路线几何一致。

Agent 的系统提示要求：待排序景点达到 2 个（含起点至少 3 个点）且需要比较顺序时，
先调用一次 `optimize_itinerary_order`，再按返回的 `names` 顺序发布。因此 Agent
不再只依赖语义排序；如果工具失败，才退回原有的语义顺序。

### Agent 读取界面当前路线

规划器规划的路线只存在于前端状态里，不在 Agent 自己的 MCP 调用记录中。为了让
「解释当前路线为什么这样走」能工作，聊天请求新增可选的 `route_context`：

- 前端把当前 `route` 压缩成总距离、预计时间、出行方式、权重、是否闭环、访问
  顺序（名称+坐标）和逐段距离/分钟；
- `AgentService` 在每轮用户消息前加入「当前界面路线（规划器已显示）」块，明确
  告诉模型这是界面当前路线，不是 MCP 历史，不能回答“没有已规划/发布的路线”；
- 上下文没有给出的算法细节不允许编造；如果 `source` 不是 `optimize/agent`，
  Agent 不应声称做过 TSP、2-opt 或算法对比；
- 用户要求改路线时，Agent 仍可调用 MCP 工具重新规划。只有没有 `route_context`
  时，Agent 才会按原来的方式向用户询问起终点。

### Windows 捆绑 DSH 运行时兼容

部分 Windows `deepseek-harness-runtime-bin` 包把 `@koromix/koffi` 原生模块的路径
写死为打包时的 `F:\snapshot\node\...`。运行时能启动，但每个回合都会以
`turn/end: error` 结束，前端因此显示「Agent已完成处理，但没有返回文本。」。

先执行一次：

```powershell
python .\scripts\prepare_dsh_runtime.py
```

脚本把锁定的 koffi sidecar 下载到 `Datasets/runtime/dsh-resources/`（项目内，不写
用户目录）；如果 Windows 缓存发布失败，会从已下载归档重建期望布局。
`backend/app/config.py` 随后自动注入 `DSH_KOFFI_ENTRY`、`DSH_KOFFI_PLATFORM` 和
`NODE_OPTIONS=--require scripts/dsh_koffi_loader.cjs`，由 preload 把 `koffi` 的
CommonJS/`process.dlopen` 加载重定向到 sidecar。sidecar 缺失时服务仍能启动，但
Agent 回合会失败；修改后需重启后端并新建会话。

同一个单文件运行时还缺少 `node-pty` 的 `prebuilds/win32-x64/conpty.node`，会让
`pwsh` 工具在启动 PTY 时退出。准备脚本会同时安装匹配版本的 `node-pty`，
preload 把 `node-pty` 和 `conpty.node/pty.node` 重定向到 sidecar，并强制使用
内置 ConPTY；[cordis.patch.yml](F:/GitSpace/intelligent-city/plugins/zyourroad-osm/cordis.patch.yml)
还显式给 `terminal-pwsh` 补回 `shellDialect: pwsh` 和 `shellPath`，避免把 bash
参数 `--noprofile --norc -i` 传给 PowerShell 导致启动即退出。现在 `pwsh` 工具
可以在 Windows 上正常执行命令。

### 可审计工具卡片

Agent 的「可审计执行过程」不再把所有步骤都显示成「调用工具」：

- 标题显示工具用途，例如「列出 MCP 资源」「执行 PowerShell」「解析地点」；
- 标题右侧显示原始工具名，例如 `list_mcp_resources`、`pwsh`、`geocode_location`；
- 详情显示本次参数摘要，例如 `server=zyourroad`、`Get-ChildItem ...`、查询半径；
- 失败卡片显示实际错误首行，而不是只有「调用失败，Agent将停止无效重试」。

例如截图中的三次调用现在会分别显示为「列出 MCP 资源 `list_mcp_resources`」
（查询 zyourroad 资源清单）、「列出 MCP 资源模板 `list_mcp_resource_templates`」
和「执行 PowerShell `pwsh`」（附 `Get-ChildItem ...` 命令）；第三次的历史失败
会显示 `conpty.node` 加载错误。

### 离线OSM与路径规划

- 内置北京、上海、浙江的Geofabrik全量 `.osm.pbf` 数据。
- 使用Pyrosm按查询范围裁剪PBF，不会一次性把整个省市加载进内存。
- 生成本地地点名称索引，常见景点、公园、酒店和公共设施无需在线地理编码。
- 使用 OSMnx 将地点吸附到最近道路节点。
- 建图后统一提取**最大强连通分量**，并记录清洗前后的节点/边数；
  OSMnx/Pyrosm 的 `retain_all=False` 只保证弱连通，不能保证任意两个景点互相可达。
- 为每条有向边写入 `travel_time_s`：按 OSM `highway` 标签（步行道、台阶、小路、
  主次干道等）查速度表，而不是整段距离除以一个常数。
- 使用 NetworkX 按道路 `length` 权重计算最短距离，也可按 `travel_time_s` 权重
  计算最快时间；两种口径共用同一份离线路网。
- 支持起点、终点、多个途经点、不连续换乘段，以及最后回到起点的闭环行程。
- 相同区域查询会缓存为GraphML和GeoPackage，以加快后续规划。
- 西湖固定数据用于快速演示和可重复实验；其他未安装地区以Overpass作为兜底。

### 多景点访问顺序优化

`backend/app/order_optimizer.py` 在真实路网上求解景点访问顺序问题。支持两种
行程模型和两种代价口径：

- 行程模型：固定起点的开放行程（Open-loop）、最后回到起点的闭环行程
  （Closed-loop，目标函数额外加上最后一点到起点的回边）。
- 代价口径：`length` 按路网距离最短；`time` 按道路等级估速后的最快路径。
  时间口径不是实时 ETA，速度表是公开、可复现的实验假设。

实现要点：

- 以起点和全部景点为节点，在可步行有向路网上分别执行单源 Dijkstra，构建
  两份代价矩阵：`network_m`（米）和 `travel_s`（秒）。不可达点对会被显式记录，
  并拒绝继续求解；正常数据在强连通清洗后不应出现不可达点对。
- 代价矩阵与路网缓存都写入 `Datasets/runtime/`。矩阵缓存键包含点集、路网缓存键、
  出行方式、速度表版本，不含权重，因此距离/时间、开放/闭环可以复用同一份矩阵。
- 四种方案共用同一矩阵，保证比较公平：
  - `given_order`：用户/界面当前列表顺序，作为基线；
  - `nearest_neighbor`：最近邻构造初始解；
  - `nearest_neighbor_2opt`：在最近邻解上做 2-opt 局部搜索；
  - `held_karp`：小规模（≤15 个景点）动态规划精确解。
- 2-opt 针对有向路网实现：反转子序列后会完整重算目标函数，不使用对称 TSP 的
  两边增量公式；只有总代价下降时才接受交换。测试中另用 ≤8 个景点的全排列
  结果核对开放与闭环 Held-Karp 的正确性。
- 每个方案都会按最优顺序调用既有规划接口恢复逐段道路几何，同时输出总代价、
  总公里数、预计时间、求解耗时、相对精确解的 Gap 和 2-opt 改进幅度。
- 结果还包含：地点吸附距离、逐对路网/直线距离、逐对最快时间、路网距离/直线
  距离比值统计、强连通清洗统计（清洗前后节点/边数、剔除数量），以及矩阵构建
  耗时和缓存命中/读取耗时。单次查询跨度上限沿用 10 公里内存保护。

该能力通过 `POST /api/routes/optimize` 暴露。请求新增 `weight`
（`length`/`time`）和 `closed_loop` 参数；前端规划器增加“距离优先/时间优先”
切换、“最后返回第一个地点”闭环选项和导出按钮，并展示同一代价矩阵下四种方案
的对照表；点击任一方案即可在地图上切换对应路线。Agent 通过
`optimize_itinerary_order` 工具调用同一套能力。

前端导出（`frontend/src/utils/export.ts`）支持：

- 算法对照 CSV：方案、代价、单位、公里数、预计时间、求解耗时、Gap、改进率、顺序；
- 逐对距离 CSV：起点/景点两两之间的路网距离、最快时间、直线距离和比值；
- 路线 GeoJSON：路线折线 + 带编号的地点；
- 路线 GPX：可直接导入常见 GPS/地图软件。

### 路线地点移出与仅保留地点重算

规划出路线后，规划器底部出现「路线地点」列表。勾选要移出的地点，再点「仅规划
保留的 N 个地点」即可。规则：

- 至少保留 2 个地点；起点、终点和途经点都可以移出，保留点按当前路线顺序重连。
- 旧路线进入最多 5 条的历史栈，地图用暗灰线、暗色圆点保留；当前路线用亮蓝线
  和编号标记。重合路段由新路线覆盖，因此视觉上总是看到新路线。
- 已移出的地点只在旧路线中保留暗色标记；保留地点的新标记覆盖在旧标记之上。
- 自由选点模式会直接把保留点写回地点列表；起终点模式会把第一个/最后一个保留点
  写回起点/终点，中间点写回途经点。
- 原来是闭环的路线会继续以 `closed_loop=true` 重算，旧闭环和新闭环都保留在地图上。
- 重算完成后「路线地点」列表不会消失，仍保留最初路线的全部地点和勾选状态：
  已移出的地点继续勾选并标「移出」，可以取消勾选把它加回来，也可以再勾选其他
  地点；调整后再次点按钮即可重新规划，后续流程与首次勾选一致。
- 如果取消全部移出，按钮变为「恢复全部 N 个地点并重规划」，可一次恢复原路线；
  恢复后按钮回到禁用状态，等待下一次勾选。
- 重算会清空旧算法对照，避免把旧矩阵的 Gap/耗时误当成新路线的结果；优化按钮、
  指标、分段列表、导出和周边POI检索都只使用保留地点。

重算复用 `POST /api/routes/plan`，前端在请求中额外发送 `closed_loop`；不需要新的
后端接口。移出选择保存在规划器的 `routeStops/removedStopKeys` 中，不跟随新路线
重建，因此调整后可以反复重算。

配套实验脚本 `scripts/run_order_experiment.py` 在西湖演示路网上固定起点，
按景点规模、重复次数、距离/时间口径和开放/闭环模型批量运行四种方案。矩阵
构建时间、缓存读取时间和顺序求解时间分开记录，并生成对照 CSV、逐对数据
JSONL、口径差异 CSV 与图表。

### 前后端与会话

- Vue 3 + TypeScript + MapLibre交互地图。
- DeepSeek蓝白视觉风格，路线规划器和Agent窗口支持拖动、缩放、折叠与关闭。
- 支持地点搜索、起终点、任意途经点、地图POI选点和自由选点模式。
- 支持距离/时间两种代价口径、开放/闭环两种行程模型。
- 支持四种算法结果的对照与地图切换，以及算法对照 CSV、逐对距离 CSV、
  路线 GeoJSON/GPX 导出。
- 规划完成后可勾选移出若干地点，仅重算保留地点；旧路线和已移出地点保留为暗色，
  新路线用亮色覆盖，重合路段显示新路线。
- 重算会同步更新地点列表、优化输入、指标、分段、导出和POI检索范围。
- 规划器显示矩阵是缓存命中还是本次构建，并显示强连通清洗剔除的节点/边数。
- 支持Markdown回答、最终路线、多段路线、换乘虚线和动态城市标题。
- FastAPI提供REST接口、SSE流式Agent事件和Swagger文档。
- 对话保存为 `zyourroad-chat.jsonl`。
- 工具调用和完整结果保存为 `zyourroad-events.jsonl`。
- 支持新建会话、历史会话列表、切换会话及恢复工具时间线。

## 系统架构

```text
Vue 3 / MapLibre
        │ REST + SSE
FastAPI Backend
        ├─ DeepSeek Harness Python SDK
        │       └─ DSH MCP Client
        │              └─ ZYourRoad Python MCP Server
        ├─ GIS Service
        │       ├─ Pyrosm / OSMnx
        │       ├─ 最大强连通分量清洗 / 逐边估速
        │       ├─ NetworkX（length / travel_time_s）
        │       └─ OSM PBF / GraphML / GeoPackage
        └─ Order Optimizer
                ├─ 距离/时间双代价矩阵（Dijkstra）
                ├─ 最近邻 / 2-opt / 闭环 Held-Karp
                └─ 矩阵缓存、逐对数据与对照指标
```

`third_party/deepseek-harness` 以Git子模块保存DSH上游源码，供研究和调试使用；
项目运行时默认使用Conda环境中安装的官方SDK。项目没有修改上游DSH源码，
自己的扩展位于 `plugins/zyourroad-osm`。

## 目录说明

- `backend/app/`：FastAPI、Agent服务、MCP工具、GIS算法、顺序优化和会话持久化。
- `backend/tests/`：后端、数据服务、强连通清洗、顺序优化测试。
- `frontend/`：Vue 3前端和MapLibre地图；`frontend/src/utils/export.ts` 负责结果导出。
- `scripts/`：启动、实验、DSH运行时准备（`prepare_dsh_runtime.py`）和koffi/node-pty加载器。
- `Datasets/`：西湖演示数据、三地离线PBF、本地点位索引和运行时缓存。
- `Datasets/runtime/matrices/`：按点集/路网/速度表哈希缓存的景点代价矩阵，
  同一份缓存同时包含 `network_m` 和 `travel_s`。
- `Datasets/runtime/experiments/`：顺序优化对照实验的 JSONL/CSV 与 `figures/` 图表。
- `plugins/zyourroad-osm/`：DSH外部Bundle及MCP Client配置。
- `scripts/`：Conda准备、前后端启动、OSM网络诊断和顺序优化实验脚本。
- `documents/`：开题材料、文献调研、实验背景、策略与未来计划。
- `notes.md`：面向使用者的界面说明书与已知限制。
- `third_party/deepseek-harness/`：DeepSeek Harness上游Git子模块。
- `.dsh-home/`：本机DSH Profile和会话数据，不提交Git。

## 环境要求

- Windows 10/11与PowerShell。
- Git及Git LFS。
- Conda或Miniconda。
- Node.js 20.19+。
- 可用的DeepSeek API Key。

所有命令均假设当前PowerShell位于仓库根目录，不依赖任何本机绝对路径。

## 完整安装与运行

### 1. 克隆代码和大文件

```powershell
git clone --recurse-submodules <你的仓库URL> ZYourRoad
Set-Location .\ZYourRoad
git lfs install
git lfs pull
```

如果普通克隆时没有获取子模块：

```powershell
git submodule update --init --recursive
```

### 2. 创建Conda环境

推荐直接使用环境文件：

```powershell
conda env create -f .\environment.yml
conda activate zyourroad
```

如果环境已经存在：

```powershell
conda env update -n zyourroad -f .\environment.yml --prune
conda activate zyourroad
```

也可以使用项目脚本：

```powershell
.\scripts\setup-conda.ps1
conda activate zyourroad
```

项目统一使用Conda，不需要创建 `venv` 或 `.venv`。

### 3. 安装前端依赖

```powershell
Push-Location .\frontend
npm ci
Pop-Location
```

### 4. 配置DeepSeek

```powershell
Copy-Item .\.env.example .\.env
```

编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
ZYOURROAD_DSH_MODEL=deepseek-v4-flash
```

不要使用 `DSH_MODEL`，该变量只能由启动环境设置。`.env`已被Git忽略，严禁把
真实密钥提交到仓库。可选配置还包括 `API_HOST`、`API_PORT`、`FRONTEND_ORIGINS`
以及Overpass超时、失败冷却和备用端点。

Windows 上首次运行前还需要准备 DSH 运行时 sidecar（约 100 MB，只需一次）：

```powershell
python .\scripts\prepare_dsh_runtime.py
```

如果 Agent 一直显示「Agent已完成处理，但没有返回文本。」，先确认该脚本输出
「DSH koffi sidecar 已就绪」，再重启后端并使用新会话。

### 5. 检查离线数据

Git LFS拉取完成后执行：

```powershell
python .\Datasets\prepare_offline_regions.py --validate-only
```

仓库已经包含北京、上海、浙江PBF、地点索引以及示例区域缓存，正常情况下不必
重新处理。如果需要重新生成某个地区：

```powershell
python .\Datasets\prepare_offline_regions.py --region shanghai
python .\Datasets\prepare_offline_regions.py --region beijing
python .\Datasets\prepare_offline_regions.py --region zhejiang
```

首次重建可能需要较长时间。详细数据说明见 `Datasets/README.md`。

### 6. 启动开发环境

同时启动前后端：

```powershell
.\scripts\start-dev.ps1
```

也可以分别启动：

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

访问地址：

- 前端：<http://127.0.0.1:5173>
- API文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

修改MCP工具或Agent系统提示后，应重启后端并新建会话，以重新加载工具定义。

### 7. 测试和构建

```powershell
pytest -q .\backend\tests
Push-Location .\frontend
npm run build
Pop-Location
```

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 服务、模型、离线区域与数据源状态 |
| POST | `/api/geocode` | 单一地点地理编码 |
| POST | `/api/geocode/search` | 地点候选搜索 |
| POST | `/api/pois/search` | 分类旅游POI检索 |
| POST | `/api/routes/plan` | 给定顺序的真实路网路线，可选 `weight=length/time`、闭环 |
| POST | `/api/routes/optimize` | 开放/闭环访问顺序优化、双口径代价与算法对照 |
| GET | `/api/routes/optimize/{matrix_key}/pairs.csv` | 导出缓存矩阵的逐对距离（CSV） |
| POST | `/api/regions/prepare` | 准备小区域路网/POI缓存 |
| POST | `/api/agent/chat` | Agent单轮对话 |
| POST | `/api/agent/chat/stream` | Agent SSE流式对话与工具事件 |
| GET | `/api/agent/sessions` | 历史会话列表 |
| GET | `/api/agent/sessions/{id}` | 会话消息与工具时间线 |

`POST /api/agent/chat` 与 `/api/agent/chat/stream` 的请求体可带可选的
`route_context`。前端会把当前地图路线压缩成总距离、预计时间、出行方式、权重、
闭环标志、访问顺序和逐段距离/分钟传给 Agent；Agent 在每轮提示中把它标记为
「当前界面路线」，因此规划器路线也能被解释，不要求它出现在 MCP 调用记录里。

`POST /api/routes/optimize` 的请求示例：

```json
{
  "start": {"latitude": 30.258, "longitude": 120.148},
  "start_name": "断桥残雪",
  "attractions": [
    {"latitude": 30.248, "longitude": 120.140},
    {"latitude": 30.240, "longitude": 120.150}
  ],
  "attraction_names": ["苏堤春晓", "花港观鱼"],
  "weight": "time",
  "closed_loop": true,
  "network_type": "walk",
  "search_radius_m": 5000
}
```

响应中的 `weight`、`closed_loop`、`pairs`、`unreachable`、`component`、
`matrix_build_ms` 和 `matrix_lookup_ms` 分别表示本次口径、行程模型、逐对距离、
不可达点对、连通清洗统计和矩阵缓存耗时。

## 顺序优化实验

默认同时运行 5、8、10 个景点，距离/时间两种口径，开放/闭环两种模型：

```powershell
python .\scripts\run_order_experiment.py
```

常用参数：

```powershell
# 加入 12 个景点，每个规模重复 3 次，只跑距离口径的开放行程
python .\scripts\run_order_experiment.py --sizes 5 8 10 12 --repeats 3 --weights length --modes open

# 只写 CSV/JSON，不生成 matplotlib 图
python .\scripts\run_order_experiment.py --no-figures
```

脚本输出到 `Datasets/runtime/experiments/`：

- `west_lake_order_runs.jsonl`：每次运行的完整结果，包含矩阵键、缓存耗时、
  吸附记录、逐对距离、强连通统计、四种方案和逐段几何摘要；
- `west_lake_order.csv`：算法对照表，列包含 `weight`、`closed_loop`、`cost`、
  `cost_unit`、`cost_m`、`cost_s`、`matrix_elapsed_ms`、`matrix_build_ms`、
  `matrix_lookup_ms`、`cache_hit`、`gap_percent`、`improvement_percent` 等；
- `west_lake_weight_comparison.csv`：同一组点在距离/时间口径下的精确解顺序、
  是否同序、位置重合率和两种口径的公里/时间；
- `west_lake_order.json`：聚合结果；
- `figures/gap_by_size.png`：最近邻 Gap 随规模变化；
- `figures/solve_time_by_size.png`：求解耗时随规模变化（对数轴）；
- `figures/detour_ratio_hist.png`：路网距离/直线距离比值分布；
- `figures/weight_order_overlap.png`：距离/时间口径的顺序重合度。

图表由 `matplotlib` 生成，已列入 `backend/requirements.txt`；如果当前环境尚未安装，
脚本会跳过图表并保留 CSV/JSON，不会中断实验。

本次结项自检已在西湖演示图跑通默认的 12 次运行（5/8/10 个景点 × 距离/时间 ×
开放/闭环），并确认同一组点的四种组合复用同一个 `matrix_key`；对应的
`west_lake_order.csv`、`west_lake_order_runs.jsonl` 和
`west_lake_weight_comparison.csv` 已生成。当前 `zyourroad` 环境尚未安装
`matplotlib`，因此图表目录需要安装依赖后重新运行才能生成。

这些输出对应开题中的 P1（路网/直线比值）、P2（Gap 与 2-opt 改进）、
P3（矩阵/求解耗时）、P4（距离/时间口径差异）和 P5（吸附距离与强连通清洗）。

以下是一次**旧版距离口径**实测结果（单位 km；Gap 相对 Held-Karp 精确解），
只用于说明表格形状；新版脚本启用强连通清洗与逐边时间后，数值会略有变化，
请以重新运行生成的 CSV 为准：

| 景点数 | 列表顺序 | 最近邻 | 最近邻+2-opt | Held-Karp | 最近邻Gap | 2-opt改进 |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 10.44 | 6.68 | 6.68 | 6.68 | 0.00% | 0.00% |
| 8 | 14.21 | 9.62 | 9.62 | 8.75 | 9.89% | 0.00% |
| 10 | 17.06 | 11.35 | 11.27 | 10.24 | 10.85% | 0.74% |

同一批实验中，路网距离/直线距离的平均比值为 1.54～1.68，说明绕行和路网阻隔
不可忽略。以上只是一次固定样本的结果，用于验证流程与指标，不构成对算法整体
性能的结论；不同区域、POI 分布和权重会改变数值。

## 后续优化方向

本轮结项已补齐：

- **顺序优化接入 Agent**：新增 `optimize_itinerary_order` MCP 工具；
- **距离/时间双口径**：按 OSM `highway` 标签估速，开放/闭环共用矩阵；
- **结果导出**：算法对照 CSV、逐对距离 CSV、路线 GeoJSON/GPX；
- **可重复实验**：批量运行、重复抽样、口径差异和图表输出。

仍需继续的方向：

1. **更大规模与更强启发式**：Held-Karp 目前限制 15 个景点；更大实例可接
   OR-Tools、Lin-Kernighan 或其他元启发式，并保留精确解作为小规模基准。
2. **多目标路径优化**：综合距离、时间、绿化、景观、坡度、拥挤度和用户体力，
   生成可解释的 Pareto 候选路线。
3. **时间窗与预算约束**：加入景点开放时间、停留时长、门票预算和必须到访点。
4. **动态离线区域安装工具**：让 Agent 通过受限 MCP 工具从可信 Geofabrik 清单
   下载、校验并安装新地区 PBF，而不是执行任意 Shell 命令。
5. **多模式交通**：正式建模步行、轮渡、地铁和公交换乘，而不只显示换乘断点。
6. **路线质量评估**：扩大基线算法、消融实验和距离/满意度/响应时间指标。
7. **性能与部署**：预构建空间索引、缓存淘汰、后台任务进度、容器化和生产部署。

## 数据与第三方许可

- OSM地图和POI：`© OpenStreetMap contributors`，遵循ODbL。
- 离线区域数据来自Geofabrik，使用时必须保留OSM署名。
- DeepSeek Harness源码和其他第三方组件遵循各自仓库中的许可证。
