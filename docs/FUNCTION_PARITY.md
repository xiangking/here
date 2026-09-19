# Qt 与 Electron 功能对齐矩阵

对照基线：`here@2e782b26ca83e92ee9c484c5a095f5331526d72b`。

| 能力 | Electron 实现 | 验证 |
| --- | --- | --- |
| 透明、无边框、可缩放窗口 | `BrowserWindow` transparent/frame=false，最小尺寸 340×560 | 打包 `.app` 实机 |
| 窗口拖动、置顶、最小化 | Electron 原生窗口 API | 实机交互 |
| 关闭后驻留、托盘显示/隐藏/退出 | close 拦截并隐藏；托盘负责真正退出 | 实机验证进程仍在 |
| 窗口位置和尺寸恢复 | `window-state.json`，多屏可见性检查 | 构建与代码测试 |
| 角色静态立绘、逐帧动画、spritesheet | `<img>` 与 Canvas，支持 fps/interval/网格 | Playwright + 实机 |
| 角色缩放 | 按自然像素尺寸乘 `sprite_scale` 后再受容器约束 | 实机修复双重缩放 |
| 情绪状态与别名 | 保留 `state_name`，复用 emotion resolver 语义 | Python 测试 |
| 角色创建、编辑、重命名、删除 | 创建前确认名称/人设，至少一个立绘状态；支持六种核心情绪与动画帧间隔 | RPC 回归 + Playwright |
| 角色图片序列/GIF/WebP/视频导入 | sidecar 复制/解帧，视频使用可选 OpenCV | RPC + 文件选择 UI |
| Codex Pet 导入 | 复用 `codex_pet_importer` | RPC + UI |
| Agent 后端 | auto / Internal Agent / Hermes Agent | sidecar 启动测试 |
| 模型列表获取 | OpenAI-compatible `/models` | RPC + UI，需有效服务 |
| Hermes 流式解析 | 完整对话片段解析后立即发布 | Python 路由测试 |
| 图片附件与多模态 | 文件选择、剪贴板图片、拖放图片；sidecar 保存并构造 image_url content | UI 流程 |
| 停止生成 | 调用 Agent `interrupt()`，发送按钮切换停止状态 | UI 交互 |
| COT / CHOICE / STAT | 状态条、选项按钮、数值面板 | Python 保留字测试 |
| SCENE / BGM / CG / NARR | 背景、循环音乐、场景图、旁白；CG 可另存 | RPC + UI |
| 对话历史、复制、清空 | Electron 剪贴板与 sidecar 持久化 | UI 流程 |
| 历史回滚 | 从指定用户消息前截断并 reset Agent session | Python 自动化测试 |
| TTS 多提供器与扩展 schema | 复用原 TTS factory/manager | 配置 UI + sidecar |
| 分句 TTS、角色语速和音量 | sidecar 分句，renderer 顺序播放 | 代码测试 |
| 本地预设立绘语音回退 | 在线 TTS 关闭时使用 sprite `voice_path` | Python 路径 |
| 发音映射和文本清理 | Qt 无关 TextProcessor，复用 `pronunciation_map` | Python 编译测试 |
| ASR Vosk | 发布运行时内置 PyAudio/Vosk 与中文模型 | 打包 `.app` 显示“已准备” |
| faster-whisper / RealtimeSTT | 固定白名单依赖安装、模型预载 | UI/RPC，模型需联网下载 |
| T2I 与手动生图 | 复用 T2I factory/manager；实时立绘按角色/情绪/场景生成并按引擎指纹缓存，失败回退静态立绘 | 缓存回归；实网需有效服务 |
| 自拍和主动联系配图 | 复用 SelfieService 与原调度策略 | sidecar 初始化 |
| 每日生活与联系计划 | 复用 LifeEngine / ContactPlanEngine | UI 时间线 |
| 主动联系、安静时段、每日限制 | 复用 ProactiveContactScheduler / DeliveryRouter | sidecar 生命周期 |
| Telegram 发送、入站和 chat_id 识别 | 原 sender、poll bridge 与 discovery | 自动化生命周期；实网需 token |
| WeChat 扫码、账号、context token、入站监听 | 原 OpenClaw API/state/monitor | 生命周期与 UI；实网需扫码 |
| Discord / Feishu / WhatsApp 发送 | 原消息适配器，字段与 Qt 表单一致 | capability probe；实网需凭据 |
| 外部普通聊天回复 | `route_chat_response()`，失败回退桌面 | Python 路由 |
| 外部主动消息文本/图片/语音 | 原 DeliveryAdapterRegistry | sidecar 调度 |
| 中英日韩界面 | 复用 locale JSON，支持参数模板、动态 DOM 更新与多语言托盘菜单 | Playwright English 验收 |
| 对白呈现与语音跳过 | DOMPurify 清理后的 Markdown、逐字显示；点击对白立即完成文字并跳过当前语音 | 类型检查 + Playwright |
| 背景、BGM、参考图和存储目录选择 | 存储变更可选复制旧记忆/资产，重写资产路径，拒绝嵌套目标并在失败时回滚配置 | Python 迁移/回滚回归 |
| 主题色、对白宽高 | Qt rgba 透明度转换为 CSS，对白背景、宽度和高度即时应用 | TypeScript 回归 + Playwright |
| 旧版数据导入 | 只读源目录，复制到 Electron 数据根 | RPC 报告 |
| 独立发布运行时 | 可搬运 CPython + `extraResources` | `.app/.dmg/.zip` 构建成功 |

## 外部验收条件

Telegram、WeChat、Discord、Feishu、WhatsApp、在线 Agent、TTS 和 T2I 都依赖用户自己的账号、Token 或服务地址。当前完成了代码路径、字段、生命周期、能力探测和失败回退；真实服务的最终端到端发送需要在对应凭据可用时执行，测试不会自动发送外部消息。

## 本地验收结果

- `npm run typecheck`：通过。
- `npm test`：22 项通过，覆盖 Python sidecar、媒体解析、界面交互和语音中断收敛。
- `npm run backend:test`：31 项通过，覆盖存储迁移/回滚、角色会话隔离、记忆整理、实时立绘缓存、多状态角色创建等。
- `npm run build`：通过。
