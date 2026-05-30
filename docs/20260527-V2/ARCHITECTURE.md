# V2 架构（一张图）

> **正确理解**：仓库叫 **tradeagnt**，里面是 **Pi 外壳 + tradeagnt 垂类能力插件**。  
> 不是「Python 主程序旁边挂了个 Pi」。

```text
┌─────────────────────────────────────────────────────────┐
│  tradeagnt/  （唯一开发仓库 · 垂类 Trade Agent 产品）      │
│                                                         │
│   vendor/pi/          ← Pi 源码（Agent 框架，已拉取）     │
│        │                                                │
│        │  加载 Extension / Skills                       │
│        ▼                                                │
│   pi-extensions/tradeagnt/  ← 【我们写】把能力接到 Pi 里   │
│        │                                                │
│        │  子进程 / CLI 调用                              │
│        ▼                                                │
│   src/tradecat/ + scripts/  ← 【已有】唯一版本交易能力     │
│   (行情/信号/纸面/闸门/TUI 数据)                          │
│                                                         │
│   右栏：tradecat TUI（现有）◄── 同进程或同屏，给人看 KPI   │
└─────────────────────────────────────────────────────────┘

用户 ◄──chat──►  Pi（有 tradeagnt 垂类工具后 = Trade Agent）
```

## 分工（记两句）

| 谁 | 角色 |
|:---|:---|
| **Pi** | Chat Agent **外壳**（对话、tool loop） |
| **tradeagnt（Python）** | **垂类能力**（交易数据 + 模拟盘 + 闸门） |
| **接法** | 在 Pi 里做 **Extension**，工具里去调 `scripts/`、`tradecat agent` |

## 目录

| 路径 | 含义 |
|:---|:---|
| `vendor/pi/` | Pi 上游源码（gitignore，本地 clone） |
| `pi-extensions/tradeagnt/` | 接到 Pi 里的 Extension（v2-base 实现） |
| `src/tradecat/` | 能力实现，**不搬进** Pi 的 TS 里 |
