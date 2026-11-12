# 详细设计 M1：服务端 + Windows 采集脚本

- 日期：2026-11-12
- 上游文档：`需求分析/PRD_个人信息采集与查看系统.html`、`系统设计/技术方案_个人信息采集与查看系统.html`
- 里程碑目标：**一台电脑每 5 分钟一条报告入库，curl 能查到**（PRD M1 验收口径）
- 运行环境：服务端部署在自用阿里云 ECS（主机 `caigaozhen`），采集端/查询直连 `http://<ECS公网IP>:8100`；全程 HTTP（2026-11-12 确认：不上 HTTPS，接受明文传输，无需证书、无需反代）
- 主数据库（2026-11-12 确认）：**MySQL 8.0**，复用 ECS 上已运行的 docker 容器 `mysql:8.0`；**不使用 Redis**（设计中无必须用它的场景）；采集端补推队列仍为本地 SQLite

## 1. M1 范围裁剪（相对完整方案）

| 能力 | M1 做法 | 完整做法（后续里程碑） |
|---|---|---|
| 设备鉴权 | 固定开发令牌：两端读同一个 `dev_token.txt`，请求头 `X-Device-Token` | M2 绑定码 + 服务器签发设备令牌 |
| 主人登录/JWT | 不做（查询接口暂用同一开发令牌保护） | M4 |
| 聚合表 / 历史查询 / 导出 | 不做 | M4 |
| 30 天清理 | 做（一条 SQL，成本为零） | 同 |
| 托盘/打包/开机自启 | 不做，命令行运行 | M2 |
| 断网补推队列 | 做（采集端核心逻辑，早验证） | M2 沿用 |

## 2. 代码目录结构（`code/`，PyCharm 项目根）

```
code/                   # PyCharm 项目根（.venv、.idea 在这层）
├── server/             # FastAPI 服务端
│   ├── app.py          # 入口：路由 + 生命周期
│   ├── db.py           # MySQL 连接与建表（pymysql）
│   ├── ingest.py       # 报告接收：校验、去重、入库
│   ├── query.py        # 设备列表 / latest 查询
│   ├── auth.py         # 开发令牌校验依赖
│   ├── cleanup.py      # 30 天清理任务（APScheduler）
│   ├── config.py       # 环境变量读取（DB 连接参数、令牌文件路径）
│   ├── dev_token.txt   # 开发令牌（.gitignore 排除）
│   └── requirements.txt    # fastapi uvicorn apscheduler pymysql
├── collector/          # Windows 采集端（脚本版）
│   ├── main.py         # 主循环：5 分钟 ±30s 抖动
│   ├── metrics.py      # psutil 采集 → metrics dict
│   ├── foreground.py   # 前台窗口采样计时
│   ├── ipinfo.py       # 本机/公网 IP（公网缓存 30 分钟）
│   ├── queue.py        # 本地 SQLite 补推队列
│   ├── config.py       # config.yaml 读取
│   ├── config.yaml     # server_url / device_id / 周期
│   └── requirements.txt    # psutil pywin32 pyyaml requests
└── tests/
    └── smoke.ps1       # 冒烟：启动服务→模拟上报→curl 查询
```

约定：Python ≥3.11；服务端不引入 ORM，用 `pymysql` 直接写 SQL；两个子项目独立 `requirements.txt`（依赖统一装进 `code/.venv` 这一个 venv，适配 PyCharm 单解释器；ECS 部署时只用 `server/requirements.txt`）。数据库连接参数一律走环境变量（`DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME`），**密码不得写进代码**。

## 3. 服务端详细设计

### 3.1 建表 SQL（db.py，启动时幂等执行）

