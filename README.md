# Codex 监控月盘

这是一个随 Codex 桌面进程运行的 Windows 浮动仪表盘。窗口固定为 390×275，可拖动、置顶，也可以手动关闭；Codex 退出后仪表盘自动关闭。

## 功能

- 不显示 5 小时额度，也不加入天气效果。
- 使用提供的月球图片作为完整背景；额度越充足越接近满月，消耗后通过 33 张柔和过渡的月相图片逐步变为弦月，不使用硬裁切。
- 整体外框和信息区均为圆角玻璃效果；表头使用 Codex 雷达的深蓝色，表头以下使用参考图中的 `#27384d` 灰蓝色，文字不带黑色底框。
- 标题使用比上一版小一号的常规字重，移除 `TOKEN OBSERVER` 副标题，同步状态靠近右侧控制区。
- 显示账户近期额度剩余百分比，并在额度消耗时由有色渐变为低饱和灰色。
- 显示真实账户摘要中的“可用手动重置”次数，并上下分行显示额度自动重置时间与手动重置到期时间。
- 最近 7 天、消耗总 TOKEN 和本次打开 Codex 后的 token 使用量压缩在同一行显示，不使用柱状图。
- Codex 工作时才会以 40 FPS 显示偶尔划过的流星；停止使用后，月球周围会逐渐浮现并闪烁星点。
- 顶部设置按钮打开可拖拽的 RGB、透明度和天体对比度滑块，设置会保存到 `%USERPROFILE%/.codex/codex-moon-dashboard-settings.json`。
- 顶部收起按钮可切换为参考图风格的单行胶囊，按“时间 · 工作状态 · 额度 · 本次 Token”显示；再次点击恢复完整仪表盘。
- 支持星空点缀、拖动、手动关闭和置顶切换。

## 安装与自动启动

在 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
& .\scripts\install.ps1
```

安装脚本会创建 Windows Startup 快捷方式，并启动生命周期监视器。监视器只关注 WindowsApps 下的 Codex 桌面进程（`ChatGPT.exe` / `codex.exe`），忽略独立 app-server：Codex 打开时启动仪表盘，Codex 全部退出时关闭仪表盘。

移除自动启动：

```powershell
& .\scripts\uninstall.ps1
```

## 手动预览

```powershell
python .\scripts\dashboard.py
```

## 数据说明

token 统计来自本地 `%USERPROFILE%\.codex\state_5.sqlite` 中线程的 `tokens_used`，按线程更新时间汇总近 7 天和近 30 天；本次使用量按当前 Codex 生命周期及线程创建时间计算。

额度百分比和自动重置时间来自最新 rollout 的 `rate_limits` 元数据。手动重置次数和手动到期时间来自 Codex Desktop 使用的官方只读账户摘要接口 `/wham/rate-limit-reset-credits`，凭证只在内存中使用，不记录 token 或响应内容。接口暂不可用时显示 `--`，不会把额度周期的 `resets_at` 冒充成手动重置次数。
