# ZYourRoad 图形界面说明书

本文写给两类读者：第一次打开页面的使用者和第一次读代码的程序员。它按屏幕上的实际位置说明每个模块做什么、怎么用、操作后会看到什么，以及请求进入后端之后发生了什么。文末单独列出当前实现的边界，以及从这些边界自然长出来的改进方向。

产品名是 **ZYourRoad**。它是一张全屏交互地图，上面叠了两个可拖动的玻璃面板：左侧「路线规划器」用确定的地点顺序走真实道路；右侧「DeepSeek Harness Agent」用自然语言组织游览，再把距离和路线交给同一套地图工具计算。模型负责理解约束和安排顺序，不负责编造坐标、距离或道路几何。

---

## 1. 打开之后首先看到什么

启动开发环境后，浏览器访问 `http://127.0.0.1:5173`。Vite 把以 `/api` 开头的请求代理到 `http://127.0.0.1:8000`。页面本身没有登录，也没有独立的「首页」和「结果页」，所有功能都铺在同一张地图上。

默认镜头对准杭州西湖：中心约北纬 30.2525、东经 120.1552，缩放 13.2，俯仰 46°，朝向偏西约 12°。底图是 OpenStreetMap 栅格瓦片，经过降饱和、略提对比和轻微色相旋转，看起来偏冷、偏淡。地图四周有一层深蓝暗角，左右上角有两团缓慢漂移的蓝色光晕，它们不拦截鼠标。

页面加载时同时做三件事：

1. `GET /api/health`。成功时顶栏右侧圆点变为蓝色，文字是 `SYSTEM ONLINE`，小字是当前模型名（默认 `deepseek-v4-flash`）。失败时圆点保持橙色，文字是 `CONNECTING`，并弹出约 3.6 秒的提示：「后端尚未启动，请运行 start-backend.ps1」。进页后每 20 秒自动刷新一次，后端后启动或中途重启时顶栏会自行恢复。
2. 以西湖中心、半径 3000 米、类别「景点 / 历史 / 公园」调用 `POST /api/pois/search`。命中西湖演示数据包时，地图上出现一批白芯蓝边的圆点，规划器底部数据来源写成「西湖演示缓存」。
3. `GET /api/agent/sessions`。如果浏览器 `localStorage` 里的 `zyourroad.session-id` 能在历史列表中找到，就自动打开那次对话，恢复消息和工具时间线。地图上的路线不会跟着恢复。

整体字体是楷体优先、微软雅黑兜底。主色是 DeepSeek 蓝 `#4d6bfe`。面板是半透明白底、模糊、圆角和轻阴影。系统提示和错误气泡偏琥珀色。

屏幕分区可以记成这张图：

```text
┌──────────────────────────────────────────────────────────┐
│ 顶栏：标志 · 当前城市包 · 后端/模型状态                    │
│                                                          │
│  ┌路线规划器┐                          ┌ Agent 对话 ┐    │
│  │          │      全屏倾斜地图         │            │    │
│  │          │      POI 圆点 / 蓝线      │            │    │
│  └──────────┘                          └────────────┘    │
│  [缩放/罗盘]          [选中 POI 卡片]            © OSM    │
│                    [关闭后面板的停靠按钮]                 │
└──────────────────────────────────────────────────────────┘
```

两个面板默认都打开：规划器靠左上（约 x=24, y=98，440×720），Agent 靠右上（距右边 24px，同样高度）。点击面板会把它抬到最前。位置和尺寸写在 `localStorage` 的 `zyourroad.panel.v2.planner` 与 `zyourroad.panel.v2.agent`。

---

## 2. 顶栏

位置：地图上方一条横贯左右的玻璃条，高 64px。

| 位置 | 看见什么 | 含义 |
| --- | --- | --- |
| 最左地图图标 + `ZYourRoad` / `PATH INTELLIGENCE` | 产品标识 | 不可点击 |
| 中间图层图标后的城市名 | 当前数据语境 | 由坐标框粗略判断，不是地理编码返回的行政区 |
| 最右圆点 + `SYSTEM ONLINE` 或 `CONNECTING` | 后端是否可达 | 进页时请求一次，之后每 20 秒自动刷新 |
| 圆点下的小字 | 模型名 | 来自健康检查的 `dsh_model`；后端没起来时显示 `DeepSeek Harness` |

城市名的判断顺序是：先看当前路线的第一个途经点，没有路线就看第一个 POI。落在上海框内显示「上海 · 离线城市包」，北京框内显示「北京 · 离线城市包」，西湖实验框（约北纬 29.8–30.6、东经 119.8–120.6）显示「杭州 · 西湖实验区」，更宽的浙江框显示「浙江 · 离线城市包」，其余显示「自定义城市区域」。刚进页、还没有点时显示「城市旅游路径规划」。窄屏（宽度 ≤760px）会藏掉这段城市名。

顶栏不发规划请求。健康检查另外告诉程序员：DeepSeek 密钥是否已配置、DSH profile、会话目录、已有会话文件数、本应用对话文件数、工具事件文件数、支持的 POI 类别，以及北京 / 上海 / 浙江离线包是否在磁盘上。密钥本身不会出现在响应里。

---

## 3. 地图画布

组件是 `MapCanvas`，铺满整个视口，位于所有面板下面。

### 3.1 底图与导航

底图只负责「看起来在哪」，不参与算路。算路用的是后端本地 PBF、GraphML 和 Overpass，和浏览器拉的瓦片是两套数据。瓦片来自 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`，需要能访问公网；瓦片失败时路线算法仍可能成功，只是底图空白或发灰。

左下角是 MapLibre 导航控件：放大、缩小、复位朝向，并显示俯仰。控件是磨砂白底圆角。拖拽旋转、滚轮缩放、右键或双指改变俯仰，都是地图库的默认交互。右下角有一行很小的 `© OpenStreetMap contributors`，窄屏隐藏。

### 3.2 POI 圆点

每个兴趣点是两层圆：外圈淡蓝光晕，内圈白芯、深蓝描边，半径约 4.5px。鼠标移上去变成手型。点击后不会在地图上改样式，而是在屏幕底部正中弹出选中卡片（见第 6 节）。

这些点来自最近一次 POI 查询，最多 60 个（规划器路径的 `limit`）。点的类别由规划器里亮起的芯片决定，默认景点、历史、公园。Agent 完成一轮并且返回了 POI 结果时，会整表替换这些点。

### 3.3 路线、序号和换乘

规划成功或 Agent 在回合结束时带回路线后，地图发生这些变化：

- 一条半透明的粗蓝光晕（线宽约 13、带模糊）压在一条实心蓝线（线宽 4，颜色 `#4264ed`）下面。线是道路折线，不是两点之间的直线。
- 每个访问点上出现编号圆标。第 1 个是较大的圆，中间点略小，最后一个标是旋转约 12° 的圆角方块，数字是深蓝而不是亮蓝。编号从 1 开始，对应规划顺序，不是推荐优先级。
- 若路线里有「非步行衔接」，两段实线之间会多一条橙色虚线（`#e29a39`，`line-dasharray: 2,2`）。虚线只连接断点两端的坐标，不表示轮渡或地铁的真实轨迹。
- 规划完成后勾选移出地点并重算时，旧路线不会被删除，而是画在更底层：`prior-route` 用暗灰蓝实线（`#5f6b85`，宽 4，透明度 0.78），旧换乘用暗棕虚线；当前路线仍用亮蓝线和蓝色光晕。新路线图层在旧路线之上，重合路段看到的是新路线。
- 旧路线的每个访问点保留一个 16px 的暗色圆点（无编号）；保留地点的新编号标记覆盖在旧标记上，已移出地点只剩暗点。
- 镜头范围同时包住旧路线和新路线，避免移出较远地点后旧路线被裁掉。

