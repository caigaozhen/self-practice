# mobile · 手机 App（uni-app）

用 **uni-app（Vue3 + Vite）** 写的查看端：一套代码既能出安卓 APK，也能出 H5 网页。

## 目录

```
mobile/
├── package.json          依赖与脚本（DCloud 私有版本号，不能用 ^）
├── vite.config.js        @dcloudio/vite-plugin-uni
├── index.html            H5 的宿主页
└── src/
    ├── main.js           createSSRApp 入口
    ├── App.vue           全局样式
    ├── pages.json        路由 + 导航栏
    ├── manifest.json     应用信息（appid 留空，打包时 HBuilderX 生成）
    ├── pages/
    │   ├── index/index.vue   主界面：日期 / 总时长 / 设备筛选 / 三页签
    │   └── setup/setup.vue   连接设置：地址 + anon key + 账号密码
    ├── utils/
    │   ├── format.js     纯函数：时长、日期、聚合（可在 Node 里测）
    │   └── api.js        Supabase 认证 + REST 查询（uni.request）
    └── static/logo.png   应用图标（由 win/icon.py 生成）
```

## 开发

```bash
cd mobile
npm install          # 首次约 5 分钟；网络慢可加 --fetch-timeout=600000
npm run dev:h5       # 浏览器预览，改代码热更新
npm run build:h5     # 产出 dist/build/h5
npm run build:app    # 产出 dist/build/app（给 HBuilderX 打包用）
```

依赖版本是 DCloud 的日期版本号（`3.0.0-5030420261029001`），**必须写死，不能用 `^`**。
Vue 锁在 3.4.21、Vite 锁在 5.2.8，和这版 uni-app 的 peer 要求一致。

## 测试

```bash
node dev/test_format.mjs     # 24 个断言，测时长格式化 / 日期推算 / 聚合
```

`format.js` 不依赖 uni 的任何 API，所以能在 Node 里直接跑；`api.js` 依赖 `uni.request`，只能跑在 uni 环境里。

## 打成 APK（云打包）

1. 打开 **HBuilderX**（本机已有：`D:\HBuilderX`）
2. 文件 → 导入 → 打开目录 → 选 `F:\self-practice\windows\info-collect\mobile`
3. 菜单 **发行 → 原生App-云打包**
4. Android 页签里：
   - **应用名称** `时间去向`
   - **AppID** 如果为空，点右侧「重新获取」申请一个（需登录 DCloud 账号，免费）
   - 图标：选 `src/static/logo.png`（512×512）
   - 勾「使用公共测试证书」（自己用足够；上架才需要正式证书）
   - 打包方式选「传统打包」
5. 点「打包」，等 5~15 分钟（免费通道会排队），完成后给出 APK 下载链接

> 云打包把资源上传到 DCloud 服务器编译，**不需要本机装 Android SDK**。
> 想完全离线打包要装 Android SDK + JDK17，工作量大得多，自己用没必要。

## 装到手机上

- 安卓：下载 APK 直接装（会提示"未知来源"，允许即可）
- iPhone：云打包也能选 iOS，但需要苹果开发者证书（$99/年）；自己用建议直接用下面的 H5
- H5 备用：把 `dist/build/h5` 扔到任意静态托管，手机浏览器打开后「添加到主屏幕」，效果接近原生

## 三个和网页版不同的地方

| 网页版 | uni-app | 原因 |
|---|---|---|
| `fetch` | `uni.request` | App 端没有 `fetch`，也没有 `XMLHttpRequest` |
| `localStorage` | `uni.setStorageSync` | App 端没有 Web Storage |
| 地址栏 / 链接 | `pages.json` + `uni.navigateTo` | App 里没有 URL |

## 数据链路

```
Windows 采集端 → 本地 SQLite → 每 4 小时推一次 → Supabase → 手机读
```

手机端只读两个视图：

| 视图 | 用途 |
|---|---|
| `v_daily` | 按天聚合：日期 + 设备 + 程序 + 分类 + 秒数 |
| `v_devices` | 设备清单，给顶部筛选 chips 用 |

登录走 Supabase Auth（邮箱密码）；access_token 过期前 60 秒自动用 refresh_token 续期，续不上再重新登录。配置存在本机，不写进代码。

## 已知限制

- 没有「本周/本月」视图，只能按天翻
- 跨午夜那一段，云端按**开始那天**整段算（本地报表是精确切分的，两边会有几十分钟差异）
- 服务端默认不存窗口标题（`include_title: false`），所以看不到"在写哪个项目"，只有程序名和时长
- 没有真机和模拟器，**真机上的状态栏安全区、字体缩放只能装上后看**
