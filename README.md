# ZYourRoad

基于 DeepSeek Harness（DSH）、OpenStreetMap（OSM）和确定性路网算法的城市旅游路径规划 Agent。项目将大模型的需求理解和工具编排能力，与可验证的离线地图数据、NetworkX最短路径算法及交互式地图可视化结合。

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
- `plan_walking_route`：计算单段真实步行最短路径。
- `publish_tourism_itinerary`：发布最终地点顺序、多段步行路线和换乘断点。

### 离线OSM与路径规划

- 内置北京、上海、浙江的Geofabrik全量 `.osm.pbf` 数据。
- 使用Pyrosm按查询范围裁剪PBF，不会一次性把整个省市加载进内存。
- 生成本地地点名称索引，常见景点、公园、酒店和公共设施无需在线地理编码。
- 使用OSMnx将地点吸附到最近道路节点。
- 使用NetworkX按道路 `length` 权重计算Dijkstra最短路径。
- 支持起点、终点、多个途经点和不连续换乘段。
- 相同区域查询会缓存为GraphML和GeoPackage，以加快后续规划。
- 西湖固定数据用于快速演示和可重复实验；其他未安装地区以Overpass作为兜底。

当前景点访问顺序主要由Agent根据语义和约束决定；NetworkX负责按该顺序连接
真实道路。尚未实现基于路网距离矩阵的全局最优景点排序。

### 前后端与会话

- Vue 3 + TypeScript + MapLibre交互地图。
- DeepSeek蓝白视觉风格，路线规划器和Agent窗口支持拖动、缩放、折叠与关闭。
- 支持地点搜索、起终点、任意途经点、地图POI选点和自由选点模式。
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
        └─ GIS Service
                ├─ Pyrosm / OSMnx
                ├─ NetworkX
                └─ OSM PBF / GraphML / GeoPackage
```

`third_party/deepseek-harness` 以Git子模块保存DSH上游源码，供研究和调试使用；
项目运行时默认使用Conda环境中安装的官方SDK。项目没有修改上游DSH源码，
自己的扩展位于 `plugins/zyourroad-osm`。

## 目录说明

- `backend/app/`：FastAPI、Agent服务、MCP工具、GIS算法和会话持久化。
- `backend/tests/`：后端与数据服务测试。
- `frontend/`：Vue 3前端和MapLibre地图。
- `Datasets/`：西湖演示数据、三地离线PBF、本地点位索引和运行时缓存。
- `plugins/zyourroad-osm/`：DSH外部Bundle及MCP Client配置。
- `scripts/`：Conda准备、前后端启动和OSM网络诊断脚本。
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
真实密钥提交到仓库。

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
## 后续优化方向

1. **确定性景点排序工具**：构建真实路网距离矩阵，使用TSP、2-opt或OR-Tools
   优化访问顺序，而不是仅依赖模型语义排序。
2. **多目标路径优化**：综合距离、时间、绿化、公园、景观、坡度、拥挤度和
   用户体力，生成可解释的Pareto候选路线。
3. **时间窗与预算约束**：加入景点开放时间、停留时长、门票预算和必须到访点。
4. **动态离线区域安装工具**：让Agent通过受限MCP工具从可信Geofabrik清单下载、
   校验并安装新地区PBF，而不是执行任意Shell命令。
5. **多模式交通**：正式建模步行、轮渡、地铁和公交换乘，而不只显示换乘断点。
6. **路线质量评估**：建立基线算法、消融实验和距离/满意度/响应时间指标。
7. **性能与部署**：预构建空间索引、缓存淘汰、后台任务进度、容器化和生产部署。

## 数据与第三方许可

- OSM地图和POI：`© OpenStreetMap contributors`，遵循ODbL。
- 离线区域数据来自Geofabrik，使用时必须保留OSM署名。
- DeepSeek Harness源码和其他第三方组件遵循各自仓库中的许可证。