没有路线时这两层数据被清空，POI 仍留着。新建对话会清掉路线；切换历史对话也会清掉路线。手动规划和 Agent 规划共用同一个 `route` 状态，后完成的那次覆盖前一次。`priorRoutes` 只由“仅保留地点重算”产生，最多保留 5 条旧路线。

多段路线在数据上是 GeoJSON `MultiLineString`；单段是 `LineString`。前端两种都能画。

### 3.4 地图上不能做的事

点击空白地图不会落下一个自由点。「自由选点」是规划器里的一种列表模式，点仍然来自搜索框或已有 POI 圆点。地图也不显示道路名称气泡、分段距离标注、方向箭头或动画小人。

---

## 4. 浮动窗口本身

左右两个面板共用 `FloatingPanel`。标题栏从左到右是：拖拽把手图标、标题（「路线规划器」或「DeepSeek Harness Agent」）、折叠、最大化、关闭。

| 操作 | 结果 |
| --- | --- |
| 按住标题栏空白处拖动 | 窗口跟着走，但不能拖进顶栏区域（大约 y&lt;76）或贴死屏幕边缘 |
| 拖右下角 | 浏览器原生双向缩放。规划器最小约 380×520，Agent 最小约 400×520 |
| 减号 | 收成 42px 高的标题条，内容隐藏，不能再缩放 |
| 展开图标 | 从折叠恢复 |
| 最大化 | 几乎铺满顶栏以下的区域；再点一次回到刚才的尺寸。最大化时不能拖、不能缩放 |
| 关闭 | 窗口消失，底部正中出现停靠按钮 |

关掉规划器后，底部出现「路线规划器」按钮；关掉 Agent 后出现「Agent」按钮。再点即可按关闭前保存在本地的位置打开。折叠、最大化和关闭状态本身不写入本地存储，只有矩形位置会保存。刷新页面后窗口回到打开状态，但会用上次的坐标和大小。

标题栏上的按钮不会触发拖拽。窗口被点中时 `z-index` 提到很高，所以规划器和对话可以互相叠住，后点的在上面。

---

## 5. 左侧：路线规划器

这是不经过大模型的规划入口。标题区写着「探索你的城市轨迹」和「真实路网 · 动态POI · 可验证路线」，旁边有一个缓慢浮动的圆规图标。其下是模式开关、输入区、POI 类别、规划按钮、三格指标和数据来源。

### 5.1 两种模式

**起终点模式（默认）**

- 「起点」「终点」各有一个带图钉图标的搜索框。选中后，框下方出现一条蓝左边（终点是更浅的蓝）的短名称，右侧可清除。清除会重建输入框。
- 「途经点（可选）」使用放大镜搜索框。每选中一个地点就追加到列表，不会替换上一个。
- 列表左侧是序号。上箭头、下箭头调整途经顺序，叉号删除。第一个不能再上移，最后一个不能再下移。
- 真正拿去算路的顺序是：起点 → 途经点从上到下 → 终点。
- 起点和终点都选好之后，按钮文案变成「连接 N 个地点」。缺任一个时按钮禁用，文案是「请选择起点和终点」。

**自由选点**

- 不区分起点和终点。提示语写明：搜索或从地图 POI 加入至少 2 个地点，再按列表顺序连接。
- 搜索框占位示例是「断桥残雪、苏堤春晓」。选中后进入可滚动列表（大约最多显示 174px 高）。
- 勾选「最后返回第一个地点，生成闭环」后，手动规划仍会把第一个点再追加到末尾，例如 A→B→C 变成 A→B→C→A。地图上最后一个方块标记会落回 A 的坐标，和 1 号圆标重叠。
- 同一个复选框在「优化访问顺序」时不再靠追加重复点实现，而是把 `closed_loop=true` 传给后端；优化器把最后一点回起点的边计入目标函数，地图只显示一份起点标记。
- 少于 2 个点时按钮文案是「请至少选择 2 个地点」。

两种模式的列表互不干扰：在起终点模式里加的途经点，切到自由选点后不会出现；切回来还在。从地图卡片「加入当前路线」时，自由选点模式加入地点列表，起终点模式加入途经点，不会自动填起点或终点。

同一个坐标（经纬度差小于约 0.000001°）不会重复加入。

### 5.2 地点搜索框

`LocationSearchInput` 在起点、终点、途经点和自由选点里是同一组件。

用法：输入至少 2 个字符。停止输入约 260ms 后请求 `POST /api/geocode/search`，最多 8 条。输入框右侧出现旋转图标。下拉层贴在输入框下方，每条显示短名称（逗号前）和完整 `display_name`。用鼠标点一条，或在有结果时按 Enter 选第一条。没有匹配时下拉层写「没找到匹配地点，请换个更具体的名称」。焦点离开约 160ms 后下拉层关闭，这段延迟是为了让点击选项先生效。

后端检索顺序：

1. 西湖演示 POI 名称索引（`Datasets/raw/osm_features.gpkg`，中文名、官方名、别名都参与匹配）。
2. 北京、上海、浙江离线地点索引（各地区 `processed/locations.csv`）。
3. 只有本地一条都没有时，才请求 Nominatim（`countrycodes=cn`，中文优先）。城市前缀会被改写成更明确的查询，例如「杭州断桥」会变成「断桥, 杭州市, 浙江省, 中国」。

匹配分三档：名称集合里有完整词、以关键词开头、关键词出现在名称中。完全命中排在前面，同档再按名称长短。离线结果的展示名会带「（上海市离线数据）」这类后缀，输入框里采用的短名会把后缀截掉。结果按「展示名 + 约 5 位小数的坐标」去重。

地理编码缓存写在 `Datasets/runtime/geocode.json`。Agent 使用的 `geocode_location` 会先读这份缓存，再走上面的搜索并取第一条。规划器搜索框本身不写「只返回第一条」；它把候选都给用户选。

### 5.3 POI 类别芯片

五个胶囊按钮：景点、历史、公园、博物馆、酒店。再点一次取消。默认前三个亮起。它们只决定这次规划时地图上刷新哪些点，不改变道路算法，也不从路线里删点。

全部取消时，前端仍会用 `attraction` 去查，避免空类别。后端还认识 `arts`（艺术中心、剧院）和 `information`（旅游咨询），规划器没有把它们做成按钮；Agent 可以在工具参数里使用。

各类别对应的 OSM 标签：

| 界面/工具名 | OSM 含义 |
| --- | --- |
| attraction | `tourism=attraction` 或 `viewpoint` |
| history | 任意 `historic=*` |
| park | `leisure` 为 park、garden、nature_reserve |
| museum | `tourism` 为 museum、gallery |
| hotel | hotel、guest_house、hostel、apartment、motel |
| arts | `amenity` 为 arts_centre、theatre |
| information | `tourism=information` |

查询结果只保留有名称的点，面状地物取内部代表点，再按到查询中心的地面距离过滤。同一 OSM 对象只留一个。

### 5.4 按下「连接 N 个地点」

