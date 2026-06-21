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
        if not servers:
            return "暂无服务器信息"
        
        lines = ["📊 **服务器列表**"]
        lines.append("")
        for svr in servers:
            name = svr.get("name", "未命名")
            server_id = svr.get("id", "?")
            status = svr.get("status", "unknown")
            status_icon = "🟢" if status == "online" else "🔴"
            cpu = svr.get("cpu", 0)
            mem = svr.get("memory", 0)
            
            lines.append(f"{status_icon} **{name}** (ID: {server_id})")
            lines.append(f"   CPU: {cpu}%")
            lines.append(f"   内存: {mem}%")
            lines.append("")
        
        return "\n".join(lines)

    def _format_server_detail(self, server: Dict) -> str:
        if not server:
            return "未找到服务器信息"
        
        if "error" in server:
            return f"❌ {server['error']}"
        
        lines = ["📋 **服务器详细信息**"]
        lines.append("")
        lines.append(f"🔹 **名称**: {server.get('name', 'N/A')}")
        lines.append(f"🔹 **ID**: {server.get('id', 'N/A')}")
        lines.append(f"🔹 **状态**: {'🟢 在线' if server.get('status') == 'online' else '🔴 离线'}")
        lines.append(f"🔹 **操作系统**: {server.get('os', 'N/A')}")
        lines.append(f"🔹 **CPU**: {server.get('cpu', 0)}%")
        lines.append(f"🔹 **内存**: {server.get('memory', 0)}%")
        lines.append(f"🔹 **磁盘**: {server.get('disk', 0)}%")
        lines.append(f"🔹 **入站流量**: {self._format_bytes(server.get('net_in', 0))}")
        lines.append(f"🔹 **出站流量**: {self._format_bytes(server.get('net_out', 0))}")
        lines.append(f"🔹 **运行时间**: {server.get('uptime', 'N/A')}")
        
        load = server.get('load', {})
        if load:
            lines.append(f"🔹 **负载**: 1min={load.get('load1', 0)}, 5min={load.get('load5', 0)}, 15min={load.get('load15', 0)}")
        
        return "\n".join(lines)

    def _format_bytes(self, bytes_val: int) -> str:
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.2f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.2f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"

    # ==================== 指令处理器 ====================

    @filter.command("nezha")
    async def nezha_cmd(self, event: AstrMessageEvent):
        """
        查看哪吒监控服务器状态
        用法: /nezha [list|detail <id>|status]
        """
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
        """处理列出所有服务器 - 异步生成器"""
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
        """处理查看服务器详情 - 异步生成器"""
        result = await self._make_request("GET", f"/api/v1/server/{server_id}")
        if result and "error" not in result:
            server = result.get("data", {}) if isinstance(result, dict) else result
            yield event.plain_result(self._format_server_detail(server))
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取服务器详情失败: {error_msg}")

    async def _handle_status(self, event: AstrMessageEvent):
        """处理查看状态概览 - 异步生成器"""
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                total = len(servers)
                online = sum(1 for s in servers if s.get("status") == "online")
                offline = total - online
                
                total_cpu = sum(s.get("cpu", 0) for s in servers)
                total_mem = sum(s.get("memory", 0) for s in servers)
                avg_cpu = total_cpu / total if total > 0 else 0
                avg_mem = total_mem / total if total > 0 else 0
                
                lines = [
                    "📊 **服务器状态概览**",
                    "",
                    f"📌 **总计**: {total} 台",
                    f"🟢 **在线**: {online} 台",
                    f"🔴 **离线**: {offline} 台",
                    "",
                    f"📈 **平均 CPU**: {avg_cpu:.1f}%",
                    f"📈 **平均内存**: {avg_mem:.1f}%",
                    "",
                ]
                
                lines.append("**服务器列表:**")
                for svr in servers:
                    name = svr.get("name", "未命名")
                    status_icon = "🟢" if svr.get("status") == "online" else "🔴"
                    cpu = svr.get("cpu", 0)
                    mem = svr.get("memory", 0)
                    lines.append(f"  {status_icon} {name} - CPU: {cpu}% 内存: {mem}%")
                
                yield event.plain_result("\n".join(lines))
            else:
                yield event.plain_result("❌ 获取状态失败：数据格式异常")
        else:
            error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
            yield event.plain_result(f"❌ 获取状态失败: {error_msg}")

    # ==================== LLM Tools ====================

    @filter.llm_tool(
        name="nezha_list_servers",
        description="获取哪吒监控中所有服务器的列表和基本状态信息（名称、ID、状态、CPU、内存等）"
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
        result = await self._make_request("GET", f"/api/v1/server/{server_id}")
        if result and "error" not in result:
            server = result.get("data", {}) if isinstance(result, dict) else result
            return self._format_server_detail(server)
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取服务器详情失败: {error_msg}"

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
            f"🖥️ **CPU**: {result_data.get('cpu', 0)}%",
            f"🧠 **内存**: {result_data.get('memory', 0)}%",
            f"💾 **磁盘**: {result_data.get('disk', 0)}%",
            f"📥 **入站流量**: {self._format_bytes(result_data.get('net_in_speed', 0))}",
            f"📤 **出站流量**: {self._format_bytes(result_data.get('net_out_speed', 0))}",
            f"🔗 **TCP连接**: {result_data.get('tcp_conn', 0)}",
            f"🔗 **UDP连接**: {result_data.get('udp_conn', 0)}",
            f"📦 **进程数**: {result_data.get('process_count', 0)}",
        ]
        return "\n".join(lines)

    @filter.llm_tool(
        name="nezha_server_status_summary",
        description="获取所有服务器的状态概览，包括总数量、在线数量、离线数量、平均CPU和内存使用率"
    )
    async def llm_server_status_summary(self) -> str:
        result = await self._make_request("GET", "/api/v1/server")
        if result and "error" not in result:
            servers = result.get("data", []) if isinstance(result, dict) else result
            if isinstance(servers, list):
                total = len(servers)
                online = sum(1 for s in servers if s.get("status") == "online")
                offline = total - online
                total_cpu = sum(s.get("cpu", 0) for s in servers)
                total_mem = sum(s.get("memory", 0) for s in servers)
                avg_cpu = total_cpu / total if total > 0 else 0
                avg_mem = total_mem / total if total > 0 else 0
                
                return (
                    f"📊 服务器状态概览\n"
                    f"- 总计: {total} 台\n"
                    f"- 在线: {online} 台\n"
                    f"- 离线: {offline} 台\n"
                    f"- 平均CPU: {avg_cpu:.1f}%\n"
                    f"- 平均内存: {avg_mem:.1f}%"
                )
            return "获取状态失败：数据格式异常"
        error_msg = result.get("error", "未知错误") if result else "无法连接到面板"
        return f"获取状态失败: {error_msg}"

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
                    return "暂无通知组配置"
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