```sql
CREATE TABLE IF NOT EXISTS devices (
  id             VARCHAR(32)  PRIMARY KEY,          -- 如 "pc-home"，M1 由上报方自带
  name           VARCHAR(64)  NOT NULL,
  type           VARCHAR(16)  NOT NULL CHECK (type IN ('windows','android')),
  token_hash     CHAR(64)     NOT NULL,             -- sha256(dev_token)
  created_at     BIGINT       NOT NULL,             -- epoch 秒
  last_report_at BIGINT       NULL                  -- 每次成功入库时更新
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reports (
  report_id    CHAR(36)  PRIMARY KEY,               -- uuid v4，天然幂等
  device_id    VARCHAR(32) NOT NULL,
  collected_at BIGINT    NOT NULL,
  received_at  BIGINT    NOT NULL,
  payload_json JSON      NOT NULL,                  -- metrics 原样存 JSON
  KEY idx_reports_dev_time (device_id, collected_at),
  CONSTRAINT fk_reports_device FOREIGN KEY (device_id) REFERENCES devices(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

在线判定不入库：查询时用 `last_report_at` 与当前时间差 ≤900 秒计算。

### 3.2 API 定义

| 方法 | 路径 | 请求 | 成功响应 | 错误 |
|---|---|---|---|---|
| POST | `/v1/reports` | `{"reports":[<report>,...]}`，report 即技术方案 3.1 协议包（单条也包数组） | `{"accepted":n,"duplicated":m,"rejected":[...]}` | 401 令牌错；422 结构非法 |
| GET | `/v1/devices` | — | `[{"id","name","type","online","last_report_at"}]` | 401 |
| GET | `/v1/devices/{id}/latest` | — | 最新一条 report 的完整 JSON + `received_at` | 404 设备无数据；401 |
| GET | `/healthz` | 无鉴权 | `{"ok":true,"db":true}` | — |

鉴权依赖 `auth.py`：读请求头 `X-Device-Token`，`sha256` 后与 `devices.token_hash` 匹配（`/v1/reports`）；查询接口 M1 同样比对该开发令牌。

### 3.3 接收校验规则（ingest.py，逐条独立处理，部分失败不整批拒绝）

1. `report_id` 为合法 uuid4 且未入库 → MySQL `INSERT IGNORE`（主键冲突时受影响行数为 0），行数为 0 则计入 `duplicated`。
2. `collected_at` 为整数且 `|received_at - collected_at| ≤ 86400` → 否则 `rejected:{reason:"timestamp"}`。
3. `device_id` 存在且未解绑 → 否则 `rejected:{reason:"device"}`。
4. `metrics` 为对象 → 否则 `rejected:{reason:"metrics"}`。
5. 成功入库后更新 `devices.last_report_at = received_at`（取该批最大时间）。

### 3.4 清理任务（cleanup.py）

APScheduler 每日 03:07 执行：`DELETE FROM reports WHERE collected_at < now-30d`；每周日执行 `OPTIMIZE TABLE reports` 回收空间（MySQL 版的 VACUUM）。

### 3.5 部署与数据库准备（阿里云 ECS）

1. **一次性**：在 MySQL 容器里建库建账号（不用 root 连接业务）：
   ```bash
   docker exec -it mysql mysql -uroot -p
   CREATE DATABASE info_collect CHARACTER SET utf8mb4;
   CREATE USER 'info'@'%' IDENTIFIED BY '<强密码>';
   GRANT ALL ON info_collect.* TO 'info'@'%';
   ```
2. 上传 `code/server/` 到 ECS（如 `/opt/info-collect/server/`），`pip install -r requirements.txt`（含 pymysql）。
3. 放置 `dev_token.txt`（与 Windows 采集端同一份内容）。
4. 配置环境变量：`DB_HOST=127.0.0.1`、`DB_PORT=3306`、`DB_USER=info`、`DB_PASSWORD=<强密码>`、`DB_NAME=info_collect`（**密码不进代码、不进 git**）。本机开发阶段 `DB_HOST=<ECS公网IP>`（PowerShell：`$env:DB_HOST="x.x.x.x"`），部署到 ECS 后改回 `127.0.0.1`。
5. 启动：`nohup uvicorn app:app --host 0.0.0.0 --port 8100 &`（启动时 `init_db()` 自动幂等建表）。
6. 阿里云安全组：放行入方向 TCP 8100；`GET http://<ECS公网IP>:8100/healthz` 返回 200 即通。
7. 数据库端口 3306 当前对公网开放（`0.0.0.0:3306`），存在被爆破风险——**建议**：服务端只经 `127.0.0.1` 访问，3306 用强密码；有条件时在安全组把 3306 源 IP 限定或关闭公网访问（Redis 6379 同理）。

## 4. Windows 采集端详细设计

### 4.1 主循环（main.py）

