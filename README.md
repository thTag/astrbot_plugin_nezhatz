# 哪吒探针插件 (astrbot_plugin_nezhatz)

为 AstrBot 框架开发的哪吒监控面板查询插件，通过聊天指令快速查看服务器状态。

> ⚠️ **早期开发状态**：本插件目前处于早期开发阶段，功能仍在完善中。欢迎提交 Issue 和 PR 来帮助改进！

---

## 📦 功能

| 指令 | 说明 |
|------|------|
| `/nezha status` | 生成服务器状态概览图（CPU、内存、磁盘使用率） |
| `/nezha list` | 文字版服务器列表，显示名称、状态、CPU 负载 |
| `/nezha detail <ID>` | 查看单台服务器完整信息（CPU、内存、磁盘、流量、负载、运行时间） |

> 📌 **后续计划**：后续版本将支持更多功能和自定义选项。

---

## ⚙️ 前置要求

### 哪吒面板配置

本插件依赖哪吒面板的 **API 接口** 获取数据。请确保：

1. 在哪吒面板的 **系统设置** 中启用 **"启用 MCP 接入"**（默认关闭）。
   > 启用前请确认已审阅 API 令牌 scope 与服务器白名单，确保安全。

2. 获取有效的 **API Token**，并确认其具有访问服务器信息的权限。

### 插件依赖

- `httpx>=0.25.0`
- `python-dateutil>=2.8.2`

---

## 🔧 配置项说明

| 配置项 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `base_url` | string | ✅ | `""` | 哪吒面板访问地址，如 `https://nezha.example.com:8008` |
| `api_token` | string | ✅ | `""` | 面板 API Token，在面板后台生成 |
| `admin_token` | string | ❌ | `""` | 管理员 Token，用于调用部分需要管理员权限的接口（非必填） |
| `verify_ssl` | bool | ❌ | `true` | 是否验证 SSL 证书。如面板使用自签名证书且连接出错，可关闭验证 |
| `request_timeout` | float | ❌ | `30.0` | API 请求超时时间（秒），网络较慢时可适当增大，最小值 1.0 |
| `cache_ttl_seconds` | float | ❌ | `30.0` | 服务器列表缓存有效期（秒），数值越小数据越实时但 API 请求越频繁，最小值 1.0 |
| `max_keepalive_connections` | int | ❌ | `20` | HTTP 连接池保持的最大空闲连接数，保持长连接复用以减少握手开销，最小值 1 |
| `max_connections` | int | ❌ | `50` | HTTP 连接池最大并发连接数，同时请求多个服务器时的并发限制，最小值 1 |

---

## 🔒 安全提醒

> **请务必注意以下安全事项：**

1. **API Token 安全**：`api_token` 是明文存储在 AstrBot 配置文件中的，请妥善保管相关配置文件，避免泄露。
2. **插件行为**：本插件**不会主动输出或暴露您的 API Token**，但在调试日志中可能包含脱敏后的 Token 预览（仅显示前4位）。
3. **网络传输**：建议启用 HTTPS 并开启 `verify_ssl`，避免 API Token 在网络传输中被窃取。
4. **面板配置**：启用 MCP 接入前，请仔细审阅 API 令牌的 scope 范围及服务器白名单设置，遵循最小权限原则。

---

## 📥 安装

### 插件商店（推荐）

AstrBot 管理面板 → 插件商店 → 搜索「哪吒探针」→ 安装

### 手动安装

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/thTag/astrbot_plugin_nezhatz
cd astrbot_plugin_nezhatz
pip install -r requirements.txt
```

安装后在管理面板加载插件，填写 `base_url` 和 `api_token` 即可使用。

---

## ❓ 常见问题

### Q: 认证失败 / API Token 错误

- 检查 `api_token` 是否正确，可在哪吒面板后台重新生成
- 确认哪吒面板的 **MCP 接入** 已开启
- 检查 API Token 的 scope 是否包含服务器读取权限

### Q: 图片生成失败

- 确认模板文件 `model/sysinfo.html` 存在
- 检查 AstrBot 日志中的详细错误
- 确认 HTML 渲染环境是否正常

### Q: 数据不更新 / 显示旧数据

- 默认缓存 30 秒，可调整 `cache_ttl_seconds` 配置
- 如需立即刷新，可等待缓存过期后重试

### Q: 无法连接到面板

- 检查 `base_url` 是否正确（注意端口号）
- 确认面板服务是否正常运行
- 检查网络连通性和防火墙设置

### Q: `/nezha status` 图片无法生成

本插件依赖 AstrBot 的 **T2I（文本转图像）** 服务来渲染状态图片。如遇图片生成失败，请检查：

- AstrBot 的 T2I 服务是否正常运行（配置路径：**设置 → 外观 → 文本转图像**）
- T2I 服务对应的后端（如 Playwright、浏览器等）是否可用
- 查看 AstrBot 日志中的详细错误信息

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

目前插件处于早期阶段，以下方向尤其需要帮助：

- 新增更多查询指令和展示方式
- 支持自定义监控指标
- 优化图片渲染效果
- 多面板支持

提交 PR 前请确保代码风格与项目一致，并经过充分测试。

---

## 📄 License

MIT