按钮在请求期间变成「正在穿行真实路网…」，并显示白色转圈，此时不能重复提交。

前端并行发两个 POST：

- `/api/routes/plan`：`network_type` 固定为 `walk`，`search_radius_m` 为 5000。waypoints 是去掉首尾之后的点。
- `/api/pois/search`：中心是全部选点的平均经纬度，半径 3000 米，`limit` 60，类别为当前芯片。

两条都成功后：

- 三格指标更新。总距离是 `distance_m / 1000`，保留两位，单位 km。时间指标是 `estimated_duration_min` 四舍五入后的分钟：距离口径下按同一路径逐边估速，时间口径下按最快路径；不是实时路况。周边 POI 是返回条数，查询到 0 个时显示 0，未查询时显示破折号。
- 路线下方逐段列出「起点 → 第 1 站 0.8 km · 10 min」；`segments` 现在同时带 `distance_m` 和 `duration_min`。
- 脚注左侧变成数据来源：「西湖演示缓存」「离线城市数据包」「OSM查询缓存」或「OSM实时查询」。
- 地图画出路线并飞到该范围。

任一请求失败，顶部弹出错误原文（后端 `detail`），已有路线不一定被清掉。规划中会先清掉当前选中的 POI 卡片。

### 5.5 这条路线在后端怎么算出来

`OsmService.plan_route` 的步骤是固定的，和谁调用无关（规划器 REST、Agent 的 `plan_walking_route`、最终发布里的每一段，都走这里）：

1. 用全部点的平均坐标当查询中心。所需半径 = 中心到最远点的大圆距离 + 750 米，再和请求里的 `search_radius_m` 取较大值。超过 10000 米直接拒绝，提示缩小区域或分段。因此一条横跨整个上海的步行路线不会被一次算完。
2. 准备步行路网，优先级是：
   - 内存里已经加载过的图；
   - 若全部访问点都落在西湖演示包内（离演示中心不超过 5 km 减 10 m 缓冲），读取 `Datasets/raw/osm_graph.graphml`；不再要求 `search_radius_m` 的 5 km 默认值也落在包内；
   - 否则若查询圆完全落在某个已安装离线包里，用 Pyrosm 按边界框从对应 `.osm.pbf` 裁剪，只建这一小块的步行图，并写成 GraphML 缓存；
   - 否则走 Overpass。端点按配置依次尝试，失败后冷却约 90 秒，冷却期内再请求会直接说明剩余秒数。
3. 建图后统一提取**最大强连通分量**，剔除单行道造成的死胡同、孤立子图等无法互相到达的节点；清洗前后的节点/边数写入组件统计。之后才把地点吸附到最近道路节点，因此吸附节点一定在最大强连通分量内。
4. 给每条有向边写入 `travel_time_s`：按 `highway` 标签查步行速度表（台阶 2.5、小路 4.0、普通步道 4.8 km/h 等）。
5. 相邻节点之间用 NetworkX 的 Dijkstra：距离口径权重是 `length`，时间口径权重是 `travel_time_s`。不是直线，也不是模型估计。
6. 把每条边的几何按行走方向接成一条折线，相邻段去掉重复的连接点。
7. 时间 = 路径上各边 `travel_time_s` 之和；距离口径下也逐边累加，而不是整段距离除以 4.8。自行车 15 km/h、驾车 30 km/h 只在 API 的 `network_type` 里存在，当前界面仍只发送步行。
8. 闭环时起点和终点传同一个坐标，`RouteResult.visited_points` 去掉重复的末尾起点，但 `segments` 仍包含最后一段回起点的路。

返回体里还有 `segments`：每一跳的米数、预计分钟和起止坐标；路线下方会逐段列出。`RouteResult` 同时带回 `weight`、`closed_loop` 和 `speed_profile`，方便界面区分口径。

POI 查询的数据优先级与路网类似，但演示包判定更严：查询中心到西湖演示中心的距离再加上查询半径，必须仍小于等于 5000 米，才读 `osm_features.gpkg` 并标记 `demo-cache`。否则依次是离线 PBF 裁剪、已有 GeoPackage 缓存、Overpass。来源字段就是脚注上的那四个中文名。

离线包边界（`Datasets/regions/catalog.json`）大致是：上海东经 120.84–122.20、北纬 30.65–31.90；北京东经 115.40–117.60、北纬 39.40–41.10；浙江东经 118–123、北纬 27–31.30。浙江优先级低于京沪。查询圆必须完全落在包内才会用该包，探出边界就会改走 Overpass。

### 5.6 优化访问顺序、双口径与导出

「连接 N 个地点」下面是「路线代价口径」两段开关和「优化访问顺序」按钮。

- **距离优先**：Dijkstra 用 `length`，目标函数是总米数。
- **时间优先**：Dijkstra 用 `travel_time_s`，目标函数是总秒数。速度按 `highway` 标签查表，台阶、小路、普通步道不同；不是实时路况，也不是导航 ETA。
- 优化请求把 `weight` 和 `closed_loop` 一起发给 `POST /api/routes/optimize`。景点数 2–15；Held-Karp 在 13–15 个点时可能需要数秒。
- 固定起点；起终点模式里「终点」和所有途经点都作为待排序景点；自由选点模式里第一个点是起点，其余是景点。勾选闭环时，最后一个景点之后回到起点，回边计入目标函数。
- 四种方案共用同一份矩阵：当前列表顺序、最近邻、最近邻 + 2-opt、Held-Karp。点击任一方案，地图和下方指标一起切到该方案的路线。
- 对照表第一行显示当前是距离/时间口径、开放/闭环，以及矩阵是「缓存命中」还是「矩阵构建」。命中时还会显示首次构建耗时和本次读取耗时。
- 表下方显示路网/直线距离平均比值、最大吸附距离，以及强连通清洗剔除的节点/边数。若某矩阵存在不可达点对，优化会返回明确错误而不是画一条假路线。
- 导出按钮：
  - 「对照 CSV」：四种方案的代价、单位、公里数、预计时间、求解耗时、Gap、2-opt 改进和顺序；
  - 「距离明细 CSV」：起点/景点两两之间的 `network_m`、`travel_s`、`straight_m` 和 `ratio`；
  - 「路线 GeoJSON」：当前方案折线 + 带编号地点；
  - 「路线 GPX」：当前方案折线，可导入常见 GPS 软件。

时间口径下总距离仍显示公里数，因为它来自同一批最快路径；两条不同口径的路线可能给出不同的公里数和分钟数，这是正常的，不应该把分钟数再按 4.8 km/h 反推。

### 5.7 移出地点与仅保留地点重算

规划完成后，指标和分段列表下方出现「路线地点」列表，每行是当前路线实际经过的地点，带复选框。列表保存在 `routeStops` 中，和当前 `route` 分开：第一次规划时用路线初始化，之后重算只更新地图路线，不清空这个列表。

