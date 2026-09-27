# here 从 Qt 到 Electron 的迁移经验

## 1. 先冻结行为基线

迁移不是“把窗口画得相似”，而是把旧程序的可观察行为列成清单。本次固定 `here@2e782b...`，从启动入口、桌面菜单、各设置对话框、worker、handler、消息平台和构建脚本反推功能矩阵。只看主窗口会漏掉历史回滚、微信监听重启、ASR 依赖准备、角色视频解帧和关闭后驻留等能力。

资源核对必须递归进行。浅层目录列表曾让默认动画看起来像是缺失；递归文件数、体积和 `diff -qr` 证明 `assets/defaults` 实际完整。迁移审计应以可重复命令为准，不凭目录印象下结论。

## 2. 保留领域层，只替换 Qt 边界

这里没有把 Agent、记忆、生活计划、主动联系、TTS/ASR/T2I 和消息平台改写成 JavaScript。原非 Qt Python 模块复制到 `backend/`，Electron 只替换：

- `QWidget/QDialog/QSystemTrayIcon` -> `BrowserWindow/<dialog>/Tray`
- Qt signal/slot 和 Queue -> JSONL event/response
- `QFileDialog/QClipboard` -> Electron dialog/clipboard
- Qt 音频与图片显示 -> HTML Audio、Image、Canvas

这样迁移风险集中在边界协议，领域算法仍与原版同源。需要移除 Qt 的公共工具应做最小改造，例如 TextProcessor 用 HTML 清理替代 `QTextDocument`，而不是把整条 TTS 流程重写。

## 3. sidecar 协议必须严格

sidecar 使用 stdin/stdout 的 newline-delimited JSON。stdout 只能写协议，所以启动时保留协议流并把普通 `print` 重定向到 stderr；写消息加锁，避免 TTS、主动联系和 RPC 线程把 JSON 交叉写坏。

协议至少区分：

- `response`: 带 request id 的调用结果或结构化错误
- `event`: dialog/audio/options/status/background 等主动事件
- `ready/fatal`: 启动握手和初始化失败

Electron 主进程维护超时、pending request、进程退出拒绝和白名单 RPC。renderer 不直接访问 Node/Python，所有能力经 context-isolated preload 暴露。

## 4. 系统对话标记是协议，不是角色名

`COT/CHOICE/STAT/SCENE/BGM/CG/NARR` 看起来像特殊角色，但实际上是控制协议。一次实现曾在解析后把“非当前角色名”统一改成当前角色，导致所有系统行为静默失效。正确顺序是：

1. 先识别保留字和旧中文别名。
2. 只对普通角色对话做名称归一。
3. 流中解析到完整对话片段就立即路由。
4. 对系统消息分别进入状态、选项、背景、音乐或 CG 分支。

这种协议必须有自动化测试，不能只靠普通聊天截图。

## 5. Electron 的图片缩放与 Qt 不同

Qt sprite 组件已经包含自然尺寸、可见区域和窗口比例；Web 首版又对容器做了一次比例缩放，真 Electron 中出现双重缩小。最终规则是先取图片或 spritesheet 单帧的自然像素尺寸，乘角色 `sprite_scale`，再用容器上限裁住。浏览器 mock 截图不能替代真 Electron，因为设备缩放、透明窗口和图片解码路径不同。

## 6. 平台接入要同时迁移字段和生命周期

只画 Token 输入框不算对齐。本次发现 Telegram Electron 表单写 `bot_token`，原 adapter 实际读取 `token`；WhatsApp 同样应使用 `api_token`。字段必须直接以 adapter 的 `required_fields/target_fields` 为准。

入站平台还有生命周期：

- 启动时按 `chat_delivery_channel` 创建 bridge。
- 修改系统或消息配置后停止旧 bridge，再启动新 bridge。
- 微信扫码确认后刷新账号 monitor。
- sidecar 退出时停止长轮询。
- 外部回复失败时回退桌面并给出原因。

Telegram/WeChat 支持接收，其他平台按原版只发送；这应在界面和对齐矩阵里明确。

## 7. 数据隔离比代码隔离更重要

不修改原仓库还不够。如果两个桌面框架共用 `~/.local/here`，测试新程序仍可能覆盖旧配置。Electron 为 sidecar 注入独立 `HERE_APP_HOME=<electron userData>/python-data`，默认配置和角色资源只播种到这里。

旧数据迁移采用显式导入：读取用户选择的旧目录，复制允许的子目录，拒绝把当前 Electron 数据目录当源。原路径永远不做原地升级。

## 8. 开发 `.venv` 不是发布运行时

virtualenv 的解释器和 native library 路径通常指向构建机，直接放入 `extraResources` 不能形成可搬运应用。发布流程应：

1. 准备目标平台的 standalone CPython。
2. 安装运行依赖和基础 ASR。
3. 处理 PortAudio 等 native library 的相对链接与签名。
4. 用该解释器真正启动 `rpc_bridge.py` 并完成 ready/ping。
5. 再由 Electron Builder 打包 backend/runtime。

`npm run dist` 现在把这五步串在一起。macOS 无 Developer ID 时只能得到未签名产物；功能完成与可公开分发是两项不同验收。

## 9. 验证要分层

本次有效的验证顺序是：

1. TypeScript typecheck、Python `py_compile/compileall`。
2. Python 单元测试锁住保留字、历史回滚和 bridge 重启。
3. Vitest 检查开发/发布 Python runtime 解析。
4. JSONL sidecar 真实 ready/ping/get_state。
5. Playwright 检查 430×780、340×560、设置滚动、历史和语言切换。
6. 真 Electron 检查透明窗口、自然尺寸、托盘、文件资源和 sidecar。
7. 打包 `.app` 再次检查进程命令，确认使用包内 Python。

最终还要重新检查原 `here` 的提交和工作区状态。只有“功能证据 + 发布证据 + 原项目未变”同时成立，迁移才算完成。
