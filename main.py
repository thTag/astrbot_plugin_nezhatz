"""
哪吒探针插件 (astrbot_plugin_nezhatz)

用于查看哪吒监控站点的服务器状态等信息
支持指令与LLM Tools调用
基于哪吒监控 2.2.6 版本 API

作者: 叹号大帝
"""

from typing import Optional, Dict, List, Any, AsyncGenerator, Union
from datetime import datetime
from pathlib import Path

import httpx
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools


@register(
    "astrbot_plugin_nezhatz",
    "叹号大帝",
    "哪吒探针 - 查看哪吒监控站点服务器状态",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_nezhatz"
)
class NezhaPlugin(Star):
    """哪吒探针插件主类"""

    ONLINE_THRESHOLD_SECONDS = 300
    DEFAULT_REQUEST_TIMEOUT = 30.0

    # 国家旗帜映射
    COUNTRY_FLAGS = {
        "cn": "🇨🇳", "us": "🇺🇸", "hk": "🇭🇰", "jp": "🇯🇵",
        "kr": "🇰🇷", "sg": "🇸🇬", "uk": "🇬🇧", "de": "🇩🇪",
        "fr": "🇫🇷", "ru": "🇷🇺", "au": "🇦🇺", "ca": "🇨🇦",
        "in": "🇮🇳", "br": "🇧🇷", "mx": "🇲🇽", "it": "🇮🇹",
        "es": "🇪🇸", "nl": "🇳🇱", "se": "🇸🇪", "no": "🇳🇴",
        "fi": "🇫🇮", "is": "🇮🇸", "pl": "🇵🇱", "ua": "🇺🇦",
        "tr": "🇹🇷", "ae": "🇦🇪", "sa": "🇸🇦", "il": "🇮🇱",
        "za": "🇿🇦", "eg": "🇪🇬", "ng": "🇳🇬", "ke": "🇰🇪",
        "tw": "🇹🇼", "mo": "🇲🇴", "my": "🇲🇾", "th": "🇹🇭",
        "vn": "🇻🇳", "ph": "🇵🇭", "id": "🇮🇩", "pk": "🇵🇰",
        "bd": "🇧🇩", "kz": "🇰🇿", "uz": "🇺🇿"
    }

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = self.config.get("base_url", "").rstrip("/")
        self.api_token = self.config.get("api_token", "")
        self.admin_token = self.config.get("admin_token", "")
        self.verify_ssl = self.config.get("verify_ssl", True)
        self.request_timeout = self.config.get("request_timeout", self.DEFAULT_REQUEST_TIMEOUT)
        
        # 初始化模板路径 - 优先使用数据目录下的自定义模板
        data_dir = StarTools.get_data_dir()
        custom_template = data_dir / "model" / "sysinfo.html"
        if custom_template.exists():
            self.template_path = custom_template
        else:
            self.template_path = Path(__file__).parent / "model" / "sysinfo.html"
        
        # 缓存模板内容和修改时间
        self._template_cache: Optional[str] = None
        self._template_mtime: Optional[float] = None
        
        logger.info(f"哪吒探针插件已加载，面板地址: {self.base_url}")

    def _load_template(self) -> str:
        """加载 HTML 模板（带缓存和修改时间检测）"""
        if not self.template_path.exists():
            logger.error(f"模板文件不存在: {self.template_path}")
            return "<h1>模板加载失败</h1>"
        
        current_mtime = self.template_path.stat().st_mtime
        if self._template_cache is None or self._template_mtime != current_mtime:
            try:
                with open(self.template_path, "r", encoding="utf-8") as f:
                    self._template_cache = f.read()
                    self._template_mtime = current_mtime
                    logger.debug("模板已重新加载")
            except Exception as e:
                logger.error(f"加载模板失败: {e}")
                return "<h1>模板加载失败</h1>"
        
        return self._template_cache or "<h1>模板加载失败</h1>"

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _is_online(self, server: Dict) -> bool:
        """判断服务器是否在线，基于 last_active 字段"""
        last_active_str = server.get("last_active")
        if not last_active_str:
            return False
        try:
            from dateutil import parser
            last_time = parser.parse(last_active_str)
            now = datetime.now(last_time.tzinfo)
            diff = now - last_time
            return diff.total_seconds() < self.ONLINE_THRESHOLD_SECONDS
        except ImportError:
            logger.warning("dateutil 未安装，使用简单时间判断，建议安装 python-dateutil")
            return True
        except Exception as e:
            logger.warning(f"解析 last_active 失败，可能影响在线状态判断: {e}")
            return False

    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        data: Optional[Dict] = None,
        use_admin: bool = False
    ) -> Optional[Dict]:
        if not self.base_url:
            logger.error("未配置哪吒监控面板地址 (base_url)")
            return {"error": "未配置面板地址"}
            
        url = f"{self.base_url}{endpoint}"
        logger.debug(f"请求 URL: {url}")
        
        # 处理 headers
        if use_admin and self.admin_token:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.admin_token}"}
        elif use_admin and not self.admin_token:
            # 如果没有 admin_token，移除普通 token 以避免权限混淆
            headers = {"Content-Type": "application/json"}
        else:
            headers = self._get_headers()
        
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=self.request_timeout) as client:
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
                    return {"error": f"不支持的HTTP方法: {method}"}
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    logger.error("API认证失败，请检查API Token是否正确")
                    return {"error": "认证失败，请检查API Token"}
                else:
                    logger.error(f"API请求失败: {response.status_code} - {response.text}")
                    return {"error": f"请求失败: {response.status_code}"}
                    
        except httpx.ConnectError:
            logger.error(f"无法连接到哪吒面板: {self.base_url}")
            return {"error": f"无法连接到面板: {self.base_url}"}
        except httpx.TimeoutException:
            logger.error("请求超时")
            return {"error": "请求超时"}
        except Exception as e:
            logger.error(f"请求异常: {e}")
            return {"error": str(e)}

    def _get_country_flag(self, country_code: str) -> str:
        """获取国家旗帜 Emoji"""
        return self.COUNTRY_FLAGS.get(country_code.lower(), "🌍")

    def _get_os_icon(self, platform: str) -> str:
        """根据操作系统返回 font-logos 图标类名"""
        platform_lower = platform.lower()
        match platform_lower:
            case p if "ubuntu" in p:
                return "fl-ubuntu"
            case p if "debian" in p:
                return "fl-debian"
            case p if "centos" in p or "rhel" in p:
                return "fl-centos"
            case p if "fedora" in p:
                return "fl-fedora"
            case p if "alpine" in p:
                return "fl-alpine"
            case p if "arch" in p:
                return "fl-archlinux"
            case p if "opensuse" in p:
                return "fl-opensuse"
            case p if "windows" in p:
                return "fl-windows"
            case p if "mac" in p or "darwin" in p:
                return "fl-macos"
            case _:
                return "fl-tux"  # 默认使用 Linux 通用企鹅图标

    def _format_bytes(self, bytes_val: int) -> str:
        """格式化字节大小"""
        if bytes_val < 0:
            return "0 B"
        
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if bytes_val < 1024:
                if unit == "B":
                    return f"{bytes_val:.0f} B"
                return f"{bytes_val:.2f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.2f} PB"

    def _format_uptime(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            return f"{seconds // 60}分钟"
        elif seconds < 86400:
            return f"{seconds // 3600}小时 {seconds % 3600 // 60}分钟"
        else:
            days = seconds // 86400
            hours = seconds % 86400 // 3600
            return f"{days}天 {hours}小时"

    # ==================== 指令处理器 ====================

    @filter.command("nezha")
    async def nezha_cmd(self, event: AstrMessageEvent) -> AsyncGenerator:
        parts = event.message_str.strip().split()
        
        if len(parts) < 2:
            async for result in self._handle_status(event):
                yield result
            return
        
        sub_cmd = parts[1].lower()
        
        if sub_cmd == "list":
            async for result in self._handle_list(event):
                yield result
        elif sub_cmd == "detail" and len(parts) >= 3:
            server_id = parts[2]
            async for result in self._handle_detail(event, server_id):
                yield result
        elif sub_cmd == "status":
            async for result in self._handle_status(event):
                yield result
        else:
            yield event.plain_result(
                "📖 **哪吒探针使用帮助**\n\n"
                "`/nezha list` - 列出所有服务器\n"
                "`/nezha detail <id>` - 查看服务器详情\n"
                "`/nezha status` - 查看状态概览（图片）"
            )

    async def _handle_list(self, event: AstrMessageEvent) -> AsyncGenerator:
        """文字版列表"""
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                lines = ["📊 **服务器列表**", ""]
                for svr in servers:
                    name = svr.get("name", "未命名")
                    is_online = self._is_online(svr)
                    status_icon = "🟢" if is_online else "🔴"
                    state = svr.get("state", {})
                    cpu = state.get("cpu", 0)
                    lines.append(f"{status_icon} {name} - CPU: {cpu:.1f}%")
                yield event.plain_result("\n".join(lines))
            else:
                yield event.plain_result("❌ 获取服务器列表失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取服务器列表失败: {error_msg}")

    async def _handle_detail(self, event: AstrMessageEvent, server_id: str) -> AsyncGenerator:
        """文字版详情"""
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                server = next((s for s in servers if str(s.get("id")) == server_id), None)
                if server:
                    state = server.get("state", {})
                    host = server.get("host", {})
                    is_online = self._is_online(server)
                    
                    lines = [
                        "📋 **服务器详细信息**",
                        "",
                        f"🔹 **名称**: {server.get('name', 'N/A')}",
                        f"🔹 **ID**: {server.get('id', 'N/A')}",
                        f"🔹 **状态**: {'🟢 在线' if is_online else '🔴 离线'}",
                        f"🔹 **系统**: {host.get('platform', 'N/A')} {host.get('platform_version', '')}",
                        f"🔹 **CPU**: {state.get('cpu', 0):.1f}%",
                        f"🔹 **内存**: {self._format_bytes(state.get('mem_used', 0))} / {self._format_bytes(host.get('mem_total', 0))}",
                        f"🔹 **磁盘**: {self._format_bytes(state.get('disk_used', 0))} / {self._format_bytes(host.get('disk_total', 0))}",
                        f"🔹 **入站**: {self._format_bytes(state.get('net_in_transfer', 0))}",
                        f"🔹 **出站**: {self._format_bytes(state.get('net_out_transfer', 0))}",
                        f"🔹 **运行时间**: {self._format_uptime(state.get('uptime', 0))}",
                    ]
                    yield event.plain_result("\n".join(lines))
                else:
                    yield event.plain_result(f"❌ 未找到 ID 为 {server_id} 的服务器")
            else:
                yield event.plain_result("❌ 获取服务器详情失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取服务器详情失败: {error_msg}")

    async def _handle_status(self, event: AstrMessageEvent) -> AsyncGenerator:
        """状态概览 - 图片版"""
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                # 准备数据
                total = len(servers)
                online_count = sum(1 for s in servers if self._is_online(s))
                offline_count = total - online_count
                
                server_data = []
                for svr in servers:
                    state = svr.get("state", {})
                    host = svr.get("host", {})
                    mem_total = host.get("mem_total", 0)
                    mem_used = state.get("mem_used", 0)
                    mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
                    
                    disk_total = host.get("disk_total", 0)
                    disk_used = state.get("disk_used", 0)
                    disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
                    
                    geoip = svr.get("geoip", {})
                    country = geoip.get("country_code", "")
                    
                    server_data.append({
                        "name": svr.get("name", "未命名"),
                        "online": self._is_online(svr),
                        "cpu": state.get("cpu", 0),
                        "mem": mem_percent,
                        "disk": disk_percent,
                        "country_code": country.lower(),
                        "os_icon": self._get_os_icon(host.get("platform", "")),
                    })
                
                # 加载模板并渲染
                template = self._load_template()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                try:
                    image_url = await self.html_render(
                        template,
                        {
                            "total": total,
                            "online": online_count,
                            "offline": offline_count,
                            "servers": server_data,
                            "update_time": now
                        },
                        options={
                            "full_page": True,
                            "type": "png",
                            "scale": "css"
                        }
                    )
                    
                    if not image_url:
                        yield event.plain_result("❌ 生成状态图片失败，请检查 HTML 模板是否完整")
                    else:
                        yield event.image_result(image_url)
                except Exception as e:
                    logger.error(f"渲染图片失败: {e}")
                    yield event.plain_result(f"❌ 渲染图片失败: {e}")
            else:
                yield event.plain_result("❌ 获取状态失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取状态失败: {error_msg}")

    # ==================== LLM Tools ====================

    @filter.llm_tool(
        name="nezha_list_servers",
        description="获取哪吒监控中所有服务器的列表和基本状态信息"
    )
    async def llm_list_servers(self) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                lines = ["📊 服务器列表:"]
                for svr in servers:
                    name = svr.get("name", "未命名")
                    is_online = self._is_online(svr)
                    status_icon = "🟢" if is_online else "🔴"
                    state = svr.get("state", {})
                    cpu = state.get("cpu", 0)
                    lines.append(f"{status_icon} {name} - CPU: {cpu:.1f}%")
                return "\n".join(lines)
            return "获取服务器列表失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器列表失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_detail",
        description="获取指定服务器的详细信息"
    )
    async def llm_get_server_detail(self, server_id: str) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                server = next((s for s in servers if str(s.get("id")) == server_id), None)
                if server:
                    state = server.get("state", {})
                    host = server.get("host", {})
                    is_online = self._is_online(server)
                    lines = [
                        f"📋 {server.get('name', 'N/A')} 详情:",
                        f"状态: {'在线' if is_online else '离线'}",
                        f"CPU: {state.get('cpu', 0):.1f}%",
                        f"内存: {self._format_bytes(state.get('mem_used', 0))} / {self._format_bytes(host.get('mem_total', 0))}",
                        f"运行时间: {self._format_uptime(state.get('uptime', 0))}",
                    ]
                    return "\n".join(lines)
                return f"❌ 未找到 ID 为 {server_id} 的服务器"
            return "获取服务器详情失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器详情失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_server_status_summary",
        description="获取所有服务器的状态概览"
    )
    async def llm_server_status_summary(self) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                total = len(servers)
                online = sum(1 for s in servers if self._is_online(s))
                total_cpu = sum(s.get("state", {}).get("cpu", 0) for s in servers)
                avg_cpu = total_cpu / total if total > 0 else 0
                return f"📊 服务器状态概览\n总计: {total} 台\n在线: {online} 台\n离线: {total - online} 台\n平均CPU: {avg_cpu:.1f}%"
            return "获取状态失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取状态失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_data",
        description="获取服务器的实时数据指标"
    )
    async def llm_get_server_data(self, server_id: str) -> str:
        """使用 asyncio.gather 并发获取多个指标"""
        import asyncio
        
        metrics = ["cpu", "memory", "disk", "net_in_speed", "net_out_speed", "tcp_conn", "process_count"]
        
        async def fetch_metric(metric: str) -> tuple[str, Union[float, str]]:
            result = await self._make_request("GET", f"/api/v1/server/{server_id}/metrics?metric={metric}")
            if result and "error" not in result:
                data = result.get("data", {})
                points = data.get("data_points", [])
                if points:
                    return (metric, points[-1].get("value", 0))
                return (metric, 0)
            elif result and "error" in result:
                return (metric, f"错误: {result['error']}")
            return (metric, "获取失败")
        
        tasks = [fetch_metric(m) for m in metrics]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        result_data = {}
        error_messages = []
        for res in results:
            if isinstance(res, tuple):
                metric, value = res
                result_data[metric] = value
                if isinstance(value, str):
                    error_messages.append(f"{metric}: {value}")
            elif isinstance(res, Exception):
                logger.warning(f"获取指标异常: {res}")
        
        # 如果有错误，在输出中显示
        lines = [f"📊 **服务器 {server_id} 实时数据**"]
        if error_messages:
            lines.append("⚠️ 部分指标获取失败:")
            lines.extend(f"  - {msg}" for msg in error_messages)
            lines.append("")
        
        # 只显示成功获取的数值指标
        numeric_metrics = ["cpu", "memory", "disk", "net_in_speed", "net_out_speed", "tcp_conn", "process_count"]
        for metric in numeric_metrics:
            value = result_data.get(metric, 0)
            if not isinstance(value, str):
                if metric in ["net_in_speed", "net_out_speed"]:
                    lines.append(f"{self._format_metric_label(metric)}: {self._format_bytes(value)}")
                else:
                    lines.append(f"{self._format_metric_label(metric)}: {value}%")
        
        return "\n".join(lines)

    def _format_metric_label(self, metric: str) -> str:
        """格式化指标名称"""
        labels = {
            "cpu": "CPU",
            "memory": "内存",
            "disk": "磁盘",
            "net_in_speed": "入站",
            "net_out_speed": "出站",
            "tcp_conn": "TCP连接",
            "process_count": "进程数"
        }
        return labels.get(metric, metric)

    @filter.llm_tool(
        name="nezha_get_notification_groups",
        description="获取所有通知组列表"
    )
    async def llm_get_notification_groups(self) -> str:
        result = await self._make_request("GET", "/api/v1/notification-group")
        if result and "error" not in result:
            notifications = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(notifications, list):
                if not notifications:
                    return "📭 暂无通知组配置"
                lines = ["📢 **通知组列表**"]
                for ntf in notifications:
                    lines.append(f"- {ntf.get('name', '未命名')} (类型: {ntf.get('type', 'N/A')}, 启用: {'✅' if ntf.get('enabled') else '❌'})")
                return "\n".join(lines)
            return "获取通知组失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取通知组失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_config",
        description="获取指定服务器的配置信息"
    )
    async def llm_get_server_config(self, server_id: str) -> str:
        result = await self._make_request("GET", f"/api/v1/server/config/{server_id}")
        if result and "error" not in result:
            config = result.get("data", {}) if isinstance(result, dict) else result
            lines = [
                f"⚙️ **服务器 {server_id} 配置**",
                f"通知组: {config.get('notification_group_id', '未配置')}",
                f"启用状态: {'✅' if config.get('enabled') else '❌'}",
            ]
            return "\n".join(lines)
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器配置失败: {error_msg}"

    async def terminate(self):
        logger.info("哪吒探针插件已卸载")
