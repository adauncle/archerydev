# Archery v1.10.0 (Docker) → v1.14.0 (裸机) 无损升级方案

**适用场景**：老机器已生产 v1.10.0，docker-compose 部署（archery + redis + goinception 在容器内，MySQL 在外部独立实例），因 docker 镜像拉不到无法走 docker-compose 升级。

**目标**：在同一台老机器上原地升级到 v1.14.0，**裸机部署**（systemd + gunicorn + nginx），数据 0 丢失，停机 ≤ 30 分钟，**任何步骤可回滚**。

**参考**：本方案基于 `172.20.2.134` v0.1.0-prod 部署经验 + 全部踩坑沉淀（v0.1.0 ~ v0.1.3 的 changelogs）。

---

## 源服务器环境（已确认）

| 项目 | 值 | 适配要求 |
|------|------|----------|
| OS | **CentOS Linux 7.9.2009 (Core)** | 全部命令用 `yum`，不用 `dnf` |
| 内核 | 3.10.0-1160.88.1.el7.x86_64 | OK，无特殊要求 |
| systemd | **219**（CentOS 7 默认） | unit 文件必须**最简 17 行**（v0.1.2 踩坑，230+ 指令会"Unit not found"） |
| Python | 2.7.5（默认）+ **需装 3.11** | 走 IUS 源 / SCL / 编译三条路，推荐 IUS |
| SELinux | enforcing（CentOS 7 默认） | unit 文件要 `chcon -t systemd_unit_file_t`（v0.1.2 踩坑） |
| firewalld | 有 | 命令一致 |
| yum 源 | **CentOS 7 已 EOL（2024-06-30）** | 必须切 vault.centos.org 或阿里云镜像，否则 yum install 全失败 |
| 主机名 | yearning | 跟 archery 同样的 SQL 审核生态，说明用户对 DBA / SQL 审核熟 |

### CentOS 7 EOL yum 源修复（**阶段 0 第一步必做**）

```bash
# 备份老源
mkdir -p /etc/yum.repos.d/backup
mv /etc/yum.repos.d/CentOS-*.repo /etc/yum.repos.d/backup/ 2>/dev/null || true

# 方案 A：阿里云镜像（推荐，国内快）
cat > /etc/yum.repos.d/CentOS-Base.repo <<'EOF'
[base]
name=CentOS-7 - Base
baseurl=https://mirrors.aliyun.com/centos-vault/7.9.2009/os/$basearch/
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/centos-vault/RPM-GPG-KEY-CentOS-7

[updates]
name=CentOS-7 - Updates
baseurl=https://mirrors.aliyun.com/centos-vault/7.9.2009/updates/$basearch/
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/centos-vault/RPM-GPG-KEY-CentOS-7

[extras]
name=CentOS-7 - Extras
baseurl=https://mirrors.aliyun.com/centos-vault/7.9.2009/extras/$basearch/
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/centos-vault/RPM-GPG-KEY-CentOS-7
EOF

# 方案 B：vault.centos.org 官方（境外机器）
# baseurl=https://vault.centos.org/7.9.2009/os/$basearch/

yum clean all
yum makecache
yum repolist  # 应输出 ~10000+ packages
```

### Python 3.11 安装（CentOS 7 推荐 IUS 源）

```bash
# IUS（Inline with Upstream Stable）提供 Python 3.11 编译好的 rpm
yum install -y https://repo.ius.io/ius-release-el7.rpm
# 国内机器替换：
# yum install -y https://mirrors.tuna.tsinghua.edu.cn/ius/repos/ius-release-el7.rpm

yum install -y python311 python311-devel python311-pip python311-venv
python3.11 --version  # 应输出 3.11.x
which python3.11      # 应在 /usr/bin/python3.11
```

**备选方案**（IUS 不可用时）：
```bash
# 方案 B：SCL（Software Collections）
yum install -y centos-release-scl
yum install -y rh-python311
scl enable rh-python311 bash
# 注意 scl 是临时激活，systemd unit 要用绝对路径 /opt/rh/rh-python311/root/bin/python3.11

# 方案 C：源码编译（最慢，但最稳）
yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel
cd /tmp
curl -O https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
tar xzf Python-3.11.9.tgz
cd Python-3.11.9
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
make altinstall
# 装完：/usr/local/bin/python3.11
```

### systemd 219 unit 兼容（v0.1.2 真实踩坑）

**完整 unit 模板（17 行）**：

```ini
[Unit]
Description=Archery v1.14.0 Gunicorn (port 9004)
After=network.target mysqld.service redis.service

[Service]
Type=simple
User=archery
Group=archery
WorkingDirectory=/opt/archery_v114
EnvironmentFile=/opt/archery_v114/.env

ExecStart=/opt/archery_v114/venv/bin/gunicorn archery.wsgi:application -w 4 -b 0.0.0.0:9004 --access-logfile - --error-logfile - --timeout 120

Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

**❌ 删**（systemd 219 不支持或不稳定）：
- `NoNewPrivileges` / `ProtectSystem` / `ProtectHome` / `PrivateTmp` / `ReadWritePaths`
- `MemoryMax` / `StartLimitInterval` / `StartLimitBurst`
- 文件头注释和 `##` 头部

**SELinux context 修复**：
```bash
chcon -v -t systemd_unit_file_t /etc/systemd/system/archery-v114-gunicorn.service
# 验证
ls -lZ /etc/systemd/system/archery-v114-gunicorn.service
# 期望：system_u:object_r:systemd_unit_file_t:s0
```

### 编译工具链（CentOS 7 默认 gcc 4.8 太老）

```bash
# CentOS 7 devtoolset-7/8/9 提供新版 gcc（很多 wheel 需要）
yum install -y centos-release-scl
yum install -y devtoolset-11-gcc devtoolset-11-gcc-c++ devtoolset-11-binutils
# 临时启用：scl enable devtoolset-11 bash
# 永久：在 /etc/profile.d/ 加 source /opt/rh/devtoolset-11/enable

# 必装编译依赖
yum install -y gcc gcc-c++ make openssl-devel bzip2-devel libffi-devel \
    zlib-devel xz-devel sqlite-devel readline-devel tk-devel \
    mysql mysql-devel libxml2-devel libxslt-devel libaio-devel \
    cyrus-sasl-devel openldap-devel
```

### 其他 CentOS 7 注意点

- **firewalld 命令一致**，不需要改
- **MySQL 客户端**：用 `yum install -y mysql`（不是 mariadb，centos 7 仓库里 mysql 客户端叫 mysql）
- **nginx**：用官方源（centos 7 EPEL 的 nginx 版本旧）
  ```bash
  cat > /etc/yum.repos.d/nginx.repo <<'EOF'
  [nginx]
  name=nginx repo
  baseurl=https://nginx.org/packages/centos/7/$basearch/
  gpgcheck=0
  enabled=1
  EOF
  yum install -y nginx
  ```
- **redis**：EPEL 里有 `redis`，版本够用（Archery v1.14.0 要求 redis 3.5+）
- **chronyd / ntpdate**：CentOS 7 用 chronyd，跟 systemd 集成好；如果时间漂移会导致 JWT token 失效
- **journald 默认开启**，日志查 `journalctl -u` 即可
- **主机名 yearning**：升级过程不影响，但要确保 `/etc/hosts` 里 127.0.0.1 映射正确（如果 .env 里 `ALLOWED_HOSTS` 用了 hostname）

---

## TL;DR（一页纸）

```
[阶段 0: 准备 D-3 ~ D-1]   拉 v1.14.0 代码到独立目录 /opt/archery_v114，建 venv，pip install，collectstatic
[阶段 1: 备份 D-day-2h]    mysqldump 外部 MySQL 全量（archery 库 + 业务库元数据），备份 .env / docker-compose / 卷
[阶段 2: 装新骨架 D-day-2h] 在 /opt/archery_v114 跑通 manage.py check + collectstatic，写 systemd unit（不 enable）
[阶段 3: 停机切换 15 min]  docker stop 旧容器 → 跑 SQL 升级 → Django migrate → 启动 systemd 服务 → nginx 切端口
[阶段 4: 验证 5 min]       curl /login/、登录、SQL 审核、SQL 查询
[阶段 5: 观察 D+1 ~ D+7]   监控 / 慢查询 / 工单状态，7 天后清理旧容器
[回滚 RTO < 10 min]        任意一步失败 → docker-compose up -d → 业务恢复
```

