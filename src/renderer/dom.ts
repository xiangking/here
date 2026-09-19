import { createIcons, icons } from "lucide";

export const $ = <T extends Element>(selector: string): T => {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
};
export const $$ = <T extends Element>(selector: string): T[] => Array.from(document.querySelectorAll<T>(selector));
export const esc = (value: unknown): string => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");
export const clone = <T>(value: T): T => structuredClone(value);
const callPixelIcons = {
  lock: { width: 6, height: 6, rows: "033300/070220/386750/697882/694682/698882", className: "lock" },
  participants: { width: 12, height: 10, rows: "000005bc8000/00003cffe600/05004defe700/3c303beed500/8c84049b7200/4b3200230000/070049ddb720/0029efffffc3/004deeeeeee8/002788888874", className: "participants" },
  more: { width: 4, height: 12, rows: "0020/07c6/08e6/0230/0230/08b5/08d5/0020/0020/08d5/28b5/0230", className: "more" },
  hangup: { width: 17, height: 12, rows: "00000000000000000/00000000000000000/000369aba97420000/05adeeeeeeedc8300/8deeda999aceeec50/dfee9300024ceeec2/eeee8000000beeed3/ceeb40000006ceea0/58420000000005840/00000000000000000/00000000000000000/00000000000000000", className: "hangup" },
} as const;
type CallPixelIconName = keyof typeof callPixelIcons;

const renderCallPixelIcons = (): void => {
  $$<SVGSVGElement>("[data-call-pixel-icon]:not([data-call-pixel-ready])").forEach((svg) => {
    const name = svg.dataset.callPixelIcon as CallPixelIconName;
    const icon = callPixelIcons[name];
    if (!icon) return;
    const rects: string[] = [];
    icon.rows.split("/").forEach((row, y) => {
      let x = 0;
      while (x < row.length) {
        const alpha = row[x];
        let end = x + 1;
        while (end < row.length && row[end] === alpha) end += 1;
        const value = Number.parseInt(alpha, 16);
        if (value) rects.push(`<rect x="${x}" y="${y}" width="${end - x}" height="1" fill="currentColor" fill-opacity="${value / 15}"/>`);
        x = end;
      }
    });
    svg.setAttribute("viewBox", `0 0 ${icon.width} ${icon.height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("shape-rendering", "crispEdges");
    svg.innerHTML = rects.join("");
    svg.dataset.callPixelReady = "true";
  });
};

export const refreshIcons = (): void => {
  createIcons({ icons });
  renderCallPixelIcons();
};

const callIconMarkup = (icon: string): string => {
  if (icon === "video" || icon === "video-off") {
    return '<span class="call-video-icon" aria-hidden="true"><i data-lucide="video"></i></span>';
  }
  if (icon === "mic" || icon === "mic-off") {
    return '<span class="call-microphone-icon" aria-hidden="true"><i data-lucide="mic"></i></span>';
  }
  const pixelName = icon;
  if (pixelName in callPixelIcons) {
    const spec = callPixelIcons[pixelName as CallPixelIconName];
    return `<svg class="call-glyph call-pixel-glyph call-glyph-${spec.className}" data-call-pixel-icon="${pixelName}" aria-hidden="true"></svg>`;
  }
  return `<i data-lucide="${icon}"></i>`;
};

export const updateCallControl = (control: HTMLButtonElement, isOff: boolean): void => {
  const kind = control.dataset.callToggle;
  control.classList.toggle("is-off", isOff);
  control.setAttribute("aria-pressed", String(isOff));
  const icon = kind === "video" ? (isOff ? "video-off" : "video")
    : kind === "microphone" ? (isOff ? "mic-off" : "mic")
      : kind === "speaker" ? (isOff ? "volume-x" : "volume-2")
        : "switch-camera";
  control.innerHTML = callIconMarkup(icon);
  control.title = kind === "video" ? (isOff ? "开启视频通话" : "关闭视频通话")
    : kind === "microphone" ? (isOff ? "取消静音" : "静音")
      : kind === "speaker" ? (isOff ? "打开扬声器" : "关闭扬声器")
        : "切换摄像头";
  refreshIcons();
};

export function switchRow(id: string, title: string, detail: string, checked: boolean): string {
  return `<div class="switch-row">
    <div class="switch-copy"><strong>${esc(title)}</strong>${detail ? `<span class="switch-detail">${esc(detail)}</span>` : ""}</div>
    <label class="toggle"><input id="${esc(id)}" type="checkbox" ${checked ? "checked" : ""}><span></span></label>
  </div>`;
}

export function field(
  id: string,
  label: string,
  value: unknown,
  options?: { type?: string; wide?: boolean; min?: number; max?: number; step?: number; rows?: number; placeholder?: string; extraClass?: string; readOnly?: boolean; disabled?: boolean },
): string {
  const config = options || {};
  const className = `field${config.wide ? " field-wide" : ""}${config.extraClass ? ` ${config.extraClass}` : ""}`;
  const editState = `${config.readOnly ? " readonly" : ""}${config.disabled ? " disabled" : ""}`;
  if (config.type === "textarea") {
    return `<label class="${className}"><span>${esc(label)}</span><textarea id="${esc(id)}" rows="${config.rows || 4}"${config.placeholder ? ` placeholder="${esc(config.placeholder)}"` : ""}${editState}>${esc(value)}</textarea></label>`;
  }
  return `<label class="${className}"><span>${esc(label)}</span><input id="${esc(id)}" type="${esc(config.type || "text")}" value="${esc(value)}"${config.min !== undefined ? ` min="${config.min}"` : ""}${config.max !== undefined ? ` max="${config.max}"` : ""}${config.step !== undefined ? ` step="${config.step}"` : ""}${config.placeholder ? ` placeholder="${esc(config.placeholder)}"` : ""}${editState}></label>`;
}

export function pathField(
  id: string,
  label: string,
  value: unknown,
  picker: "background" | "bgm" | "reference" | "directory",
  wide = true,
  placeholder = "",
): string {
  return `<label class="field${wide ? " field-wide" : ""}"><span>${esc(label)}</span><span class="path-control"><input id="${esc(id)}" type="text" value="${esc(value)}"${placeholder ? ` placeholder="${esc(placeholder)}"` : ""}><button class="icon-button" data-file-picker="${picker}" data-picker-target="${esc(id)}" type="button" title="选择"><i data-lucide="folder-open"></i></button></span></label>`;
}

export function selectField(id: string, label: string, value: unknown, options: Array<[string, string]>, wide = false): string {
  return `<label class="field${wide ? " field-wide" : ""}"><span>${esc(label)}</span><select id="${esc(id)}">${options.map(([key, text]) =>
    `<option value="${esc(key)}" ${String(value) === key ? "selected" : ""}>${esc(text)}</option>`).join("")}</select></label>`;
}

export function editableChoiceField(id: string, label: string, value: unknown, choices: string[], placeholder = ""): string {
  const listId = `${id}-choices`;
  return `<label class="field"><span>${esc(label)}</span><input id="${esc(id)}" type="text" value="${esc(value)}" list="${esc(listId)}"${placeholder ? ` placeholder="${esc(placeholder)}"` : ""}><datalist id="${esc(listId)}">${choices.map((choice) => `<option value="${esc(choice)}"></option>`).join("")}</datalist></label>`;
}

export function pageHeader(title: string, subtitle: string): string {
  return `<h2 class="page-title">${esc(title)}</h2>${subtitle ? `<p class="page-subtitle">${esc(subtitle)}</p>` : ""}`;
}