- 勾选若干地点后按「仅规划保留的 N 个地点」。至少保留 2 个点；如果只剩 1 个，按钮禁用。
- 保留点按当前 `route.visited_points` 的顺序重连；起点、终点和途经点都可以移出。
- 重算请求仍走 `POST /api/routes/plan`，额外发送 `closed_loop`。原来是闭环（`closed_loop=true` 或首尾坐标相同）就继续算闭环，否则算开放路线。
- 自由选点模式下，保留点直接写回 `places`；起终点模式下，第一个保留点写回起点、最后一个写回终点、中间点写回途经点；闭环时终点与起点相同。
- 旧路线进入 `priorRoutes` 历史栈（最多 5 条），地图暗色保留；新路线亮色覆盖。
- 重算成功后会清空 `optimizeResult` 和 `selectedAlgorithm`：旧矩阵的 Gap、耗时和算法对照不能冒充新路线的结果。
- 指标、分段、GeoJSON/GPX 导出、优化按钮和周边 POI 检索都只看新的 `route` 和更新后的地点列表。
- 重算失败时保留原路线并弹出 toast，不会把地图清空。
- 重算成功后 `removedStopKeys` 不清空，已移出的地点继续显示勾选和「移出」标记；`routeStops` 也仍是首次规划的全集。因此可以取消某个勾选把它加回来，或再勾选其他地点，再点一次按钮重新规划，流程与首次完全一致。
- 取消全部勾选后，按钮文案变成「恢复全部 N 个地点并重规划」，可以一次恢复原路线；恢复成功后 `hasAppliedRemoval` 归零，按钮回到禁用状态。
- 规划器用 `preserveRemoval` 标记“下一次 route 变化来自本面板的重算”，避免路由 watcher 把刚保留的选择重置；`loading` 结束后 250ms 的清标记逻辑会在请求失败时兜底，另有 120 秒超时。
- 只有外部路线变化（重新点「连接 N 个地点」、切换算法、Agent 发布、切换会话）才会重建 `routeStops` 并清空勾选。

如果只是移动/新增地点而不是移出，仍用原来的「连接 N 个地点」或「优化访问顺序」，这条路径不会产生旧路线图层。

---

## 6. 底部 POI 卡片

只有点中地图上的圆点才出现。卡片在屏幕下部正中，宽约 260px，自下而上淡入。

卡片内容：

- 小标题 `SELECTED POINT`
- 地点名称
- 类别，用中点连接 OSM 类别键名（例如 `attraction · park`）。没有类别时写 `OSM POI`
- 纬度、经度，各 5 位小数
- 右上角关闭
- 「加入当前路线」

加入之后卡片消失，顶部提示「已将“某某”加入路线」。点被送进规划器当前模式的列表，但不会立刻重算路线，需要再按规划按钮。若该点已在列表里，列表不变，提示仍会出现。

窄屏时卡片会被抬高，以免挡住下半屏面板。

---

## 7. 右侧：Agent 对话

标题栏下是 Agent 面板，不是第二个规划表单。它的职责是：把一句中文变成工具调用，再把最终文字和最终路线交回界面。

### 7.1 头部状态

- 左侧机器人图标，右下角有一个蓝点。名字是「YourRoad Agent」。
- 副标题在健康检查认为密钥已配置时显示「DeepSeek · DSH工具在线」，否则是「等待DeepSeek密钥」。这只反映进页那次健康检查；密钥是后来才写进 `.env` 的话，需要刷新页面。没有密钥时仍可打字，但发送后会在对话里收到系统错误，大意是尚未设置 `DEEPSEEK_API_KEY`。
- `DSH` 徽章只是标识。
- 方框加号：新建对话。思考过程中禁用。
- 时钟图标：展开或收起历史菜单。

### 7.2 历史菜单

菜单浮在面板右上，列出本机已保存的会话。每条是第一句用户话的前 32 个字（更长加省略号）、消息条数、月日和时间。当前会话左侧有一条蓝线。没有记录时显示「发送第一条消息后，对话会自动保存在本地。」

点一条会话会：

- 换成该 `session_id`，并写入 `localStorage`
- 用 `GET /api/agent/sessions/{id}` 拉回消息和工具时间线
- 清空地图路线和选中的 POI
- 脚注数据来源改成「历史对话」

思考过程中不能切换。历史里的路线几何没有存进聊天记录，所以切换回来只能看到当时的文字和工具名称，看不到那条蓝线。若要看线，需要在该会话里再让 Agent 规划一次，或用左侧规划器重算。

新建对话会生成 `session-` 加 UUID，消息重置为一条新的欢迎语，清空工具步骤和地图路线，脚注写成「新对话」。POI 圆点保留。正在思考时不能新建。

### 7.3 消息区

欢迎语是：

> 你好，我是 YourRoad。告诉我你想去哪里、偏好什么、最多走多远，我会调用真实OSM工具完成规划与验证。

用户气泡靠右，蓝渐变白字。Agent 气泡靠左，带火花图标，内容按 Markdown 渲染：标题、粗体、斜体、行内代码、代码块、列表、引用、表格。原始 HTML 会先转义，不会执行。表格可横向滚动。系统错误是通栏的琥珀色气泡，例如连接失败或工具抛出的异常文本。

消息少于 3 条时（通常是还没完成第一轮问答），输入框上方有三条可横向滑动的建议，点一下就发送：

- 规划一条经过公园的西湖步行路线
- 帮我找附近的酒店和历史景点
- 解释当前路线为什么这样走

第三句并不会把「当前地图路线」作为结构化数据发给模型。模型只能看到本会话里已经说过的话和工具结果。刚进页就点它，Agent 并不知道左侧还没规划。

输入框占位是「描述你的旅行愿望与限制…」。Enter 发送，Shift+Enter 换行。发送按钮在空白或思考中禁用。发送后用户气泡立刻出现，输入被清空。

思考中，消息区底部有三个跳动的蓝点，旁边写「正在调用真实地图工具」。同时脚注会先变成「Agent正在理解并规划…」。

### 7.4 可审计执行过程

一轮对话进行时，消息下方出现「可审计执行过程」。副标题写明：展示工具调用，不展示隐藏思维链。

每一行有工具图标、中文标题、标题右侧的原始工具名小标签、一句参数摘要，以及状态图标。内置探查工具也有可读名称：`list_mcp_resources` 显示「列出 MCP 资源」，`list_mcp_resource_templates` 显示「列出 MCP 资源模板」，`pwsh` 显示「执行 PowerShell」。参数摘要会写出 `server=zyourroad`、`Get-ChildItem ...` 等关键内容。

| 状态 | 图标 | 含义 |
| --- | --- | --- |
| running | 旋转圈 | 工具已发出，结果未回 |
| completed | 绿色勾 | 工具返回了可解析结果 |
| failed | 红色感叹号 | 工具报错；摘要显示参数 + 实际错误首行 |

图标对应关系：地理编码是图钉，POI 检索是放大镜，准备区域是数据库，步行规划和最终发布是路线，`pwsh/bash` 是终端图标，`list_mcp_*` 是列表树图标，其他是芯片图标。

标题和摘要由后端根据工具名生成，例如：

- 解析地点：查找「某地名」的真实坐标
- 检索旅游 POI：查询类别和半径
- 准备区域地图数据：下载或读取某半径的小区域缓存
- 计算真实步行路线：连接起终点与若干途经点
- 发布最终游览路线：发布若干地点，包含若干处非步行衔接

同一工具调用先出现 running，结果回来后原位改成 completed 或 failed，不会刷成两行。失败时不再只写「调用失败，Agent将停止无效重试」，而是保留调用参数并附上工具返回的第一行错误，例如 `执行PowerShell命令：Get-ChildItem ...；失败：Error: ...`。这些行来自 SSE 的 `trace` 事件。模型内部推理 token 不会流到页面上；最终回答在整轮结束后一次插入。历史会话重新打开时，`_stored_traces` 用同样的 `call_details` 重建标题、参数和错误。

