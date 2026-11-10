from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402


DEFAULT_LATITUDE = 31.2289274
DEFAULT_LONGITUDE = 121.4879752
USER_AGENT = "ZYourRoad-OSM-Diagnostics/0.1 smart-city-course-project"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "分层诊断上海OSM数据下载：检查DNS、TLS、代理、Overpass最小查询，"
            "并可选执行与项目相同的OSMnx路网和POI查询。"
        ),
    )
    parser.add_argument("--latitude", type=float, default=DEFAULT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LONGITUDE)
    parser.add_argument(
        "--radius-m",
        type=int,
        default=3000,
        help="--full模式下的OSMnx查询半径，默认3000米。",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=35,
        help="每个网络步骤的超时秒数，默认35秒。",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="覆盖项目配置中的Overpass端点；可重复传入。",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="在最小查询成功的第一个端点上执行OSMnx路网和POI真实查询。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="诊断报告路径；默认写入Datasets/runtime/diagnostics。",
    )
    return parser.parse_args()


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def error_chain(error: BaseException) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(
            {
                "type": type(current).__name__,
                "message": str(current),
            }
        )
        current = current.__cause__ or current.__context__
    return chain


def classify_exception(error: BaseException) -> str:
    text = " | ".join(
        f"{item['type']}: {item['message']}" for item in error_chain(error)
    ).casefold()
    if "proxy" in text:
        return "proxy_error"
    if "certificate_verify_failed" in text or "certificateverify" in text:
        return "certificate_verify_failed"
    if "ssl" in text or "tls" in text:
        return "tls_handshake_failed"
    if "name or service not known" in text or "getaddrinfo failed" in text:
        return "dns_failed"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection reset" in text or "forcibly closed" in text:
        return "connection_reset"
    if "connection refused" in text:
        return "connection_refused"
    return "connection_error"


def classify_http_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code == 403:
        return "http_forbidden"
    if status_code == 429:
        return "rate_limited"
    if status_code in {502, 503, 504}:
        return "upstream_unavailable"
    if status_code >= 500:
        return "upstream_error"
    return "http_error"


def sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def effective_proxies(url: str) -> dict[str, str]:
    return {
        key: sanitize_url(value)
        for key, value in requests.utils.get_environ_proxies(url).items()
    }