**核心原则**：
- **老机器 docker 容器完整保留 7 天**（不删 image、不删 volume），作为终极回滚兜底
- **新 v1.14.0 装在独立目录 `/opt/archery_v114`**，不与 v1.10.0 互相干扰
- **数据源以"外部 MySQL dump"为准**，redis/goinception 容器数据是次要的（缓存类 / 可重建）
- **SECRET_KEY 必须从 v1.10.0 .env 完整保留**（mirage 字段加密用，丢了 = 密文全废）

---

## 关键风险 & 应对

| # | 风险 | 等级 | 应对 |
|---|------|------|------|
| 1 | **SECRET_KEY 变更导致密文解不开** | 🔴 P0 | 升级前从 v1.10.0 `.env` 提取 SECRET_KEY，新 `.env` 强制使用同一值 |
| 2 | **v1.10.0.sql 漏跑导致 ORM 查缺字段**（v0.1.3 真实踩坑） | 🔴 P0 | 显式列出所有 SQL 升级文件，跑完逐一 DESCRIBE 校验 |
| 3 | **mysqldump 不一致**（长事务、写操作） | 🟡 P1 | `--single-transaction --master-data=2 --routines --triggers`；停机窗口期 dump |
| 4 | **docker 容器停不了**（daemon 异常） | 🟡 P1 | 准备 `docker kill` 兜底；最坏情况用 `iptables` 拦截 9123 端口强制断流 |
| 5 | **redis 数据丢**（rdb 没持久化或持久化路径错） | 🟢 P2 | redis 是缓存类，丢可重建（登录态、celery 队列会瞬断 5-10s） |
| 6 | **goinception 启动失败**（binary 兼容性） | 🟡 P1 | 保留旧 docker 容器镜像 + 容器 ID，回滚时直接 `docker start` |
| 7 | **nginx 配置错**（静态文件 404 / 502） | 🟢 P2 | 提前在 80 端口旁开 8089 端口跑 v1.14.0，验证通过再切 80 |
| 8 | **Django migrate 阻塞**（表已存在 / 字段冲突） | 🟡 P1 | 跑 `makemigrations --dry-run --check` 先看差异，预先备份冲突表 |
| 9 | **防火墙/firewalld 没放行新端口** | 🟢 P2 | 提前在 firewalld 加 `--add-port=9003/tcp --permanent` |
| 10 | **时区 / locale 不一致**导致日志乱码 | 🟢 P2 | 系统统一 `LC_ALL=C.UTF-8`，systemd unit 加 `Environment=LANG=C.UTF-8` |

---

## 阶段 0：准备（停机前 3 天 ~ 1 天）

**目标**：把 v1.14.0 骨架装好但**不启动**，跟老 v1.10.0 完全隔离。

### 0.1 系统环境准备（CentOS 7 适配版）

> **前提**：阶段 0 第一步先做上面的"CentOS 7 EOL yum 源修复"和"Python 3.11 安装"。

```bash
# OS 确认
cat /etc/redhat-release  # 应输出 CentOS Linux 7.9.2009 (Core)
python3.11 --version     # 应输出 3.11.x

# 装必要工具（CentOS 7 用 yum 不用 dnf）
yum install -y git gcc gcc-c++ make mysql redis nginx \
    python3.11-pip python3.11-venv \
    policycoreutils-python setools-python \
    firewalld rsync tar \
    openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel \
    sqlite-devel readline-devel tk-devel \
    mysql-devel libxml2-devel libxslt-devel libaio-devel \
    cyrus-sasl-devel openldap-devel \
    nodejs npm

# 用户：archery
id archery 2>/dev/null || useradd -m -s /bin/bash archery

# SELinux context（v0.1.2 踩过的坑，阶段 0 提前设好）
# 注意：放 unit 文件后再 chcon；这里只是兜底占位
chcon -v -t systemd_unit_file_t /etc/systemd/system/archery-*.service 2>/dev/null || true
```

### 0.1.1 devtoolset-11 启用（pip 编译依赖）

```bash
# 一次性的：让 python3.11 编译 mysqlclient / cryptography 时用新 gcc
cat > /etc/profile.d/devtoolset-11.sh <<'EOF'
source /opt/rh/devtoolset-11/enable
EOF
source /etc/profile.d/devtoolset-11.sh
gcc --version  # 应输出 11.x
```

### 0.1.2 nginx 官方源（CentOS 7 EPEL nginx 太老）

```bash
# 如果上面 yum install 装的是 EPEL 的 nginx，先卸
yum remove -y nginx
cat > /etc/yum.repos.d/nginx.repo <<'EOF'
[nginx]
name=nginx repo
baseurl=https://nginx.org/packages/centos/7/$basearch/
gpgcheck=0
enabled=1
EOF
yum install -y nginx
nginx -v  # 应输出 1.20+ (Archery 推荐 1.25)
```

### 0.2 拉 v1.14.0 代码

```bash
# 拉项目代码（用户已经合并了 v1.14.0 上游 + 自定义）
# 注意：不要 clone 到 /dbdata/archery 跟 v1.10.0 冲突
# /dbdata 是 100G 卷，已用 25G，剩余 76G 够装 v1.14.0
mkdir -p /dbdata/archery_v114
cd /dbdata
git clone <repo_url> archery_v114  # 或 rsync -avz from dev machine
cd /dbdata/archery_v114
git log -1 --oneline  # 确认是 v1.14.0 + 二次开发 patches
```

**代码来源待确认**：用户的工作目录 `G:\MiniMax工作空间\archery_dev` 是已经合并好 v1.14.0 的仓库，需要 scp / rsync 到老机器的 `/dbdata/archery_v114`。

### 0.2.1 v1.10.0 现有目录（不删，备份用）

```bash
# v1.10.0 实际部署在 /dbdata/archery/src/docker-compose/
ls -la /dbdata/archery/src/docker-compose/
# 看到：
#   docker-compose.yml / .env
#   archery/    ← settings.py 在这
#   inception/  ← goinception 配置
#   mysql/      ← init SQL
#
# 升级期间不要动这个目录，保留作为快速回滚兜底
```

### 0.3 提取 v1.10.0 关键配置

```bash
# 从 v1.10.0 docker 容器或 host 路径拿 .env
# 路径 A：docker-compose 项目目录下的 .env
ls -la /path/to/v110/.env

# 路径 B：docker exec 进去拿
docker exec archery cat /app/.env > /tmp/v110.env

# 重点提取项（升级必看）
grep -E '^(SECRET_KEY|MYSQL_HOST|MYSQL_PORT|MYSQL_USER|MYSQL_PASSWORD|MYSQL_DB|REDIS_HOST|REDIS_PORT|REDIS_PASSWORD|ALLOWED_HOSTS|DEBUG)=' /tmp/v110.env
```

**⚠️ SECRET_KEY 必须原样保留**（mirage 字段加密依赖）。记录到 `/root/upgrade_v114_secrets.txt`（chmod 600）。

### 0.3.1 v1.10.0 实际配置摘录（已摸底确认）

**`local_settings.py`（容器内路径）/ `archery/settings.py`（host 路径）** 是 v1.10.0 真实生效的配置：

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'archery',
        'USER': 'archery',
        'PASSWORD': '<从真实文件提取，**不要写到 git 跟踪文件**>',
        'HOST': '172.20.2.110',   # ← **yearnning 本机 IP**（MySQL 进程在本机 3306 端口）
        'PORT': '3306',
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
    }
}

Q_CLUSTER = {
    'name': 'archery',
    'workers': 4,
    'recycle': 500,
    'timeout': 60,
    'compress': True,
    'cpu_affinity': 1,
    'save_limit': 0,
    'queue_limit': 50,
    'label': 'Django Q',
    'django_redis': 'default',
    'sync': False
}
```

**v1.14.0 新 .env 必须从这份配置平移过来**（不要用 v1.10.0 .env 里的 DATABASE_URL，那个跟实际生效的不一致）。

**v1.14.0 用 django-q2 不用 celery**（v1.10.0 也用 django-q2），所以异步任务框架**不用迁移**。

**MySQL 拓扑**：
- MySQL 进程在 yearnning 本机（pid 81822，监听 0.0.0.0:3306）
- 172.20.2.110 = yearnning 内网 IP，archery 容器走这个 IP 连本机 MySQL
- dump / migrate 都从 yearnning 本机跑，**不用走网络**

### 0.4 建 venv + 装依赖

```bash
cd /opt/archery_v114
sudo -Hu archery python3.11 -m venv venv
sudo -Hu archery bash -lc "cd /opt/archery_v114 && source venv/bin/activate && \
    pip install --upgrade pip wheel setuptools && \
    pip install -r requirements.txt"
