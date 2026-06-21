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
from pathlib import Path

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

    ONLINE_THRESHOLD_SECONDS = 300

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.base_url = self.config.get("base_url", "").rstrip("/")
        self.api_token = self.config.get("api_token", "")
        self.admin_token = self.config.get("admin_token", "")
        self.verify_ssl = self.config.get("verify_ssl", True)
        
        # 模板路径
        self.template_path = Path(__file__).parent / "model" / "sysinfo.html"
        
        logger.info(f"哪吒探针插件已加载，面板地址: {self.base_url}")

    def _load_template(self) -> str:
        """加载 HTML 模板"""
        if not self.template_path.exists():
            logger.error(f"模板文件不存在: {self.template_path}")
            return "<h1>模板加载失败</h1>"
        try:
            with open(self.template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"加载模板失败: {e}")
            return "<h1>模板加载失败</h1>"

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
            logger.debug(f"解析 last_active 失败: {e}")
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

    async def _handle_list(self, event: AstrMessageEvent):
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

    async def _handle_detail(self, event: AstrMessageEvent, server_id: str):
        """文字版详情"""
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                server = next((s for s in servers if str(s.get("id")) == server_id), None)
                if server:
                    state = server.get("state", {})
                    host = server.get("host", {})
                    geoip = server.get("geoip", {})
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

    async def _handle_status(self, event: AstrMessageEvent):
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
                    
                    geoip = svr.get("geoip", {})
                    country = geoip.get("country_code", "")
                    flag = self._get_country_flag(country)
                    
                    server_data.append({
                        "name": svr.get("name", "未命名"),
                        "online": self._is_online(svr),
                        "cpu": state.get("cpu", 0),
                        "mem": mem_percent,
                        "flag": flag
                    })
                
                # 加载模板并渲染
                template = self._load_template()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
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
                # 返回图片（当前版本不支持 extra 参数）
                yield event.image_result(image_url)
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
        metrics = ["cpu", "memory", "disk", "net_in_speed", "net_out_speed", "tcp_conn", "process_count"]
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
            f"CPU: {result_data.get('cpu', 0)}%",
            f"内存: {result_data.get('memory', 0)}%",
            f"磁盘: {result_data.get('disk', 0)}%",
            f"入站: {self._format_bytes(result_data.get('net_in_speed', 0))}",
            f"出站: {self._format_bytes(result_data.get('net_out_speed', 0))}",
            f"TCP: {result_data.get('tcp_conn', 0)}",
            f"进程: {result_data.get('process_count', 0)}",
        ]
        return "\n".join(lines)

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
