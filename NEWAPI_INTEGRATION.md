# Genius Art 2API → new-api-Max 渠道对接指南

> **仓库**: https://github.com/lza6/Genius_Art-APP-2api
> **任务**: 把 Genius Art (gen-ai.amobear.com) t2i 接入 new-api-Max 作为渠道
> **给执行会话**: 本文档自包含，按步骤做即可，不需要逆向知识。

---

## 1. 前置：demo server 必须先跑起来

demo server 是协议转换层（加密走模拟器内 native 库），new-api 只跟它通信。

### 1.1 环境要求（已就绪，仅供了解）
- Windows 宿主机，模拟器 `emulator-5570`（openchat AVD，arm64 转译）
- App 已装：`com.aiart.artgenerator.photoeditor.aiimage`（D:/apk-analysis/genius-art/genius-art.apk）
- frida-server `fs16` 已在模拟器内运行
- 工作目录：`D:/apk-analysis/genius-art/`

### 1.2 启动 demo server

```powershell
cd D:\apk-analysis\genius-art

# 若 App/模拟器状态不明，先自愈：
python heal.py emulator-5570

# 启动（后台）：
Start-Process -WindowStyle Hidden python -ArgumentList "demo_server.py","emulator-5570","8907"
# 日志: demo_out.log
```

### 1.3 验证 demo server 存活

```powershell
# 健康检查（返回 {"status":"ok","pool":N} 即正常）
curl http://127.0.0.1:8907/health

# 真实出图测试（30 秒内返回 URL）：
curl http://127.0.0.1:8907/v1/images/generations `
  -H "Authorization: Bearer sk-geniusart-demo" `
  -H "Content-Type: application/json" `
  -d '{\"prompt\":\"a cat in ghibli style\"}'
```

**返回 200 + data[0].url = demo 正常，进行第 2 步。**
失败排查见第 5 节。

---

## 2. new-api 渠道配置

在 new-api-Max 管理后台 → 渠道 → 添加渠道：

| 配置项 | 值 |
|---|---|
| 类型 | **OpenAI** |
| 名称 | `genius-art-t2i` |
| Base URL | `http://127.0.0.1:8907`（同机）或 `http://<局域网IP>:8907` |
| 密钥 | `sk-geniusart-demo` |
| 模型 | 手动输入：`genius-art` |
| 模型重定向 | 无需 |
| 状态 | 启用 |

### 2.1 模型倍率设置

策略 → 运营/倍率设置，给 `genius-art` 配置：
- **模型倍率**: 建议按时间成本定价（单图 8~34s），可参考同站其它 t2i 模型
- **补全倍率**: 1（不适用，纯图片模型）

### 2.2 令牌可用性测试

用你的 new-api 用户令牌直接调：

```powershell
curl http://<new-api地址>/v1/images/generations `
  -H "Authorization: Bearer sk-你的new-api令牌" `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"genius-art\",\"prompt\":\"a dragon over tokyo\",\"n\":1}'
```

预期：200 + data[0].url（GCS 签名链接，15 分钟有效）。

---

## 3. 协议要点（给 new-api 侧排查用）

- **请求**: OpenAI `/v1/images/generations` 标准；`n` 最多 4；`tier` 可选 1/2/3（默认 1，无实际差异）
- **响应**: `{"created":..., "data":[{"url":"..."}]}` — **只有 URL，没有 b64**。若你的前端需要 b64，需在 demo_server 加下载转 b64 功能（可让执行会话加：读 url → base64 → 填 `b64_json`）
- **耗时**: 单图 8~34s；**new-api 渠道超时建议 ≥60s**（渠道设置里如有超时项调大）
- **内容过滤**: 上游敏感词拦截返回 410，demo 透传为 502 + 上游 message，new-api 显示为渠道错误属正常
- **并发**: 已压测 4 并发稳定；同 device 10 并发无配额限制；**勿开 >8 并发**（加密桥是单线程锁）

## 4. 已知限制

