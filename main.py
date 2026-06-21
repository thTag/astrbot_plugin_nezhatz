"""
哪吒探针插件 (astrbot_plugin_nezhatz)

用于查看哪吒监控站点的服务器状态等信息
支持指令与LLM Tools调用
基于哪吒监控 2.2.6 版本 API

作者: 叹号大帝
"""

import json
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

import httpx
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register


@register(
    "astrbot_plugin_nezhatz",
    "叹号大帝",
    "哪吒探针 - 查看哪吒监控站点服务器状态",
    "1.0.0",
    "https://github.com/thTag/astrbot_plugin_nezhatz"
)
class NezhaPlugin(Star):
    """哪吒探针插件主类"""

    # 在线判断阈值：5分钟内有活动视为在线
    ONLINE_THRESHOLD_SECONDS = 300

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = self.config.get("base_url", "").rstrip("/")
        self.api_token = self.config.get("api_token", "")
        self.admin_token = self.config.get("admin_token", "")
        self.verify_ssl = self.config.get("verify_ssl", True)
        
        logger.info(f"哪吒探针插件已加载，面板地址: {self.base_url}")

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _is_online(self, server: Dict) -> bool:
        """
        判断服务器是否在线。
        基于 last_active 字段，如果最后活动时间在阈值内，视为在线。
        """
        last_active_str = server.get("last_active")
        if not last_active_str:
            return False
        
        try:
            # 尝试解析 ISO 8601 格式的时间字符串
            # 处理可能的时区格式，如 +08:00 或 Z
            from dateutil import parser
            last_time = parser.parse(last_active_str)
            # 获取当前时间，赋予与 last_time 相同的时区信息
            now = datetime.now(last_time.tzinfo)
            diff = now - last_time
            return diff.total_seconds() < self.ONLINE_THRESHOLD_SECONDS
        except ImportError:
            # 如果没有 dateutil，使用简单的字符串判断
            # 这是一个后备方案，不够精确但可以工作
            logger.warning("dateutil 未安装，使用简单时间判断，建议安装 python-dateutil")
            return True  # 保守起见，有值就认为在线
        except Exception as e:
            logger.debug(f"解析 last_active 失败: {e}, 原始值: {last_active_str}")
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
        headers = self._get_headers()
        
        if use_admin and self.admin_token:
            headers["Authorization"] = f"Bearer {self.admin_token}"
        
        try:
            async with httpx.AsyncClient(verify=self.verify_ssl, timeout=30.0) as client:
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

    def _format_server_list(self, servers: List[Dict]) -> str:
        """格式化服务器列表 - 卡片风格"""
        if not servers:
            return "📭 暂无服务器信息"
        
        lines = ["📊 **服务器列表**"]
        lines.append("")
        
        for svr in servers:
            name = svr.get("name", "未命名")
            server_id = svr.get("id", "?")
            is_online = self._is_online(svr)
            status_icon = "🟢" if is_online else "🔴"
            status_text = "在线" if is_online else "离线"
            
            state = svr.get("state", {})
            host = svr.get("host", {})
            cpu = state.get("cpu", 0)
            mem_used = state.get("mem_used", 0)
            mem_total = host.get("mem_total", 0)
            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            
            # 获取地区信息
            geoip = svr.get("geoip", {})
            country = geoip.get("country_code", "")
            flag = self._get_country_flag(country)
            
            lines.append(f"{flag} **{name}**")
            lines.append(f"   {status_icon} {status_text}")
            lines.append(f"   💻 CPU: {cpu:.1f}%")
            lines.append(f"   🧠 内存: {mem_percent:.1f}%")
            lines.append("")
        
        return "\n".join(lines)

    def _format_server_detail(self, server: Dict) -> str:
        """格式化服务器详情 - 卡片风格"""
        if not server:
            return "📭 未找到服务器信息"
        
        if "error" in server:
            return f"❌ {server['error']}"
        
        state = server.get("state", {})
        host = server.get("host", {})
        geoip = server.get("geoip", {})
        ip_info = geoip.get("ip", {})
        
        is_online = self._is_online(server)
        status_icon = "🟢" if is_online else "🔴"
        status_text = "在线" if is_online else "离线"
        
        # 获取 CPU 信息
        cpu_model = host.get("cpu", [])
        if cpu_model and isinstance(cpu_model, list):
            cpu_model = cpu_model[0] if cpu_model else "N/A"
        else:
            cpu_model = "N/A"
        
        country = geoip.get("country_code", "")
        flag = self._get_country_flag(country)
        
        lines = ["📋 **服务器详细信息**"]
        lines.append("")
        lines.append(f"{flag} **名称**: {server.get('name', 'N/A')}")
        lines.append(f"   🆔 ID: {server.get('id', 'N/A')}")
        lines.append(f"   {status_icon} {status_text}")
        lines.append("")
        lines.append("--- **系统信息** ---")
        lines.append(f"   🐧 系统: {host.get('platform', 'N/A')} {host.get('platform_version', '')}")
        lines.append(f"   🏗️ 架构: {host.get('arch', 'N/A')}")
        lines.append(f"   💻 CPU: {cpu_model}")
        lines.append("")
        lines.append("--- **资源使用** ---")
        lines.append(f"   📈 CPU: {state.get('cpu', 0):.1f}%")
        lines.append(f"   🧠 内存: {self._format_bytes(state.get('mem_used', 0))} / {self._format_bytes(host.get('mem_total', 0))}")
        lines.append(f"   💾 磁盘: {self._format_bytes(state.get('disk_used', 0))} / {self._format_bytes(host.get('disk_total', 0))}")
        lines.append("")
        lines.append("--- **网络与进程** ---")
        lines.append(f"   📥 入站: {self._format_bytes(state.get('net_in_transfer', 0))}")
        lines.append(f"   📤 出站: {self._format_bytes(state.get('net_out_transfer', 0))}")
        lines.append(f"   🔗 TCP连接: {state.get('tcp_conn_count', 0)}")
        lines.append(f"   🔗 UDP连接: {state.get('udp_conn_count', 0)}")
        lines.append(f"   📦 进程数: {state.get('process_count', 0)}")
        lines.append("")
        lines.append("--- **负载与运行** ---")
        lines.append(f"   ⏱️ 运行时间: {self._format_uptime(state.get('uptime', 0))}")
        lines.append(f"   📊 负载: {state.get('load_1', 0):.2f} / {state.get('load_5', 0):.2f} / {state.get('load_15', 0):.2f} (1/5/15min)")
        
        if ip_info.get("ipv4_addr"):
            lines.append(f"   🌐 IP: {ip_info.get('ipv4_addr')}")
        
        return "\n".join(lines)

    def _format_status_summary(self, servers: List[Dict]) -> str:
        """格式化状态概览 - 卡片风格"""
        if not servers:
            return "📭 暂无服务器数据"
        
        total = len(servers)
        online = sum(1 for s in servers if self._is_online(s))
        offline = total - online
        
        total_cpu = 0
        total_mem_percent = 0
        total_disk_percent = 0
        valid_servers = 0
        
        for s in servers:
            state = s.get("state", {})
            host = s.get("host", {})
            cpu = state.get("cpu", 0)
            mem_used = state.get("mem_used", 0)
            mem_total = host.get("mem_total", 0)
            mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
            disk_used = state.get("disk_used", 0)
            disk_total = host.get("disk_total", 0)
            disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0
            
            total_cpu += cpu
            total_mem_percent += mem_percent
            total_disk_percent += disk_percent
            valid_servers += 1
        
        avg_cpu = total_cpu / valid_servers if valid_servers > 0 else 0
        avg_mem = total_mem_percent / valid_servers if valid_servers > 0 else 0
        avg_disk = total_disk_percent / valid_servers if valid_servers > 0 else 0
        
        lines = [
            "📊 **服务器状态概览**",
            "",
            f"   📌 总计: **{total}** 台",
            f"   🟢 在线: **{online}** 台",
            f"   🔴 离线: **{offline}** 台",
            "",
            "--- **平均资源使用** ---",
            f"   📈 CPU: **{avg_cpu:.1f}%**",
            f"   🧠 内存: **{avg_mem:.1f}%**",
            f"   💾 磁盘: **{avg_disk:.1f}%**",
            "",
            "--- **服务器列表** ---",
        ]
        
        for svr in servers:
            name = svr.get("name", "未命名")
            is_online = self._is_online(svr)
            status_icon = "🟢" if is_online else "🔴"
            state = svr.get("state", {})
            cpu = state.get("cpu", 0)
            
            geoip = svr.get("geoip", {})
            country = geoip.get("country_code", "")
            flag = self._get_country_flag(country)
            
            lines.append(f"   {flag} {status_icon} {name} - {cpu:.1f}%")
        
        return "\n".join(lines)

    def _get_country_flag(self, country_code: str) -> str:
        """获取国家旗帜 Emoji"""
        flags = {
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
        return flags.get(country_code.lower(), "🌍")

    def _format_bytes(self, bytes_val: int) -> str:
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.2f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.2f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"

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
    async def nezha_cmd(self, event: AstrMessageEvent):
        parts = event.message_str.strip().split()
        
        if len(parts) < 2:
            async for result in self._handle_list(event):
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
                "`/nezha status` - 查看状态概览"
            )

    async def _handle_list(self, event: AstrMessageEvent):
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                yield event.plain_result(self._format_server_list(servers))
            else:
                yield event.plain_result("❌ 获取服务器列表失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取服务器列表失败: {error_msg}")

    async def _handle_detail(self, event: AstrMessageEvent, server_id: str):
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                server = next((s for s in servers if str(s.get("id")) == server_id), None)
                if server:
                    yield event.plain_result(self._format_server_detail(server))
                else:
                    yield event.plain_result(f"❌ 未找到 ID 为 {server_id} 的服务器")
            else:
                yield event.plain_result("❌ 获取服务器详情失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取服务器详情失败: {error_msg}")

    async def _handle_status(self, event: AstrMessageEvent):
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                yield event.plain_result(self._format_status_summary(servers))
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
                return self._format_server_list(servers)
            return "获取服务器列表失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器列表失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_detail",
        description="获取指定服务器的详细信息，包括CPU、内存、磁盘、流量、负载等。参数server_id为服务器ID"
    )
    async def llm_get_server_detail(self, server_id: str) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                server = next((s for s in servers if str(s.get("id")) == server_id), None)
                if server:
                    return self._format_server_detail(server)
                return f"❌ 未找到 ID 为 {server_id} 的服务器"
            return "获取服务器详情失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器详情失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_server_status_summary",
        description="获取所有服务器的状态概览，包括总数量、在线数量、离线数量、平均资源使用率"
    )
    async def llm_server_status_summary(self) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                return self._format_status_summary(servers)
            return "获取状态失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取状态失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_data",
        description="获取服务器的实时数据，包括CPU、内存、磁盘、网络流量、连接数等详细指标。参数server_id为服务器ID"
    )
    async def llm_get_server_data(self, server_id: str) -> str:
        metrics = ["cpu", "memory", "disk", "net_in_speed", "net_out_speed", "tcp_conn", "udp_conn", "process_count"]
        result_data = {}
        
        for metric in metrics:
            result = await self._make_request("GET", f"/api/v1/server/{server_id}/metrics?metric={metric}")
            if result and "error" not in result:
                data = result.get("data", {})
                points = data.get("data_points", [])
                if points:
                    result_data[metric] = points[-1].get("value", 0)
                else:
                    result_data[metric] = 0
            else:
                result_data[metric] = 0
        
        lines = [
            f"📊 **服务器 {server_id} 实时数据**",
            "",
            f"   📈 CPU: {result_data.get('cpu', 0)}%",
            f"   🧠 内存: {result_data.get('memory', 0)}%",
            f"   💾 磁盘: {result_data.get('disk', 0)}%",
            f"   📥 入站: {self._format_bytes(result_data.get('net_in_speed', 0))}",
            f"   📤 出站: {self._format_bytes(result_data.get('net_out_speed', 0))}",
            f"   🔗 TCP: {result_data.get('tcp_conn', 0)}",
            f"   🔗 UDP: {result_data.get('udp_conn', 0)}",
            f"   📦 进程: {result_data.get('process_count', 0)}",
        ]
        return "\n".join(lines)

    @filter.llm_tool(
        name="nezha_get_notification_groups",
        description="获取所有通知组列表和配置信息"
    )
    async def llm_get_notification_groups(self) -> str:
        result = await self._make_request("GET", "/api/v1/notification-group")
        if result and "error" not in result:
            notifications = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(notifications, list):
                if not notifications:
                    return "📭 暂无通知组配置"
                lines = ["📢 **通知组列表**", ""]
                for ntf in notifications:
                    lines.append(f"🔹 **{ntf.get('name', '未命名')}** (ID: {ntf.get('id', '?')})")
                    lines.append(f"   类型: {ntf.get('type', 'N/A')}")
                    lines.append(f"   启用: {'✅' if ntf.get('enabled') else '❌'}")
                    lines.append("")
                return "\n".join(lines)
            return "获取通知组失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取通知组失败: {error_msg}"

    @filter.llm_tool(
        name="nezha_get_server_config",
        description="获取指定服务器的配置信息，包括Agent配置、通知组等。参数server_id为服务器ID"
    )
    async def llm_get_server_config(self, server_id: str) -> str:
        result = await self._make_request("GET", f"/api/v1/server/config/{server_id}")
        if result and "error" not in result:
            config = result.get("data", {}) if isinstance(result, dict) else result
            lines = [
                f"⚙️ **服务器 {server_id} 配置**",
                "",
            ]
            if config.get('secret'):
                lines.append(f"🔹 **Agent密钥**: {config.get('secret')[:20]}...")
            lines.append(f"🔹 **通知组**: {config.get('notification_group_id', '未配置')}")
            lines.append(f"🔹 **启用状态**: {'✅' if config.get('enabled') else '❌'}")
            return "\n".join(lines)
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器配置失败: {error_msg}"

    async def terminate(self):
        logger.info("哪吒探针插件已卸载")
