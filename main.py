"""
哪吒探针插件 (astrbot_plugin_nezhatz)

用于查看哪吒监控站点的服务器状态等信息
支持指令调用
基于哪吒监控 2.2.x 版本 API

作者: 叹号大帝
"""

import asyncio
import json
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register


@dataclass
class ServerInfo:
    id: int
    name: str
    online: bool
    cpu: float
    mem_used: int
    mem_total: int
    disk_used: int
    disk_total: int
    uptime: int
    platform: str
    platform_version: str
    net_in_transfer: int
    net_out_transfer: int
    last_active: str
    geoip_country: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@register(
    "astrbot_plugin_nezhatz",
    "叹号大帝",
    "哪吒探针 - 查看哪吒监控站点服务器状态",
    "1.2.0",
    "https://github.com/thTag/astrbot_plugin_nezhatz",
)
class NezhaPlugin(Star):

    SECONDS_PER_MINUTE = 60
    SECONDS_PER_HOUR = 3600
    SECONDS_PER_DAY = 86400
    ONLINE_THRESHOLD_SECONDS = 300

    DEFAULT_REQUEST_TIMEOUT = 30.0
    MIN_TIMEOUT = 1.0
    BYTES_PER_UNIT = 1024
    CACHE_TTL_SECONDS = 30.0
    MAX_RETRY_ATTEMPTS = 3
    RETRY_BACKOFF_BASE = 2
    RETRY_JITTER = 0.5

    MAX_KEEPALIVE_CONNECTIONS = 20
    MAX_HTTP_CONNECTIONS = 50

    SERVICE_STATUS_ONLINE = 1
    SERVICE_STATUS_OFFLINE = 0
    SERVICE_STATUS_UNKNOWN = -1

    HELP_TEXT = (
        "📖 **哪吒探针使用帮助**\n\n"
        "**服务器查询**\n"
        "`/nezha status` - 查看服务器状态概览（图片）\n"
        "`/nezha detail <id>` - 查看服务器详情（图片）\n\n"
        "**服务监控**\n"
        "`/nezha service` - 查看服务监控列表（图片）\n"
        "`/nezha service detail <id>` - 查看服务详情（图片）\n\n"
        "**历史指标**\n"
        "`/nezha history <id> <指标> [周期]` - 查看历史趋势（图片）\n"
        "  指标: cpu, memory, disk, load1, tcp_conn, process_count...\n"
        "  周期: 1d, 7d, 30d (默认 1d)\n\n"
        "📌 示例: `/nezha history 1 cpu 1d`"
    )

    COUNTRY_FLAGS: Dict[str, str] = {
        "cn": "🇨🇳", "us": "🇺🇸", "hk": "🇭🇰", "jp": "🇯🇵", "kr": "🇰🇷",
        "sg": "🇸🇬", "uk": "🇬🇧", "de": "🇩🇪", "fr": "🇫🇷", "ru": "🇷🇺",
        "au": "🇦🇺", "ca": "🇨🇦", "in": "🇮🇳", "br": "🇧🇷", "mx": "🇲🇽",
        "it": "🇮🇹", "es": "🇪🇸", "nl": "🇳🇱", "se": "🇸🇪", "no": "🇳🇴",
        "fi": "🇫🇮", "is": "🇮🇸", "pl": "🇵🇱", "ua": "🇺🇦", "tr": "🇹🇷",
        "ae": "🇦🇪", "sa": "🇸🇦", "il": "🇮🇱", "za": "🇿🇦", "eg": "🇪🇬",
        "ng": "🇳🇬", "ke": "🇰🇪", "tw": "🇹🇼", "mo": "🇲🇴", "my": "🇲🇾",
        "th": "🇹🇭", "vn": "🇻🇳", "ph": "🇵🇭", "id": "🇮🇩", "pk": "🇵🇰",
        "bd": "🇧🇩", "kz": "🇰🇿", "uz": "🇺🇿",
    }

    METRIC_DISPLAY_NAMES: Dict[str, str] = {
        "cpu": "CPU 使用率",
        "memory": "内存使用率",
        "swap": "Swap 使用率",
        "disk": "磁盘使用率",
        "net_in_speed": "入站速率",
        "net_out_speed": "出站速率",
        "net_in_transfer": "入站流量",
        "net_out_transfer": "出站流量",
        "load1": "负载 (1分钟)",
        "load5": "负载 (5分钟)",
        "load15": "负载 (15分钟)",
        "tcp_conn": "TCP 连接数",
        "udp_conn": "UDP 连接数",
        "process_count": "进程数",
        "temperature": "温度",
        "uptime": "运行时间",
        "gpu": "GPU 使用率",
    }

    METRIC_UNITS: Dict[str, str] = {
        "cpu": "%", "memory": "%", "swap": "%", "disk": "%",
        "net_in_speed": "bps", "net_out_speed": "bps",
        "load1": "", "load5": "", "load15": "",
        "tcp_conn": "个", "udp_conn": "个", "process_count": "个",
        "temperature": "°C", "uptime": "秒", "gpu": "%",
    }

    FIELD_ERROR = "error"
    FIELD_DATA = "data"
    FIELD_LAST_ACTIVE = "last_active"
    FIELD_STATE = "state"
    FIELD_HOST = "host"
    FIELD_NAME = "name"
    FIELD_ID = "id"
    FIELD_GEOIP = "geoip"
    FIELD_COUNTRY_CODE = "country_code"
    FIELD_PLATFORM = "platform"
    FIELD_PLATFORM_VERSION = "platform_version"
    FIELD_MEM_TOTAL = "mem_total"
    FIELD_MEM_USED = "mem_used"
    FIELD_DISK_TOTAL = "disk_total"
    FIELD_DISK_USED = "disk_used"
    FIELD_UPTIME = "uptime"
    FIELD_NET_IN_TRANSFER = "net_in_transfer"
    FIELD_NET_OUT_TRANSFER = "net_out_transfer"
    FIELD_CPU = "cpu"

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = self.config.get("base_url", "").rstrip("/")
        self.api_token = self.config.get("api_token", "")
        self.admin_token = self.config.get("admin_token", "")
        self.verify_ssl = self.config.get("verify_ssl", True)

        self._check_dependencies()

        if not self.verify_ssl:
            logger.warning("SSL 验证已禁用，可能存在安全风险")

        self.request_timeout = self._parse_timeout_config()
        self.cache_ttl = self.config.get("cache_ttl_seconds", self.CACHE_TTL_SECONDS)
        self.max_keepalive = self.config.get("max_keepalive_connections", self.MAX_KEEPALIVE_CONNECTIONS)
        self.max_connections = self.config.get("max_connections", self.MAX_HTTP_CONNECTIONS)

        data_dir = StarTools.get_data_dir()
        self.model_dir = data_dir / "model"
        if not self.model_dir.exists():
            self.model_dir = Path(__file__).parent / "model"

        self.template_paths = {
            "status": self.model_dir / "sysinfo.html",
            "server_detail": self.model_dir / "server_detail.html",
            "service_list": self.model_dir / "service_list.html",
            "service_detail": self.model_dir / "service_detail.html",
            "history": self.model_dir / "history.html",
        }

        for name, path in self.template_paths.items():
            if not path.exists():
                logger.error(f"模板文件不存在: {path}")

        self._template_cache: Dict[str, tuple[float, str]] = {}
        self._template_lock = asyncio.Lock()

        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

        self._servers_cache: Optional[tuple[float, List[Dict[str, Any]]]] = None
        self._servers_cache_lock = asyncio.Lock()

        self._shutting_down = False

        if self.api_token:
            token_preview = self.api_token[:4] + "***" if len(self.api_token) >= 4 else "***"
        else:
            token_preview = "未配置"
        logger.info(f"哪吒探针插件 v1.2.0 已加载，面板: {self.base_url}")

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._shutting_down:
            raise RuntimeError("插件正在关闭，拒绝创建新连接")

        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    verify=self.verify_ssl,
                    timeout=self.request_timeout,
                    limits=httpx.Limits(
                        max_keepalive_connections=self.max_keepalive,
                        max_connections=self.max_connections,
                    ),
                )
            return self._client

    async def terminate(self):
        self._shutting_down = True

        async with self._client_lock:
            if self._client:
                await self._client.aclose()
                self._client = None

        async with self._template_lock:
            self._template_cache.clear()

        async with self._servers_cache_lock:
            self._servers_cache = None

        logger.info("哪吒探针插件已卸载")

    def _check_dependencies(self) -> None:
        try:
            import dateutil
        except ImportError:
            logger.error("python-dateutil 未安装，请运行: pip install python-dateutil")
            raise RuntimeError("缺少必需依赖 python-dateutil")

    def _parse_timeout_config(self) -> float:
        try:
            raw_timeout = self.config.get("request_timeout", self.DEFAULT_REQUEST_TIMEOUT)
            timeout = float(raw_timeout)
            if timeout > self.MIN_TIMEOUT:
                return timeout
            logger.warning(f"超时时间 {timeout}s 过小，使用默认值")
        except (TypeError, ValueError):
            logger.warning("request_timeout 配置无效，使用默认值")
        return self.DEFAULT_REQUEST_TIMEOUT

    async def _load_template(self, template_name: str) -> str:
        async with self._template_lock:
            path = self.template_paths.get(template_name)
            if not path or not path.exists():
                logger.error(f"模板文件不存在: {path}")
                return f"<h1>模板 {template_name} 加载失败</h1>"

            now = time.time()
            cache_entry = self._template_cache.get(template_name)
            if cache_entry:
                cached_time, cached_content = cache_entry
                if now - cached_time < 60.0:
                    return cached_content

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    self._template_cache[template_name] = (now, content)
                    logger.debug(f"模板已重新加载: {template_name}")
                    return content
            except Exception as e:
                logger.error(f"加载模板失败 {template_name}: {e}")
                return f"<h1>模板加载失败: {template_name}</h1>"

    async def _get_cached_servers(self) -> Optional[List[Dict[str, Any]]]:
        async with self._servers_cache_lock:
            if self._servers_cache is None:
                return None

            cached_time, cached_data = self._servers_cache
            age = time.time() - cached_time

            if age < self.cache_ttl:
                logger.debug(f"使用缓存的服务器列表 (缓存年龄: {age:.1f}s)")
                return cached_data

            logger.debug(f"服务器列表缓存已过期 (缓存年龄: {age:.1f}s)")
            return None

    async def _fetch_servers_with_retry(self) -> Optional[List[Dict[str, Any]]]:
        last_error = None

        for attempt in range(self.MAX_RETRY_ATTEMPTS):
            result = await self._make_request("GET", "/api/v1/server")

            if result is None:
                last_error = "连接失败"
                if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                    wait_time = (self.RETRY_BACKOFF_BASE ** attempt) + random.uniform(0, self.RETRY_JITTER)
                    logger.debug(f"获取服务器列表失败，{wait_time:.2f}s 后重试 (尝试 {attempt + 1}/{self.MAX_RETRY_ATTEMPTS})")
                    await asyncio.sleep(wait_time)
                    continue
                return None

            if self.FIELD_ERROR in result:
                error_msg = result[self.FIELD_ERROR]
                if self._is_retryable_error(error_msg):
                    last_error = error_msg
                    if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                        wait_time = (self.RETRY_BACKOFF_BASE ** attempt) + random.uniform(0, self.RETRY_JITTER)
                        logger.debug(f"获取服务器列表失败 (可重试): {error_msg}，{wait_time:.2f}s 后重试")
                        await asyncio.sleep(wait_time)
                        continue
                logger.error(f"获取服务器列表失败 (不可重试): {error_msg}")
                return None

            servers = result.get(self.FIELD_DATA, []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                return servers

            last_error = "数据格式异常"
            logger.error(f"服务器数据格式异常: {type(servers)}")
            return []

        logger.error(f"获取服务器列表失败，已重试 {self.MAX_RETRY_ATTEMPTS} 次: {last_error}")
        return None

    @staticmethod
    def _is_retryable_error(error_msg: str) -> bool:
        non_retryable_keywords = ["认证失败", "未配置", "响应格式错误", "不支持的HTTP方法"]
        for keyword in non_retryable_keywords:
            if keyword in error_msg:
                return False
        return True

    async def _fetch_servers(self) -> Optional[List[Dict[str, Any]]]:
        cached = await self._get_cached_servers()
        if cached is not None:
            return cached

        async with self._servers_cache_lock:
            if self._servers_cache is not None:
                cached_time, cached_data = self._servers_cache
                age = time.time() - cached_time
                if age < self.cache_ttl:
                    logger.debug(f"双重检查命中缓存 (缓存年龄: {age:.1f}s)")
                    return cached_data

            servers = await self._fetch_servers_with_retry()
            if servers is not None:
                self._servers_cache = (time.time(), servers)
                logger.debug(f"服务器列表已更新，共 {len(servers)} 台服务器")
            return servers

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, bool):
            logger.warning(f"布尔值被转换为浮点数: {value} -> {1.0 if value else 0.0}")
            return 1.0 if value else 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            logger.warning(f"布尔值被转换为整数: {value} -> {1 if value else 0}")
            return 1 if value else 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _is_online(self, server: Dict[str, Any]) -> bool:
        last_active_str = server.get(self.FIELD_LAST_ACTIVE)
        if not last_active_str:
            return False

        try:
            from dateutil import parser
            last_time = parser.parse(last_active_str)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = now - last_time
            return diff.total_seconds() < self.ONLINE_THRESHOLD_SECONDS
        except Exception as e:
            logger.warning(f"解析 last_active 失败: {e}，服务器 {server.get(self.FIELD_NAME, '未知')} 视为离线")
            return False

    def _parse_server(self, server: Dict[str, Any]) -> ServerInfo:
        state = server.get(self.FIELD_STATE, {})
        host = server.get(self.FIELD_HOST, {})
        geoip = server.get(self.FIELD_GEOIP, {})

        platform = host.get(self.FIELD_PLATFORM) or "N/A"
        platform_version = host.get(self.FIELD_PLATFORM_VERSION) or ""
        geoip_country = geoip.get(self.FIELD_COUNTRY_CODE) or ""

        return ServerInfo(
            id=self._safe_int(server.get(self.FIELD_ID)),
            name=server.get(self.FIELD_NAME, "未命名"),
            online=self._is_online(server),
            cpu=self._safe_float(state.get(self.FIELD_CPU)),
            mem_used=self._safe_int(state.get(self.FIELD_MEM_USED)),
            mem_total=self._safe_int(host.get(self.FIELD_MEM_TOTAL)),
            disk_used=self._safe_int(state.get(self.FIELD_DISK_USED)),
            disk_total=self._safe_int(host.get(self.FIELD_DISK_TOTAL)),
            uptime=self._safe_int(state.get(self.FIELD_UPTIME)),
            platform=platform,
            platform_version=platform_version,
            net_in_transfer=self._safe_int(state.get(self.FIELD_NET_IN_TRANSFER)),
            net_out_transfer=self._safe_int(state.get(self.FIELD_NET_OUT_TRANSFER)),
            last_active=server.get(self.FIELD_LAST_ACTIVE, ""),
            geoip_country=geoip_country,
        )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        use_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            logger.error("未配置哪吒监控面板地址 (base_url)")
            return {self.FIELD_ERROR: "未配置面板地址"}

        if use_admin and not self.admin_token:
            error_msg = "管理员 Token 未配置，无法执行管理员操作"
            logger.error(error_msg)
            return {self.FIELD_ERROR: error_msg}

        url = f"{self.base_url}{endpoint}"
        safe_endpoint = endpoint.split("?")[0]
        logger.debug(f"请求: {method} {safe_endpoint}")

        if use_admin and self.admin_token:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.admin_token}",
            }
        else:
            headers = self._get_headers()

        try:
            client = await self._ensure_client()

            if method.upper() == "GET":
                response = await client.get(url, headers=headers)
            elif method.upper() == "POST":
                response = await client.post(url, headers=headers, json=data)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                logger.error(f"不支持的HTTP方法: {method}")
                return {self.FIELD_ERROR: f"不支持的HTTP方法: {method}"}

            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"解析 JSON 响应失败: {e}, 响应内容: {response.text[:200]}")
                    return {self.FIELD_ERROR: "响应格式错误，请检查面板地址是否正确"}
            elif response.status_code == 401:
                logger.error("API认证失败，请检查API Token是否正确")
                return {self.FIELD_ERROR: "认证失败，请检查API Token"}
            elif response.status_code >= 500:
                logger.error(f"服务器错误: {response.status_code}")
                return {self.FIELD_ERROR: f"服务器错误: {response.status_code}"}
            else:
                logger.error(f"API请求失败: {response.status_code}")
                return {self.FIELD_ERROR: f"请求失败: {response.status_code}"}

        except RuntimeError as e:
            logger.error(f"插件状态错误: {e}")
            return {self.FIELD_ERROR: "插件正在关闭，请稍后重试"}
        except httpx.ConnectError:
            logger.error(f"无法连接到哪吒面板: {self.base_url}")
            return {self.FIELD_ERROR: f"无法连接到面板: {self.base_url}"}
        except httpx.TimeoutException:
            logger.error("请求超时")
            return {self.FIELD_ERROR: "请求超时"}
        except Exception as e:
            logger.error(f"请求异常: {e}")
            return {self.FIELD_ERROR: "请求处理失败，请检查日志"}

    def _format_error_message(self, error: Exception, context: str = "") -> str:
        error_str = str(error).lower()

        if "render" in error_str or "html" in error_str or "playwright" in error_str:
            return (
                "❌ **图片渲染失败**\n\n"
                "AstrBot 的 T2I（文本转图像）服务未正常运行。\n\n"
                "💡 **请检查：**\n"
                "1. AstrBot 设置 → 外观 → 文本转图像 是否已正确配置\n"
                "2. T2I 服务后端（如 Playwright）是否已安装\n"
                "3. 服务器是否安装了必要的浏览器依赖\n\n"
                "📖 查看日志获取详细错误"
            )

        if "401" in error_str or "unauthorized" in error_str or "认证" in error_str:
            return (
                "❌ **API 认证失败**\n\n"
                "哪吒面板的 API Token 无效或已过期。\n\n"
                "💡 **请检查：**\n"
                "1. `api_token` 配置是否正确\n"
                "2. Token 是否已过期，可在面板后台重新生成\n"
                "3. Token 是否具有 `nezha:inventory:read` 权限"
            )

        if "connect" in error_str or "timeout" in error_str or "超时" in error_str:
            return (
                "❌ **连接哪吒面板失败**\n\n"
                "无法连接到哪吒面板 API 服务。\n\n"
                "💡 **请检查：**\n"
                "1. `base_url` 配置是否正确（注意端口号）\n"
                "2. 面板服务是否正常运行\n"
                "3. 网络连通性是否正常\n"
                "4. 如使用自签名证书，可尝试设置 `verify_ssl: false`"
            )

        if "tsdb" in error_str or "timescale" in error_str:
            return (
                "❌ **TSDB 未启用**\n\n"
                "该功能需要哪吒面板启用 TSDB（时序数据库）。\n\n"
                "💡 **请检查：**\n"
                "1. 哪吒面板配置文件是否设置了 `tsdb: true`\n"
                "2. TimescaleDB 是否已安装并正常运行\n"
                "3. 查看面板日志确认 TSDB 连接状态"
            )

        return f"❌ **操作失败**\n\n发生未知错误：`{str(error)[:200]}`\n\n💡 请查看 AstrBot 日志获取详细错误信息"

    def _get_country_flag(self, country_code: str) -> str:
        return self.COUNTRY_FLAGS.get(country_code.lower(), "🌍")

    @staticmethod
    @lru_cache(maxsize=128)
    def _get_os_icon_cached(platform: str) -> str:
        if not platform or platform == "N/A":
            return "fl-tux"

        platform_lower = platform.lower()
        icon_map = {
            "ubuntu": "fl-ubuntu", "debian": "fl-debian", "centos": "fl-centos",
            "rhel": "fl-centos", "fedora": "fl-fedora", "alpine": "fl-alpine",
            "arch": "fl-archlinux", "opensuse": "fl-opensuse",
            "windows": "fl-windows", "mac": "fl-macos", "darwin": "fl-macos",
        }
        for key, icon in icon_map.items():
            if key in platform_lower:
                return icon
        return "fl-tux"

    def _get_os_icon(self, platform: str) -> str:
        return self._get_os_icon_cached(platform)

    def _format_bytes(self, bytes_val: int) -> str:
        if bytes_val < 0:
            logger.warning(f"负数字节值: {bytes_val}，已转换为 0 B")
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        val = float(bytes_val)

        for unit in units:
            if val < self.BYTES_PER_UNIT:
                if unit == "B":
                    return f"{val:.0f} B"
                return f"{val:.2f} {unit}"
            val /= self.BYTES_PER_UNIT

        return f"{val:.2f} PB"

    def _format_uptime(self, seconds: int) -> str:
        if seconds < self.SECONDS_PER_MINUTE:
            return f"{seconds}秒"
        elif seconds < self.SECONDS_PER_HOUR:
            minutes = seconds // self.SECONDS_PER_MINUTE
            return f"{minutes}分钟"
        elif seconds < self.SECONDS_PER_DAY:
            hours = seconds // self.SECONDS_PER_HOUR
            minutes = (seconds % self.SECONDS_PER_HOUR) // self.SECONDS_PER_MINUTE
            return f"{hours}小时 {minutes}分钟"
        else:
            days = seconds // self.SECONDS_PER_DAY
            hours = (seconds % self.SECONDS_PER_DAY) // self.SECONDS_PER_HOUR
            return f"{days}天 {hours}小时"

    def _prepare_server_data(self, server_infos: List[ServerInfo]) -> List[Dict[str, Any]]:
        server_data = []
        for info in server_infos:
            data = info.to_dict()
            data["mem_percent"] = info.mem_used / max(info.mem_total, 1) * 100
            data["disk_percent"] = info.disk_used / max(info.disk_total, 1) * 100
            data["os_icon"] = self._get_os_icon(info.platform)
            data["flag"] = self._get_country_flag(info.geoip_country)
            data["country_code"] = info.geoip_country.lower()
            server_data.append(data)
        return server_data

    def _format_metric_value(self, value: float, metric: str) -> str:
        if metric == "disk":
            return f"{value:.1f}%"
        if metric in ("net_in_transfer", "net_out_transfer"):
            return self._format_bytes(int(value))
        if metric == "uptime":
            return self._format_uptime(int(value))
        return f"{value:.2f}{self.METRIC_UNITS.get(metric, '')}"

    async def _fetch_services(self) -> Optional[List[Dict[str, Any]]]:
        try:
            result = await self._make_request("GET", "/api/v1/service")
            if result is None or self.FIELD_ERROR in result:
                return []

            data = result.get(self.FIELD_DATA, {})

            if isinstance(data, dict) and "services" in data:
                services_dict = data["services"]
                result_list = []
                for service_id, svc_data in services_dict.items():
                    if not isinstance(svc_data, dict):
                        continue

                    up_list = svc_data.get("up", [])
                    down_list = svc_data.get("down", [])
                    delay_list = svc_data.get("delay", [])

                    total_up = sum(up_list) if up_list else 0
                    total_down = sum(down_list) if down_list else 0
                    total_checks = total_up + total_down

                    up_percent = (total_up / total_checks * 100) if total_checks > 0 else 0
                    avg_delay = sum(delay_list) / len(delay_list) if delay_list else 0

                    current_up = svc_data.get("current_up", 0)
                    current_down = svc_data.get("current_down", 0)
                    if current_up > 0 and current_down == 0:
                        status = self.SERVICE_STATUS_ONLINE
                    elif current_down > 0:
                        status = self.SERVICE_STATUS_OFFLINE
                    else:
                        status = self.SERVICE_STATUS_UNKNOWN

                    result_list.append({
                        "id": int(service_id),
                        "name": svc_data.get("service_name", "未命名"),
                        "status": status,
                        "avg_delay": avg_delay,
                        "up_percent": up_percent,
                        "current_up": current_up,
                        "current_down": current_down,
                        "total_up": total_up,
                        "total_down": total_down,
                    })
                return result_list

            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]

            if isinstance(data, dict):
                values = list(data.values())
                if values and all(isinstance(v, dict) for v in values):
                    return values

            logger.warning(f"服务监控数据格式异常: {type(data)}")
            return []
        except Exception as e:
            logger.error(f"获取服务监控失败: {e}")
            return []

    async def _fetch_service_history(self, service_id: int, period: str = "1d") -> Optional[Dict[str, Any]]:
        result = await self._make_request("GET", f"/api/v1/service/{service_id}/history?period={period}")
        if result is None or self.FIELD_ERROR in result:
            return None
        return result.get(self.FIELD_DATA, {})

    async def _fetch_server_metrics(self, server_id: int, metric: str, period: str = "1d") -> Optional[Dict[str, Any]]:
        endpoint = f"/api/v1/server/{server_id}/metrics?metric={metric}&period={period}"
        result = await self._make_request("GET", endpoint)

        if result is None:
            return None
        if self.FIELD_ERROR in result:
            error_msg = result[self.FIELD_ERROR]
            if "tsdb" in error_msg.lower() or "timescale" in error_msg.lower():
                logger.error(f"TSDB 未启用，无法获取历史指标: {error_msg}")
                return {"error": "tsdb_not_enabled", "message": error_msg}
            return None

        data = result.get(self.FIELD_DATA, {})
        if not data:
            return {"error": "no_data", "message": "未获取到数据"}
        return data

    def _parse_service_status(self, status: int) -> tuple[str, str]:
        if status == self.SERVICE_STATUS_ONLINE:
            return "🟢", "正常"
        elif status == self.SERVICE_STATUS_OFFLINE:
            return "🔴", "异常"
        else:
            return "⚪", "未知"

    async def _render_image(self, event: AstrMessageEvent, template_name: str,
                            data: Dict[str, Any], error_msg: str = "图片生成失败") -> AsyncGenerator:
        try:
            template = await self._load_template(template_name)
            image_url = await self.html_render(
                template,
                data,
                options={
                    "full_page": True,
                    "type": "png",
                    "scale": "css",
                    "timeout": 30000,
                },
            )
            if image_url:
                yield event.image_result(image_url)
            else:
                logger.error(f"渲染失败: {template_name}")
                yield event.plain_result(f"❌ {error_msg}")
        except asyncio.TimeoutError:
            logger.error(f"渲染超时: {template_name}")
            yield event.plain_result("❌ 渲染超时，请稍后重试")
        except Exception as e:
            logger.error(f"渲染异常: {e}")
            yield event.plain_result(self._format_error_message(e))

    @filter.command("nezha")
    async def nezha_cmd(self, event: AstrMessageEvent) -> AsyncGenerator:
        parts = event.message_str.strip().split()

        if len(parts) < 2:
            async for result in self._handle_status(event):
                yield result
            return

        sub_cmd = parts[1].lower()

        if sub_cmd == "help":
            yield event.plain_result(self.HELP_TEXT)
        elif sub_cmd == "status":
            async for result in self._handle_status(event):
                yield result
        elif sub_cmd == "detail":
            if len(parts) >= 3:
                async for result in self._handle_detail(event, parts[2]):
                    yield result
            else:
                yield event.plain_result("❌ 请指定服务器 ID，如: `/nezha detail 1`")
        elif sub_cmd == "service":
            if len(parts) >= 3 and parts[2].lower() == "detail":
                if len(parts) >= 4:
                    async for result in self._handle_service_detail(event, parts[3]):
                        yield result
                else:
                    yield event.plain_result("❌ 请指定服务 ID，如: `/nezha service detail 1`")
            else:
                async for result in self._handle_service_list(event):
                    yield result
        elif sub_cmd == "history":
            async for result in self._handle_history_dispatch(event):
                yield result
        else:
            yield event.plain_result(self.HELP_TEXT)

    async def _handle_status(self, event: AstrMessageEvent) -> AsyncGenerator:
        servers = await self._fetch_servers()
        if servers is None:
            yield event.plain_result("❌ 获取状态失败：API 错误，请检查配置")
            return
        if not servers:
            yield event.plain_result("📭 暂无服务器")
            return

        server_infos = [self._parse_server(svr) for svr in servers]
        total = len(server_infos)
        online_count = sum(1 for info in server_infos if info.online)

        server_data = self._prepare_server_data(server_infos)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        t2i_data = {
            "total": total,
            "online": online_count,
            "offline": total - online_count,
            "servers": server_data,
            "update_time": now,
        }

        async for result in self._render_image(event, "status", t2i_data, "生成状态图片失败"):
            yield result

    async def _handle_detail(self, event: AstrMessageEvent, server_id: str) -> AsyncGenerator:
        if not server_id.isdigit():
            yield event.plain_result(f"❌ 无效的服务器 ID: {server_id}，请输入数字")
            return

        servers = await self._fetch_servers()
        if servers is None:
            yield event.plain_result("❌ 获取服务器详情失败：API 错误，请检查配置")
            return
        if not servers:
            yield event.plain_result("📭 暂无服务器")
            return

        server = next((s for s in servers if str(s.get(self.FIELD_ID)) == server_id), None)
        if not server:
            yield event.plain_result(f"❌ 未找到 ID 为 {server_id} 的服务器")
            return

        info = self._parse_server(server)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        t2i_data = {
            "server": {
                "name": info.name,
                "online": info.online,
                "cpu": info.cpu,
                "mem_percent": info.mem_used / max(info.mem_total, 1) * 100,
                "mem_used": self._format_bytes(info.mem_used),
                "mem_total": self._format_bytes(info.mem_total),
                "disk_percent": info.disk_used / max(info.disk_total, 1) * 100,
                "disk_used": self._format_bytes(info.disk_used),
                "disk_total": self._format_bytes(info.disk_total),
                "uptime": self._format_uptime(info.uptime),
                "platform": info.platform,
                "platform_version": info.platform_version,
                "net_in": self._format_bytes(info.net_in_transfer),
                "net_out": self._format_bytes(info.net_out_transfer),
                "last_active": info.last_active,
                "country_code": info.geoip_country.lower() if info.geoip_country else "un",
                "cpu_cores": "N/A",
            },
            "update_time": now,
        }

        async for result in self._render_image(event, "server_detail", t2i_data, "生成详情图片失败"):
            yield result

    async def _handle_service_list(self, event: AstrMessageEvent) -> AsyncGenerator:
        services = await self._fetch_services()
        if services is None:
            yield event.plain_result("❌ 获取服务监控列表失败，请检查面板配置和 API Token 权限")
            return
        if not services:
            yield event.plain_result("📭 暂无服务监控")
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(services)
        online = sum(1 for s in services if s.get("status") == self.SERVICE_STATUS_ONLINE)
        offline = sum(1 for s in services if s.get("status") == self.SERVICE_STATUS_OFFLINE)

        service_data = []
        for svc in services:
            status = svc.get("status", self.SERVICE_STATUS_UNKNOWN)
            icon, status_text = self._parse_service_status(status)
            status_class = "online" if status == self.SERVICE_STATUS_ONLINE else "offline" if status == self.SERVICE_STATUS_OFFLINE else "unknown"
            avg_delay = svc.get("avg_delay", 0)
            service_data.append({
                "id": svc.get("id", "N/A"),
                "name": svc.get("name", "未命名"),
                "status": status_text,
                "status_class": status_class,
                "up_percent": svc.get("up_percent", 0),
                "avg_delay": f"{avg_delay:.1f}ms" if avg_delay > 0 else "N/A",
            })

        t2i_data = {
            "services": service_data,
            "total": total,
            "online": online,
            "offline": offline,
            "update_time": now,
        }

        async for result in self._render_image(event, "service_list", t2i_data, "生成服务列表图片失败"):
            yield result

    async def _handle_service_detail(self, event: AstrMessageEvent, service_id: str) -> AsyncGenerator:
        if not service_id.isdigit():
            yield event.plain_result(f"❌ 无效的服务 ID: {service_id}，请输入数字")
            return

        service_data = await self._fetch_service_history(int(service_id), "1d")
        if service_data is None:
            yield event.plain_result(f"❌ 获取服务 ID {service_id} 详情失败，请确认 ID 是否正确")
            return

        service_name = service_data.get("service_name", "未命名")
        servers = service_data.get("servers", [])

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not servers:
            t2i_data = {
                "service_name": service_name,
                "servers": [],
                "overall_up_percent": 0,
                "overall_avg_delay": "N/A",
                "total_checks": 0,
                "overall_status_text": "未知",
                "overall_status_class": "unknown",
                "update_time": now,
            }
            async for result in self._render_image(event, "service_detail", t2i_data, "生成服务详情图片失败"):
                yield result
            return

        total_up = 0
        total_down = 0
        total_avg_delay = 0
        server_items = []

        for svr in servers:
            stats = svr.get("stats", {})
            up = stats.get("total_up", 0)
            down = stats.get("total_down", 0)
            avg_delay = stats.get("avg_delay", 0)
            up_percent = stats.get("up_percent", 0)

            total_up += up
            total_down += down
            total_avg_delay += avg_delay

            status_class = "online" if up_percent >= 95 else "offline" if up_percent >= 50 else "warning"
            status_text = "正常" if up_percent >= 95 else "异常" if up_percent >= 50 else "异常"

            server_items.append({
                "server_name": svr.get("server_name", "未知服务器"),
                "up_percent": up_percent,
                "avg_delay": f"{avg_delay:.1f}ms" if avg_delay > 0 else "N/A",
                "status_class": status_class,
                "status_text": status_text,
            })

        total_checks = total_up + total_down
        overall_up_percent = (total_up / total_checks * 100) if total_checks > 0 else 0
        overall_avg_delay = f"{total_avg_delay / len(servers):.1f}ms" if servers else "N/A"

        overall_status_text = "正常" if overall_up_percent >= 95 else "异常" if overall_up_percent >= 50 else "异常"
        overall_status_class = "online" if overall_up_percent >= 95 else "offline" if overall_up_percent >= 50 else "unknown"

        t2i_data = {
            "service_name": service_name,
            "servers": server_items,
            "overall_up_percent": overall_up_percent,
            "overall_avg_delay": overall_avg_delay,
            "total_checks": total_checks,
            "overall_status_text": overall_status_text,
            "overall_status_class": overall_status_class,
            "update_time": now,
        }

        async for result in self._render_image(event, "service_detail", t2i_data, "生成服务详情图片失败"):
            yield result

    async def _handle_history_dispatch(self, event: AstrMessageEvent) -> AsyncGenerator:
        parts = event.message_str.strip().split()

        if len(parts) < 4:
            yield event.plain_result(
                "📖 **历史指标查询用法**\n\n"
                "`/nezha history <服务器ID> <指标名> [周期]`\n\n"
                "**指标名**：cpu, memory, disk, load1, tcp_conn, process_count 等\n"
                "**周期**：1d (默认), 7d, 30d\n\n"
                "📌 示例：`/nezha history 1 cpu 1d`"
            )
            return

        server_id = parts[2]
        metric = parts[3].lower()
        period = parts[4].lower() if len(parts) >= 5 else "1d"

        if not server_id.isdigit():
            yield event.plain_result(f"❌ 无效的服务器 ID: {server_id}，请输入数字")
            return

        if metric not in self.METRIC_DISPLAY_NAMES:
            valid_metrics = ", ".join(list(self.METRIC_DISPLAY_NAMES.keys())[:10])
            yield event.plain_result(
                f"❌ 不支持的指标: {metric}\n"
                f"💡 支持的指标: {valid_metrics} ...\n"
                f"📖 使用 `/nezha history` 查看完整用法"
            )
            return

        if period not in ("1d", "7d", "30d"):
            yield event.plain_result(f"❌ 不支持的周期: {period}\n💡 支持的周期: 1d, 7d, 30d")
            return

        async for result in self._handle_history(event, int(server_id), metric, period):
            yield result

    async def _handle_history(self, event: AstrMessageEvent, server_id: int, metric: str, period: str) -> AsyncGenerator:
        servers = await self._fetch_servers()
        server_name = f"ID:{server_id}"
        disk_total = None
        if servers:
            for s in servers:
                if s.get(self.FIELD_ID) == server_id:
                    server_name = s.get(self.FIELD_NAME, server_name)
                    host = s.get(self.FIELD_HOST, {})
                    disk_total = host.get(self.FIELD_DISK_TOTAL)
                    break

        data = await self._fetch_server_metrics(server_id, metric, period)

        if data is None:
            yield event.plain_result(f"❌ 获取服务器 {server_name} 的 {metric} 历史数据失败")
            return

        if isinstance(data, dict) and data.get("error") == "tsdb_not_enabled":
            yield event.plain_result(
                f"❌ **TSDB 未启用**\n\n"
                f"获取历史指标 ({metric}) 需要哪吒面板启用 TSDB（时序数据库）。\n\n"
                "💡 **解决方法：**\n"
                "1. 在哪吒面板配置文件中设置 `tsdb: true`\n"
                "2. 确保 TimescaleDB 已安装并运行\n"
                "3. 重启哪吒面板服务"
            )
            return

        if isinstance(data, dict) and data.get("error") == "no_data":
            yield event.plain_result(f"📭 服务器 {server_name} 暂无 {metric} 历史数据")
            return

        data_points = data.get("data_points", [])
        if not data_points:
            yield event.plain_result(f"📭 服务器 {server_name} 暂无 {metric} 历史数据")
            return

        values = []
        timestamps = []
        for point in data_points:
            ts = point.get("ts", 0)
            val = point.get("value", 0)
            if val is not None:
                val = float(val)
                if metric == "disk" and disk_total and disk_total > 0:
                    val = (val / disk_total) * 100
                values.append(val)
                timestamps.append(ts)

        if not values:
            yield event.plain_result(f"📭 服务器 {server_name} 的 {metric} 数据为空")
            return

        # 削峰：将超出均值 + 3倍标准差的值截断（仅用于图表显示，统计值使用原始数据）
        clipped_values = values.copy()
        if len(clipped_values) > 2:
            mean = sum(clipped_values) / len(clipped_values)
            std = (sum((v - mean) ** 2 for v in clipped_values) / len(clipped_values)) ** 0.5
            upper_limit = mean + 3 * std
            clipped_values = [min(v, upper_limit) for v in clipped_values]

        current = values[-1] if values else 0
        max_val = max(values) if values else 0
        min_val = min(values) if values else 0
        avg_val = sum(values) / len(values) if values else 0

        max_idx = values.index(max_val) if values else -1
        min_idx = values.index(min_val) if values else -1

        def format_timestamp(ts: int) -> str:
            try:
                if ts > 1e12:
                    dt = datetime.fromtimestamp(ts / 1000)
                else:
                    dt = datetime.fromtimestamp(ts)
                return dt.strftime("%m-%d %H:%M")
            except:
                return ""

        max_time = format_timestamp(timestamps[max_idx]) if max_idx >= 0 else ""
        min_time = format_timestamp(timestamps[min_idx]) if min_idx >= 0 else ""
        start_time = format_timestamp(timestamps[0]) if timestamps else ""
        end_time = format_timestamp(timestamps[-1]) if timestamps else ""

        display_name = self.METRIC_DISPLAY_NAMES.get(metric, metric)
        period_names = {"1d": "过去24小时", "7d": "过去7天", "30d": "过去30天"}

        def format_metric_value(value: float) -> str:
            if metric == "disk":
                return f"{value:.1f}%"
            if metric in ("net_in_transfer", "net_out_transfer"):
                return self._format_bytes(int(value))
            if metric == "uptime":
                return self._format_uptime(int(value))
            return f"{value:.2f}{self.METRIC_UNITS.get(metric, '')}"

        # 使用削峰后的数据生成 SVG 点
        if len(clipped_values) > 1:
            min_val_plot = min(clipped_values)
            max_val_plot = max(clipped_values)
            range_val_plot = max_val_plot - min_val_plot if max_val_plot != min_val_plot else 1
            points = []
            for i, v in enumerate(clipped_values):
                x = (i / max(len(clipped_values) - 1, 1)) * 600
                y = 140 - ((v - min_val_plot) / range_val_plot) * 120 - 10
                points.append(f"{x:.1f},{y:.1f}")
            points_str = " ".join(points)
        else:
            points_str = ""

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        t2i_data = {
            "server_name": server_name,
            "metric_name": display_name,
            "period_label": period_names.get(period, period),
            "current_value": format_metric_value(current),
            "max_value": format_metric_value(max_val),
            "max_time": max_time,
            "min_value": format_metric_value(min_val),
            "min_time": min_time,
            "avg_value": format_metric_value(avg_val),
            "points": points_str,
            "start_time": start_time,
            "end_time": end_time,
            "update_time": now,
        }

        async for result in self._render_image(event, "history", t2i_data, "生成历史趋势图片失败"):
            yield result
