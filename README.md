哪吒探针插件 (astrbot_plugin_nezhatz)
====================================

作者：叹号大帝

为 AstrBot 提供的哪吒监控面板查询插件，支持指令和 LLM Tools 调用。


功能特性
--------

- 查看服务器状态 - 生成精美的状态概览图片，包含所有服务器的在线状态和资源使用率
- 查看服务器列表 - 文字版服务器列表，包含名称、状态和 CPU 使用率
- 查看服务器详情 - 查看指定服务器的完整信息（CPU、内存、磁盘、流量、负载、运行时间等）
- LLM Tools 支持 - 可被 AstrBot 的 Agent 系统调用，实现智能问答
- WebUI 配置 - 支持在 AstrBot 管理面板中可视化配置


指令说明
--------

/nezha status    生成服务器状态概览图片（推荐）
/nezha list      列出所有服务器
/nezha detail 1  查看 ID 为 1 的服务器详情


状态图片预览
------------

生成的状态图片包含以下信息：
- 顶部：服务器总计数量、在线/离线数量
- 列表：每台服务器的国旗、名称、操作系统图标、CPU/内存/磁盘使用率、在线状态
- 底部：数据更新时间


LLM Tools 列表
--------------

nezha_list_servers           获取所有服务器列表和基本状态信息
nezha_get_server_detail      获取指定服务器的详细信息
nezha_get_server_data        获取服务器的实时数据指标
nezha_server_status_summary  获取所有服务器的状态概览
nezha_get_notification_groups 获取通知组列表
nezha_get_server_config      获取指定服务器的配置信息


安装方法
--------

方法一：通过 AstrBot WebUI 安装（推荐）
1. 打开 AstrBot 管理面板
2. 进入「插件管理」->「插件市场」
3. 搜索 astrbot_plugin_nezhatz
4. 点击「安装」

方法二：手动安装
1. 进入 AstrBot 的 data/plugins 目录
2. git clone https://github.com/thTag/astrbot_plugin_nezhatz.git
3. 重启 AstrBot


配置说明
--------

在 WebUI 中配置（「插件管理」->「哪吒探针」->「配置」）：

base_url      哪吒监控面板地址，如 https://nezha.example.com:8008
api_token     哪吒监控 API Token（PAT，以 nzp_ 开头）
admin_token   管理员 Token（可选，用于调用管理接口）
verify_ssl    是否验证 SSL 证书（自签名证书可关闭）

TODO
---

[ ] 打算 1:1 还原 nezha-dash 但这非常困难, 我们暂时只能使用 HTML

[ ] 适配更多功能, 如 服务 、 详细信息 等

[ ] 目前有 LLM Tools 调用的能力 (后续可能会移除), 哪吒官方提供了 MCP 接口, 因此建议使用官方 MCP


文件结构
--------

astrbot_plugin_nezhatz/

├── main.py               插件主文件

├── model/

│   └── sysinfo.html      状态图片 HTML 模板

├── _conf_schema.json     配置定义文件

├── metadata.yaml         插件元数据

├── requirements.txt      依赖列表

└── README.md             本文档


依赖
----

httpx >= 0.25.0
python-dateutil >= 2.8.2

（一般情况下会自动安装）


许可证
------

MIT License


问题反馈
--------

如有问题请提交 Issue 或联系作者。
