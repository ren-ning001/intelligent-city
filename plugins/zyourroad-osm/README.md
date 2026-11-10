# ZYourRoad OSM DSH Bundle

这是 ZYourRoad 的外部 DeepSeek Harness bundle，不修改 `third_party/deepseek-harness`。

Bundle 通过官方 `@deepseek-ai/dsh-mcp-client` 启动 Python MCP 服务器：

```text
DSH Agent
  → @deepseek-ai/dsh-mcp-client
  → python -m backend.app.mcp_server
  → OSMnx / NetworkX / Datasets
```

模型看到的工具名称带有稳定命名空间：

```text
mcp__zyourroad__geocode_location
mcp__zyourroad__search_tourism_pois
mcp__zyourroad__plan_walking_route
mcp__zyourroad__publish_tourism_itinerary
mcp__zyourroad__prepare_osm_region
```

## 环境变量

- `ZYOURROAD_ROOT`：项目绝对路径；
- `ZYOURROAD_PYTHON`：`zyourroad` Conda 环境的 Python 绝对路径；
- `DEEPSEEK_API_KEY`：只由 DSH 模型适配器读取，不传给 MCP 子进程。

## 通过 Python SDK 使用

后端把本目录的 `cordis.patch.yml` 作为 `DeepSeekHarness(..., patches=(...))`
的启动覆盖层，不需要修改 DSH 源码。

## 安装为持久 Profile Bundle

```powershell
$env:DSH_HOME = (Join-Path (Get-Location) ".dsh-home")
$PluginPath = (Resolve-Path ".\plugins\zyourroad-osm").Path.Replace("\", "/")
dsh --profile sdk-minimal --dump-default-config | Out-Null
dsh plugin --profile sdk-minimal add "file:$PluginPath"
```

开发阶段优先使用后端传入 patch 的方式，避免本地 profile 安装状态影响复现。
