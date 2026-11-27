"""西湖演示路网上的景点顺序优化对照实验。

覆盖距离/时间两种代价口径与开放/闭环两种行程模型，比较：
当前列表顺序、最近邻、最近邻 + 2-opt、Held-Karp。

输出：
- west_lake_order_runs.jsonl：每次运行的完整结果；
- west_lake_order.csv：便于绘图的算法对照表；
- west_lake_weight_comparison.csv：同一组点的距离/时间顺序差异；
- figures/*.png：Gap、求解耗时、路网/直线比值、口径顺序重合度。

矩阵构建时间与顺序求解时间分开记录；命中缓存时同时记录首次构建耗时和本次读取耗时。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models import Coordinate, OptimizeRequest, PoiSearchRequest  # noqa: E402
from backend.app.order_optimizer import optimize_open_tour  # noqa: E402
from backend.app.osm_service import get_osm_service  # noqa: E402


DEFAULT_SIZES = (5, 8, 10)
DEFAULT_WEIGHTS = ("length", "time")
DEFAULT_MODES = ("open", "closed")
OUTPUT_DIR = PROJECT_ROOT / "Datasets" / "runtime" / "experiments"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="西湖演示路网的开放/闭环、距离/时间顺序优化实验。",
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_SIZES),
        help="景点数量，默认 5 8 10；Held-Karp 上限 15。",
    )
    parser.add_argument(
        "--weights",
        nargs="+",
        choices=DEFAULT_WEIGHTS,
        default=list(DEFAULT_WEIGHTS),
        help="代价口径，默认同时跑 length 与 time。",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=DEFAULT_MODES,
        default=list(DEFAULT_MODES),
        help="行程模型，默认同时跑 open 与 closed。",
    )
    parser.add_argument("--repeats", type=int, default=1, help="每个规模重复次数。")
    parser.add_argument("--seed", type=int, default=42, help="重复抽样随机种子。")
    parser.add_argument("--max-pois", type=int, default=40, help="候选景点池大小。")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="输出目录，默认 Datasets/runtime/experiments。",
    )
    parser.add_argument(
        "--no-figures",
        action="store_true",
        help="只写 CSV/JSON，不生成 matplotlib 图。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sizes = sorted(set(size for size in args.sizes if 2 <= size <= 15))
    if not sizes:
        raise SystemExit("--sizes 至少需要一个 2–15 之间的整数")

    service = get_osm_service()
    start, pool = _candidate_pool(service, args.max_pois)

    runs: list[dict[str, Any]] = []
    for size in sizes:
        if len(pool) < size:
            continue
        for repeat in range(args.repeats):
            chosen = _choose(pool, size, repeat, args.seed)
            for mode in args.modes:
                closed_loop = mode == "closed"
                for weight in args.weights:
                    runs.append(
                        _run_once(
                            service,
                            start,
                            chosen,
                            size,
                            repeat,
                            weight,
                            closed_loop,
                        )
                    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_outputs(runs, args.out_dir)
    comparisons = _weight_comparisons(runs)
    _write_weight_comparisons(comparisons, args.out_dir)
    figures_written = False
    if not args.no_figures:
        figures_written = _write_figures(
            runs,
            comparisons,
            args.out_dir / "figures",
        )

    print(f"完成 {len(runs)} 次运行")
    print(args.out_dir / "west_lake_order.csv")
    print(args.out_dir / "west_lake_order_runs.jsonl")
    print(args.out_dir / "west_lake_weight_comparison.csv")
    if figures_written:
        print(args.out_dir / "figures")


def _candidate_pool(service: Any, limit: int) -> tuple[Any, list[Any]]:
    located = service.search_locations("断桥残雪", limit=1).results
    if not located:
        raise RuntimeError("西湖演示数据中没有找到断桥残雪，无法固定实验起点")
    start = located[0]
    pois = service.search_pois(
        PoiSearchRequest(
            center=Coordinate(latitude=start.latitude, longitude=start.longitude),
            radius_m=2500,
            categories=["attraction", "history", "park"],
            limit=min(max(limit, 40), 100),
        )
    )
    pool = []
    seen: set[str] = set()
    for poi in sorted(pois.pois, key=lambda item: item.name):
        if poi.name in seen or poi.name == start.display_name.split(",")[0]:
            continue
        if _same_point(start.latitude, start.longitude, poi.latitude, poi.longitude):
            continue
        seen.add(poi.name)
        pool.append(poi)
    return start, pool


def _choose(pool: list[Any], size: int, repeat: int, seed: int) -> list[Any]:
    if repeat == 0:
        return pool[:size]
    rng = random.Random(seed + repeat * 997)
    return rng.sample(pool, size)


def _run_once(
    service: Any,
    start: Any,
    chosen: list[Any],
    size: int,
    repeat: int,
    weight: str,
    closed_loop: bool,
) -> dict[str, Any]:
    result = optimize_open_tour(
        OptimizeRequest(
            start=Coordinate(latitude=start.latitude, longitude=start.longitude),
            start_name=start.display_name.split(",")[0],
            attractions=[
                Coordinate(latitude=poi.latitude, longitude=poi.longitude)
                for poi in chosen
            ],
            attraction_names=[poi.name for poi in chosen],
            weight=weight,
            closed_loop=closed_loop,
        ),
        service,
    )
    return {
        "size": size,
        "repeat": repeat,
        "weight": result.weight,
        "closed_loop": result.closed_loop,
        "status": "ok",
        "matrix_key": result.matrix_key,
        "network_cache_key": result.network_cache_key,
        "matrix_elapsed_ms": result.matrix_elapsed_ms,
        "matrix_build_ms": result.matrix_build_ms,
        "matrix_lookup_ms": result.matrix_lookup_ms,
        "cache_hit": result.cache_hit,
        "start": result.snap[0].name,
        "attractions": [poi.name for poi in chosen],
        "max_snap_distance_m": max(item.snap_distance_m for item in result.snap),
        "straight_line": result.straight_line.model_dump(),
        "component": result.component.model_dump() if result.component else None,
        "pairs": [item.model_dump() for item in result.pairs],
        "unreachable": [item.model_dump() for item in result.unreachable],
        "algorithms": [
            {
                "algorithm": item.algorithm,
                "label": item.label,
                "order": item.order,
                "names": item.names,
                "cost": item.cost,
                "cost_unit": item.cost_unit,
                "cost_m": item.cost_m,
                "cost_s": item.cost_s,
                "route_distance_m": item.route.distance_m,
                "duration_min": item.route.estimated_duration_min,
                "elapsed_ms": item.elapsed_ms,
                "gap_percent": item.gap_percent,
                "improvement_percent": item.improvement_percent,
                "segments_m": [
                    segment["distance_m"] for segment in item.route.segments
                ],
                "segments_min": [
                    segment.get("duration_min") for segment in item.route.segments
                ],
                "covers_each_attraction_once": (
                    sorted(item.order) == list(range(size))
                ),
            }
            for item in result.algorithms
        ],
    }


def _write_outputs(runs: list[dict[str, Any]], out_dir: Path) -> None:
    jsonl_path = out_dir / "west_lake_order_runs.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for run in runs:
            handle.write(json.dumps(run, ensure_ascii=False) + "\n")

    json_path = out_dir / "west_lake_order.json"
    json_path.write_text(
        json.dumps(
            {
                "region": "west-lake-demo",
                "model": "open/closed-loop-tsp",
                "weights": sorted({run["weight"] for run in runs}),
                "runs": runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = out_dir / "west_lake_order.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "size",
                "repeat",
                "weight",
                "closed_loop",
                "algorithm",
                "label",
                "cost",
                "cost_unit",
                "cost_m",
                "cost_s",
                "route_distance_m",
                "duration_min",
                "matrix_elapsed_ms",
                "matrix_build_ms",
                "matrix_lookup_ms",
                "cache_hit",
                "elapsed_ms",
                "gap_percent",
                "improvement_percent",
                "mean_network_straight_ratio",
                "max_network_straight_ratio",
                "max_snap_distance_m",
                "removed_nodes",
                "removed_edges",
                "covers_each_attraction_once",
                "order",
            ],
        )
        writer.writeheader()
        for run in runs:
            component = run.get("component") or {}
            for item in run["algorithms"]:
                writer.writerow(
                    {
                        "size": run["size"],
                        "repeat": run["repeat"],
                        "weight": run["weight"],
                        "closed_loop": run["closed_loop"],
                        "algorithm": item["algorithm"],
                        "label": item["label"],
                        "cost": item["cost"],
                        "cost_unit": item["cost_unit"],
                        "cost_m": item["cost_m"],
                        "cost_s": item["cost_s"],
                        "route_distance_m": item["route_distance_m"],
                        "duration_min": item["duration_min"],
                        "matrix_elapsed_ms": run["matrix_elapsed_ms"],
                        "matrix_build_ms": run["matrix_build_ms"],
                        "matrix_lookup_ms": run["matrix_lookup_ms"],
                        "cache_hit": run["cache_hit"],
                        "elapsed_ms": item["elapsed_ms"],
                        "gap_percent": item["gap_percent"],
                        "improvement_percent": item["improvement_percent"],
                        "mean_network_straight_ratio": run["straight_line"]["mean_ratio"],
                        "max_network_straight_ratio": run["straight_line"]["max_ratio"],
                        "max_snap_distance_m": run["max_snap_distance_m"],
                        "removed_nodes": component.get("removed_nodes"),
                        "removed_edges": component.get("removed_edges"),
                        "covers_each_attraction_once": item["covers_each_attraction_once"],
                        "order": " -> ".join(item["names"]),
                    }
                )


def _weight_comparisons(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, bool], dict[str, dict[str, Any]]] = defaultdict(dict)
    for run in runs:
        grouped[(run["size"], run["repeat"], run["closed_loop"])][run["weight"]] = run

    rows: list[dict[str, Any]] = []
    for (size, repeat, closed_loop), by_weight in sorted(grouped.items()):
        if "length" not in by_weight or "time" not in by_weight:
            continue
        length_run = by_weight["length"]
        time_run = by_weight["time"]
        length_order = _preferred(length_run)["names"]
        time_order = _preferred(time_run)["names"]
        overlap = sum(
            1 for first, second in zip(length_order, time_order) if first == second
        )
        rows.append(
            {
                "size": size,
                "repeat": repeat,
                "closed_loop": closed_loop,
                "same_order": length_order == time_order,
                "positional_overlap_percent": round(overlap / size * 100, 2),
                "length_order": " -> ".join(length_order),
                "time_order": " -> ".join(time_order),
                "length_cost_m": _preferred(length_run)["cost_m"],
                "time_cost_m": _preferred(time_run)["cost_m"],
                "length_cost_s": _preferred(length_run)["cost_s"],
                "time_cost_s": _preferred(time_run)["cost_s"],
            }
        )
    return rows


def _preferred(run: dict[str, Any]) -> dict[str, Any]:
    algorithm = "held_karp" if run["size"] <= 15 else "nearest_neighbor_2opt"
    return next(
        item for item in run["algorithms"] if item["algorithm"] == algorithm
    )


def _write_weight_comparisons(rows: list[dict[str, Any]], out_dir: Path) -> None:
    path = out_dir / "west_lake_weight_comparison.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "size",
                "repeat",
                "closed_loop",
                "same_order",
                "positional_overlap_percent",
                "length_order",
                "time_order",
                "length_cost_m",
                "time_cost_m",
                "length_cost_s",
                "time_cost_s",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_figures(
    runs: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    out_dir: Path,
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安装 matplotlib，跳过图表生成；可执行 pip install matplotlib")
        return False

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 最近邻 Gap 随规模变化（两种口径、开放/闭环）
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for weight in sorted({run["weight"] for run in runs}):
        for closed in (False, True):
            grouped: dict[int, list[float]] = defaultdict(list)
            for run in runs:
                if run["weight"] != weight or run["closed_loop"] != closed:
                    continue
                item = next(
                    algorithm
                    for algorithm in run["algorithms"]
                    if algorithm["algorithm"] == "nearest_neighbor"
                )
                grouped[run["size"]].append(item["gap_percent"] or 0.0)
            if not grouped:
                continue
            points = [
                (size, sum(values) / len(values))
                for size, values in sorted(grouped.items())
            ]
            ax.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                marker="o",
                label=f"{weight}/{'closed' if closed else 'open'}",
            )
    ax.set_xlabel("attractions")
    ax.set_ylabel("nearest-neighbor gap (%)")
    ax.set_title("West Lake demo: gap by instance size")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "gap_by_size.png", dpi=150)
    plt.close(fig)

    # 2) 求解耗时随规模变化（Held-Karp 用对数轴）
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for algorithm in ("nearest_neighbor", "nearest_neighbor_2opt", "held_karp"):
        grouped: dict[int, list[float]] = defaultdict(list)
        for run in runs:
            item = next(
                algorithm_item
                for algorithm_item in run["algorithms"]
                if algorithm_item["algorithm"] == algorithm
            )
            grouped[run["size"]].append(item["elapsed_ms"])
        if not grouped:
            continue
        points = [
            (size, sum(values) / len(values))
            for size, values in sorted(grouped.items())
        ]
        ax.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            marker="o",
            label=algorithm,
        )
    ax.set_yscale("log")
    ax.set_xlabel("attractions")
    ax.set_ylabel("solve time (ms, log)")
    ax.set_title("Order solve time")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out_dir / "solve_time_by_size.png", dpi=150)
    plt.close(fig)

    # 3) 路网/直线距离比值分布（同一矩阵只画一次）
    ratios = []
    seen_matrices: set[str] = set()
    for run in runs:
        if run["matrix_key"] in seen_matrices:
            continue
        seen_matrices.add(run["matrix_key"])
        ratios.extend(
            pair["ratio"]
            for pair in run["pairs"]
            if pair["ratio"] is not None
        )
    if ratios:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.hist(ratios, bins=18, color="#4d6bfe", alpha=0.78)
        ax.set_xlabel("network distance / straight-line distance")
        ax.set_ylabel("pair count")
        ax.set_title("Detour ratio distribution")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(out_dir / "detour_ratio_hist.png", dpi=150)
        plt.close(fig)

    # 4) 距离/时间口径的顺序重合度
    if comparisons:
        labels = [
            f"{row['size']}{'C' if row['closed_loop'] else 'O'}"
            for row in comparisons
        ]
        values = [row["positional_overlap_percent"] for row in comparisons]
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.bar(labels, values, color="#7f9dff")
        ax.set_ylim(0, 105)
        ax.set_ylabel("positional overlap (%)")
        ax.set_title("Length vs time order overlap (C=closed, O=open)")
        ax.grid(axis="y", alpha=0.2)
        fig.tight_layout()
        fig.savefig(out_dir / "weight_order_overlap.png", dpi=150)
        plt.close(fig)

    return True


def _same_point(lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    return abs(lat1 - lat2) < 0.0002 and abs(lon1 - lon2) < 0.0002


if __name__ == "__main__":
    main()
