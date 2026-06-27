"""
哪吒探针插件 (astrbot_plugin_nezhatz)

用于查看哪吒监控站点的服务器状态等信息
支持指令调用
基于哪吒监控 2.2.6 版本 API

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
    """服务器信息数据类"""

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
        """转换为字典，便于模板渲染"""
        return asdict(self)


@register(
    "astrbot_plugin_nezhatz",
    "叹号大帝",
    "哪吒探针 - 查看哪吒监控站点服务器状态",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_nezhatz",
)
class NezhaPlugin(Star):
    """哪吒探针插件主类"""

    # ==================== 时间常量 ====================

    SECONDS_PER_MINUTE = 60
    SECONDS_PER_HOUR = 3600
    SECONDS_PER_DAY = 86400
    ONLINE_THRESHOLD_SECONDS = 300  # 5分钟

    # ==================== 网络请求常量 ====================

    DEFAULT_REQUEST_TIMEOUT = 30.0
    MIN_TIMEOUT = 1.0
    BYTES_PER_UNIT = 1024
    CACHE_TTL_SECONDS = 30.0  # 默认30秒，平衡实时性和API负载
    MAX_RETRY_ATTEMPTS = 3
    RETRY_BACKOFF_BASE = 2
    RETRY_JITTER = 0.5

    # HTTP 连接池配置
    MAX_KEEPALIVE_CONNECTIONS = 20
    MAX_HTTP_CONNECTIONS = 50

    # 帮助文本
    HELP_TEXT = (
        "📖 **哪吒探针使用帮助**\n\n"
        "`/nezha list` - 列出所有服务器\n"
        "`/nezha detail <id>` - 查看服务器详情\n"
        "`/nezha status` - 查看状态概览（图片）"
    )

    # 国家旗帜映射（使用 MappingProxyType 防止意外修改）
    COUNTRY_FLAGS: Dict[str, str] = {
        "cn": "🇨🇳",
        "us": "🇺🇸",
        "hk": "🇭🇰",
        "jp": "🇯🇵",
        "kr": "🇰🇷",
        "sg": "🇸🇬",
        "uk": "🇬🇧",
        "de": "🇩🇪",
        "fr": "🇫🇷",
        "ru": "🇷🇺",
        "au": "🇦🇺",
        "ca": "🇨🇦",
        "in": "🇮🇳",
        "br": "🇧🇷",
        "mx": "🇲🇽",
        "it": "🇮🇹",
        "es": "🇪🇸",
        "nl": "🇳🇱",
        "se": "🇸🇪",
        "no": "🇳🇴",
        "fi": "🇫🇮",
        "is": "🇮🇸",
        "pl": "🇵🇱",
        "ua": "🇺🇦",
        "tr": "🇹🇷",
        "ae": "🇦🇪",
        "sa": "🇸🇦",
        "il": "🇮🇱",
        "za": "🇿🇦",
        "eg": "🇪🇬",
        "ng": "🇳🇬",
        "ke": "🇰🇪",
        "tw": "🇹🇼",
        "mo": "🇲🇴",
        "my": "🇲🇾",
        "th": "🇹🇭",
        "vn": "🇻🇳",
        "ph": "🇵🇭",
        "id": "🇮🇩",
        "pk": "🇵🇰",
        "bd": "🇧🇩",
        "kz": "🇰🇿",
        "uz": "🇺🇿",
    }

    # 操作系统图标映射
    OS_ICON_MAP: Dict[str, str] = {
        "ubuntu": "fl-ubuntu",
        "debian": "fl-debian",
        "centos": "fl-centos",
        "rhel": "fl-centos",
        "fedora": "fl-fedora",
        "alpine": "fl-alpine",
        "arch": "fl-archlinux",
        "opensuse": "fl-opensuse",
        "windows": "fl-windows",
        "mac": "fl-macos",
        "darwin": "fl-macos",
    }

    # 指标名称映射
    METRIC_LABELS: Dict[str, str] = {
        "cpu": "CPU",
        "memory": "内存",
        "disk": "磁盘",
        "net_in_speed": "入站",
        "net_out_speed": "出站",
        "tcp_conn": "TCP连接",
        "process_count": "进程数",
    }

    # API 响应字段常量
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

        # 验证依赖（模块级别导入）
        self._check_dependencies()

        # SSL 警告
        if not self.verify_ssl:
            logger.warning(
                "SSL 验证已禁用，可能存在安全风险（中间人攻击）。"
                "建议配置有效的 SSL 证书或启用验证。"
            )

        # 验证并设置超时时间
        self.request_timeout = self._parse_timeout_config()

        # 缓存 TTL（支持用户配置）
        self.cache_ttl = self.config.get("cache_ttl_seconds", self.CACHE_TTL_SECONDS)

        # 连接池大小（支持用户配置）
        self.max_keepalive = self.config.get(
            "max_keepalive_connections", self.MAX_KEEPALIVE_CONNECTIONS
        )
        self.max_connections = self.config.get(
            "max_connections", self.MAX_HTTP_CONNECTIONS
        )

        # 初始化模板路径 - 优先使用数据目录下的自定义模板
        data_dir = StarTools.get_data_dir()
        custom_template = data_dir / "model" / "sysinfo.html"
        if custom_template.exists():
            self.template_path = custom_template
        else:
            self.template_path = Path(__file__).parent / "model" / "sysinfo.html"

        # 验证默认模板是否存在
        if not self.template_path.exists():
            logger.error(f"默认模板文件不存在: {self.template_path}")

        # 模板缓存（受锁保护）
        self._template_cache: Optional[str] = None
        self._template_mtime: Optional[float] = None
        self._template_last_check: float = 0.0
        self._template_check_interval = 60.0  # 每60秒检查一次文件修改
        self._template_lock = asyncio.Lock()

        # HTTP 客户端（连接池复用），受锁保护
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

        # 服务器列表缓存
        self._servers_cache: Optional[tuple[float, List[Dict[str, Any]]]] = None
        self._servers_cache_lock = asyncio.Lock()

        # 插件关闭标志
        self._shutting_down = False

        # 安全日志：不输出完整 API Token
        if self.api_token:
            token_preview = (
                self.api_token[:4] + "***" if len(self.api_token) >= 4 else "***"
            )
        else:
            token_preview = "未配置"
        logger.info(
            f"哪吒探针插件已加载，面板地址: {self.base_url}，Token: {token_preview}"
        )

    # ==================== 生命周期管理 ====================

    async def _ensure_client(self) -> httpx.AsyncClient:
        """
        确保 HTTP 客户端已初始化（线程安全）

        Returns:
            已初始化的 HTTP 客户端实例

        Raises:
            RuntimeError: 插件正在关闭时调用
        """
        # 检查关闭标志
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
        """插件卸载时清理资源"""
        self._shutting_down = True

        async with self._client_lock:
            if self._client:
                await self._client.aclose()
                self._client = None

        async with self._template_lock:
            self._template_cache = None
            self._template_mtime = None

        async with self._servers_cache_lock:
            self._servers_cache = None

        logger.info("哪吒探针插件已卸载")

    # ==================== 依赖检查 ====================

    def _check_dependencies(self) -> None:
        """
        检查必需依赖是否已安装

        在 __init__ 中调用，确保依赖在插件加载时就被验证
        """
        try:
            import dateutil  # noqa: F401
        except ImportError:
            logger.error(
                "python-dateutil 未安装，在线状态判断将不准确。"
                "请运行: pip install python-dateutil"
            )
            # 抛出异常，阻止插件加载
            raise RuntimeError(
                "缺少必需依赖 python-dateutil，请运行: pip install python-dateutil"
            )

    def _parse_timeout_config(self) -> float:
        """
        解析并验证超时配置

        Returns:
            有效的超时时间（秒）
        """
        try:
            raw_timeout = self.config.get(
                "request_timeout", self.DEFAULT_REQUEST_TIMEOUT
            )
            timeout = float(raw_timeout)
            if timeout > self.MIN_TIMEOUT:
                return timeout
            logger.warning(
                f"超时时间 {timeout}s 过小，使用默认值 {self.DEFAULT_REQUEST_TIMEOUT}s"
            )
        except (TypeError, ValueError):
            logger.warning("request_timeout 配置无效，使用默认值")
        return self.DEFAULT_REQUEST_TIMEOUT

    # ==================== 模板相关 ====================

    async def _load_template(self) -> str:
        """
        加载 HTML 模板（带缓存和定期检查）

        每60秒检查一次文件修改时间，避免频繁系统调用

        Returns:
            模板内容字符串，加载失败时返回错误 HTML
        """
        async with self._template_lock:
            # 重新检查路径是否存在
            if not self.template_path or not self.template_path.exists():
                logger.error(f"模板文件不存在: {self.template_path}")
                return "<h1>模板加载失败</h1>"

            now = time.time()
            # 仅在间隔时间到达时检查文件修改时间
            if now - self._template_last_check >= self._template_check_interval:
                current_mtime = self.template_path.stat().st_mtime
                self._template_last_check = now

                if (
                    self._template_cache is None
                    or self._template_mtime != current_mtime
                ):
                    try:
                        with open(self.template_path, "r", encoding="utf-8") as f:
                            self._template_cache = f.read()
                            self._template_mtime = current_mtime
                            logger.debug("模板已重新加载")
                    except Exception as e:
                        logger.error(f"加载模板失败: {e}")
                        return "<h1>模板加载失败</h1>"

            return self._template_cache or "<h1>模板加载失败</h1>"

    # ==================== 数据获取 ====================

    async def _get_cached_servers(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取缓存的服务器列表

        Returns:
            - 有效缓存数据
            - None: 缓存过期或不存在
        """
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
        """
        获取服务器列表（带重试）

        对可重试错误（连接失败、5xx 错误）进行重试，
        对不可重试错误（401、400 等）直接返回。

        Returns:
            - List[Dict[str, Any]]: 服务器列表
            - None: 所有重试均失败
        """
        last_error = None

        for attempt in range(self.MAX_RETRY_ATTEMPTS):
            result = await self._make_request("GET", "/api/v1/server")

            # 网络或 API 完全不可达（可重试）
            if result is None:
                last_error = "连接失败"
                if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                    wait_time = (self.RETRY_BACKOFF_BASE**attempt) + random.uniform(
                        0, self.RETRY_JITTER
                    )
                    logger.debug(
                        f"获取服务器列表失败，{wait_time:.2f}s 后重试 "
                        f"(尝试 {attempt + 1}/{self.MAX_RETRY_ATTEMPTS})"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                return None

            # API 返回错误
            if self.FIELD_ERROR in result:
                error_msg = result[self.FIELD_ERROR]
                # 判断是否为可重试错误
                if self._is_retryable_error(error_msg):
                    last_error = error_msg
                    if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                        wait_time = (self.RETRY_BACKOFF_BASE**attempt) + random.uniform(
                            0, self.RETRY_JITTER
                        )
                        logger.debug(
                            f"获取服务器列表失败 (可重试): {error_msg}，"
                            f"{wait_time:.2f}s 后重试 (尝试 {attempt + 1}/{self.MAX_RETRY_ATTEMPTS})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                logger.error(f"获取服务器列表失败 (不可重试): {error_msg}")
                return None

            # 正常响应
            servers = (
                result.get(self.FIELD_DATA, []) if isinstance(result, dict) else result
            )
            if isinstance(servers, list):
                return servers

            last_error = "数据格式异常"
            logger.error(f"服务器数据格式异常: {type(servers)}")
            return []

        logger.error(
            f"获取服务器列表失败，已重试 {self.MAX_RETRY_ATTEMPTS} 次: {last_error}"
        )
        return None

    @staticmethod
    def _is_retryable_error(error_msg: str) -> bool:
        """
        判断错误是否可重试

        Args:
            error_msg: 错误消息

        Returns:
            True 表示可重试，False 表示不可重试
        """
        non_retryable_keywords = [
            "认证失败",
            "未配置",
            "响应格式错误",
            "不支持的HTTP方法",
        ]
        for keyword in non_retryable_keywords:
            if keyword in error_msg:
                return False
        # 默认视为可重试（如连接错误、超时等）
        return True

    async def _fetch_servers(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取服务器列表（带缓存和双重检查锁）

        设计说明：使用双重检查锁模式，避免高并发时重复请求 API。
        缓存更新在锁保护下完成，确保原子性。

        Returns:
            - List[Dict[str, Any]]: 服务器列表（可能为空列表）
            - None: API 错误或网络错误
        """
        # 1. 快速路径：检查缓存（只读锁）
        cached = await self._get_cached_servers()
        if cached is not None:
            return cached

        # 2. 双重检查：获取写锁，再次检查缓存
        async with self._servers_cache_lock:
            # 再次检查缓存（可能在等待锁期间已被其他协程更新）
            if self._servers_cache is not None:
                cached_time, cached_data = self._servers_cache
                age = time.time() - cached_time
                if age < self.cache_ttl:
                    logger.debug(f"双重检查命中缓存 (缓存年龄: {age:.1f}s)")
                    return cached_data

            # 3. 缓存确实过期或不存在，获取新数据
            servers = await self._fetch_servers_with_retry()
            if servers is not None:
                # 在锁保护下更新缓存
                self._servers_cache = (time.time(), servers)
                logger.debug(f"服务器列表已更新，共 {len(servers)} 台服务器")
            return servers

    def _get_headers(self) -> Dict[str, str]:
        """构建 API 请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """
        安全地将值转换为浮点数

        Args:
            value: 待转换的值
            default: 转换失败时的默认值

        Returns:
            转换后的浮点数或默认值
        """
        if value is None:
            return default
        # 布尔值特殊处理（记录警告）
        if isinstance(value, bool):
            logger.warning(f"布尔值被转换为浮点数: {value} -> {1.0 if value else 0.0}")
            return 1.0 if value else 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        """
        安全地将值转换为整数

        Args:
            value: 待转换的值
            default: 转换失败时的默认值

        Returns:
            转换后的整数或默认值
        """
        if value is None:
            return default
        # 布尔值特殊处理（记录警告）
        if isinstance(value, bool):
            logger.warning(f"布尔值被转换为整数: {value} -> {1 if value else 0}")
            return 1 if value else 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _is_online(self, server: Dict[str, Any]) -> bool:
        """
        判断服务器是否在线，基于 last_active 字段

        如果解析失败，返回 False（视为离线）。

        Args:
            server: 服务器原始数据字典

        Returns:
            True 表示在线，False 表示离线
        """
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
            # 解析异常视为离线（严格策略）
            logger.warning(
                f"解析 last_active 失败: {e}，"
                f"服务器 {server.get(self.FIELD_NAME, '未知')} 视为离线"
            )
            return False

    def _parse_server(self, server: Dict[str, Any]) -> ServerInfo:
        """
        将原始服务器数据解析为 ServerInfo 对象（带类型安全转换）

        Args:
            server: 服务器原始数据字典

        Returns:
            结构化的服务器信息对象
        """
        state = server.get(self.FIELD_STATE, {})
        host = server.get(self.FIELD_HOST, {})
        geoip = server.get(self.FIELD_GEOIP, {})

        # 安全获取字符串字段
        platform = host.get(self.FIELD_PLATFORM) or "N/A"
        platform_version = host.get(self.FIELD_PLATFORM_VERSION) or ""
        geoip_country = geoip.get(self.FIELD_COUNTRY_CODE) or ""

        # 安全转换数值字段（防止 API 返回 None 或非数字字符串）
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
        """
        发送 HTTP 请求到哪吒面板 API

        Args:
            method: HTTP 方法 (GET, POST, PUT, DELETE)
            endpoint: API 端点路径
            data: 请求体数据（POST/PUT 时使用），为 None 时不发送 body
            use_admin: 是否使用管理员 Token

        Returns:
            解析后的 JSON 响应，失败时返回包含 "error" 字段的字典或 None
        """
        if not self.base_url:
            logger.error("未配置哪吒监控面板地址 (base_url)")
            return {self.FIELD_ERROR: "未配置面板地址"}

        # 管理员 Token 缺失时明确报错
        if use_admin and not self.admin_token:
            error_msg = "管理员 Token 未配置，无法执行管理员操作"
            logger.error(error_msg)
            return {self.FIELD_ERROR: error_msg}

        url = f"{self.base_url}{endpoint}"
        # 安全日志：仅记录端点路径，不包含查询参数
        safe_endpoint = endpoint.split("?")[0]
        logger.debug(f"请求: {method} {safe_endpoint}")

        # 处理 headers
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
                    logger.error(
                        f"解析 JSON 响应失败: {e}, 响应内容: {response.text[:200]}"
                    )
                    return {self.FIELD_ERROR: "响应格式错误，请检查面板地址是否正确"}
            elif response.status_code == 401:
                logger.error("API认证失败，请检查API Token是否正确")
                return {self.FIELD_ERROR: "认证失败，请检查API Token"}
            elif response.status_code >= 500:
                # 5xx 错误可重试
                logger.error(f"服务器错误: {response.status_code}")
                return {self.FIELD_ERROR: f"服务器错误: {response.status_code}"}
            else:
                logger.error(f"API请求失败: {response.status_code}")
                return {self.FIELD_ERROR: f"请求失败: {response.status_code}"}

        except RuntimeError as e:
            # 插件关闭时的异常
            logger.error(f"插件状态错误: {e}")
            return {self.FIELD_ERROR: "插件正在关闭，请稍后重试"}
        except httpx.ConnectError:
            logger.error(f"无法连接到哪吒面板: {self.base_url}")
            return {self.FIELD_ERROR: f"无法连接到面板: {self.base_url}"}
        except httpx.TimeoutException:
            logger.error("请求超时")
            return {self.FIELD_ERROR: "请求超时"}
        except Exception as e:
            # 记录详细异常，返回通用错误信息
            logger.error(f"请求异常: {e}")
            return {self.FIELD_ERROR: "请求处理失败，请检查日志"}

    # ==================== 格式化辅助 ====================

    def _get_country_flag(self, country_code: str) -> str:
        """
        获取国家旗帜 Emoji

        Args:
            country_code: 两位国家代码（如 "cn", "us"）

        Returns:
            对应的旗帜 Emoji，未找到时返回 🌍
        """
        return self.COUNTRY_FLAGS.get(country_code.lower(), "🌍")

    @staticmethod
    @lru_cache(maxsize=128)
    def _get_os_icon_cached(platform: str) -> str:
        """
        带缓存的操作系统图标查找（静态方法，共享缓存）

        使用 @staticmethod 避免实例持有引用导致内存泄漏

        Args:
            platform: 操作系统名称字符串

        Returns:
            font-logos 图标类名
        """
        if not platform or platform == "N/A":
            return "fl-tux"

        platform_lower = platform.lower()
        # 注意：静态方法无法直接访问类属性，使用硬编码映射
        icon_map = {
            "ubuntu": "fl-ubuntu",
            "debian": "fl-debian",
            "centos": "fl-centos",
            "rhel": "fl-centos",
            "fedora": "fl-fedora",
            "alpine": "fl-alpine",
            "arch": "fl-archlinux",
            "opensuse": "fl-opensuse",
            "windows": "fl-windows",
            "mac": "fl-macos",
            "darwin": "fl-macos",
        }
        for key, icon in icon_map.items():
            if key in platform_lower:
                return icon
        return "fl-tux"

    def _get_os_icon(self, platform: str) -> str:
        """
        根据操作系统返回 font-logos 图标类名（带缓存）

        Args:
            platform: 操作系统名称字符串

        Returns:
            font-logos 图标类名
        """
        return self._get_os_icon_cached(platform)

    def _format_bytes(self, bytes_val: int) -> str:
        """
        格式化字节大小

        Args:
            bytes_val: 字节数

        Returns:
            格式化后的字符串（如 "1.23 MB"）
        """
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
        """
        格式化运行时间

        Args:
            seconds: 秒数

        Returns:
            人类可读的运行时间字符串
        """
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

    def _format_metric_label(self, metric: str) -> str:
        """
        格式化指标名称

        Args:
            metric: 指标键名

        Returns:
            中文标签
        """
        return self.METRIC_LABELS.get(metric, metric)

    # ==================== 模板数据准备 ====================

    def _prepare_template_data(
        self, server_infos: List[ServerInfo]
    ) -> List[Dict[str, Any]]:
        """
        准备模板渲染所需的数据

        会创建新的字典副本，不会修改原始 ServerInfo 对象

        Args:
            server_infos: ServerInfo 对象列表

        Returns:
            模板数据字典列表
        """
        server_data = []
        for info in server_infos:
            data = info.to_dict()
            # 添加计算字段（使用 max(1, ...) 防止除零）
            data["mem_percent"] = info.mem_used / max(info.mem_total, 1) * 100
            data["disk_percent"] = info.disk_used / max(info.disk_total, 1) * 100
            data["os_icon"] = self._get_os_icon(info.platform)
            data["flag"] = self._get_country_flag(info.geoip_country)
            data["country_code"] = info.geoip_country.lower()
            server_data.append(data)
        return server_data

    # ==================== 指令处理器 ====================

    @filter.command("nezha")
    async def nezha_cmd(self, event: AstrMessageEvent) -> AsyncGenerator:
        """
        哪吒探针主命令处理器

        支持子命令:
            /nezha list    - 列出所有服务器
            /nezha status  - 查看状态概览（图片）
            /nezha detail <id> - 查看服务器详情
        """
        parts = event.message_str.strip().split()

        # 无参数时默认显示状态
        if len(parts) < 2:
            async for result in self._handle_status(event):
                yield result
            return

        sub_cmd = parts[1].lower()

        # 命令路由字典
        handlers = {
            "list": self._handle_list,
            "status": self._handle_status,
        }

        if sub_cmd in handlers:
            async for result in handlers[sub_cmd](event):
                yield result
        elif sub_cmd == "detail":
            if len(parts) >= 3:
                async for result in self._handle_detail(event, parts[2]):
                    yield result
            else:
                yield event.plain_result("❌ 请指定服务器 ID，如: `/nezha detail 1`")
        else:
            yield event.plain_result(self.HELP_TEXT)

    async def _handle_list(self, event: AstrMessageEvent) -> AsyncGenerator:
        """
        处理 /nezha list 命令 - 文字版服务器列表
        """
        servers = await self._fetch_servers()
        if servers is None:
            yield event.plain_result("❌ 获取服务器列表失败：API 错误，请检查配置")
            return
        if not servers:
            yield event.plain_result("📭 暂无服务器")
            return

        lines = ["📊 **服务器列表**", ""]
        for svr in servers:
            info = self._parse_server(svr)
            status_icon = "🟢" if info.online else "🔴"
            lines.append(f"{status_icon} {info.name} - CPU: {info.cpu:.1f}%")
        yield event.plain_result("\n".join(lines))

    async def _handle_detail(
        self, event: AstrMessageEvent, server_id: str
    ) -> AsyncGenerator:
        """
        处理 /nezha detail <id> 命令 - 服务器详细信息
        """
        # 验证 server_id 是否为有效数字
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

        server = next(
            (s for s in servers if str(s.get(self.FIELD_ID)) == server_id), None
        )
        if not server:
            yield event.plain_result(f"❌ 未找到 ID 为 {server_id} 的服务器")
            return

        info = self._parse_server(server)
        lines = [
            "📋 **服务器详细信息**",
            "",
            f"🔹 **名称**: {info.name}",
            f"🔹 **ID**: {info.id}",
            f"🔹 **状态**: {'🟢 在线' if info.online else '🔴 离线'}",
            f"🔹 **系统**: {info.platform} {info.platform_version}",
            f"🔹 **CPU**: {info.cpu:.1f}%",
            f"🔹 **内存**: {self._format_bytes(info.mem_used)} / {self._format_bytes(info.mem_total)}",
            f"🔹 **磁盘**: {self._format_bytes(info.disk_used)} / {self._format_bytes(info.disk_total)}",
            f"🔹 **入站**: {self._format_bytes(info.net_in_transfer)}",
            f"🔹 **出站**: {self._format_bytes(info.net_out_transfer)}",
            f"🔹 **运行时间**: {self._format_uptime(info.uptime)}",
        ]
        yield event.plain_result("\n".join(lines))

    async def _handle_status(self, event: AstrMessageEvent) -> AsyncGenerator:
        """
        处理 /nezha status 命令 - 状态概览图片
        """
        servers = await self._fetch_servers()
        if servers is None:
            yield event.plain_result("❌ 获取状态失败：API 错误，请检查配置")
            return
        if not servers:
            yield event.plain_result("📭 暂无服务器")
            return

        # 使用 ServerInfo 统一解析所有服务器数据
        server_infos = [self._parse_server(svr) for svr in servers]
        total = len(server_infos)
        online_count = sum(1 for info in server_infos if info.online)
        offline_count = total - online_count

        # 准备模板数据
        server_data = self._prepare_template_data(server_infos)

        # 加载模板并渲染
        template = await self._load_template()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            image_url = await self.html_render(
                template,
                {
                    "total": total,
                    "online": online_count,
                    "offline": offline_count,
                    "servers": server_data,
                    "update_time": now,
                },
                options={
                    "full_page": True,
                    "type": "png",
                    "scale": "css",
                    "timeout": 30000,  # 30秒超时（毫秒）
                },
            )

            if not image_url:
                yield event.plain_result(
                    "❌ 生成状态图片失败，请检查 HTML 模板是否完整"
                )
            else:
                yield event.image_result(image_url)
        except asyncio.TimeoutError:
            logger.error("渲染图片超时")
            yield event.plain_result("❌ 渲染图片超时，请稍后重试")
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            yield event.plain_result(f"❌ 渲染图片失败: {e}")