回合结束时：

- 若响应里有 `route`，地图换成该路线，脚注变为「Agent · OSM真实路网」。
- 若响应里有 `poi_result`，圆点被替换，脚注再被写成「Agent · 」加数据来源。两者都有时，后写的 POI 来源会盖住前一句「OSM真实路网」。路线本身仍然画上。
- Agent 文本追加为一条新气泡。
- 历史列表在后台刷新，新会话会出现。

失败时追加系统气泡，同样尝试刷新历史。后端会在对话文件里记一条「请求失败：异常类名」，不会把密钥或堆栈写进这条面向用户的系统消息；SSE 的 `error` 事件则带异常字符串，所以界面上仍可能看到较具体的失败原因。

底部固定小字：「路线与距离由OSM确定性工具计算，Agent不直接编造地图事实」。

### 7.5 一次对话在后端怎么走

浏览器 `POST /api/agent/chat/stream`，体是 `{ message, session_id }`。响应是 `text/event-stream`。前端按空行切块，识别 `status`、`trace`、`message`、`error`。后端还会发出原始 `notification`，当前界面不使用它。非流式的 `POST /api/agent/chat` 做同样的计算，但不推中间过程；页面没用这条。

服务端流程：

1. 立刻推送状态「Agent正在理解并规划…」。
2. `AgentService` 用一把全局锁串行处理所有会话。上一个用户的回合没结束时，下一个回合会排队。这是为了复用同一个 DSH 进程。
3. 把用户消息追加到 `.dsh-home/sessions/--<仓库路径>--/<session_id>/zyourroad-chat.jsonl`。
4. 启动或复用一个 `DeepSeekHarness` 进程：provider `deepseek-official`，模型来自 `ZYOURROAD_DSH_MODEL`，`max_tokens` 8192，profile `sdk-minimal`，并加载 `plugins/zyourroad-osm/cordis.patch.yml`。该补丁用官方 MCP Client 以 stdio 启动 `python -m backend.app.mcp_server`，工具超时 180 秒。工具在模型侧的名字带前缀 `mcp__zyourroad__`。
5. 若进程内已经有这个会话，就 `start_session` 继续；否则尝试 `resume_session`。原生 DSH 日志丢失时，把本应用最近约 12 条、最多约 12000 字的对话贴进本次输入，让模型接着聊，并要求它不要逐字复述。
6. 系统提示（环境变量 `DSH_SYSTEM_PROMPT`，只在未设置时写入）要求模型：优先调用工具；不编造距离和坐标；待排序景点达到 2 个（含起点至少 3 个点）时先调用一次 `optimize_itinerary_order`，再按返回的 `names` 顺序发布；最终地点必须用 `publish_tourism_itinerary` 一次提交；轮渡、地铁等非步行衔接要把后一段第一个地点的下标放进 `break_before_indexes`；不要用多次 `plan_walking_route` 充当最终发布；用户没指定起终点时可以自行排多个想去的点；同一轮不要反复地理编码或换半径碰运气；最终中文回答只保留顺序、总距离、时间和必要提示。
7. 每个 `session.event` 里的 `tool/call` 与 `tool/result` 追加到同目录 `zyourroad-events.jsonl`，并转成上面的 trace。思考链事件即使 DSH 产生了，也不会被收成界面上的步骤。
8. `AgentArtifactCollector` 从工具结果的 JSON 文本里收集地图数据。`publish_tourism_itinerary` 的结果记为正式路线。`plan_walking_route` 只作为探索路线留着；若最终没有发布，界面会退回最后一条坐标序列不同的探索路线。`search_tourism_pois` 的最后一次成功结果成为 POI。探索路线不会在工具返回的中途画到地图上，因为前端只在 `message` 事件里更新地图。正式发布存在时，探索路线不会覆盖它。
9. 助手最终文本写入聊天 jsonl，SSE 推送 `message` 和 `done`。

因此「解释当前路线」这类问题通常只有文字，不一定改地图。只有工具结果里解析出路线或 POI，地图才变。

### 7.6 Agent 能调用的六个工具

它们和 REST 共用同一个 `OsmService` 单例，所以缓存、半径上限和错误信息一致。

| 工具 | 模型用它做什么 | 成功后界面可能看到 |
| --- | --- | --- |
| `geocode_location` | 把地名变成一个 WGS84 坐标 | 只有 trace，地图不变 |
| `search_tourism_pois` | 按地名或经纬度、半径、类别找 POI，可排除类别 | 回合结束时圆点更新 |
| `prepare_osm_region` | 预先裁剪小区域路网和 POI，返回节点数、边数、POI 数和缓存键 | 只有 trace；为后续算路热缓存 |
| `plan_walking_route` | 试算一段真实路线（可选距离/时间口径） | 若本轮没有最终发布，回合结束时可能把这条画出来 |
| `optimize_itinerary_order` | 对 2–15 个待排序景点比较当前顺序、最近邻、2-opt 和 Held-Karp，返回确定性顺序与代价 | 只有 trace；最终发布应使用返回的 `names` 顺序 |
| `publish_tourism_itinerary` | 按最终顺序一次提交 2–15 个点，并用断点下标切开非步行段 | 这是应该出现在地图上的那条线 |

顺序优化工具接受 `start_latitude/start_longitude`、`attractions` 坐标数组、`weight`（`length`/`time`）、`closed_loop` 和 `network_type`。它和规划器共用矩阵缓存；返回 `order`、`names`、`cost`、`cost_unit`、`cost_m`、`cost_s`、`gap_percent` 和四种方案对照。系统提示要求待排序景点达到 2 个（含起点至少 3 个点）时先调用一次，再按 `names` 发布。`plan_walking_route` 和 `publish_tourism_itinerary` 也接受可选的 `weight`/`network_type`；发布时应沿用顺序优化的 `weight`，否则会出现“按时间排序、却按距离画线”的口径错位。

发布工具的断点规则：下标从 0 起，必须严格递增，每一段至少两个点。例如点是 `[A,B,C,D]`，`break_before_indexes: [2]` 表示 A–B 步行、然后从 B 到 C 画橙色虚线、再 C–D 步行。各段距离和时间相加；步行段内部仍是 Dijkstra。虚线不计入路网距离。

工具失败时，trace 变红，系统提示要求模型停止无效重试。Overpass 冷却、超过 10 km、未知类别、找不到地名，都会变成这种失败。

修改系统提示或 MCP 工具代码后，需要重启后端并新建会话，旧会话里的工具定义不会热更新。

### 7.7 为什么会出现「Agent已完成处理，但没有返回文本」

这句话来自前端 `onMessage` 的兜底：`response.answer` 为空时显示它。真正的错误不一定在模型，而在 DSH 运行时启动后的第一个回合。

用最小对话抓 `RunResult` 可以看到：

- `finish_reason` 是 `error`，不是 `stop`；
- 事件只有 `turn/start` 和 `turn/end`，没有 `assistant/message`；
- `turn/end.data.reason.error.message` 是 `The specified module could not be found. \\?\F:\snapshot\node\node_modules\@koromix\koffi-win32-x64\win32_x64\koffi.node`。

原因是部分 Windows `deepseek-harness-runtime-bin` 把 `@koromix/koffi` 的路径写死为打包机的 `F:\snapshot\node\...`。DSH 的 `sandbox-local`/`fs-local` 在 Windows 上要加载这个原生模块；找不到后整个回合直接失败，模型没有被调用。

