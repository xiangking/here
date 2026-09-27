type LocaleCode = "zh_CN" | "en" | "ja" | "ko";
type Catalog = Record<string, unknown>;


const originalText = new WeakMap<Node, string>();
const originalAttributes = new WeakMap<Element, Map<string, string>>();
let currentLocale: LocaleCode = "zh_CN";
let translations = new Map<string, string>();
let templates: Array<{ pattern: RegExp; names: string[]; target: string }> = [];

const manual: Record<Exclude<LocaleCode, "zh_CN">, Record<string, string>> = {
  en: {
    "设置": "Settings", "通用": "General", "语音": "Voice", "图像": "Images", "主动联系": "Proactive contact",
    "消息平台": "Messaging", "角色": "Character", "状态立绘": "State sprites", "记忆": "Memory", "存储": "Storage", "选择": "Choose",
    "关闭": "Close", "保存": "Save", "取消": "Cancel", "发送": "Send", "最小化": "Minimize", "置顶": "Pin",
    "隐藏到后台": "Hide in background", "对话记录": "Chat history", "生活日程": "Daily life", "生成图片": "Generate image",
    "朗读开关": "Speech toggle", "添加图片": "Attach images", "语音输入": "Voice input", "输入消息…": "Type a message...",
    "界面": "Interface", "桌面窗口": "Desktop window", "背景与声音": "Background and sound", "界面语言": "UI language",
    "基础字号": "Base font size", "窗口置顶": "Always on top", "显示对白": "Show dialog", "显示过程状态": "Show activity status",
    "显示输入栏": "Show input bar", "背景图片路径": "Background image", "BGM 路径": "BGM path", "BGM 音量": "BGM volume",
    "运行后端": "Agent backend", "模型": "Model", "供应商": "Provider", "最大迭代次数": "Max iterations",
    "流式响应": "Streaming response", "语音引擎": "Speech engine", "语音语言": "Speech language", "识别后端": "Recognition engine",
    "识别语言": "Recognition language", "计算设备": "Compute device", "计算精度": "Compute type", "生图引擎": "Image engine",
    "引擎": "Engine", "API 地址": "API URL", "允许主动联系": "Enable proactive contact", "外部平台送达": "External delivery",
    "发送前确认": "Confirm before sending", "附带语音": "Include audio", "送达渠道": "Delivery channel", "普通聊天渠道": "Chat channel",
    "启用": "Enabled", "当前角色": "Current character", "名称": "Name", "对话颜色": "Dialog color", "资源前缀": "Asset prefix",
    "立绘缩放": "Sprite scale", "语速倍率": "Speech speed", "语音音量": "Speech volume", "视觉参考图": "Visual reference",
    "视觉身份": "Visual identity", "角色设定": "Character profile", "状态立绘与动画": "State sprites and animation",
    "状态": "State", "状态分组": "State group", "帧间隔 ms": "Frame interval (ms)", "位置": "Locations",
    "角色记忆目录": "Character memory folder", "角色资产目录": "Character assets folder", "旧版 here": "Legacy here",
    "已保存": "Saved", "已准备": "Ready", "正在处理": "Working", "正在思考": "Thinking", "正在输入……": "Typing...",
    "我在。想聊什么？": "I'm here. What would you like to talk about?", "暂无": "None", "消息": "Message",
    "当前角色立绘": "Current character sprite", "当前角色动画": "Current character animation", "收起对白": "Collapse dialog",
    "设置分类": "Settings categories", "场景图": "Scene image", "保存场景图": "Save scene image", "关闭场景图": "Close scene image",
    "对白宽度 %": "Dialog width %", "对白高度 %": "Dialog height %", "主题色": "Theme color",
    "Electron 数据目录": "Electron data folder", "旧版数据": "Legacy data",
    "固定情绪与欢迎动画": "Core emotions and welcome animation", "其他状态": "Other states", "新增自定义状态": "Add custom state",
    "平静": "Neutral", "开心": "Happy", "思考": "Thinking", "惊讶": "Surprised", "难过": "Sad", "生气": "Angry", "欢迎动画": "Welcome animation",
    "核心情绪": "Core emotions", "系统状态": "System states", "鼠标动作": "Mouse actions", "执行中": "Working", "检查中": "Reviewing", "向右移动": "Moving right", "向左移动": "Moving left",
    "未设置": "Not set", "空": "Empty", "当前角色未配置": "Not configured for this character", "添加素材": "Add asset",
    "保存设置": "Save settings", "替换素材": "Replace asset", "清空": "Clear", "添加自定义素材": "Add custom asset",
  },
  ja: {
    "设置": "設定", "通用": "一般", "语音": "音声", "图像": "画像", "主动联系": "プロアクティブ連絡", "消息平台": "メッセージ",
    "角色": "キャラクター", "状态立绘": "状態立ち絵", "记忆": "メモリ", "存储": "ストレージ", "选择": "選択", "关闭": "閉じる", "保存": "保存",
    "取消": "キャンセル", "发送": "送信", "最小化": "最小化", "置顶": "最前面", "隐藏到后台": "バックグラウンドに隠す",
    "对话记录": "会話履歴", "生活日程": "生活予定", "生成图片": "画像生成", "朗读开关": "読み上げ切替", "添加图片": "画像を追加",
    "语音输入": "音声入力", "输入消息…": "メッセージを入力…", "界面": "インターフェース", "桌面窗口": "デスクトップウィンドウ",
    "背景与声音": "背景とサウンド", "界面语言": "表示言語", "基础字号": "基本フォントサイズ", "窗口置顶": "常に最前面",
    "显示对白": "台詞を表示", "显示过程状态": "処理状況を表示", "显示输入栏": "入力欄を表示", "背景图片路径": "背景画像",
    "BGM 路径": "BGM パス", "BGM 音量": "BGM 音量", "运行后端": "Agent バックエンド", "模型": "モデル", "供应商": "プロバイダー",
    "最大迭代次数": "最大反復回数", "流式响应": "ストリーミング応答", "语音引擎": "音声エンジン", "语音语言": "音声言語",
    "识别后端": "認識エンジン", "识别语言": "認識言語", "计算设备": "計算デバイス", "计算精度": "計算精度", "生图引擎": "画像生成エンジン",
    "引擎": "エンジン", "API 地址": "API URL", "允许主动联系": "プロアクティブ連絡を許可", "外部平台送达": "外部配信",
    "发送前确认": "送信前に確認", "附带语音": "音声を添付", "送达渠道": "配信先", "普通聊天渠道": "チャット先", "启用": "有効",
    "当前角色": "現在のキャラクター", "名称": "名前", "对话颜色": "会話色", "资源前缀": "アセット接頭辞", "立绘缩放": "立ち絵倍率",
    "语速倍率": "話速", "语音音量": "音声音量", "视觉参考图": "ビジュアル参照", "视觉身份": "ビジュアル設定", "角色设定": "キャラクター設定",
    "状态立绘与动画": "状態別立ち絵とアニメーション", "状态": "状態", "状态分组": "状態グループ", "帧间隔 ms": "フレーム間隔 (ms)",
    "位置": "保存先", "角色记忆目录": "キャラクターメモリフォルダ", "角色资产目录": "キャラクター素材フォルダ", "旧版 here": "旧版 here",
    "已保存": "保存しました", "已准备": "準備完了", "正在处理": "処理中", "正在思考": "思考中", "正在输入……": "入力中…",
    "我在。想聊什么？": "ここにいるよ。何を話そうか？", "暂无": "なし", "消息": "メッセージ",
    "当前角色立绘": "現在のキャラクター立ち絵", "当前角色动画": "現在のキャラクターアニメーション", "收起对白": "台詞欄を閉じる",
    "设置分类": "設定カテゴリ", "场景图": "シーン画像", "保存场景图": "シーン画像を保存", "关闭场景图": "シーン画像を閉じる",
    "对白宽度 %": "台詞欄の幅 %", "对白高度 %": "台詞欄の高さ %", "主题色": "テーマカラー",
    "Electron 数据目录": "Electron データフォルダ", "旧版数据": "旧バージョンのデータ",
    "固定情绪与欢迎动画": "基本感情とウェルカムアニメーション", "其他状态": "その他の状態", "新增自定义状态": "カスタム状態を追加",
    "平静": "平静", "开心": "喜び", "思考": "思考", "惊讶": "驚き", "难过": "悲しみ", "生气": "怒り", "欢迎动画": "ウェルカムアニメーション",
    "核心情绪": "基本感情", "系统状态": "システム状態", "鼠标动作": "マウス動作", "执行中": "実行中", "检查中": "確認中", "向右移动": "右へ移動", "向左移动": "左へ移動",
    "未设置": "未設定", "空": "空", "当前角色未配置": "このキャラクターには未設定", "添加素材": "素材を追加",
    "保存设置": "設定を保存", "替换素材": "素材を置換", "清空": "クリア", "添加自定义素材": "カスタム素材を追加",
  },
  ko: {
    "设置": "설정", "通用": "일반", "语音": "음성", "图像": "이미지", "主动联系": "능동 연락", "消息平台": "메시지 플랫폼",
    "角色": "캐릭터", "状态立绘": "상태 스프라이트", "记忆": "메모리", "存储": "저장소", "选择": "선택", "关闭": "닫기", "保存": "저장", "取消": "취소",
    "发送": "보내기", "最小化": "최소화", "置顶": "고정", "隐藏到后台": "백그라운드로 숨기기", "对话记录": "대화 기록",
    "生活日程": "생활 일정", "生成图片": "이미지 생성", "朗读开关": "읽기 전환", "添加图片": "이미지 추가", "语音输入": "음성 입력",
    "输入消息…": "메시지 입력…", "界面": "인터페이스", "桌面窗口": "데스크톱 창", "背景与声音": "배경 및 소리", "界面语言": "UI 언어",
    "基础字号": "기본 글꼴 크기", "窗口置顶": "항상 위", "显示对白": "대화 표시", "显示过程状态": "처리 상태 표시",
    "显示输入栏": "입력창 표시", "背景图片路径": "배경 이미지", "BGM 路径": "BGM 경로", "BGM 音量": "BGM 볼륨",
    "运行后端": "Agent 백엔드", "模型": "모델", "供应商": "공급자", "最大迭代次数": "최대 반복 횟수", "流式响应": "스트리밍 응답",
    "语音引擎": "음성 엔진", "语音语言": "음성 언어", "识别后端": "인식 엔진", "识别语言": "인식 언어", "计算设备": "연산 장치",
    "计算精度": "연산 정밀도", "生图引擎": "이미지 생성 엔진", "引擎": "엔진", "API 地址": "API URL", "允许主动联系": "능동 연락 허용",
    "外部平台送达": "외부 전송", "发送前确认": "전송 전 확인", "附带语音": "음성 첨부", "送达渠道": "전송 채널", "普通聊天渠道": "채팅 채널",
    "启用": "사용", "当前角色": "현재 캐릭터", "名称": "이름", "对话颜色": "대화 색상", "资源前缀": "에셋 접두사",
    "立绘缩放": "스프라이트 배율", "语速倍率": "말하기 속도", "语音音量": "음성 볼륨", "视觉参考图": "비주얼 참조",
    "视觉身份": "비주얼 정체성", "角色设定": "캐릭터 설정", "状态立绘与动画": "상태 스프라이트 및 애니메이션", "状态": "상태",
    "状态分组": "상태 그룹", "帧间隔 ms": "프레임 간격 (ms)", "位置": "위치", "角色记忆目录": "캐릭터 메모리 폴더",
    "角色资产目录": "캐릭터 에셋 폴더", "旧版 here": "이전 here", "已保存": "저장됨", "已准备": "준비됨", "正在处理": "처리 중",
    "正在思考": "생각 중", "正在输入……": "입력 중…", "我在。想聊什么？": "여기 있어. 무슨 이야기를 할까?", "暂无": "없음", "消息": "메시지",
    "当前角色立绘": "현재 캐릭터 스프라이트", "当前角色动画": "현재 캐릭터 애니메이션", "收起对白": "대화창 접기",
    "设置分类": "설정 카테고리", "场景图": "장면 이미지", "保存场景图": "장면 이미지 저장", "关闭场景图": "장면 이미지 닫기",
    "对白宽度 %": "대화창 너비 %", "对白高度 %": "대화창 높이 %", "主题色": "테마 색상",
    "Electron 数据目录": "Electron 데이터 폴더", "旧版数据": "이전 버전 데이터",
    "固定情绪与欢迎动画": "기본 감정 및 환영 애니메이션", "其他状态": "기타 상태", "新增自定义状态": "사용자 지정 상태 추가",
    "平静": "평온", "开心": "기쁨", "思考": "생각", "惊讶": "놀람", "难过": "슬픔", "生气": "화남", "欢迎动画": "환영 애니메이션",
    "核心情绪": "핵심 감정", "系统状态": "시스템 상태", "鼠标动作": "마우스 동작", "执行中": "실행 중", "检查中": "검토 중", "向右移动": "오른쪽 이동", "向左移动": "왼쪽 이동",
    "未设置": "설정 안 됨", "空": "비어 있음", "当前角色未配置": "현재 캐릭터에 설정되지 않음", "添加素材": "에셋 추가",
    "保存设置": "설정 저장", "替换素材": "에셋 교체", "清空": "비우기", "添加自定义素材": "사용자 지정 에셋 추가",
  },
};

