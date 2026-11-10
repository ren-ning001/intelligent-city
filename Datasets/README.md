# ZYourRoad OSM 数据准备

本目录用于可重复地下载和整理 OpenStreetMap（OSM）道路与旅游 POI 数据。
默认示例区域是杭州西湖周边 5 km，适合先完成步行旅游路径规划 MVP。

运行时不要求下载全国数据。北京、上海和浙江优先从`regions/`中的完整PBF
按用户指定的小区域裁剪，并将结果写入`runtime/`缓存；西湖固定数据承担
快速演示和可重复实验，其他未安装地区才使用Overpass兜底。

## 目录结构

运行脚本后会生成：

```text
Datasets/
├─ config.example.json       # 区域、半径、路网类型和 POI 标签
├─ prepare_osm.py            # 下载及预处理脚本
├─ requirements.txt          # 数据处理依赖
├─ raw/                      # 原始 OSM 查询结果
│  ├─ osm_graph.graphml      # 可直接由 OSMnx/NetworkX 加载的有向路网
│  └─ osm_features.gpkg      # 原始旅游 POI
└─ processed/
   ├─ network.gpkg           # nodes/edges 图层，供 QGIS 检查
   ├─ poi_candidates.csv     # 路径规划使用的候选 POI 表
   └─ manifest.json          # 数据区域、时间、规模与来源记录
```

`raw/`、`processed/`、`regions/`和`runtime/`中的正式数据随项目发布；
大型PBF、GraphML、GeoPackage和区域索引CSV通过Git LFS管理。

## 第 1 步：创建 Conda 环境

在项目根目录使用 PowerShell：

```powershell
conda create -n zyourroad python=3.12 -y
conda activate zyourroad
python -m pip install --upgrade pip
python -m pip install -r .\Datasets\requirements.txt
```

后续所有后端、MCP、DSH SDK 与数据处理命令统一在 `zyourroad` 环境中执行。
在未激活环境的脚本或 CI 中，可使用 `conda run -n zyourroad <命令>`。

## 第 2 步：确认数据范围

编辑 `config.example.json`：

- `center_point`：中心点，顺序固定为 `[纬度, 经度]`；
- `radius_m`：下载半径，初期建议 3000～5000 米；
- `network_type`：旅游步行项目使用 `walk`；
- `poi_tags`：需要检索的 OSM POI 标签。
- `poi_exclusions`：从候选表排除酒店、民宿等住宿设施；
- `require_poi_name`：仅保留可向用户展示名称的 POI。

建议先下载一个小区域。不要一开始下载整座城市，否则 Overpass 查询和最短路径矩阵都会明显变慢。

## 第 3 步：检查配置

```powershell
python .\Datasets\prepare_osm.py `
  --config .\Datasets\config.example.json `
  --validate-only
```

## 第 4 步：下载并预处理

```powershell
python .\Datasets\prepare_osm.py `
  --config .\Datasets\config.example.json
```

脚本会依次完成：

1. 从 OSM 下载可步行道路；
2. 保留道路的有向拓扑、长度和通行属性；
3. 下载旅游、历史、休闲等 POI；
4. 将面状景点转换为内部代表点；
5. 输出 GraphML、GeoPackage、CSV 和数据清单。

首次执行需要访问 Nominatim/Overpass 服务，耗时取决于网络和区域大小。若请求超时，先减小 `radius_m` 后重试，不要高频连续请求公共服务。

## 第 5 步：检查数据

检查 `processed/manifest.json` 中：

- `node_count` 和 `edge_count` 不为 0；
- `poi_count` 足够支持实验；
- `network_type` 为 `walk`；
- 中心点和半径符合预期。

可以用 QGIS 打开：

```text
Datasets/processed/network.gpkg
Datasets/raw/osm_features.gpkg
```

重点检查道路是否连通、景点是否落在研究范围内、POI 是否存在大量重复或无名称记录。

## 第 6 步：路径规划时如何读取

```python
import osmnx as ox
import pandas as pd

graph = ox.load_graphml("Datasets/raw/osm_graph.graphml")
pois = pd.read_csv("Datasets/processed/poi_candidates.csv")
```

后续应将每个 POI 吸附到最近道路节点，再根据这些节点计算有向最短路径距离矩阵。不要直接使用经纬度欧氏距离代替真实道路距离。

## 北京、上海和浙江离线区域包

`prepare_osm.py`只负责固定小区域的在线演示数据，不读取省市级PBF。
离线全量文件放在：

```text
regions/
├─ catalog.json
├─ beijing/source/beijing-latest.osm.pbf
├─ shanghai/source/shanghai-latest.osm.pbf
└─ zhejiang/source/zhejiang-latest.osm.pbf
```

程序先为每个区域生成`processed/locations.csv`本地地点名称索引，再使用
Pyrosm从完整PBF中按用户查询半径裁剪数据，不会把整个省市一次性加载为
NetworkX图。裁剪后的路网和POI写入`runtime/networks`与`runtime/pois`，
后续相同查询直接复用。常见景点、公园、酒店和公共设施也不再依赖在线
Nominatim解析。

更新依赖后先检查文件：

```powershell
python -m pip install -r .\backend\requirements.txt
python .\Datasets\prepare_offline_regions.py --validate-only
```

为三个区域各预热一份3 km示例缓存：

```powershell
python .\Datasets\prepare_offline_regions.py
```

也可以只处理上海：

```powershell
python .\Datasets\prepare_offline_regions.py --region shanghai
```

完整PBF通过Git LFS提交。运行时优先级为：西湖固定演示数据、可用的离线区域包、
已有动态缓存、Overpass在线查询。

## 数据许可

数据来源为 OpenStreetMap，发布地图或演示结果时标注：

```text
© OpenStreetMap contributors
```

OSM 数据受 ODbL 许可约束：https://www.openstreetmap.org/copyright