修复分三步，已经在项目内实现：

1. 运行 `python .\scripts\prepare_dsh_runtime.py`，把锁定的 Office/koffi sidecar 下载到 `Datasets/runtime/dsh-resources/<identity>/office`，同时把匹配的 `node-pty` 安装到 `Datasets/runtime/dsh-resources/node-pty`。如果 Windows 的缓存 rename 失败，脚本会从已下载归档重建同样的目录布局。
2. `backend/app/config.py` 的 `_export_koffi_sidecar()` 找到 sidecar 后注入 `DSH_KOFFI_ENTRY`、`DSH_KOFFI_PLATFORM`、`DSH_OFFICE_SIDECAR`，并在 `NODE_OPTIONS` 后追加 `--require .../scripts/dsh_koffi_loader.cjs`。
3. preload 同时改写 `Module._resolveFilename` 和 `process.dlopen`：前者处理 `require('koffi')`，后者把 SEA 快照里的 `\\?\F:\snapshot\...\koffi.node` 重定向到 sidecar 的真实 `win32_x64/koffi.node`。

验证：最小对话返回“收到”，`finish_reason=completed`；真实西湖规划返回 200+ 字、路线和 POI。若仍看到兜底文案，先确认 sidecar 脚本输出「已就绪」，再重启后端并新建会话（旧的 DSH 子进程不会热替换）。

### 7.8 为什么规划后 Agent 还说「没有当前路线」

规划器的路线只存在前端 `route` 状态里。Agent 的 MCP 会话是另一套进程/上下文，`plan_walking_route`、`publish_tourism_itinerary` 的调用记录不会自动包含规划器那条线。所以旧版聊天请求只有 `message` 和 `session_id`，模型确实看不到“当前路线”，只能按提示词向用户重问起点。

现在 `ChatRequest` 增加可选的 `route_context`：

- `App.vue` 的 `buildRouteContext()` 从当前 `route` 生成：总距离、预计时间、出行方式、`weight`、`closed_loop`、访问顺序（名称+坐标）和分段距离/分钟；
- 地点名称优先从当前 `pois` 按坐标匹配，匹配不到就用 `地点N`；
- `streamAgentChat()` 把 `route_context` 一起 POST 到 `/api/agent/chat/stream`；
- `AgentService.chat()` 在用户消息前拼一个「当前界面路线（规划器已显示）」块，并明确说明“这是界面当前路线，不是 MCP 历史；问解释路线时不能声称没有已规划/已发布路线”；
- 同时要求模型不要编造上下文没有给出的算法细节；`source` 不是 `optimize/agent` 时不要说做过 TSP、2-opt 或算法对比；
- 用户要求改路线时，Agent 仍然可以调用 MCP 工具重新规划。

因此规划器路线和 Agent 路线现在都能被解释：前端的 `route` 是唯一“当前路线”来源，Agent 不需要去 MCP 历史里找。没有路线时 `route_context` 为 `null`，Agent 还是按原来的方式询问起点和偏好。

### 7.9 截图里三次工具调用分别是什么

从 `zyourroad-events.jsonl` 可以还原：

1. `list_mcp_resources`，参数 `{"server":"zyourroad"}`：成功，返回 `{"resources":[]}`。它在枚举 MCP 资源，不是在查路线。
2. `list_mcp_resource_templates`，参数 `{"server":"zyourroad"}`：成功，返回空模板列表。
3. `pwsh`，参数 `Get-ChildItem -Force | Select-Object Mode,LastWriteTime,Length,Name | Format-Table -AutoSize`：失败。模型在找不到资源后试图用 PowerShell 看工作目录。

第三次失败有两层原因：

- 捆绑运行时的 `node-pty` 缺少 `prebuilds/win32-x64/conpty.node`，PTY 根本起不来；
- 项目 patch 覆盖 `terminal-pwsh` 配置时漏了 `shellDialect: pwsh`，实际把 bash 参数 `--noprofile --norc -i` 传给 PowerShell，即使原生模块修好，PowerShell 也会立刻退出。

现在：`prepare_dsh_runtime.py` 安装匹配的 `node-pty`；preload 重定向 `node-pty`/`conpty.node/pty.node` 并强制内置 ConPTY；`cordis.patch.yml` 补回 `shellDialect: pwsh`、`shellPath` 和 `timeoutMs`。实测 Agent 执行 `echo fixed-ok` 返回 `fixed-ok`。系统提示也新增“不要用 `list_mcp_resources`/`list_mcp_resource_templates`/`pwsh` 探测路线工具”，正常情况下不会再出现这两次资源枚举。

界面上三次调用现在分别显示为「列出 MCP 资源 `list_mcp_resources`」「列出 MCP 资源模板 `list_mcp_resource_templates`」「执行 PowerShell `pwsh`」，并显示参数摘要；第三次历史上会显示实际错误首行，未来成功则显示「执行 PowerShell 命令：…；已完成」。

---

## 8. 一次手动规划的例子

目标：从断桥走到苏堤，并在地图上看公园和历史点。

1. 确认顶栏是 `SYSTEM ONLINE`。若只是橙点，先启动后端；规划器本身不需要 DeepSeek 密钥。
2. 保持「起终点模式」。
3. 起点输入「断桥」，在下拉里点「断桥残雪」或名称最接近的一条。不要只靠 Enter，除非第一条就是你要的。
4. 终点同样选择「苏堤春晓」或苏堤相关条目。
5. 若要经过平湖秋月，在途经点搜索并加入，再用箭头把它放在合适的位置。
6. 确认「景点、历史、公园」仍亮着。不想看酒店就不要点亮「酒店」。
7. 按「连接 N 个地点」。按钮转圈时等待，西湖演示图通常比第一次裁剪省级 PBF 快。
8. 看三格数字：总距离、按道路等级估速得到的分钟、周边 POI 个数。脚注应为「西湖演示缓存」或「离线城市数据包」。
9. 地图飞到一条贴着道路的蓝线，1 号在断桥侧，末号方块在终点。圆点是周边 POI，不是路线必经点。
10. 点一个圆点，读名称和坐标，按「加入当前路线」。它会变成新的途经点。再按一次规划按钮，蓝线才会改道。

若提示查询半径超过 10000 米，说明起终点离得太远。改成同一城区内的点，或让 Agent 用断点把行程拆开。

---

## 9. 一次 Agent 规划的例子

目标：用一句话得到西湖公园步行顺序。

1. 顶栏模型名出现，且 Agent 副标题是「DeepSeek · DSH工具在线」。否则先在仓库根目录 `.env` 配置 `DEEPSEEK_API_KEY`，重启后端并刷新页面。
2. 点建议「规划一条经过公园的西湖步行路线」，或自己写约束，例如「明天在西湖步行，想看公园和历史景点，总路程不要太长，从断桥出发再回到断桥附近」。
3. 先看到三个跳动点，然后执行过程逐行出现：解析地点、检索 POI、准备区域、发布路线。绿色勾表示该步拿到了工具数据。
4. 全部结束后出现一段中文说明，通常含地点顺序、总距离和预计时间。地图同时出现蓝线；若回答里安排了轮渡或地铁，对应位置是橙色虚线。
5. 若只想保留这段对话以后再看文字，刷新页面即可，只要会话 id 还在历史列表里。蓝线需要重新规划才会出现。

