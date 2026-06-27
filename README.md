# 哪吒探针插件 (astrbot_plugin_nezhatz)

为 AstrBot 框架开发的哪吒监控面板查询插件，通过指令快速查看服务器状态。

---

## 功能

| 指令 | 说明 |
|------|------|
| `/nezha status` | 生成服务器状态概览图（CPU、内存、磁盘使用率） |
| `/nezha list` | 文字版服务器列表，显示名称、状态、CPU 负载 |
| `/nezha detail <ID>` | 查看单台服务器完整信息（CPU、内存、磁盘、流量、负载、运行时间） |

---

## 配置

| 配置项 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `base_url` | ✅ | - | 哪吒面板地址，如 `https://nezha.example.com:8008` |
| `api_token` | ✅ | - | 面板 API Token |
| `verify_ssl` | ❌ | `true` | 是否验证 SSL 证书 |
| `request_timeout` | ❌ | `30.0` | API 请求超时时间（秒） |
| `cache_ttl_seconds` | ❌ | `30.0` | 数据缓存时间（秒） |

---

## 安装

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

## 依赖

```
httpx>=0.25.0
python-dateutil>=2.8.2
```

---

## 常见问题

### 认证失败
检查 `api_token` 是否正确，可在哪吒面板后台重新生成。

### 图片生成失败
- 确认模板文件 `model/sysinfo.html` 存在
- 检查 AstrBot 日志中的详细错误

### 数据不更新
默认缓存 30 秒，可调整 `cache_ttl_seconds` 配置。

---

## License

MIT