```
启动 → 读 config.yaml → 确保 dev_token 存在
loop:
    metrics = collect_all()            # metrics.py + foreground.py + ipinfo.py
    report  = build_report(report_id=uuid4(), device_id, collected_at=now, metrics)
    ok      = queue.flush_pending()    # 先补历史（旧→新，批量）
    if not ok_send(report): queue.push(report)
    sleep(300 + random.uniform(-30, 30))
```

Ctrl+C 退出；异常全部捕获记日志，循环不崩。

### 4.2 采集函数清单（metrics.py）

| 函数 | 返回字段 | 实现 | 失败行为 |
|---|---|---|---|
| `cpu()` | model, cores, percent | `platform.processor()` / `psutil.cpu_count` / `psutil.cpu_percent(interval=1)` | 单字段 null |
| `memory()` | total, used | `psutil.virtual_memory()` | null |
| `disks()` | [{name,total,used}] | `psutil.disk_partitions()` + `disk_usage` | [] |
| `gpu()` | vendor, model, percent | pynvml；不可用则 null | null（M1 允许缺省，M2 补 wmi） |
| `battery()` | health_percent | `psutil.sensors_battery()`（无则 null） | null |
| `display()` | resolution | `user32.GetSystemMetrics(0/1)` | null |
| `net()` | sent_bytes, recv_bytes | `psutil.net_io_counters()` 相邻差值（首包为 0） | null |
| `uptime()` | uptime_seconds | `time.time() - psutil.boot_time()` | null |
| `ips()` | local[], public, mac[] | `psutil.net_if_addrs()`；公网 api.ipify.org，缓存 30 分钟，失败 null | 部分 null |
| `foreground(seconds)` | app, title_head, active_seconds | 见 4.2.1 | "系统空闲" |

#### 4.2.1 前台软件计时（foreground.py）——M1 唯一有算法含量的模块

- 采样法：主循环外起守护线程，每 2 秒采一次 `GetForegroundWindow → GetWindowThreadProcessId → psutil.Process(pid).name()`；焦点为 0 或属锁屏/桌面进程（`dwm.exe`、`explorer.exe` 且无窗口标题）记为 `system_idle`。
- 计数器：`{进程名: 秒数}`，每 2 秒给当前焦点进程 +2。
- 每个上报周期：取计数快照，选占比最大的进程作为 `app`，其秒数作为 `active_seconds`（上限 300），`title_head` 取该进程任一窗口标题前 40 字符；随后清零计数。
- 已知局限（接受）：单值上报丢失次活跃软件——M2 升级为 `foreground_list:[{app,seconds}...]`，协议预留数组兼容。

### 4.3 补推队列（queue.py）

- 本地 SQLite `pending(report_id TEXT PRIMARY KEY, collected_at INTEGER, payload_json TEXT)`。
- `push()`：入队；超过 2016 条（7 天 ×288）删最旧。
- `flush_pending()`：按 `collected_at` 升序取最多 100 条批量 POST；成功即删除；网络失败返回 False，下轮再试。
- 发送超时 10 秒，不重试（下轮天然重试）。

### 4.4 配置（config.yaml）

```yaml
server_url: "http://<ECS公网IP>:8100"   # 直连云服务器，全程 HTTP
device_id: "pc-home"
device_name: "家里电脑"
interval_seconds: 300
jitter_seconds: 30
token_file: "../server/dev_token.txt"   # M1 开发共享令牌
```

## 5. 联调与验收（tests/smoke.ps1）

1. 数据库已按 §3.5.1 建好、环境变量已配；本机启动 server → `GET http://127.0.0.1:8100/healthz` 200（部署后改测 ECS 地址）。
2. 手工 POST 一条合法 report → `accepted:1`；重发同 `report_id` → `duplicated:1`。
3. POST 错误令牌 → 401；POST 未来时间戳 → `rejected:timestamp`。
4. 运行 collector 1 小时 → `GET /v1/devices` 显示 `pc-home` online；`latest` 返回最新 metrics 完整。
5. 拔网线 10 分钟再恢复 → 队列补推，缺口 ≤1 条。

## 6. 编码顺序（提交粒度）

S1 server 骨架+建表+healthz → S2 ingest+鉴权+去重 → S3 devices/latest 查询 → S4 cleanup → S5 collector metrics+ips → S6 foreground 计时 → S7 queue 补推 → S8 主循环+联调冒烟。每步可独立运行验证。
