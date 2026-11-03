# InfoCollect 开发流程

> 面向"改这个项目的人"（大概率就是未来的自己）。只写本项目真实存在的命令和约定，
> 每条命令都对照过仓库里的脚本；仓库里没有依据的地方用 ⚠️ 标出。
>
> 配套文档：设计决策与验收标准见 `design.md`，各端用法见 `win/` `mobile/` `supabase/` 下的 README。

---

## 1. 环境与依赖

### 1.1 win/（Windows 采集端，Python）

| 项 | 值 | 依据 |
|---|---|---|
| 系统 | Windows 10 / 11 | 根 README |
| Python | 3.10+（本机开发用的是 3.14） | 根 README + 历史 `__pycache__` 的 cpython-314 |
| 第三方依赖 | **零**（托盘/图标/UI 全是 ctypes + 标准库） | `win/` 无 requirements.txt，也不需要 |
| 打包依赖 | PyInstaller（仅打包需要） | `win/build_exe.bat` 自检并提示安装命令 |

**日常命令**（都在 `win\` 目录下，`-X utf8` 必带，否则中文标题乱码）：

```bash
py -3 -X utf8 app.py tray          # 托盘常驻（等价双击 start_silent.bat）
py -3 -X utf8 app.py run           # 前台调试，有控制台日志
py -3 -X utf8 app.py stop          # 正常退出托盘实例
py -3 -X utf8 app.py report        # 今日报表
py -3 -X utf8 app.py ui            # 配置界面
py -3 -X utf8 app.py status        # 数据位置 / 进程状态 / 待上传数
py -3 -X utf8 app.py cloud --ping      # 云端配置与连通性自检
py -3 -X utf8 app.py cloud --dry-run   # 看要上报什么，不真发
py -3 -X utf8 app.py upload        # 手动推一次
```

**调试用 bat**（双击即用，全部实测存在）：`start.bat`（前台）、`start_silent.bat`（托盘）、
`stop.bat`、`config_ui.bat`、`report.bat`、`install_autostart.bat` / `uninstall_autostart.bat`。

### 1.2 mobile/（uni-app · Vue3 + Vite）

| 项 | 值 | 依据 |
|---|---|---|
| Node + npm | 无版本锁定 ⚠️ 仓库里没有 `.nvmrc` / `engines` 字段，建议本地 Node ≥ 18（Vite 5 的要求） | `mobile/package.json` |
| 依赖锁定 | **package.json 里全部写死精确版本**（DCloud 日期版本号，禁止 `^`）；另有 package-lock.json。Vue 3.4.21 / Vite 5.2.8 与该版 uni-app 的 peer 要求绑定，**不要单独升级其中任何一个** | `mobile/package.json` + 其 README |
| 本地依赖 | 已 `npm install`（node_modules 在本机存在） | 实测 |

```bash
cd mobile
npm install          # 首次约 5 分钟，网络慢加 --fetch-timeout=600000
npm run dev:h5       # 浏览器预览 + 热更新（日常开发用这个）
npm run build:h5     # 产出 dist/build/h5
npm run build:app    # 产出 dist/build/app，给 HBuilderX 云打包用
```

APK 云打包走 HBuilderX，步骤见 `mobile/README.md`，不在命令行里。

### 1.3 环境变量与 Supabase 配置

本项目**不用 .env 文件、不用环境变量管配置**，全部走两条路：

1. **win 端运行时配置**：`%APPDATA%\InfoCollect\config.json`（可用 `app.py ui` 界面改）。
   Supabase 的项目地址 + anon key 写在 `upload` 段，格式见 `supabase/README.md` §五步接通。
   改完 30 秒内被托盘进程热加载，不用重启。
2. **唯一的环境变量** `INFOCOLLECT_HOME`：测试脚本用它把数据目录指到临时目录，
   保证测试绝不碰真实数据（见 `dev/test_upload_protocol.py`）。日常开发不需要手动设。

安全约定：anon key 敢放进 config.json / exe 的前提是 `schema.sql` 里 anon **只有 insert 没有 select**，
这个权限模型是底线，改 schema 时不能破坏（见 §3）。

---

## 2. 编码与协作规范

### 2.1 版本控制现状 ⚠️

git 仓库根在 `F:\self-practice`（上级），**info-collect 目录本身尚未提交过**。
pre-commit 配置在仓库根 `F:\self-practice\.pre-commit-config.yaml`，包含三个钩子：

| 钩子 | 阶段 | 作用 |
|---|---|---|
| commitizen v4.8.2 | commit-msg | 强制 Conventional Commits 格式 |
| check-added-large-files（≤1024KB） | pre-commit | 挡大文件（对 exe 入库是个天然阻力，呼应根目录整理时的待确认项） |
| check-merge-conflict + gitleaks v8.24.0 | pre-commit | 冲突标记 / 密钥泄露检查 |

钩子生效前提：项目文件被 `git add` 后走正常提交流程，且本机装过 `pre-commit install`。

### 2.2 分支策略 ⚠️（仓库无既有约定，给建议）

单人项目，不需要 feature branch 流程。建议最低限度：

- 上级仓库或项目独立建仓后，`main` 保持可运行（跑得通 §4 的两个测试）；
- 稍大改动（改采集状态机、改协议）开 `dev/xxx` 或直接在 main 上做但**提交前必须跑测试**；
- 不用强制 PR / 代码评审——单人项目用"提交前自查清单"替代：
  ① 测试通过 ② README 相关段落同步了 ③ 没把真实 key / %APPDATA% 数据写进仓库。

### 2.3 提交信息

沿用 commitizen 钩子强制的 **Conventional Commits**（历史提交 `feat: test`、`chore: 添加 pre-commit 配置文件` 已是这个风格）：

```text
feat: 上报增加关机前推送
fix: 闲置回填把锁屏时间算成了活跃
docs: 补充 supabase 免费版暂停行为
chore: 更新 uni-app 依赖
```

### 2.4 格式化与静态检查 ⚠️（仓库无配置，给建议但不引入重依赖）

- Python 端：现有代码风格是"注释即文档"，没有 lint 配置。最小做法：提交前
  `py -3 -m py_compile win\*.py` 保证语法可编译。若想加 lint，**建议只加 ruff（单二进制、零配置可跑）**，不要上 black+isort+flake8 全家桶；是否引入待定。
- mobile 端：无 eslint/prettier 配置 ⚠️。uni-app 工程加 eslint 收益低，建议维持现状，
  以 `npm run dev:h5` 无报错 + 测试通过为准。

---

## 3. 数据库与后端流程（supabase/）

**没有 migration 框架、没有本地 Supabase 实例** ⚠️——不用 supabase CLI / Docker，
流程就是"改幂等 SQL → Dashboard 全量重跑"。原因是单人 + 免费版 + 脚本刻意写成可重复执行，
引入 migration 工具属于过度设计。

### schema 变更流程（唯一流程）

1. 改 `supabase/schema.sql`。**硬性约定：保持幂等**——表用 `create table if not exists`、
   策略用 `drop policy if exists` + `create policy`、函数 `create or replace`。
   这样新环境一条脚本建全量，老环境重跑不炸。
2. Supabase Dashboard → SQL Editor → 整段粘贴 → Run。
   （只改了 `push_sessions` 函数时，可只跑 `push_fn.sql`，它末尾带 `notify pgrst, 'reload schema'` 刷新缓存。）
3. 验证：
   ```bash
   cd win
   py -3 -X utf8 app.py cloud --ping     # 报 PGRST202 = 函数没建好
   py -3 -X utf8 app.py cloud --dry-run
   py -3 -X utf8 app.py upload           # 真发一次
   ```
   再到 Table Editor 看 `sessions` 有没有行。

### 环境切换

只有**一个线上 Supabase 项目**（ap-south-1），没有 dev/prod 分离 ⚠️。
本地/离线调试**不碰云端**，用 `dev/mock_server.py` 顶替：

```bash
# 终端 A：起假服务端（模拟 Supabase 协议，端口用位置参数传）
py -3 -X utf8 dev/mock_server.py --postgrest 8766
# 之后把 config.json 的 upload.endpoint 指到 http://127.0.0.1:8766，
# 或手机 H5 的「项目地址」填 http://127.0.0.1:8766（邮箱密码随便填）
```

**权限底线（改 schema 前必读）**：anon 只 insert / authenticated 只 select / 谁都没有 update、delete；
客户端上报必须走 `push_sessions` security-definer 函数（直接写表需要 SELECT，anon 没有，会被 401 挡）。
函数里 `set search_path = public` 不能删（防提权）。完整推理见 `supabase/README.md`。

---

## 4. 测试与质量

### 现有测试（两层，都是提交前必跑）

| 层 | 命令 | 覆盖 | 位置无关性 |
|---|---|---|---|
| L1 纯函数单测 | `node dev/test_format.mjs` | 时长格式化 / 日期推算 / 聚合，24 个断言；只依赖 `mobile/src/utils/format.js`（不 import uni API，所以能在 Node 跑） | 在仓库根跑 |
| L2 协议端到端 | 终端 A `py -3 -X utf8 dev/mock_server.py --postgrest 8766`；终端 B `py -3 -X utf8 dev/test_upload_protocol.py 8766` | endpoint 归一化、payload 形状、首推、重推幂等；用 `INFOCOLLECT_HOME` 指到临时目录，**不碰真实数据** | 在仓库根跑 |
| 手工验收 | `design.md` 的验收标准 | 采集口径、报表、自启等无法自动化的部分 | — |

### 建议的分层与最小可行做法

- **维持 L1 + L2 即可**，这是本项目的最优性价比点：核心风险全在"上报协议两边说好了什么"，
  L2 恰好测这个。不值得为 win 端再引 pytest/UI 自动化（无依赖、强 Windows API，自动化成本 > 收益）。
- 唯一建议补的：`sampler.py` 状态机（粘滞切换 / 闲置回填）是纯逻辑最多的模块 ⚠️，
  目前只有 L2 间接覆盖。若以后改它，参照 `test_upload_protocol.py` 的套路
  （构造 Store + 喂状态序列）补一个同类脚本放 `dev/`，不要引测试框架。
- 改动后没跑测试不提交；手机端真机表现（状态栏安全区等）只能装机后看，见 `mobile/README.md` 已知限制。

---

## 5. 交付与发布

### win 端（exe）

```bash
py -3 -m pip install pyinstaller   # 仅首次
cd win && build_exe.bat            # 产物 dist\InfoCollect\（约 30MB）
```

- 发布物 = **整个 `dist\InfoCollect\` 目录**（含自动拷入的 6 个 bat），目标机器不需要 Python。
- `build_exe.bat` 先跑 `make_version_info.py`（版本号来自 `config.APP_VERSION`），
  再以 `--version-file` 打包，exe 文件属性与界面版本一致。
- 用 `--onedir` 不用 `--onefile`（启动快 1~3 秒、少被杀软误报），理由已写在 build_exe.bat 注释里。
- 验证：双击 exe 出托盘图标 → 配置界面勾自启 → `app.py autostart status` 显示路径正确 →
  右键 exe 属性确认版本 → 确认 `report.bat` 等 6 个 bat 都在。
- **分发给第二台机器后**，在那台机器上配置"本机显示名"，否则手机端分不清设备。

### 版本号

| 端 | 现状 | 约定 |
|---|---|---|
| mobile | `package.json` version=1.0.0、`manifest.json` versionName=1.0.0 / versionCode=100 | 三处同步；versionCode 递增（100 → 101…） |
| win | `config.APP_VERSION = "0.3"`；exe 由 `version_info.txt` 写入文件版本 `0.3.0.0` | 改版本只改 `config.APP_VERSION`，重新执行 `build_exe.bat` |

- 不引入 changelog 文件，版本说明写在对应提交信息 + `design.md` 的完成状态行里。
- `version_info.txt` 是生成物，不要手改。

### 发布步骤（mobile 云打包）

`mobile/README.md` §打成 APK：HBuilderX 导入目录 → 发行 → 原生App-云打包 → 用公共测试证书 → 等 5~15 分钟拿 APK 链接。H5 备用：`dist/build/h5` 扔任意静态托管。

### README / docs 维护规则

1. **行为改了，文档同一次提交里改**：改上报协议 → `win/README.md` 代码地图 + `supabase/README.md`；
   改配置项 → `win/README.md` 配置表；改手机端页面 → `mobile/README.md`。
2. **踩坑即记录**：遇到"报错 → 原因 → 处理"的问题，加进对应 README 的坑表（`supabase/README.md` 的坑表是好样板），不另开笔记文件。
3. 设计层变更（采集口径、权限模型、存储结构）更新 `docs/design.md` 的"已定下来的决策"表；
   需求/设计/数据库/运维的变更同步更新 `docs/requirements.md`、`docs/detailed-design.md`、
   `docs/database-design.md`、`docs/operations.md`；
   根 README 只维护"是什么 / 怎么开始 / 数据在哪"，细节下沉到各端 README。

---

## 附：本仓库无法回答、只能给建议的项汇总

| 项 | 现状 | 建议 |
|---|---|---|
| git 仓库归属 | 项目整体 untracked，挂在 `F:\self-practice` 仓库下 | 独立 `git init` 或纳入上级仓库，二选一（待确认） |
| 分支策略 | 无历史可循 | 单人项目：main 可运行 + 提交前跑测试 |
| formatter/linter | 无任何配置 | Python 最低用 py_compile；要 lint 只考虑 ruff |
| Node 版本约束 | 无 engines 字段 | package.json 加 `"engines": {"node": ">=18"}`（动 package.json，需确认） |
| win 版本号 | 已落地：`config.APP_VERSION` + exe 版本资源 | 改版本只改 `config.APP_VERSION`，重跑 `build_exe.bat` |
| dev/prod 环境 | 只有一个 Supabase 项目 | 单人可接受；若建第二个项目，环境差异全部落在 config.json 的 upload 段 |
