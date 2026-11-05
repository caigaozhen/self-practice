# V0.3 · 每秒自动刷新

> V0.2 的数字只能手点刷新，这一版让它们自己动：`after()` 每秒跑一次；不变的项只采一次，只有会变的项才反复采。

**状态**：✅ 已完成（2026-11-05）。`py_compile` 通过，`--selftest` 退出码 0，exe 已打包验证。

---

## 一、V0.2 → V0.3

| 项 | V0.2 | V0.3 |
|---|---|---|
| 更新方式 | 只有手动点「刷新」 | 每秒自动 + 手动仍可用 |
| 采集策略 | 每次全采一遍（含注册表、分区表） | 静态只采一次，动态每秒采 |
| `cpu_percent` | `interval=0.2`（阻塞 0.2 秒） | `interval=None`（不阻塞） |
| 界面 | Label + Button | 不变 |
| exe 名 | `HardwareInfo.exe` | `HardwareLive.exe` |

代码从 153 行增到 190 行，**没加任何新依赖**。

---

## 二、静态 / 动态怎么分

| 静态（`collect_static()`，启动时一次） | 动态（每秒） |
|---|---|
| 计算机名、系统版本、架构 | CPU 使用率 |
| CPU 型号、物理/逻辑核心 | 内存可用、内存占用 |
| CPU 频率（Windows 上是注册表标称值） | 各盘可用、已用% |
| 内存总量、开机时间、各盘总容量 | — |

静态项收进一个字典，之后所有函数都从它取：

```python
static = collect_static()          # 只调一次

def system_block(st):              # 静态：直接用
    return [f"计算机   : {st['node']}", ...]

def cpu_block(st):                 # 动态：现采
    usage = psutil.cpu_percent(interval=None)
    return [f"CPU 使用 : {usage}%", ...]
```

**为什么不每秒钟全采一遍**：注册表查询和 `disk_partitions()` 都比读内存慢，每秒做一次纯浪费。分开之后，每秒只做「读几个数 + 改标签」这一件事。

磁盘的盘符列表也是静态的（`st["drives"]` 存了盘符、挂载点、总容量），动态只读可用空间——**代价是运行期间插上的 U 盘不会自动出现**，要重启程序。

---

## 三、`after()` 的三件事

```python
def tick() -> None:
    try:
        refresh()
    except Exception as exc:
        label.config(text=f"刷新失败：{exc}")
    finally:
        root.after(REFRESH_MS, tick)   # 排下一次
```

**① 非阻塞**：`after(1000, f)` 只是「登记一个 1 秒后执行 f 的任务」，然后立刻返回。它不是 `sleep`，界面不会卡。

**② 递归排自己**：`tick` 里排下一个 `tick`，形成循环。入口只调一次 `tick()`，不要在 `while` 里调。

**③ `finally` 保证不断链**：刷新抛异常时，`tick` 后面的 `after` 就不会执行，循环从此停住。放进 `finally` 才能「无论成败都排下一次」。

**不会叠加**：只有 `tick` 里排 `after`，按钮的 `refresh` 只刷新、不排队列。实测 3.5 秒内点 5 次手动刷新：

```
3.5 秒内总刷新次数: 9
= 4 次定时（0/1/2/3 秒） + 5 次手动
```

如果按钮也排 `after`，次数会随点击翻倍增长，越点越快。

---

## 四、`cpu_percent` 的两种模式

| 参数 | 行为 | 什么时候用 |
|---|---|---|
| `interval=0.2` | 阻塞 0.2 秒，采完再返回 | 一次性快照（`collect_all()`、命令行打印） |
| `interval=None` | 立刻返回「距上次调用以来」的平均值 | 定时刷新（V0.3 界面） |

`None` 模式的**第一次调用没有基准，必定返回 `0.0`**。所以启动时先"预热"一次并丢掉结果：

```python
psutil.cpu_percent(interval=None)   # 预热，返回值丢弃
```

不预热的话，界面第一秒会显示 `CPU 使用 : 0.0%`，看起来像采错了。

实测每秒采三次：`11.3% → 8.4% → 4.2%`，值在正常变化。

---

## 五、运行 / 打包

```bash
cd F:/self-practice/windows/tkinter-tool/V0.3
py -3 -m pip install -r requirements.txt   # 首次
py -3 app.py                               # 运行（数字每秒自己变）
py -3 app.py --selftest                    # 1.2 秒自动关窗，验证用
双击 build.bat                             # → dist/HardwareLive.exe
```

`import app` 仍然安全，不会弹窗：

```bash
py -3 -c "import app; print(app.collect_all())"
```

---

## 六、验收

- [x] 窗口打开后数字每秒自己变，不用点按钮
- [x] 手动点「刷新」立即更新，且不会让之后的刷新变快
- [x] 启动第一秒就显示真实使用率（不是 0.0%）
- [x] 关窗后进程干净退出（`after` 随窗口销毁一起消失）
- [x] `--selftest` 退出码 0

---

## 七、这一版没做

| 没做 | 原因 | 计划 |
|---|---|---|
| 暂停 / 继续按钮 | 只影响交互，不影响刷新机制 | 需要时加 `after_cancel` |
| 进度条（`ttk.Progressbar`） | 换一套控件体系，是独立知识点 | 可选 |
| 开机时长（"已运行 X 小时"） | `boot_time()` 已有，只差一次减法 | 一行代码的事 |
| 插拔 U 盘自动刷新盘符 | 盘符列表是静态快照 | 改成每秒重扫分区表 |
| 导出 CSV / JSON | 属于"落盘"这条线 | **V0.4** |

**V0.4 方向**：把当前这屏信息存成文件（`csv` 标准库 + `tkinter.filedialog` 选路径），练「标准库读写 + 弹窗交互」。