Agent 选择景点顺序靠语义和提示词，不靠旅行商算法。同一句要求多运行几次，顺序可能不同，但每一段的道路几何和米数在路网不变时应可复现。

---

## 10. 提示与错误出现在哪里

顶部居中的深色琥珀条是 toast，约 3.6 秒消失。用于后端没启动、POI 加载失败、手动规划失败、加入路线成功、会话加载失败。

对话内部的琥珀色气泡是 Agent 通道的错误，会留在消息列表里。工具级失败优先看执行过程里的红行，那里有「查找失败」「半径超限」「冷却期」等更具体的句子。

常见原因对照：

| 现象 | 原因 |
| --- | --- |
| 顶栏 CONNECTING | 8000 端口没有 FastAPI |
| 搜索无结果 | 本地索引和 Nominatim 都没有合适名称；换更具体的词 |
| 规划按钮一直禁用 | 起终点没选全，或自由选点少于 2 个 |
| 半径超过 10000 米 | 点太分散；缩短跨度或分段 |
| 冷却期若干秒 | 区域不在京沪浙离线包或西湖演示包内，Overpass 刚刚失败 |
| 等待 DeepSeek 密钥 | `.env` 未配置或后端没读到 |
| Agent 总显示「已完成处理，但没有返回文本」 | DSH 的 koffi sidecar 未就绪或 `NODE_OPTIONS` preload 未生效；运行 `scripts/prepare_dsh_runtime.py`，重启后端并新建会话 |
| 规划后问「解释当前路线」，Agent 说没有路线 | 聊天请求未带 `route_context`；确认前端已更新并重启后端，见 7.8 |
| 第三次工具调用 `pwsh` 失败 | `node-pty/conpty` 缺失或 `terminal-pwsh` 丢了 `shellDialect`；运行 `prepare_dsh_runtime.py` 并重启，见 7.9 |
| 移出地点后地图只剩一条线 | 重算失败时旧路线保留；若旧路线图层被清空，检查是否又点了「连接 N 个地点」（该按钮会主动清空 `priorRoutes`） |
| 历史能看字、地图没线 | 切换会话会主动清空 `route` |
| 圆点很多但路线不经过它们 | 圆点是周边检索，不是必经点 |

---

## 11. 数据落在哪里

| 内容 | 位置 | 界面是否直接展示 |
| --- | --- | --- |
| 当前会话 id | 浏览器 `localStorage` `zyourroad.session-id` | 否 |
| 面板位置 | `zyourroad.panel.v2.*` | 否 |
| 聊天文本 | `.dsh-home/sessions/.../zyourroad-chat.jsonl` | 历史菜单和消息区 |
| 工具调用与完整结果 | 同目录 `zyourroad-events.jsonl` | 执行过程只显示摘要；完整 JSON 可通过 `GET /api/agent/sessions/{id}/events` 查看 |
| DSH 原生会话 | 同目录 `session*.jsonl` | 否 |
| 地理编码缓存 | `Datasets/runtime/geocode.json` | 否 |
| 路网 / POI 缓存 | `Datasets/runtime/networks`、`pois` | 只通过速度和来源脚注间接感觉到 |
| 代价矩阵 | `Datasets/runtime/matrices/*.json` | 对照表显示缓存命中/构建耗时；同时含 `network_m` 与 `travel_s` |
| 实验输出 | `Datasets/runtime/experiments/` | CSV/JSONL/`figures/*.png` |
| DSH koffi sidecar | `Datasets/runtime/dsh-resources/<identity>/office` | 否；Agent 启动时自动读取 |
| 西湖固定图 | `Datasets/raw/osm_graph.graphml`、`osm_features.gpkg` | 来源显示「西湖演示缓存」 |
| 省市 PBF | `Datasets/regions/*/source/*.osm.pbf` | 来源显示「离线城市数据包」 |

会话 id 只允许字母数字、下划线和连字符。界面生成的 `session-<uuid>` 符合这个规则。

API 文档在 `http://127.0.0.1:8000/docs`。和界面直接相关的路由是：

- `GET /api/health`
- `POST /api/geocode/search`（搜索下拉）
- `POST /api/geocode`（Agent 工具，界面搜索不用「只取一条」这个接口）
- `POST /api/pois/search`
- `POST /api/routes/plan`（可选 `weight`、`closed_loop`）
- `POST /api/routes/optimize`（双口径、开放/闭环、逐对数据与连通统计）
- `GET /api/routes/optimize/{matrix_key}/pairs.csv`（缓存矩阵逐对距离）
- `POST /api/regions/prepare`（Agent 准备缓存；规划器不调用）
- `POST /api/agent/chat/stream`（请求体可带 `route_context`，见 7.8）
- `GET /api/agent/sessions` 与 `GET /api/agent/sessions/{session_id}`

---

## 12. 程序员对照：界面状态从哪来

```text
App.vue
  health, mapContext, toast, sessionId
  route, priorRoutes, pois, dataSource, selectedPoi
  messages, agentSteps, agentSessions, agentThinking
        │
        ├─ MapCanvas(route, priorRoutes, pois) → 点击 emit selectPoi
        ├─ PlannerPanel → emit plan / optimize / replan
        │     LocationSearchInput → /api/geocode/search
        └─ AgentPanel → emit send / newChat / selectSession
              streamAgentChat(message, sessionId, callbacks, route_context)
              → SSE trace + message

手动 plan
  /api/routes/plan + /api/pois/search
        └─ OsmService.plan_route / search_pois

Agent
  /api/agent/chat/stream
        └─ AgentService.chat
              DeepSeekHarness + MCP stdio
                    └─ mcp_server.py 六个工具
                          └─ 同一个 OsmService
              正式路线优先：publish_tourism_itinerary
              否则最后一条 plan_walking_route
              POI：最后一次 search_tourism_pois
              多段合并：route_utils.merge_route_results
```

前端关键文件：

- `frontend/src/App.vue`：布局、健康检查、两种规划结果如何写回地图、`priorRoutes` 旧路线栈、`buildRouteContext()`、会话切换。
- `frontend/src/components/MapCanvas.vue`：底图、POI 层、旧路线暗层、当前路线层、虚线层、编号/旧地点标记、闭环标记、镜头。
- `frontend/src/components/PlannerPanel.vue`：两种模式、类别、权重开关、闭环、优化对照、持久化的地点移出选择与重算、指标与导出。
- `frontend/src/components/AgentPanel.vue`：对话、建议、trace、历史。
- `frontend/src/components/FloatingPanel.vue`：拖动、缩放、折叠、最大化、关闭。
- `frontend/src/services/api.ts`：REST 与 SSE 解析，带 `weight`/`closed_loop` 参数。
- `frontend/src/utils/export.ts`：对照 CSV、逐对 CSV、GeoJSON、GPX 导出。
- `frontend/src/style.css`：顶栏、暗角、POI 卡片、toast、停靠条。

后端关键文件：

