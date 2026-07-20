# Cloudflare Tunnel 配置指南（钉钉 OA 回调）

> 目标：让钉钉 OA 平台可以通过 `https://archery-oa.your-domain.com/dingtalk/oa/callback`
> 回调到内网服务器 `172.20.2.134`，全程 HTTPS，但本地不需要 SSL 证书。

## 1. 为什么需要 Cloudflare Tunnel

| 问题 | 钉钉 OA 平台硬要求 |
|------|-------------------|
| 钉钉回调 URL | **必须 HTTPS**（HTTP 会被拒）|
| 172.20.2.134 | 没 SSL 证书、没公网 443、办公网 NAT 后 |
| Cloudflare Tunnel 解决方案 | cloudflared 主动 outbound → 边缘自动 HTTPS → Tunnel 回到内网 |

数据流：

```
钉钉 OA 平台
  │
  │ HTTPS POST
  ▼
Cloudflare 边缘节点（自动证书）
  │
  │ 加密隧道（outbound，cloudflared 主动建连）
  ▼
172.20.2.134:cloudflared 进程
  │
  │ HTTP 127.0.0.1:80
  ▼
nginx → /dingtalk/oa/callback
  │
  ▼
gunicorn (archery-prod:9003)
  │
  ▼
Archery 钉钉 OA 视图
```

**关键优势**：

- 不需要本地 SSL 证书
- 不需要公网 IP / 端口转发
- 不需要改防火墙（cloudflared 主动 outbound 即可）
- 钉钉后台只配置一个 HTTPS URL

## 2. 前置条件

| 条件 | 说明 |
|------|------|
| 域名 | 你必须有一个**可控**的域名（例：`your-company.com`），且 NS 已切到 Cloudflare |
| Cloudflare 账号 | 免费版即可（[dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up)）|
| 服务器访问 | root 权限的 `172.20.2.134`（cloudflared 安装 + 配置文件）|
| 网络出口 | 服务器能访问 `github.com`（下载 cloudflared）和 Cloudflare 边缘（outbound）|

**关于"NS 已切到 Cloudflare"**：

只有当你的域名 NS 记录是 Cloudflare 提供的（例如 `ada.ns.cloudflare.com`）时，Cloudflare 才能管理该域名的 DNS 解析，并签发 HTTPS 证书。**没切 NS = 走不通**。

## 3. 配置步骤（7 步）

### 步骤 1：登录 Cloudflare

```bash
# 在 172.20.2.134 上以 root 执行
cloudflared tunnel login
```

会输出一个 `https://...` 的 URL，**复制到浏览器打开**：

1. 选择要使用的域名（你的 `your-domain.com`）
2. 点击 "Authorize"
3. 浏览器会显示成功页面

完成后 `/root/.cloudflared/cert.pem` 就有了授权证书。

### 步骤 2：创建 Tunnel

```bash
cloudflared tunnel create archery-oa
```

输出：

```
Tunnel credentials written to /root/.cloudflared/<TUNNEL_ID>.json
Created tunnel archery-oa with id a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

**记下 `<TUNNEL_ID>`**（一个 UUID），后面要用。

### 步骤 3：把凭据移到 /etc/cloudflared/

> systemd service 默认用 `User=root`，所以凭据放 `/root/.cloudflared/` 也能跑。
> 但放到 `/etc/cloudflared/` 更规范（脱离用户 home，便于备份）。

```bash
sudo mkdir -p /etc/cloudflared
sudo cp /root/.cloudflared/<TUNNEL_ID>.json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/<TUNNEL_ID>.json
```

### 步骤 4：写 config.yml

```bash
sudo tee /etc/cloudflared/config.yml <<'EOF'
# Tunnel 标识（在 Cloudflare 控制台可见）
tunnel: a1b2c3d4-e5f6-7890-abcd-ef1234567890

# 凭据文件路径
credentials-file: /etc/cloudflared/a1b2c3d4-e5f6-7890-abcd-ef1234567890.json

# 入口规则：哪个域名 → 转发到哪个本地服务
ingress:
  # 钉钉 OA 回调：所有路径都转发到本机 nginx（80 端口）
  - hostname: archery-oa.your-domain.com
    service: http://127.0.0.1:80
    originRequest:
      noTLSVerify: false
      connectTimeout: 30s
      keepAliveConnections: 100
      keepAliveTimeout: 90s

  # 兜底：未匹配的主机名返回 404
  # 必须放最后一条
  - service: http_status:404