def probe_dns(host: str, port: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = sorted({str(record[4][0]) for record in records})
        return {
            "ok": True,
            "classification": "ok",
            "addresses": addresses,
            "elapsed_ms": elapsed_ms(started),
        }
    except OSError as error:
        return {
            "ok": False,
            "classification": classify_exception(error),
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }


def probe_tls(host: str, port: int, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as connection:
            with context.wrap_socket(connection, server_hostname=host) as tls:
                certificate = tls.getpeercert()
                cipher = tls.cipher()
                return {
                    "ok": True,
                    "classification": "ok",
                    "tls_version": tls.version(),
                    "cipher": cipher[0] if cipher else None,
                    "certificate_subject": certificate.get("subject"),
                    "certificate_issuer": certificate.get("issuer"),
                    "certificate_expires": certificate.get("notAfter"),
                    "elapsed_ms": elapsed_ms(started),
                }
    except (OSError, ssl.SSLError) as error:
        return {
            "ok": False,
            "classification": classify_exception(error),
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }


def response_preview(response: requests.Response, limit: int = 500) -> str:
    return " ".join(response.text[:limit].split())


def probe_status(
    session: requests.Session,
    endpoint: str,
    timeout: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    url = f"{endpoint.rstrip('/')}/status"
    try:
        response = session.get(url, timeout=timeout)
        classification = classify_http_status(response.status_code)
        return {
            "ok": classification == "ok",
            "classification": classification,
            "url": url,
            "status_code": response.status_code,
            "server": response.headers.get("server"),
            "preview": response_preview(response),
            "elapsed_ms": elapsed_ms(started),
        }
    except requests.RequestException as error:
        return {
            "ok": False,
            "classification": classify_exception(error),
            "url": url,
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }


def probe_minimal_overpass(
    session: requests.Session,
    endpoint: str,
    latitude: float,
    longitude: float,
    timeout: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    url = f"{endpoint.rstrip('/')}/interpreter"
    query = (
        f"[out:json][timeout:{max(5, timeout - 5)}];"
        f"node(around:100,{latitude},{longitude});"
        "out ids 1;"
    )
    try:
        response = session.post(
            url,
            data={"data": query},
            timeout=timeout,
        )
        classification = classify_http_status(response.status_code)
        result: dict[str, Any] = {
            "ok": classification == "ok",
            "classification": classification,
            "url": url,
            "status_code": response.status_code,
            "server": response.headers.get("server"),
            "content_type": response.headers.get("content-type"),
            "elapsed_ms": elapsed_ms(started),
        }
        if classification != "ok":
            result["preview"] = response_preview(response)
            return result
        try:
            payload = response.json()
            result["element_count"] = len(payload.get("elements", []))
        except (ValueError, AttributeError) as error:
            result.update(
                {
                    "ok": False,
                    "classification": "invalid_json_response",
                    "preview": response_preview(response),
                    "errors": error_chain(error),
                }
            )
        return result
    except requests.RequestException as error:
        return {
            "ok": False,
            "classification": classify_exception(error),
            "url": url,
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }


def probe_nominatim(
    session: requests.Session,
    timeout: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    url = "https://nominatim.openstreetmap.org/search"
    try:
        response = session.get(
            url,
            params={
                "q": "豫园 黄浦区 上海",
                "format": "jsonv2",
                "limit": 3,
                "countrycodes": "cn",
                "accept-language": "zh-CN,zh,en",
            },
            timeout=timeout,
        )
        classification = classify_http_status(response.status_code)
        result: dict[str, Any] = {
            "ok": classification == "ok",
            "classification": classification,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms(started),
        }
        if classification != "ok":
            result["preview"] = response_preview(response)
            return result
        candidates = response.json()
        result["candidates"] = [
            {
                "display_name": item.get("display_name"),
                "latitude": item.get("lat"),
                "longitude": item.get("lon"),
            }
            for item in candidates[:3]
        ]
        return result
    except (requests.RequestException, ValueError) as error:
        return {
            "ok": False,
            "classification": classify_exception(error),
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }


def probe_osmnx(
    endpoint: str,
    latitude: float,
    longitude: float,
    radius_m: int,
    timeout: int,
) -> dict[str, Any]:
    import osmnx as ox

    ox.settings.use_cache = False
    ox.settings.log_console = False
    ox.settings.requests_timeout = timeout
    ox.settings.overpass_rate_limit = False
    ox.settings.overpass_url = endpoint

    result: dict[str, Any] = {
        "endpoint": endpoint,
        "radius_m": radius_m,
    }

    started = time.perf_counter()
    try:
        graph = ox.graph_from_point(
            (latitude, longitude),
            dist=radius_m,
            network_type="walk",
            simplify=True,
            retain_all=False,
        )
        result["network"] = {
            "ok": True,
            "classification": "ok",
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "elapsed_ms": elapsed_ms(started),
        }
    except Exception as error:
        result["network"] = {
            "ok": False,
            "classification": classify_exception(error),
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }

    started = time.perf_counter()
    try:
        features = ox.features_from_point(
            (latitude, longitude),
            tags={
                "tourism": ["attraction", "viewpoint", "museum", "gallery"],
                "historic": True,
                "leisure": ["park", "garden", "nature_reserve"],
            },
            dist=radius_m,
        )
        result["pois"] = {
            "ok": True,
            "classification": "ok",
            "feature_count": len(features),
            "elapsed_ms": elapsed_ms(started),
        }
    except Exception as error:
        result["pois"] = {
            "ok": False,
            "classification": classify_exception(error),
            "errors": error_chain(error),
            "elapsed_ms": elapsed_ms(started),
        }

    return result


def build_conclusions(report: dict[str, Any]) -> list[str]:
    conclusions: list[str] = []
    endpoint_results = report["overpass_endpoints"]
    minimal_results = [item["minimal_query"] for item in endpoint_results]
    successful = [item for item in endpoint_results if item["minimal_query"]["ok"]]

    if not report["nominatim"]["ok"]:
        conclusions.append(
            "Nominatim地理编码也失败，问题可能是本机整体HTTPS、代理或DNS配置。"
        )
    else:
        conclusions.append("Nominatim地理编码可访问。")

    if successful:
        conclusions.append(
            f"{len(successful)}个Overpass端点的最小查询成功，基础网络和TLS可用。"
        )
        full = report.get("osmnx_full_query")
        if full:
            network_ok = full["network"]["ok"]
            pois_ok = full["pois"]["ok"]
            if network_ok and pois_ok:
                conclusions.append(
                    "OSMnx路网与POI查询均成功；此前失败更可能是临时上游故障或冷却期。"
                )
            elif not network_ok and not pois_ok:
                conclusions.append(
                    "最小Overpass查询成功，但OSMnx大查询均失败，重点检查查询规模、"
                    "超时和上游资源限制。"
                )
            elif not network_ok:
                conclusions.append("POI查询成功但路网查询失败，问题集中在步行路网请求。")
            else:
                conclusions.append("路网查询成功但POI查询失败，问题集中在POI标签请求。")
        elif report["arguments"]["full"] is False:
            conclusions.append(
                "如需继续区分查询规模问题，请使用--full执行项目级OSMnx查询。"
            )
    else:
        classifications = [item["classification"] for item in minimal_results]
        unique_classifications = set(classifications)
        if len(unique_classifications) > 1:
            details = "；".join(
                f"{item['endpoint']}={item['minimal_query']['classification']}"
                for item in endpoint_results
            )
            conclusions.append(f"Overpass端点出现不同故障：{details}。")
        elif "certificate_verify_failed" in unique_classifications:
            conclusions.append(
                "发现TLS证书校验失败：优先检查Conda/requests CA证书、系统时间和HTTPS代理。"
            )
        elif "proxy_error" in unique_classifications:
            conclusions.append("发现代理连接错误：检查HTTP_PROXY/HTTPS_PROXY配置。")
        elif "dns_failed" in unique_classifications:
            conclusions.append("Overpass域名解析失败：检查DNS或网络拦截。")
        elif unique_classifications <= {
            "timeout",
            "connection_reset",
            "connection_refused",
        }:
            conclusions.append(
                "所有Overpass端点均无法建立稳定连接，属于网络或上游可用性问题，"
                "不是路径规划算法错误。"
            )
        else:
            conclusions.append(
                "所有Overpass最小查询均失败，请根据各端点classification和errors定位。"
            )

    return conclusions


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    args = parse_args()
    settings = get_settings()
    endpoints = [
        endpoint.rstrip("/")
        for endpoint in (args.endpoint or settings.overpass_endpoint_list)
    ]
    generated_at = datetime.now(UTC)
    output = args.output or (
        settings.datasets_dir
        / "runtime"
        / "diagnostics"
        / f"overpass-shanghai-{generated_at:%Y%m%dT%H%M%SZ}.json"
    )

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    report: dict[str, Any] = {
        "generated_at_utc": generated_at.isoformat(),
        "arguments": {
            "latitude": args.latitude,
            "longitude": args.longitude,
            "radius_m": args.radius_m,
            "timeout": args.timeout,
            "full": args.full,
        },
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "openssl": ssl.OPENSSL_VERSION,
            "requests": requests.__version__,
            "default_verify_paths": ssl.get_default_verify_paths()._asdict(),
            "ssl_cert_file_env": os.environ.get("SSL_CERT_FILE"),
            "requests_ca_bundle_env": os.environ.get("REQUESTS_CA_BUNDLE"),
        },
        "nominatim": probe_nominatim(session, args.timeout),
        "overpass_endpoints": [],
    }

    for endpoint in endpoints:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        endpoint_result: dict[str, Any] = {
            "endpoint": endpoint,
            "effective_proxies": effective_proxies(endpoint),
        }
        if not host:
            endpoint_result.update(
                {
                    "dns": {
                        "ok": False,
                        "classification": "invalid_endpoint",
                    },
                    "tls": {
                        "ok": False,
                        "classification": "invalid_endpoint",
                    },
                    "status": {
                        "ok": False,
                        "classification": "invalid_endpoint",
                    },
                    "minimal_query": {
                        "ok": False,
                        "classification": "invalid_endpoint",
                    },
                }
            )
        else:
            endpoint_result["dns"] = probe_dns(host, port)
            endpoint_result["tls"] = (
                probe_tls(host, port, args.timeout)
                if parsed.scheme == "https"
                else {
                    "ok": True,
                    "classification": "not_applicable",
                }
            )
            endpoint_result["status"] = probe_status(
                session,
                endpoint,
                args.timeout,
            )
            endpoint_result["minimal_query"] = probe_minimal_overpass(
                session,
                endpoint,
                args.latitude,
                args.longitude,
                args.timeout,
            )
        report["overpass_endpoints"].append(endpoint_result)

    if args.full:
        working_endpoint = next(
            (
                item["endpoint"]
                for item in report["overpass_endpoints"]
                if item["minimal_query"]["ok"]
            ),
            None,
        )
        if working_endpoint:
            report["osmnx_full_query"] = probe_osmnx(
                working_endpoint,
                args.latitude,
                args.longitude,
                args.radius_m,
                args.timeout,
            )
        else:
            report["osmnx_full_query_skipped"] = (
                "没有通过最小查询的Overpass端点，跳过耗时的OSMnx查询。"
            )

    report["conclusions"] = build_conclusions(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"诊断报告已写入：{output}")
    for conclusion in report["conclusions"]:
        print(f"- {conclusion}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