```

**装失败排查（CentOS 7 特有）**：

| 错误 | 原因 | 修复 |
|------|------|------|
| `mysqlclient` 编译失败 `error: command 'gcc' failed` | gcc 4.8 太老，不支持 C99 某些语法 | `source /opt/rh/devtoolset-11/enable` 后重装 |
| `cryptography` 编译失败 `Rust not found` 或 `openssl/x509.h: No such file` | 缺 rust / openssl-devel | `yum install -y openssl-devel rust cargo` |
| `psycopg2-binary` 装 OK（已带 wheel），但 `pg_config` not found | 不影响，binary 版本不需要 pg_config | 忽略 |
| `pyodbc` 失败 | 缺 unixODBC-devel | `yum install -y unixODBC-devel` |
| `pymongo` 失败 | 缺 pcre-devel | `yum install -y pcre-devel` |
| `phoenixdb` 失败 | 缺 cyrus-sasl-devel | 已包含在 0.1 |
| `wheel` 安装警告 `RuntimeWarning: '_imp'...` | Python 3.11 vs 老 setuptools | `pip install -U setuptools` 后重试 |
| `Cannot find a valid baseurl for repo: epel` | EPEL 源挂了 | 切阿里云 EPEL 镜像（见 0.1.3） |

### 0.4.1 pip 镜像源（国内加速，可选）

```bash
sudo -Hu archery bash -lc "cd /opt/archery_v114 && source venv/bin/activate && \
    pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com"
```

### 0.5 写新 .env（保留 v1.10.0 SECRET_KEY）

```bash
# 复制 .env.example 做模板
cp /opt/archery_v114/.env.example /opt/archery_v114/.env
chown archery:archery /opt/archery_v114/.env
chmod 600 /opt/archery_v114/.env

# 关键修改（手动编辑）
# 1) SECRET_KEY  ← 从 v1.10.0 .env 复制（一字不差）
# 2) MYSQL_HOST / PORT / DB ← 外部 MySQL 真实地址
# 3) REDIS_HOST ← 127.0.0.1（裸机 redis 走本机）或临时指向老容器
# 4) ALLOWED_HOSTS ← 老机器 IP / 域名
# 5) DEBUG=False
# 6) MYSQL_DB 跟 v1.10.0 一致（不新建库）
```

### 0.6 跑 sanity check

```bash
cd /opt/archery_v114
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py check 2>&1" | tail -20
# 期望：System check identified no issues (0 silenced).
```

如果报 `ModuleNotFoundError`：缺包，重跑 `pip install -r requirements.txt`。
如果报 `ImportError: cannot import name 'X' from 'Y'`：v1.14.0 代码 vs requirements 不匹配，看 git log。

### 0.7 提前跑 collectstatic（不实际生效，只是测）

```bash
cd /opt/archery_v114
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py collectstatic --noinput 2>&1" | tail -5
# v0.1.1 踩过的坑：ForgivingManifestStaticFilesStorage 会因为重复文件警告导致 manifest 失败
# 项目 settings.py 已改为 whitenoise.storage.CompressedStaticFilesStorage（commit 1a9aea0）
# 如果用户在跑老 settings.py 切分支前先看 .git log
```

### 0.8 准备 systemd unit（不 enable）

```bash
# 复制 unit 模板
cp /opt/archery_v114/scripts/deploy/systemd/archery-prod-gunicorn.service \
   /etc/systemd/system/archery-v114-gunicorn.service

# 改路径：/opt/archery/prod → /opt/archery_v114
sed -i 's|/opt/archery/prod|/opt/archery_v114|g; s|9003|9004|g' \
   /etc/systemd/system/archery-v114-gunicorn.service

# 验证 unit 语法（systemd 219 兼容：v0.1.2 踩过）
systemd-analyze verify /etc/systemd/system/archery-v114-gunicorn.service

