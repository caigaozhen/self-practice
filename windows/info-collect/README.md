# InfoCollect · 电脑时间去向

记录 Windows 上「你在哪个程序里待了多久」，存本地 SQLite，可选同步到 Supabase，手机浏览器随时看。

当前版本：**v0.3**（2026-11-02）。

## 四个部分

| 目录 | 是什么 | 跑在哪里 |
|---|---|---|
| `win/` | 采集端：Python 源码，也可打包成 exe | 每台 Windows 电脑 |
| `mobile/` | 查看端：uni-app（Vue3），一套代码出 APK 或 H5 | 手机 |
| `supabase/` | 云端：建表脚本 + 权限模型 | 一个项目，可选 |
| `dev/` | 本地测试工具（假服务端、纯函数测试） | 开发时用 |
| `docs/` | 设计文档与踩坑记录 | 不用管 |

## 立刻开始（Windows）

双击 `win\start_silent.bat` → 右下角出现图标 → 开始采集。

右键图标可以：查看今日报表 / 打开配置界面 / 立即推送 / 暂停 / 开机自启 / 退出。

## 想在手机上看

按 `supabase/README.md` 走一遍，大约 5 分钟：建表 → 创建一个登录用户 → 手机打开页面填三个值 → Windows 端开启上报。

## 数据在哪

`%APPDATA%\InfoCollect\`

| 文件 | 内容 |
|---|---|
| `infocollect.db` | 全部会话记录（SQLite，可用 DB Browser 打开） |
| `config.json` | 配置 |
| `infocollect.log` | 运行日志（排查用，静默运行时唯一的信息来源） |

## 环境

- Windows 10 / 11
- Python 3.10+（`win/dist/InfoCollect/` 里的 exe **不需要**）
- **零第三方依赖**：托盘、图标、界面全部用 ctypes + 标准库手写

## ⚠️ 移动这个目录之后必须做一件事

自启动在注册表里存的是**绝对路径**。目录一改，它就指向不存在的文件：

```bash
# 打包版（在新目录下双击 install_autostart.bat 也一样）
.\InfoCollect.exe autostart on

# 源码版
cd win
py -3 -X utf8 app.py autostart on
```

不做这一步的话，下次开机程序不会启动，**而且没有任何报错**——`pythonw` / 无控制台的 exe 失败都是静默的。只能靠 `infocollect.log` 的「最后心跳」事后发现。

v0.3 起，托盘启动时会自动体检：路径失效会弹通知，菜单里出现「开机自启：路径已失效，点此修复」，点一下就能重写。详见 `docs/operations.md` §5。

## 文档

| 文档 | 内容 |
|---|---|
| `docs/windows开机自启选型.md` | **开机自启**：当前用的 Run 键方案详解、六个场景的操作步骤、其他方案对比与选型理由 |
| `docs/requirements.md` | 需求分析：范围、功能/非功能需求、验收标准、追踪矩阵 |
| `docs/database-design.md` | 数据库设计：本地 SQLite + 云端 Postgres、RLS、幂等 |
| `docs/detailed-design.md` | 详细设计：模块、采样状态机、上报、自启、并发与异常 |
| `docs/operations.md` | 部署与运维：构建 exe、开机自启原理与操作、升级、排障 |
| `docs/design.md` | 设计决策、采集口径、踩坑记录、验收标准 |
| `docs/dev-workflow.md` | 开发流程：环境与依赖、测试、schema 变更、打包发布 |
| `win/README.md` / `mobile/README.md` / `supabase/README.md` | 各端用法 |

## 开发与测试

```bash
# 手机端纯函数测试（不需要 uni 环境，24 个断言）
node dev/test_format.mjs

# 上报链路端到端测试：终端 A 起假服务端（模拟 Supabase 协议）
py -3 -X utf8 dev/mock_server.py --postgrest 8766
# 终端 B 跑协议测试（用临时目录当 %APPDATA%，不碰真实数据）
py -3 -X utf8 dev/test_upload_protocol.py 8766

# 本地假服务端：给手机 H5 / Windows 上报当调试后端
py -3 -X utf8 dev/mock_server.py            # generic 模式，只打印收到的 JSON
```

各端的构建方式见各自 README（`win/build_exe.bat` 打包 exe；`mobile` 用 `npm run build:h5` / `build:app`）。