function flatten(value: Catalog, prefix = "", output = new Map<string, string>()): Map<string, string> {
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof item === "string") output.set(path, item);
    else if (item && typeof item === "object" && !Array.isArray(item)) flatten(item as Catalog, path, output);
  }
  return output;
}

function escapePattern(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function templatePattern(source: string, target: string): { pattern: RegExp; names: string[]; target: string } | null {
  const names: string[] = [];
  let cursor = 0;
  let expression = "^";
  for (const match of source.matchAll(/\{([^{}]+)\}/g)) {
    expression += escapePattern(source.slice(cursor, match.index)) + "(.+?)";
    names.push(match[1]);
    cursor = (match.index || 0) + match[0].length;
  }
  if (!names.length) return null;
  expression += escapePattern(source.slice(cursor)) + "$";
  return { pattern: new RegExp(expression, "s"), names, target };
}

export async function setLocale(rawCode: string): Promise<void> {
  const code = (["zh_CN", "en", "ja", "ko"].includes(rawCode) ? rawCode : "zh_CN") as LocaleCode;
  currentLocale = code;
  document.documentElement.lang = code === "zh_CN" ? "zh-CN" : code;
  if (code === "zh_CN") {
    translations = new Map();
    templates = [];
    return;
  }
  const [sourceResponse, targetResponse] = await Promise.all([
    fetch("./locales/zh_CN.json"),
    fetch(`./locales/${code}.json`),
  ]);
  const source = flatten(await sourceResponse.json() as Catalog);
  const target = flatten(await targetResponse.json() as Catalog);
  const mapped = new Map<string, string>();
  const mappedTemplates: Array<{ pattern: RegExp; names: string[]; target: string }> = [];
  for (const [key, chinese] of source) {
    const translated = target.get(key);
    if (!translated || !chinese || chinese.includes("<")) continue;
    const template = templatePattern(chinese, translated);
    if (template) mappedTemplates.push(template);
    else mapped.set(chinese, translated);
  }
  for (const [chinese, translated] of Object.entries(manual[code])) mapped.set(chinese, translated);
  translations = mapped;
  templates = mappedTemplates;
}

function translated(value: string): string {
  if (currentLocale === "zh_CN") return value;
  const exact = translations.get(value);
  if (exact) return exact;
  for (const template of templates) {
    const match = value.match(template.pattern);
    if (!match) continue;
    const values = new Map(template.names.map((name, index) => [name, match[index + 1]]));
    return template.target.replace(/\{([^{}]+)\}/g, (placeholder, name: string) => values.get(name) || placeholder);
  }
  return value;
}

export const translateText = translated;

export function applyLocale(root: ParentNode = document): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    const parent = node.parentElement;
    if (parent && !["SCRIPT", "STYLE"].includes(parent.tagName)) {
      if (!originalText.has(node)) originalText.set(node, node.textContent || "");
      const source = originalText.get(node) || "";
      const trimmed = source.trim();
      const next = trimmed ? source.replace(trimmed, translated(trimmed)) : source;
      if (node.textContent !== next) node.textContent = next;
    }
    node = walker.nextNode();
  }
  for (const element of Array.from(root.querySelectorAll?.("[title], [placeholder], [aria-label], [alt]") || [])) {
    let originals = originalAttributes.get(element);
    if (!originals) {
      originals = new Map();
      originalAttributes.set(element, originals);
    }
    for (const name of ["title", "placeholder", "aria-label", "alt"]) {
      const current = element.getAttribute(name);
      if (current === null) continue;
      if (!originals.has(name)) originals.set(name, current);
      const next = translated(originals.get(name) || current);
      if (current !== next) element.setAttribute(name, next);
    }
  }
}

let localeObserver: MutationObserver | null = null;

export function observeLocale(root: HTMLElement = document.body): void {
  localeObserver?.disconnect();
  localeObserver = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "characterData" && record.target.parentNode) applyLocale(record.target.parentNode);
      for (const node of Array.from(record.addedNodes)) {
        if (node.nodeType === Node.ELEMENT_NODE) applyLocale(node as ParentNode);
        else if (node.parentNode) applyLocale(node.parentNode);
      }
    }
  });
  localeObserver.observe(root, { childList: true, characterData: true, subtree: true });
}