EOF
```

**注意**：

- `tunnel:` 后是 Tunnel ID（不是名字）
- `credentials-file:` 后是绝对路径
- `hostname:` 是你要给钉钉用的子域名（必须是你可控的域）
- `service:` 是 Tunnel 把请求转到的本地地址
- `ingress` 最后一条必须是 `- service: http_status:404`（兜底）

### 步骤 5：DNS 路由

```bash
cloudflared tunnel route dns archery-oa archery-oa.your-domain.com
```

这条命令会**自动在 Cloudflare DNS 添加一条 CNAME 记录**：

```
archery-oa  IN  CNAME  <TUNNEL_ID>.cfargotunnel.com
```

可以到 Cloudflare Dashboard → DNS → Records 验证。

### 步骤 6：部署 systemd 单元

```bash
# 复制 service 文件
sudo cp scripts/deploy/systemd/cloudflared.service /etc/systemd/system/

# 重新加载
sudo systemctl daemon-reload

# 启用并启动
sudo systemctl enable --now cloudflared.service

# 看状态
sudo systemctl status cloudflared.service
sudo journalctl -u cloudflared.service -f
```

**期望看到**：

```
● cloudflared.service - Cloudflare Tunnel for Archery DingTalk OA Callback
   Loaded: loaded (/etc/systemd/system/cloudflared.service; enabled)
   Active: active (running) since ...
```

如果 `Active: failed`，看 journalctl 找原因（最常见是 config.yml 路径错或 credentials-file 路径错）。

### 步骤 7：验证 + 钉钉后台配置

#### 7.1 本地验证

```bash
# 在 172.20.2.134 上，测试本地 nginx 是否响应回调路径
curl -fsS http://127.0.0.1:dingtalk/oa/callback -X POST -d "{}" -i
# 期望：403 Forbidden（因为钉钉回调有签名校验，空 body 必然被拒）
# 注意：不要期望 200，403 是正常响应
```

#### 7.2 Tunnel 验证

```bash
# 测试 Tunnel 自身
cloudflared tunnel info archery-oa

# 看 Tunnel 是否正常建立连接
cloudflared tunnel run archery-oa   # 前台跑，看日志；Ctrl+C 退出
```

#### 7.3 Cloudflare 边缘验证

```bash
# 从任意能上网的机器测
curl -fsS https://archery-oa.your-domain.com/dingtalk/oa/callback -X POST -d "{}" -i -k
# 期望：经过 Tunnel 回到 172.20.2.134，最终 403
```

如果 `curl: (6) Could not resolve host` → DNS 没生效
如果 `521 Web server is down` → 本地 nginx 没起 / 端口错
如果 `523 Origin Is Unreachable` → Tunnel 没建连，看 journalctl

#### 7.4 钉钉后台配置

1. 登录 [钉钉开放平台](https://open-dev.dingtalk.com/)
2. 进入你的应用 → **事件订阅**
3. 填写：
   - **请求 URL**：`https://archery-oa.your-domain.com/dingtalk/oa/callback`
   - **加密方式**：选 **AES 加密 + SHA1 签名**（推荐）或 **加签**
4. 钉钉会显示 **Token** 和 **AES Key**（或 **AppSecret**）
5. 把这两个值加到服务器 `/opt/archery/prod/.env`：

```bash
DINGTALK_OA_CALLBACK_TOKEN=你的Token
DINGTALK_OA_CALLBACK_AES_KEY=你的AES Key
DINGTALK_OA_CALLBACK_CORP_ID=你的CorpID
```

6. 重启 Archery 让 .env 生效：

```bash
sudo systemctl restart archery-prod-gunicorn.service
```

7. 钉钉后台点 "保存" / "测试连接" → 应返回成功

## 4. 完整 config.yml 示例（含生产级配置）

```yaml
# === 必填 ===
tunnel: a1b2c3d4-e5f6-7890-abcd-ef1234567890
credentials-file: /etc/cloudflared/a1b2c3d4-e5f6-7890-abcd-ef1234567890.json

# === 可选：日志（默认 stderr 即可；journald 会收）===
logfile: /var/log/cloudflared/cloudflared.log
loglevel: info   # debug | info | warn | error

# === 入口规则 ===
ingress:
  - hostname: archery-oa.your-domain.com
    service: http://127.0.0.1:80
    originRequest:
      # 关闭 HTTP/2，钉钉回调客户端很多不支持
      http2Origin: false
      # 不验证本地服务 TLS（我们走 HTTP，不需要）
      noTLSVerify: false
      # 30s 连接超时（钉钉回调通常 < 5s）
      connectTimeout: 30s
      # 100 个 keep-alive 连接池
      keepAliveConnections: 100
      keepAliveTimeout: 90s
      # 给后端 nginx 最多 100s 处理时间（钉钉期望 5s 内，但留余地）
      tlsTimeout: 100s
      # 透传原始 Host / IP
      httpHostHeader: archery-oa.your-domain.com

  # 兜底：必须放最后
  - service: http_status:404
```

## 5. 故障排查

### 5.1 systemd 状态异常