- `backend/app/main.py`：路由、SSE、trace 文案。
- `backend/app/agent_service.py`：DSH 生命周期、会话恢复、路线/POI 收集。
- `backend/app/mcp_server.py`：六个工具的参数形状，包括顺序优化工具。
- `backend/app/osm_service.py`：检索、缓存、裁剪、强连通清洗、逐边估速、Dijkstra。
- `backend/app/order_optimizer.py`：双口径矩阵、开放/闭环、最近邻/2-opt/Held-Karp、逐对数据。
- `scripts/prepare_dsh_runtime.py`：下载/重建 DSH koffi sidecar 与 node-pty sidecar。
- `scripts/dsh_koffi_loader.cjs`：把 DSH 的 koffi/node-pty/conpty 解析重定向到 sidecar 的 Node preload。
- `backend/app/route_utils.py`：多段拼接和橙色虚线的数据结构。
- `backend/app/conversation_store.py`：jsonl 会话和历史标题。
- `backend/app/config.py`：半径上限、Overpass、系统提示、模型名、koffi/node-pty/pwsh sidecar环境。

---

## 13. 现在做不到、以及值得接着做的事

下面每条都对应已经能在界面或代码里观察到的缺口，而不是泛泛的功能清单。

**顺序优化需要显式触发，且 Agent 依赖提示词。** 规划器的「连接 N 个地点」仍严格按列表顺序走；只有按「优化访问顺序」才会算矩阵并比较四种方案。Agent 侧已注册 `optimize_itinerary_order`，系统提示要求待排序景点达到 2 个（含起点至少 3 个点）时先调用它，但模型理论上仍可能跳过；发布工具没有强制校验「顺序是否来自优化器」。下一步可以把优化后的顺序回写到规划器列表，或在 `publish_tourism_itinerary` 里增加一个可选的 `order_source` 校验。

**规划器界面仍只有步行。** 后端已有 bike、drive 和逐边速度表，Agent 的 `plan_walking_route` / `publish_tourism_itinerary` 也接受 `network_type`，但规划器界面写死 `walk`；时间口径现在按道路等级估速，逐段距离和分钟已经显示。下一步是在规划器加交通方式选择，并明确自行车的路权、台阶推行和驾车单行道规则，而不是只换一个速度常数。

**换乘只是断线。** 橙色虚线不查询轮渡、地铁或公交。`break_before_indexes` 也没有类型字段，`kind` 永远是 `unrouted-transfer`。下一步应为断点增加方式（walk / ferry / metro）和可选的站点 id，虚线旁标注方式，而不是只换颜色。

**历史会话不带回地图。** 聊天 jsonl 没有保存最后一条 `RouteResult`。切换会话、刷新后文字还在，蓝线没了。把每轮最终 `route` 和 `poi_result` 一并写入会话，打开历史时走和 `onMessage` 相同的赋值，地图就能复原。

**规划器和 Agent 互相覆盖。** 只有一份 `route`。Agent 的探索性 `plan_walking_route` 在没有发布时也会在回合结束时画上，和「只有发布才改地图」的设计意图不完全一致。可以把发布路线和试算路线分成两种图层：试算用更淡的线，发布用当前的亮蓝线，并在脚注写明哪一种。

**类别和「周边 POI」容易被理解成路线约束。** 芯片只刷新圆点。用户可能以为点亮「公园」就会让路线经过公园。文案可以改成「地图上额外标出的地点」，并在 Agent 侧把「必须经过」做成发布前的显式点列，而不是只靠模型自觉。

**不能在空白地图上落点。** 自由选点仍依赖名称搜索。若要真正自由选点，需要地图单击得到经纬度，再反向查最近地名；在此之前，卡片上的「加入当前路线」已经是地图选点的唯一入口，而且它在起终点模式里只能当途经点。

**顶栏城市名是坐标框，不是数据源。** 西湖坐标会显示「杭州 · 西湖实验区」，即使这次 POI 来自浙江离线包或 Overpass。脚注才是真实来源。顶栏可以改成同时显示来源，避免把展示标题当成数据保证。

**全局锁让所有人排队。** 一个 DSH 进程配一把锁，第二个对话要等第一个工具链结束（工具超时可达 180 秒）。本地单用户演示没问题；若要同时开两个窗口比较方案，需要按会话隔离 harness，或至少让手动规划不和 Agent 抢同一把锁（手动规划现在本来就不进这把锁，但两个 Agent 会话会互相等）。

**10 km 查询上限和「整座城市一日游」冲突。** 这是有意的内存保护。改进不应去掉上限，而应让 Agent 把一日游拆成多个已缓存小区，逐段 `plan_route`，再用发布工具的断点或一个新的「跨缓存拼接」把几何接上。顶栏也可以在半径超限时直接说明该拆段，而不是只弹出后端句子。

**没有开放时间、门票、停留和体力。** 时间现在按道路等级估速，但仍不含实时路况、红绿灯、停留时长、开放时间、门票预算和体力消耗。readme 里的时间窗、预算、坡度、绿化和拥挤度都还没有数据字段。界面上若增加这些约束，必须先有对应的数据工具；否则模型只能在文字里假装考虑了。

**首次裁剪省级 PBF 会很久，界面只有转圈。** `prepare_osm_region` 的节点数和边数已经返回给 Agent trace 的结果 JSON，但 trace 摘要不显示进度百分比。长时间任务可以改成后端推送阶段（读取 PBF、建图、写缓存），让按钮或 trace 显示阶段名，避免用户以为卡死。

**强连通清洗与时间速度表仍需校准。** 当前清洗只会保留最大强连通分量；如果某个景点原本吸附到被剔除的边界节点，清洗后会改吸到分量内更远的节点，吸附距离应在结果里重点检查。时间速度表按 `highway` 标签给出固定假设，没有用实测步行速度校准，报告里只能作为“可复现的口径”，不能当作真实 ETA。

---

## 14. 使用时可以依赖的保证

- 蓝线的折点来自路网边的几何，长度来自边的 `length` 之和。
- 时间口径的分钟数是路径上各边按 `highway` 估速后的 `travel_time_s` 之和；距离口径的分钟数也用同一路径逐边估速。两者都不是导航 App 的实时 ETA。
- 闭环路线的最后一段回到起点，计入公里数和时间；地图上不重复显示起点标记。
- “仅保留地点重算”保留旧路线和已移出地点的暗色图层，新路线亮色覆盖；重合路段显示新路线。
- 重算后「路线地点」列表仍是首次规划的全集，已移出地点保持勾选和「移出」标记；取消勾选可加回，调整后可再次重算，取消全部后可恢复全部。
- 规划器路线会作为 `route_context` 随聊天请求发送；Agent 看到“当前界面路线”后应直接解释，不得声称没有已规划/已发布路线，也不得编造上下文没有的算法细节。
- Agent 返回的 `finish_reason=completed` 且存在 `assistant/message` 文本时，界面才把它当作正常回答；空文本只可能是运行时/工具失败，不应被当成模型回答。
- 橙色虚线是两段步行之间的缺口，不计入公里数。
- 编号顺序就是本次提交的访问顺序；优化后以对照表或返回的 `names` 为准。
- 搜索和算路不会让模型填写坐标；Agent 必须通过工具拿到坐标，顺序优化也必须通过 `optimize_itinerary_order`。
- 工具参数和结果写在本机 jsonl 里，可以事后审计。隐藏思维链不在界面上，也不在这套 trace 里。
- 京沪浙范围内的小区域查询优先读本地 PBF；西湖 5 km 演示包优先于在线下载。只有包覆盖不到时才访问 Overpass。
- 路网建图后会剔除最大强连通分量以外的节点；优化结果和 `prepare_region` 都会返回清洗前后规模。
- 算法对照 CSV、逐对距离 CSV、路线 GeoJSON 和 GPX 由当前浏览器结果直接导出，不额外上传到服务器。