| 项 | 说明 |
|---|---|
| 模拟器依赖 | 加密走模拟器内 libamg.so。模拟器崩溃需手动重启 + `python heal.py emulator-5570` |
| 单点 | demo server 单实例；号池无需管理（get-token 每次自动随机新 device_id） |
| 纯文生图 | 其它端点（enhance/remove-bg/ghibli 等 v5/tools/*）协议相同，demo 未暴露，需要时扩展 demo_server.py |

## 5. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| demo health 404/拒连 | 进程没起 | `python heal.py emulator-5570` 后重启 demo_server |
| demo 日志 `app not running` | App 被杀/卸载 | heal.py 自动装；若失败手动 `adb install -r -t genius-art.apk` |
| demo 日志 `Java API not available` | frida 连接时 App 还没起来 | 等 20s 重试，或重启 App 后再起 demo |
| 上游 401 | JWT 过期（14天）| 不可能——demo 每次新建号池自动刷新 |
| 上游 IPv6 超时 | 模拟器直连 IPv6 被墙 | 已在 heal.py 里设置模拟器代理 `10.0.2.2:10808`，确认宿主机 10808 代理存活 |
| 图片 URL 打不开 | GCS 签名 15 分钟过期 | 正常，及时转存 |

## 6. 参考文件（都在 D:/apk-analysis/genius-art/ 和 GitHub 仓库）

- `demo_server.py` — 主服务
- `heal.py` — 自愈脚本
- `rpc_script.js` — frida 加密桥
- `CRYPTO_ANALYSIS.md` — libamg.so 静态分析（离线化路线，未来去掉模拟器依赖用）
- `stress_summary.json` — 压测 R1 结论

---

*生成: 2026-10-28 · 交付会话: Genius Art 逆向 · 仓库 commit 455037d*

---

## 附录 A：并发实测（2026-10-28 补测）

| 并发 | 结果 | Wall | p50 | 备注 |
|---|---|---|---|---|
| 4 | 4/4 | 18.3s | 13.9s | — |
| 8 | 8/8 | 38.1s | 22.0s | 干净 prompt |
| 8 | 8/8 | 33.1s | 21.3s | 复测 |
| 上游直压 10（同 device） | 10×201 | 22.0s | — | 无配额限制 |

**建议 new-api 侧并发上限 8**（瓶颈是上游生成 8~34s，不是加密桥）。

⚠️ **重要修复**：demo_server 早期用单线程 `HTTPServer`，8 并发会出现 `连接被拒绝(10061)`
（队列溢出，非上游问题）。已改 `ThreadingHTTPServer`，务必使用当前版本。

## 附录 B：模型 / 端点清单

### 已开放（demo 内 `genius-art`）
- `POST /v5/tools/prompt-to-image` — 自由文生图，同步 201 返回 GCS URL，512×512

### 同协议未开放（需扩展 demo_server.py）

| 端点 | 功能 | 必需字段 |
|---|---|---|
| `predict-art` | **AI Art 风格模板生图**（1553 个风格：52 组=生肖/纹身/海盗/狼人/漫画/圣诞… + 100 种职业人像）| style, skin_color(0-3), num_image("1"), original_name([]) → 返回 `_id` 异步 |
| `enhance-image` | 画质增强 | original_name(图片) |
| `remove-background` | 抠图 | original_name(图片) |
| `remove-object-auto-detect` | 自动去物 | original_name |
| `remove-object-manual` | 手绘去物 | original_name |
| `change-color` | 换色 | original_name, type_color |
| `cartoon-3d` | 3D 卡通化 | original_name, style, is_change_bg… |
| `image-to-ghibli` | 图生吉卜力 | original_name, strength |

除 prompt-to-image / predict-art 外均需**先上传图片**（对应 `*/upload-image-status` 端点，multipart 流程未还原）。

### 内容过滤（重要）
上游 prompt 审核严格且难预测，实测：
- ❌ `grass`（大麻联想）→ 410 `"The photo you choose contains sensitive content"`
- ❌ `a cat sitting on grass`、`a cat on grass` → 410
- ✅ `a cat`、`a dog sitting`、`a cat in ghibli style` → 正常出图

410 也会偶发（同一干净 prompt 并发时命中），建议 new-api 侧把 410 当作可重试错误。