```bash
# 看启动失败原因
sudo systemctl status cloudflared.service
sudo journalctl -u cloudflared.service -n 100 --no-pager

# 手动前台跑，看实时日志
sudo systemctl stop cloudflared.service
sudo cloudflared tunnel run archery-oa

# 常见错误：
#   "no such file or directory" → config.yml 路径错
#   "could not read credentials" → credentials-file 路径或权限错
#   "tunnel not found"          → tunnel ID 写错 / 凭据不对应
```

### 5.2 Tunnel 已起但请求不通

```bash
# 1. 看 Tunnel 自身状态
cloudflared tunnel info archery-oa
# 期望：列出一堆 active connections

# 2. 测试本地服务
curl -fsS http://127.0.0.1:80/dingtalk/oa/callback -X POST -d "{}" -i
# 期望：403 或 200（取决于 Archery 实现）
# 如果 connection refused → nginx 没起 / 端口错

# 3. 看 nginx access log 是否收到请求
sudo tail -f /var/log/nginx/access.log
# 在 4G/家庭网络下用 https://archery-oa.your-domain.com 触发回调
# 期望：access log 出现 POST /dingtalk/oa/callback 记录（remote_addr=127.0.0.1）

# 4. 看 cloudflared 收到请求了吗
sudo journalctl -u cloudflared.service -f
# 触发回调，应该看到请求转发日志
```

### 5.3 DNS 解析错误

```bash
# 检查 CNAME 记录
dig archery-oa.your-domain.com +short
# 期望：<TUNNEL_ID>.cfargotunnel.com.

# 如果没记录，重新跑：
cloudflared tunnel route dns archery-oa archery-oa.your-domain.com
```

### 5.4 钉钉后台 "测试连接" 失败

```bash
# 1. 钉钉 → Archery 这条链路：journalctl 看 Archery 收到请求了吗
sudo journalctl -u archery-prod-gunicorn.service -f
# 触发"测试连接"，看是否出现 "dingtalk callback" 相关日志

# 2. 检查 .env 里 DINGTALK_OA_CALLBACK_TOKEN / AES_KEY 是否填对
sudo cat /opt/archery/prod/.env | grep DINGTALK_OA
# 重启 gunicorn 让 .env 生效：
sudo systemctl restart archery-prod-gunicorn.service

# 3. 看钉钉 OA 事件处理日志
mysql -h 172.20.2.134 -u ${MYSQL_USER} -p -e "
    SELECT id, event_type, processed, error_message, created_at
    FROM ext_dingtalk_oa_event_log
    ORDER BY created_at DESC LIMIT 10;
"
```

### 5.5 完全重建 Tunnel

```bash
# 删除
cloudflared tunnel delete archery-oa
sudo rm -f /etc/cloudflared/<TUNNEL_ID>.json
sudo rm -f /etc/cloudflared/config.yml

# 重新创建
cloudflared tunnel create archery-oa
# 记下新的 TUNNEL_ID
sudo cp /root/.cloudflared/<新TUNNEL_ID>.json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/<新TUNNEL_ID>.json

# 重新配置 config.yml（新 TUNNEL_ID）
sudo tee /etc/cloudflared/config.yml <<EOF
tunnel: <新TUNNEL_ID>
credentials-file: /etc/cloudflared/<新TUNNEL_ID>.json
ingress:
  - hostname: archery-oa.your-domain.com
    service: http://127.0.0.1:80
  - service: http_status:404
EOF

# 重新配 DNS（会更新 CNAME）
cloudflared tunnel route dns archery-oa archery-oa.your-domain.com

# 重启
sudo systemctl restart cloudflared.service
```

## 6. 安全注意事项

| 项目 | 说明 |
|------|------|
| **Tunnel 凭据泄露** | 拿到 `<TUNNEL_ID>.json` = 拿到你的内网入口，立刻 `cloudflared tunnel delete` 重建 |
| **不要公网开 443** | Tunnel 通过 outbound 工作，开 443 反而引入风险 |
| **不要在 Tunnel 暴露所有端口** | `service:` 只能写 `http://127.0.0.1:80`，由 nginx 决定哪些路径可达 |
| **nginx 白名单** | `/dingtalk/oa/callback` 限制 `allow 127.0.0.1; deny all;`，不让外网直接打 nginx |
| **Cloudflare Access**（可选）| 想要更严，可以在 Cloudflare 控制台给 Tunnel 加 Access 策略（需要 JWT）|

## 7. 关联文件

- `scripts/deploy/systemd/cloudflared.service` —— systemd 单元（已实现）
- `scripts/deploy/01_init_server.sh` —— 安装 cloudflared 二进制（已实现）
- `docs/designs/2026-07-20_devops-cicd.md` §5.6 —— 设计依据
- `docs/designs/2026-07-20_dingtalk-oa-workflow.md` —— 钉钉 OA 联动设计