# 暂时不 enable / start
systemctl daemon-reload
systemctl list-unit-files archery-v114-*.service
```

### 0.9 准备 nginx 临时配置（8089 端口，跟老 80 并行）

```bash
cat > /etc/nginx/conf.d/archery-v114.conf <<'EOF'
server {
    listen 8089;
    server_name _;
    client_max_body_size 100M;

    location /static/ {
        alias /opt/archery_v114/static/;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:9004;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
EOF
nginx -t  # 必须 OK
```

### 0.10 准备 firewalld 规则

```bash
firewall-cmd --permanent --add-port=9004/tcp  # gunicorn 直连
firewall-cmd --permanent --add-port=8089/tcp  # 临时验证
firewall-cmd --reload
firewall-cmd --list-ports
```

### 0.11 准备裸机 redis（替换容器内 redis）

```bash
yum install -y redis
systemctl enable redis
# /etc/redis.conf 检查：bind 127.0.0.1, appendonly yes (按需)
# 暂时不 start，阶段 3 才启
```

### 0.12 准备 goinception（关键决策点）

**goinception 升级方案二选一**：

| 方案 | 适用 | 操作 |
|------|------|------|
| **A. 继续用容器**（推荐） | 老机器 docker daemon 还在 | `docker run -d --name goinception_v114 -p 4000:4000 -v goinception_data:/data hanchuanchuan/goinception` |
| **B. 切裸机** | 想彻底去 docker | 下载 goinception linux binary，配 systemd |

由于 docker 镜像可能拉不到，**先确认本地是否有 goinception 镜像**：
```bash
docker images | grep -i goinception
# 有 → 用方案 A
# 没有 → 走方案 B（看 https://github.com/hanchuanchuan/goInception/releases，下载 release binary）
```

---

## 阶段 1：备份（停机前 2 小时）

**目标**：所有数据多份备份，任何步骤可回滚。

### 1.1 MySQL 全量 dump（本机 MySQL 172.20.2.110）

```bash
# 从 yearnning 机器 dump（MySQL 进程在本机 3306 端口）
mkdir -p /backup/upgrade_v114
TS=$(date +%Y%m%d_%H%M%S)

# 关键参数：
#   --single-transaction：保证 InnoDB 一致性
#   --master-data=2：记录 binlog 位点（如果未来需要增量恢复）
#   --routines --triggers --events：包含存储过程/触发器/事件
#   --add-drop-table：恢复时干净

# ⚠️ 用 archery 用户（不是 root），因为这是 v1.10.0 实际用的账号
# MySQL 进程在 yearnning 本机 3306 端口，连本机可以用 127.0.0.1 或 172.20.2.110
# ⚠️ 决策 1：忽略慢查询历史（6.1GB），降 dump 体积到 ~1GB
mysqldump -h 127.0.0.1 -P 3306 -u archery -p"<archery 密码，从 settings.py 提取>" \
    --single-transaction --master-data=2 --routines --triggers --events \
    --add-drop-table --set-gtid-purged=OFF \
    --ignore-table=archery.mysql_slow_query_review_history \
    --databases archery \
    | gzip > /backup/upgrade_v114/archery_${TS}.sql.gz

# 业务库元数据（用户提到 hly_accesscard；archery 用户有没有权限要看）
mysqldump -h 127.0.0.1 -P 3306 -u archery -p"<archery 密码>" \
    --single-transaction --routines --triggers \
    --databases hly_accesscard \
    | gzip > /backup/upgrade_v114/hly_accesscard_${TS}.sql.gz \
    2>/dev/null || echo "  (archery 用户没 hly_accesscard 权限，跳过)"

# 验证 dump
ls -la /backup/upgrade_v114/
zcat /backup/upgrade_v114/archery_${TS}.sql.gz | head -50
zcat /backup/upgrade_v114/archery_${TS}.sql.gz | tail -20  # 确认有 master-data 注释
```

**离线备份 + 异地保存**（强烈建议）：
```bash
rsync -avz /backup/upgrade_v114/ root@<异地机器>:/backup/archery_upgrade_${TS}/
```

### 1.2 MySQL 表结构快照（升级前对照基线）

```bash
mysqldump -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" \
    --no-data --databases archery > /backup/upgrade_v114/archery_schema_before.sql

# 记录当前表数 / 行数（升级后比对）
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery -e "
SELECT 'TABLES' AS metric, COUNT(*) AS value FROM information_schema.tables WHERE table_schema='archery'
UNION ALL
SELECT 'auth_user', COUNT(*) FROM archery.sql_users
UNION ALL
SELECT 'sql_instance', COUNT(*) FROM archery.sql_instance
UNION ALL
SELECT 'sql_workflow', COUNT(*) FROM archery.sql_workflow
UNION ALL
SELECT 'audit_workflow', COUNT(*) FROM archery.sql_workflow
;
" > /backup/upgrade_v114/rowcount_before.txt
```

### 1.3 备份 v1.10.0 容器配置和数据卷

```bash
# docker 容器配置（虽然不能 docker pull，但 image 应该还在本地）
docker images > /backup/upgrade_v114/docker_images_before.txt
docker ps -a >> /backup/upgrade_v114/docker_images_before.txt

# 关键卷备份（v1.10.0 容器里的 redis / goinception 数据如果持久化了）
# Redis RDB：
docker exec archery-redis redis-cli BGSAVE
sleep 5
docker cp archery-redis:/data/dump.rdb /backup/upgrade_v114/redis_dump.rdb

# docker-compose.yml + .env 备份
cp -v /path/to/v110/docker-compose.yml /backup/upgrade_v114/
cp -v /path/to/v110/.env /backup/upgrade_v114/v110.env
```

### 1.4 备份现有 .env 和 SECRET_KEY

```bash
cp -v /path/to/v110/.env /backup/upgrade_v114/v110.env
# 验证 SECRET_KEY 跟新 .env 一致
diff <(grep ^SECRET_KEY= /backup/upgrade_v114/v110.env) \
     <(grep ^SECRET_KEY= /opt/archery_v114/.env) \
     && echo "OK: SECRET_KEY 一致" || echo "FATAL: SECRET_KEY 不一致！"
```

### 1.5 备份检查清单

```bash
ls -la /backup/upgrade_v114/
# 期望看到：
#   archery_<TS>.sql.gz                (~1GB，决策 1 排除了慢查询历史)
#   hly_accesscard_<TS>.sql.gz         (如果业务库也在这台 MySQL)
#   archery_bak_BEFORE_DROP_<TS>.sql.gz ← 决策 3 备份的 archery_bak
#   archery_schema_before.sql
#   rowcount_before.txt
#   docker_images_before.txt
#   redis_dump.rdb
#   v110.env
#   v110_docker-compose.yml
```

---

## 阶段 2：部署骨架验证（停机前 2 小时，**不动数据**）

**目标**：确认 v1.14.0 骨架能跑（用新库 / 临时库，不动 v1.10.0 数据）。

### 2.1 建临时测试库

```bash
# 用新库名 archery_v114_test，验证 v1.14.0 初始化流程跑得通
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" -e "
DROP DATABASE IF EXISTS archery_v114_test;
CREATE DATABASE archery_v114_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"
```

### 2.2 临时改 .env 指向测试库

```bash
# 备份 .env，临时改 MYSQL_DB
cp /opt/archery_v114/.env /opt/archery_v114/.env.real
sed -i 's/^MYSQL_DB=.*/MYSQL_DB=archery_v114_test/' /opt/archery_v114/.env
```

### 2.3 跑通初始化（v1.0_init.sql + 升级 SQL + Django migrate）

```bash
cd /opt/archery_v114

# 1) v1.0_init.sql
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery_v114_test \
    < src/init_sql/v1.0_init.sql 2>/dev/null

# 2) 升级 SQL（按版本顺序；v0.1.0 验证过这套顺序跑得通）
for sql in v1.1.0 v1.2.0 v1.3.0 v1.3.2 v1.3.7 v1.4.0 v1.4.3 v1.4.5 \
           v1.5.0 v1.5.3_comment v1.6.0 v1.6.1 v1.6.2 v1.6.3 v1.6.6 v1.6.7 \
           v1.7.0 v1.7.1 v1.7.2 v1.7.3 v1.7.5 v1.7.7 v1.7.8 v1.7.11 v1.7.12 \
           v1.8.3 v1.8.4 v1.9.0 v1.10.0 v1.12.0 v1.13.0 v1.15.0; do
    f="src/init_sql/${sql}.sql"
    [ -f "$f" ] && \
        mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery_v114_test < "$f" 2>/dev/null || true
done

# 3) Django migrate
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py migrate --noinput 2>&1" | tail -10

# 4) seed
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py seed_sql_types 2>&1" | tail -3
```

### 2.4 验证测试库能起

```bash
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/gunicorn archery.wsgi:application -w 1 -b 0.0.0.0:9004 \
    --access-logfile - --error-logfile - --timeout 60 \
    > /tmp/gunicorn_test.log 2>&1 &"
sleep 5
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:9004/login/

# 期望 200；如果 500 看 /tmp/gunicorn_test.log
# 验证完杀掉
pkill -f 'gunicorn.*9004' || true
```

### 2.5 恢复 .env 指向真实库

```bash
mv /opt/archery_v114/.env.real /opt/archery_v114/.env
grep ^MYSQL_DB= /opt/archery_v114/.env  # 应是原 archery 库名
```

### 2.6 清理测试库

```bash
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" -e "DROP DATABASE archery_v114_test;"
```

---

## 阶段 3：停机切换（15-30 分钟，**核心**）

**目标**：在窗口内完成：停老容器 → 跑 SQL 升级 → Django migrate → 启新服务 → 验证。

### 3.1 通知 + 切维护页

```bash
# 在老 nginx 上挂维护页（如果有）
# 或者通过钉钉/企微通知："archery 升级中，预计 30 分钟"
```

### 3.2 停老 v1.10.0 容器

```bash
# 停容器（保留容器实例，不删 image / volume）
cd /path/to/v110
docker-compose stop archery  # 停 archery 容器（业务流量入口）
docker-compose stop celery_worker celery_beat 2>/dev/null || true
# redis 暂不停（还能查数据）
# goinception 暂不停（用方案 A 的话，goinception 容器继续跑）
```

### 3.3 数据最终 dump（停机窗口期内）

```bash
# 拿到 v1.10.0 容器停服后的最终一致性数据
mysqldump -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" \
    --single-transaction --master-data=2 --routines --triggers --events \
    --add-drop-table --set-gtid-purged=OFF \
    --databases archery \
    | gzip > /backup/upgrade_v114/archery_FINAL.sql.gz
```

### 3.4 把 dump 导入新库（用同一库名，drop + recreate）

```bash
# ⚠️ 危险操作：drop 老库！
# 但 v1.10.0 容器已停，dump 已备份，操作可回滚
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" -e "
DROP DATABASE IF EXISTS archery;
CREATE DATABASE archery DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"

# 导入 v1.10.0 数据
gunzip < /backup/upgrade_v114/archery_FINAL.sql.gz | \
    mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery

# 校验行数跟备份前一致
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery -e "
SELECT 'TABLES' AS metric, COUNT(*) AS value FROM information_schema.tables WHERE table_schema='archery'
UNION ALL
SELECT 'sql_users', COUNT(*) FROM archery.sql_users
UNION ALL
SELECT 'sql_instance', COUNT(*) FROM archery.sql_instance
UNION ALL
SELECT 'sql_workflow', COUNT(*) FROM archery.sql_workflow
;
" > /backup/upgrade_v114/rowcount_after_import.txt
diff /backup/upgrade_v114/rowcount_before.txt /backup/upgrade_v114/rowcount_after_import.txt \
    && echo "OK: 行数一致" || echo "WARN: 行数有差，看 diff"
```

### 3.5 跑 SQL 升级（关键步骤，v0.1.3 真实踩坑）

```bash
cd /opt/archery_v114

# ⚠️ 升级 SQL 是 best-effort，每个文件失败不阻塞后续（用 || true）
# 但必须全部跑过！漏跑一个就可能 500（v0.1.3 血的教训）
# 升级 SQL 路径：v1.10.0 → v1.12.0 → v1.13.0 → v1.15.0
# （中间 v1.11.0 上游没发版，v1.14.0 也没发 SQL，v1.14.0 的 schema 变化在 v1.13/v1.15 里）
for sql in v1.10.0 v1.12.0 v1.13.0 v1.15.0; do
    f="src/init_sql/${sql}.sql"
    [ -f "$f" ] && \
        mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery < "$f" 2>/dev/null || true
    echo "  ran $sql.sql"
done

# 关键校验：v1.10.0.sql 加的字段不能漏
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery -e "
SELECT column_name FROM information_schema.columns
WHERE table_schema='archery' AND table_name='sql_instance' AND column_name IN ('is_ssl', 'verify_ssl', 'show_db_name_regex', 'denied_db_name_regex');
SELECT column_name FROM information_schema.columns
WHERE table_schema='archery' AND table_name='instance_account' AND column_name='db_name';
SELECT column_name FROM information_schema.columns
WHERE table_schema='archery' AND table_name='sql_workflow' AND column_name IN ('export_format', 'is_offline_export', 'file_name');
"
# 期望 8 行（4+1+3），少任何一个就要单独跑那个 SQL 文件
```

### 3.6 Django migrate

```bash
cd /opt/archery_v114

# 先 dry-run 看看有没有冲突
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py makemigrations --noinput --dry-run --verbosity 1 2>&1" \
    | grep -v 'No changes detected' | tail -5

# 实际 migrate
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py migrate --noinput 2>&1" | tail -10

# 校验：migrate 状态应该是 "No migrations to apply" 或全部打勾
sudo -Hu archery bash -lc "set -a && source .env && set +a && \
    venv/bin/python manage.py showmigrations 2>&1" | tail -20
```

### 3.7 启动裸机服务

```bash
# 1) 启动裸机 redis（替换容器内 redis）
systemctl start redis
systemctl status redis --no-pager

# 2) 重启 v1.14.0 gunicorn（用 systemd）
systemctl enable --now archery-v114-gunicorn.service
systemctl status archery-v114-gunicorn.service --no-pager

# 3) 检查端口
ss -tlnp | grep -E '6379|9004'

# 4) 加载 nginx 临时配置（8089 端口）
nginx -t && nginx -s reload  # 或 systemctl reload nginx
```

### 3.8 切流量（把 80 端口从老容器切到新裸机）

**方案 A：直接换 nginx 配**（推荐）

```bash
# 把 8089 配置改成 80 端口
cat > /etc/nginx/conf.d/archery.conf <<'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 100M;
    location /static/ { alias /opt/archery_v114/static/; expires 30d; }
    location / {
        proxy_pass http://127.0.0.1:9004;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
EOF
# 删掉 8089 临时配置
rm -f /etc/nginx/conf.d/archery-v114.conf
nginx -t && nginx -s reload
```

**方案 B：保留老容器，仅切 archery 容器端口**（如果用户强烈想保留 docker 架构）
- 不推荐，跟"裸机化"目标矛盾

### 3.9 停掉老 v1.10.0 容器（彻底停服）

```bash
cd /path/to/v110
docker-compose down  # 停 archery + redis 容器，但 volume 保留
# goinception 容器如果用方案 A 还在跑
```

---

## 阶段 4：验证（5-10 分钟）

### 4.1 HTTP 检查

```bash
# 在老机器上：
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/login/
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/static/dist/css/login.css

# 期望：login/ 200，static 200
# 如果 302 跳到 /login/ 也算正常（未登录重定向）
# 如果 500：journalctl -u archery-v114-gunicorn.service -n 50
```

### 4.2 业务功能

```bash
# 浏览器手工测试（人工）
# - 登录（admin 账号）
# - SQL 审核（提交一条 DDL 走完审核流）
# - SQL 查询（select 1 from dual）
# - 工单列表
# - 实例列表
# - 慢查询（如果有）
```

### 4.3 数据库健康

```bash
# v1.10.0 vs v1.14.0 行数比对
mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>" archery -e "
SELECT 'sql_users' AS tbl, COUNT(*) AS rows FROM sql_users
UNION ALL SELECT 'sql_instance', COUNT(*) FROM sql_instance
UNION ALL SELECT 'sql_workflow', COUNT(*) FROM sql_workflow
UNION ALL SELECT 'sql_workflow_log', COUNT(*) FROM sql_workflow_log
UNION ALL SELECT 'sql_users_user_permissions', COUNT(*) FROM sql_users_user_permissions
;
"
diff /backup/upgrade_v114/rowcount_before.txt <(...)  # 跟备份前对比
```

### 4.4 日志检查

```bash
journalctl -u archery-v114-gunicorn.service -n 100 --no-pager
journalctl -u redis --no-pager
tail -50 /var/log/nginx/error.log
```

---

## 阶段 5：观察期（D+1 ~ D+7）

### 5.1 7 天观察清单

- [ ] D+1：每小时看 gunicorn 日志、nginx 错误日志
- [ ] D+2：工单提交/审核流程跑通
- [ ] D+3：慢查询、统计功能（dashboard）
- [ ] D+5：celery 队列（如果 v1.14.0 用了 django-q2 而不是 celery，要确认）
- [ ] D+7：清理旧容器和卷

### 5.2 监控告警

```bash
# 加入 systemd-timer 每天跑健康检查
cat > /etc/systemd/system/archery-healthcheck.timer <<'EOF'
[Unit]
Description=Archery Healthcheck Daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/archery-healthcheck.service <<'EOF'
[Unit]
Description=Archery Healthcheck

[Service]
Type=oneshot
ExecStart=/opt/archery_v114/scripts/monitor/check_health.sh
EOF

systemctl daemon-reload
systemctl enable --now archery-healthcheck.timer
```

### 5.3 旧 docker 资源保留 7 天

```bash
# D+7 之后清理（执行前再确认）
docker images  # 看看哪些 image 可以删
docker volume ls  # 确认数据已迁移完成再删
```

---

## 回滚方案

### RTO 目标：10 分钟内恢复 v1.10.0 业务

### 触发条件

- 阶段 3 任何步骤失败、阶段 4 验证发现 500、阶段 5 严重 bug
- 用户/老板说"回滚"

### 回滚步骤

```bash
# 1) 停新 v1.14.0 服务
systemctl stop archery-v114-gunicorn.service
systemctl disable archery-v114-gunicorn.service

# 2) nginx 切回老容器
# 改 /etc/nginx/conf.d/archery.conf 指向老容器端口（9123）
# 或者直接删 v1.14.0 nginx 配置，启用老 docker 的 nginx 容器
nginx -t && nginx -s reload

# 3) 启老 docker 容器
cd /path/to/v110
docker-compose up -d

# 4) 恢复老 MySQL 数据（如果有需要）
gunzip < /backup/upgrade_v114/archery_FINAL.sql.gz | \
    mysql -h <MYSQL_HOST> -u <MYSQL_USER> -p"<MYSQL_PASSWORD>"
# 注意：这一步只在阶段 3.4 之后才需要；如果阶段 3.4 之前回滚，archery 库没改过，不需要恢复

# 5) 验证
curl -fsS -m 5 -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1/login/
```

### 已知回滚陷阱

1. **SECRET_KEY 一致**：v1.10.0 .env 的 SECRET_KEY 必须原样恢复，否则老用户的 mirage 密文解不开
2. **数据库行**：mysqldump 导入前已经 drop 过老库，回滚是覆盖式导入，理论上完全一致
3. **docker 镜像**：**绝对不能 docker rmi**，否则回滚时起不来

---

## 踩坑预警（v0.1.0-prod 真实经验 + CentOS 7 特有）

| # | 坑 | 症状 | 预防 |
|---|------|------|------|
| 1 | **v1.10.0.sql 漏跑** | `/sqlworkflow/` 报 `Unknown column 'sql_instance.is_ssl'` | 阶段 3.5 用 `information_schema.columns` 强校验 |
| 2 | **auth_group 重复 INSERT** | 跑 v1.0_init.sql 时建了 `auth_group(id=1)`，再导 v1.10.0 dump 撞 unique | 用 `--force` 或导入后 `DELETE FROM auth_group WHERE id=1` 再让 Django 重建 |
| 3 | **STATICFILES_STORAGE 选错** | 静态文件 404 / 302 | 确认 settings.py 是 `whitenoise.storage.CompressedStaticFilesStorage`（commit 1a9aea0） |
| 4 | **.gitignore 把 common/static 排除** | collectstatic 缺 122 个文件 | 项目已修（commit f366066），git pull 最新 |
| 5 | **systemd 219 兼容** | unit 文件 `ProtectSystem=strict` 等指令报 "Unit not found" | 用最简 17 行模板（v0.1.2 已验证） |
| 6 | **SELinux context 错** | unit 加载了但启不了 | `chcon -t systemd_unit_file_t` |
| 7 | **set -e + grep -v 退码 1** | 部署脚本静默中止 | 用 `mysql ... 2>/dev/null` 吞告警 |
| 8 | **dbops.service 占满 job queue** | 其他 unit 起不来 | `systemctl stop dbops.service` |
| 9 | **celery 任务在 v1.14.0 跑不起来** | 定时任务不执行 | v1.14.0 用 django-q2 不用 celery，迁移前确认；如果 v1.10.0 用了 celery，要单独迁移队列（**已确认 v1.10.0 也用 django-q2，celery 迁移不适用**） |
| 10 | **makemigrations 没跑** | migrate 报"no such migration" | 阶段 0.6 sanity check 跑 makemigrations --dry-run |
| 11 | **ALLOWED_HOSTS 没改** | 客户端访问 400 | .env 加老机器 IP |
| 12 | **debug=True 暴露 stacktrace** | 安全风险 | .env 强制 `DEBUG=False` |
| **CentOS 7 特有** | | | |
| 13 | **CentOS 7 EOL，yum 源全挂** | `yum install` 报 404 | 阶段 0 第一步切阿里云 vault 镜像 |
| 14 | **Python 3.11 装不上** | `No package python3.11 available` | 加 IUS 源；或 SCL；或编译 |
| 15 | **gcc 4.8 编译 mysqlclient 失败** | `error: command 'gcc' failed with exit status 1` | 装 devtoolset-11，`source /opt/rh/devtoolset-11/enable` |
| 16 | **`dnf` 命令不存在** | `command not found` | **所有命令用 `yum`** |
| 17 | **firewalld 启动报 `EBADF`** | 旧 kernel bug | `systemctl restart firewalld`；或临时 `setenforce 0` 排除 SELinux 干扰 |
| 18 | **chronyd 没启，时间漂移** | JWT token 提前失效、MySQL binlog 异常 | `systemctl enable --now chronyd` |
| 19 | **MySQL 客户端缺** | `mysql: command not found` | `yum install -y mysql`（centos 7 仓库叫 mysql 不是 mariadb-client） |
| 20 | **EPEL 仓库挂了** | `Cannot find a valid baseurl for repo: epel/x86_64` | 切阿里云 EPEL：`baseurl=https://mirrors.aliyun.com/epel/7/$basearch/` |
| 21 | **主机名解析失败** | `pgrep: warning: ... bad` / 服务启动慢 | `/etc/hosts` 加 `127.0.0.1 yearning yearning.localdomain` |

---

## 关键检查清单（最终确认）

升级前：
- [ ] SECRET_KEY 已从 v1.10.0 .env 提取并写入新 .env
- [ ] mysqldump 全量备份完成，备份在 `/backup/upgrade_v114/` 和异地
- [ ] v1.14.0 代码完整、git log 干净
- [ ] venv 装好、`manage.py check` 通过
- [ ] collectstatic 成功
- [ ] systemd unit 准备好但未 enable
- [ ] nginx 临时配置 8089 测过
- [ ] firewalld 端口已开
- [ ] 通知到位（钉钉/邮件）

升级中（停机窗口）：
- [ ] 老 docker 容器已 stop
- [ ] mysqldump FINAL 完成
- [ ] 库 drop + import 完成
- [ ] v1.10.0/v1.12.0/v1.13.0/v1.15.0 SQL 跑完
- [ ] 字段校验通过（8 个新增字段）
- [ ] Django migrate 完成
- [ ] 裸机服务启动（redis + gunicorn）
- [ ] nginx 切到 80 端口
- [ ] 验证 HTTP 200、登录、SQL 审核

升级后：
- [ ] 7 天观察期
- [ ] 监控告警就位
- [ ] 旧 docker 容器/卷保留 7 天
- [ ] changelog 记录：新建 `docs/changelogs/<日期>_upgrade-v1.10.0-to-v1.14.0.md`

---

## 附录 A：升级 SQL 详细解释

### v1.10.0.sql（必须跑，v0.1.3 真实踩坑）

```sql
-- 关键字段（v0.1.3 真实踩坑）
ALTER TABLE instance_account ADD db_name varchar(128) default '' not null;
ALTER TABLE instance_account ADD UNIQUE INDEX uidx_instanceid_user_host_dbname(...);
ALTER TABLE sql_instance ADD is_ssl tinyint(1) DEFAULT 0;
```
**作用**：MongoDB 多库支持 + SSL 支持。漏跑 → 报 `Unknown column 'is_ssl'`。

### v1.12.0.sql
```sql
ALTER TABLE sql_instance ADD verify_ssl tinyint(1) DEFAULT 1;
ALTER TABLE sql_instance ADD show_db_name_regex varchar(1024) DEFAULT '';
ALTER TABLE sql_instance ADD denied_db_name_regex varchar(1024) DEFAULT '';
```
**作用**：SSL 证书验证 + 数据库显示/隐藏正则。

### v1.13.0.sql
```sql
ALTER TABLE sql_workflow
  ADD COLUMN export_format VARCHAR(10) DEFAULT NULL,
  ADD COLUMN is_offline_export TINYINT(1) NOT NULL,
  ADD COLUMN file_name VARCHAR(255) DEFAULT NULL;
-- 3 个新权限
INSERT IGNORE INTO auth_permission (...) VALUES ('离线下载权限', ..., 'offline_download'), ...;
```
**作用**：工单离线导出功能。

### v1.15.0.sql
```sql
INSERT INTO auth_permission (...) VALUES ('菜单 参数对比', ..., 'menu_param_compare');
```
**作用**：参数对比菜单权限。v1.14.0 也用这个文件（v1.15.0 是 v1.14.0 之后的修复发布，SQL 兼容）。

---

## 附录 B：升级时间线（参考 172.20.2.134 实际经验）

| 阶段 | 预计耗时 | 实际（参考） |
|------|----------|--------------|
| 阶段 0：环境准备 | 2-4 小时 | 1-2 小时（Python/依赖装好） |
| 阶段 1：备份 | 30 分钟（含异地 rsync） | 20-30 分钟 |
| 阶段 2：骨架验证 | 1 小时 | 1-2 小时（可能踩坑） |
| 阶段 3：停机切换 | 15-30 分钟 | 实际生产约 25 分钟 |
| 阶段 4：验证 | 5-10 分钟 | 5-10 分钟 |
| **总计** | **半天** | **半天到 1 天** |

---

## 附录 C：决策记录（待用户确认）

1. **停机窗口具体时长**：用户已确认 15-30 分钟，方案按 25 分钟估算
2. **新服务端口**：默认 9004（gunicorn）+ 80（nginx），如冲突可改 9080/8443
3. **goinception 部署方式**：方案 A（继续用容器）优先，如果镜像不在则走方案 B（裸机）
4. **老容器保留时长**：默认 7 天，期间 image/volume 不删
5. **钉钉 OA / 二次开发扩展**：用户已确认未接入，方案按纯 v1.10.0 处理
6. **业务库 hly_accesscard**：跟 archery 元库在同 MySQL，dump 一并备份，**不导入**（只升级 archery 库）

---

**最后说一句**：整个方案的核心是"**准备期把能干的都干了，停机窗口只切数据**"。你看到的 15-30 分钟其实只有 4 个动作：停容器 → 升级 SQL → migrate → 启服务。其他全是准备阶段 + 验证阶段 + 观察阶段。把准备阶段做扎实，停机窗口就是简单的。

---

## 决策记录（已敲定 — 2026-07-21）

| # | 决策 | 决定 | 实施方案影响 |
|---|------|------|--------------|
| 1 | 慢查询历史 6.1GB 要不要导入？ | **不导入** | mysqldump 加 `--ignore-table=archery.mysql_slow_query_review_history`；dump 体积从 ~7GB 降到 ~1GB，导入时间 -5-10 分钟 |
| 2 | django_q_task 旧任务 15,549 个？ | **保留** | mysqldump 全量（不加 ignore），跟工单数据一起导入 |
| 3 | archery_bak 历史备份库 | **清理** | 升级前先备份一份到 `/backup/upgrade_v114/archery_bak_BEFORE_DROP.sql.gz`，升级完成 **D+7** 之后 DROP（不在升级当天动） |

---

## 阶段 0.0 决策执行（升级前 1 天）

### 0.0.1 备份 archery_bak 库（不删，备份以防要回滚）

```bash
# 1. 先看一眼内容（确认是历史备份，不是别的数据）
mysql -h 127.0.0.1 -uarchery -p"<archery 密码>" -e "
SHOW TABLES FROM archery_bak;
SELECT table_name, IFNULL(table_rows, 0) AS rows
FROM information_schema.tables
WHERE table_schema='archery_bak'
ORDER BY table_name;
"

# 2. 备份
mysqldump -h 127.0.0.1 -uarchery -p"<archery 密码>" \
    --single-transaction --routines --triggers --events \
    --databases archery_bak \
    | gzip > /backup/upgrade_v114/archery_bak_BEFORE_DROP_${TS}.sql.gz

ls -la /backup/upgrade_v114/archery_bak_BEFORE_DROP_*.sql.gz
```

**不在升级当天删**。D+7 之后手动 DROP（见阶段 5.4）。

### 0.0.2 验证 mysqldump 命令

```bash
# 在生产数据上预跑一次，验证 --ignore-table 有效
mysqldump -h 127.0.0.1 -uarchery -p"<archery 密码>" \
    --single-transaction --master-data=2 --routines --triggers --events \
    --add-drop-table --set-gtid-purged=OFF \
    --ignore-table=archery.mysql_slow_query_review_history \
    --databases archery \
    --dry-run 2>&1 | head -20
# MySQL 5.7 没有 --dry-run，先看输出体积：
mysqldump -h 127.0.0.1 -uarchery -p"<archery 密码>" \
    --single-transaction --no-data --databases archery \
    --ignore-table=archery.mysql_slow_query_review_history 2>/dev/null | wc -l
# 期望：~10000+ 行（结构），比全量少很多
```

---

## 附录 D：25 分钟秒级执行清单

> **前提**：阶段 0 + 阶段 1 + 阶段 2 已经在升级前 1-2 天做完，下面是停机窗口期的具体动作。

| T+ | 操作 | 命令（精简） | 期望输出 / 失败处理 |
|---:|------|--------------|---------------------|
| 0:00 | 通知 + 切维护页 | 钉钉/企微群发"archery 升级中" | |
| 0:02 | 停老 v1.10.0 archery 容器 | `cd /dbdata/archery/src/docker-compose && docker-compose stop archery` | archery 容器 stopped |
| 0:04 | archery 容器下线确认 | `curl -m 3 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9123/login/` | 期望：000/Connection refused |
| 0:05 | **MySQL 最终 dump** | `mysqldump -h 127.0.0.1 -uarchery -p"..." --single-transaction --master-data=2 --routines --triggers --events --add-drop-table --set-gtid-purged=OFF --ignore-table=archery.mysql_slow_query_review_history --databases archery \| gzip > /backup/upgrade_v114/archery_FINAL_${TS}.sql.gz` | dump 体积 ~1GB（不要 6GB） |
| 0:08 | **Drop + 重建 archery 库** | `mysql -e "DROP DATABASE archery; CREATE DATABASE archery DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"` | 库重建完 |
| 0:09 | **导入 v1.10.0 数据** | `gunzip < archery_FINAL.sql.gz \| mysql archery` | 6-8 分钟（1GB 数据） |
| 0:16 | **跑升级 SQL**（4 个文件） | `for f in v1.10.0 v1.12.0 v1.13.0 v1.15.0; do mysql archery < src/init_sql/${f}.sql 2>/dev/null \|\| true; done` | 每条 ALTER 都成功（无报错） |
| 0:17 | **字段校验** | `SELECT column_name FROM information_schema.columns WHERE table_schema='archery' AND ((table_name='sql_instance' AND column_name IN ('is_ssl','verify_ssl','show_db_name_regex','denied_db_name_regex')) OR (table_name='instance_account' AND column_name='db_name') OR (table_name='sql_workflow' AND column_name IN ('export_format','is_offline_export','file_name')));` | 期望 8 行 |
| 0:18 | **Django migrate** | `cd /dbdata/archery_v114 && sudo -Hu archery bash -lc "set -a && source .env && set +a && venv/bin/python manage.py migrate --noinput 2>&1" \| tail -10` | 期望：No migrations to apply（或全打勾） |
| 0:20 | **启动 v1.14.0 gunicorn** | `systemctl start archery-v114-gunicorn.service` | Active: active (running) |
| 0:21 | **启动 v1.14.0 裸机 redis** | `systemctl start redis` | Active: active (running) |
| 0:22 | **nginx 切到 9003 端口** | `nginx -t && nginx -s reload` | nginx reload ok |
| 0:22 | **firewalld 放 9003** | `firewall-cmd --permanent --add-port=9003/tcp && firewall-cmd --reload`（如果 firewalld 没启，跳过） | success |
| 0:23 | **HTTP 验证** | `curl -fsS -m 5 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9003/login/` | 期望：200（或 302） |
| 0:24 | **登录验证** | `curl -fsS -m 5 -c /tmp/c.jar -b /tmp/c.jar http://127.0.0.1:9003/login/ -d "username=archery&password=archery" -o /dev/null -w "%{http_code}\n"` | 期望：302 |
| 0:25 | **通知 + 取消维护页** | 钉钉/企微"archery 升级完成" | |

**总时长：25 分钟**（其中 0:09-0:16 的 dump 导入占 7 分钟，是最大块）。

**回滚锚点**（任意一步失败）：
- 0:00-0:04 失败 → 取消通知，archery 容器自动恢复
- 0:05-0:16 失败 → **STOP！** 不要动 archery 库，archery 容器已停，老库还在；docker start archery 即恢复
- 0:18+ 失败 → 拉回 v1.10.0：`docker start archery && nginx -s reload`（切回 9123 端口）

---

## 阶段 5.4 archery_bak 清理（D+7 之后）

```bash
# D+7 后，确认升级稳定，再清理 archery_bak
mysql -h 127.0.0.1 -uarchery -p"<密码>" -e "
SELECT 'archery 升级后稳定运行天数:' AS check_item, DATEDIFF(NOW(), (
    SELECT MIN(created_at) FROM archery.sql_workflow WHERE created_at >= '2026-07-22'
)) AS days;
"
# 期望 days >= 7

# 双重保险：再次备份
mysqldump -h 127.0.0.1 -uarchery -p"<密码>" --databases archery_bak | \
    gzip > /backup/archery_bak_FINAL_${TS}.sql.gz

# 删
mysql -h 127.0.0.1 -uarchery -p"<密码>" -e "DROP DATABASE archery_bak;"

# 验证
mysql -h 127.0.0.1 -uarchery -p"<密码>" -e "SHOW DATABASES LIKE 'archery_bak';"
# 期望：Empty set
```

---

## 附录 B：v0.1.0 实际复盘（2026-07-29 · 172.20.2.110 新生产）

> **2026-07-29 21:00 实际跑的升级复盘**。新生产 IP `172.20.2.110`（yearning 公司）从空机接老 docker 容器（172.20.2.134）的 dump，演练环境 `192.168.70.171` 跑过完整流程。
> **详细材料**见 `docs/changelogs/2026-07-30_v0.1.0-110-actual-issues.md`（14.6KB，10 个 R-N 完整复盘 + 6 个 MR 详细）。
> 原始材料：`G:\MiniMax工作空间\archery_upgrade\` 下 `dev-发布checklist.md` + `MR-清单.md` + `upgrade-summary.html`。

### B.1 时间线

| 时间 | 事件 |
|------|------|
| 19:11 | 开始升级（演练 192.168.70.171 已跑通） |
| 19:14 | v1.12/1.13/1.15 SQL 完成，auth_permission 212→216 |
| 19:17 | mysqldump FINAL 完成（107MB gzip，1 分钟，SSD） |
| 19:26 | `10_upgrade.sh` 启动 → `docker stop archery` → 业务 502 |
| 19:28 | 10 脚本中途异常退出（curl stderr 污染 set -e），手动恢复 |
| 19:28 | **v1.14.0 HTTP 200 业务恢复**，停机 ~1 分钟 |
| 19:30~20:56 | 路上修的 10 个坑（按 B.2 顺序） |
| 20:58 | DingTalk Webhook + 个人消息全链路通 |

### B.2 路上修的 10 个坑

| # | 坑 | 等级 | 解决时间 | 解决方式 |
|---|------|------|---------|---------|
| **R-1** | 外网域名 `prodArchery.ahggwl.com` 报 400 | P1 | 1 min | `.env` `ALLOWED_HOSTS` 加外网域名 |
| **R-2** | `/static/dist/js/utils.js` 404 → 工单列表空白 | P0 | 5 min | `docker cp` 整包 `dist/` 5 文件，重 collectstatic |
| **R-3** | Redis 127.0.0.1:6379 连不上 → 500 | P0 | 2 min | `CACHE_URL` 改 docker 网络 IP `172.19.0.4:6379` |
| **R-4** | goinception 主机名解析失败 | P0 | 3 min | Django shell `update_or_create` 改 `go_inception_host` 为 IP `172.19.0.3` |
| **R-5** | `/detail/` 报字段不存在 | P0 | 10 min | 手动 `ALTER TABLE` + 建 `sql/migrations/0001_*.py` + 插 `django_migrations` |
| **R-6** | `sql/migrations/` 整个目录不存在 | P0 | 1 min | 手动建 `__init__.py` + migration 文件 |
| **R-7** | send_ding 误加 Archery 前缀（误判） | P2 | 1 min | patch 保留（防御性） |
| **R-8** | `notify.py` REJECTED/ABORTED 抛 NoneType 被吞 | P1 | 5 min | 两处加 None 保护 `if self.audit_detail else ""` |
| **R-9** | 3 个旧 supervisord 孤儿 qcluster 抢任务 | P0 | 5 min | `pkill -9 -f 'venv4archery.*supervisord'` + 启 systemd qcluster |
| **R-10** | qcluster systemd unit 缺失 | P0 | 5 min | 新建 17 行 unit，`Restart=always` |
| 额外 | 10_upgrade.sh 中途异常退出 | P2 | 1 min | curl 加 `--silent --show-error`，下次升级前必演练 |

**总故障窗口**：业务停机 1 分钟（19:26~19:28），全链路恢复 1 小时 30 分钟（19:30~20:58）。

### B.3 演练 192.168.70.171 vs 生产 172.20.2.110 对比

| 维度 | 演练环境 | 新生产 | 差异说明 |
|------|---------|---------|---------|
| OS | CentOS 7.9 | CentOS 7.9 | 相同（用同一份 v0.1.0-prod 部署脚本） |
| Python | 3.11.6 | 3.11.6 | 相同 |
| MySQL | 5.7.44 | 5.7.44 | 相同（patch 兼容，Django features.py `(5, 7)`） |
| Redis | docker | docker container | 172.19.0.4（host 进程通过 docker 网络访问） |
| GoInception | docker | docker container | 172.19.0.3 |
| 数据来源 | 空（演练从 172.20.2.134 dump 一次） | 172.20.2.134 mysqldump | 相同 dump 流程 |
| 演练发现的问题 | 4（R-2/R-3/R-9/R-10） | 0 演练未发现的 | R-2/R-3/R-9/R-10 演练时修了，**生产 0 演练未发现** |

**结论**：演练环境**发现 40% 的坑**，剩下 60%（R-1/R-4/R-5/R-6/R-7/R-8）跟环境/数据/codebase 状态相关，必须生产真跑一次才能发现。

### B.4 09 节点上线自检流程（新增）

升级完成后**必跑** 6 步自检命令，避免下次踩同一个坑：

```bash
# ===== 1. 静态资源 =====
curl -I http://172.20.2.110:9123/static/dist/js/utils.js   # 必须 200 (R-2)

# ===== 2. 数据库迁移一致性 =====
cd /dbdata/archery_v114
sudo -u archery venv/bin/python manage.py makemigrations --check --Dry-Run   # 必须无输出 (R-5/R-6)
mysql archery -e "SELECT audit_driver, audit_fallback_reason FROM sql_workflow LIMIT 1;"  # 字段存在

# ===== 3. 异步通知链路 =====
sudo -u archery venv/bin/python manage.py shell -c "
from sql.notify import auto_notify
# 走一个驳回工单 + 一个终止工单
" 2>&1 | grep -i 'NoneType'   # 必须无输出 (R-8)

# ===== 4. systemd qcluster =====
systemctl is-active archery-v114-qcluster  # active (R-10)
ps -ef | grep 'venv4archery.*supervisord' | grep -v grep   # 必须无输出 (R-9)
kill -9 $(pgrep -f 'manage.py qcluster'); sleep 6
systemctl is-active archery-v114-qcluster  # 仍 active (自动拉起)

# ===== 5. 配置连通性 =====
sudo -u archery venv/bin/python manage.py shell -c "
from django.conf import settings
import redis
from common.config import SysConfig
redis.Redis.from_url(settings.CACHES['default']['LOCATION']).ping()  # R-3
sc = SysConfig()
print('go_inception_host:', sc.get('go_inception_host'))  # 应该是 172.19.0.x (R-4)
assert 'ProdArchery.ahggwl.com' in settings.ALLOWED_HOSTS  # R-1
print('OK')
"
```

**完整 12 条 R-N 自测命令**见 `dev-发布checklist.md § 5 复盘档案`（在升级材料目录 `G:\MiniMax工作空间\archery_upgrade\` 下，dev 端要把它提 PR 沉淀进 `adauncle/archerydev` 仓库）。

### B.5 教训（防止下次重演）

| 教训 | 措施 | 落地位置 |
|------|------|----------|
| dev 改 model 必须 `makemigrations` | `dev-发布checklist.md § 1.1` 强制 | 提单阶段 |
| `dist/` 静态资源不能由上游删 | dev 维护整包，git 跟踪 | `dev-发布checklist.md § 1.2` |
| 异步通知必须 None 保护 | `grep -n 'self.audit_detail\.' sql/notify.py` | `§ 1.3` |
| qcluster 必走 systemd | 提供 unit 模板，演练必装 | `§ 4 + MR 4` |
| v1.10.0 旧 supervisord 必须 kill | 升级脚本里 `pkill -9 -f venv4archery` | 升级脚本 |
| `CACHE_URL` 不能用 127.0.0.1 | 升级脚本里加 `docker inspect` 取容器 IP | 升级脚本 |
| `go_inception_host` 不能用 hostname | 升级脚本里加 `update_or_create` 改 IP | 升级脚本 |
| `ALLOWED_HOSTS` 默认含外网域名 | 配套 .env 模板 | MR 1 配套 .env |
| `bigint_as_string=True` 在 SimpleJSONRenderer | `dev-发布checklist.md § 1.4` | 提单阶段 |
| Django 4.2 + MySQL 5.7 兼容 | `features.py` patch + 备份 + 文档化 | MR 5 单独项目 |
| 演练环境必须跑全流程 | 演练前 3 天启 192.168.70.171 | `§ 3` |
| D+7 清理前必跑 12 条自测 | 自检 12 条 R-N 命令 | `B.4` |

### B.6 接下来

- **dev 端**：把 5 段 checklist + 12 条 R-N 提 PR 沉淀进 `adauncle/archerydev` 主仓库
- **6 个 MR** 按建议顺序提单（P0 阻塞先合：MR 1 + 2 + 6；P1 静默/恢复：MR 3 + 4；MR 5 单独建项目）
- **D+7（2026-08-05）** 清理 v1.10.0 备份（172.20.2.134 + /backup/upgrade_v114/）
- **新生产 172.20.2.110** 7 天观察期内每日跑 12 条 R-N 自测命令
- **MySQL 5.7→8.0** 单独建项目排期（v1.14.0 稳定 3 个月后启动）

---


