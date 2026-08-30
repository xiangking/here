export function normalizeThemeColor(value: string): string | null {
  const theme = value.trim();
  const rgba = theme.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)$/i);
  if (rgba) {
    const alphaValue = rgba[4] === undefined ? 1 : Number(rgba[4]);
    if (![rgba[1], rgba[2], rgba[3], alphaValue].every((item) => Number.isFinite(Number(item)))) return null;
    const alpha = Math.max(0, Math.min(1, alphaValue > 1 ? alphaValue / 255 : alphaValue));
    return `rgba(${rgba[1]}, ${rgba[2]}, ${rgba[3]}, ${alpha})`;
  }
  return /^#[\da-f]{3,8}$/i.test(theme) ? theme : null;
}

export function qtDialogBackground(themeColor: string): string | null {
  const top = normalizeThemeColor(themeColor);
  if (!top) return null;
  return `linear-gradient(180deg, ${top} 0%, rgba(50, 50, 50, 0.39215686274509803) 100%)`;
}

export function qtOverlayWidthPx(containerWidth: number, percentage: number): number {
  const width = Math.max(1, containerWidth);
  const available = Math.max(1, width - 32);
  const configured = width * Math.max(30, Math.min(100, percentage)) / 100;
  const compactMinimum = Math.min(320, available);
  return Math.round(Math.min(available, Math.max(compactMinimum, configured)));
}

export interface QtDialogLayout {
  dialogTop: number;
  dialogHeight: number;
  composerTop: number;
}

export type DialogResizeEdge = "left" | "right" | "top" | "bottom";

export interface DialogResizeBounds {
  minWidth: number;
  maxWidth: number;
  minHeight: number;
  maxHeight: number;
}

/** Calculate a clamped size while preserving the edge being dragged. */
export function qtDialogResizeSize(
  startWidth: number,
  startHeight: number,
  deltaX: number,
  deltaY: number,
  edges: ReadonlySet<DialogResizeEdge>,
  bounds: DialogResizeBounds,
): { width: number; height: number } {
  const rawWidth = edges.has("left") ? startWidth - deltaX
    : edges.has("right") ? startWidth + deltaX
      : startWidth;
  const rawHeight = edges.has("top") ? startHeight - deltaY
    : edges.has("bottom") ? startHeight + deltaY
      : startHeight;
  return {
    width: Math.round(Math.max(bounds.minWidth, Math.min(bounds.maxWidth, rawWidth))),
    height: Math.round(Math.max(bounds.minHeight, Math.min(bounds.maxHeight, rawHeight))),
  };
}

export function qtDialogLayout(
  stageHeight: number,
  composerHeight: number,
  composerBottomInset: number,
  spriteTop: number,
  spriteHeight: number,
  contentHeight: number,
  preferredHeightPct = 0,
): QtDialogLayout {
  const safeStageHeight = Math.max(1, stageHeight);
  const safeComposerHeight = Math.max(0, composerHeight);
  const safeBottomInset = safeComposerHeight > 0 ? Math.max(0, composerBottomInset) : 0;
  const available = Math.max(1, safeStageHeight - safeComposerHeight - safeBottomInset);
  const minimum = Math.max(58, available * 0.08);
  const maximum = Math.max(minimum, Math.min(available * 0.55, 260));
  const spriteLimit = spriteHeight > 0 ? spriteHeight / 3 : maximum;
  const heightLimit = Math.max(minimum, Math.min(maximum, spriteLimit));
  const configuredHeight = Number(preferredHeightPct);
  const requestedHeight = Number.isFinite(configuredHeight) && configuredHeight > 0
    ? available * Math.max(14, Math.min(70, configuredHeight)) / 100
    : contentHeight;
  const dialogHeight = Math.round(Math.max(minimum, Math.min(heightLimit, requestedHeight)));
  const latestComposerTop = safeStageHeight - safeComposerHeight - safeBottomInset;
  const latestDialogTop = latestComposerTop - 6 - dialogHeight;

  let dialogTop = latestDialogTop;
  if (spriteHeight > 0) {
    const overlap = Math.min(spriteHeight * 0.25, dialogHeight);
    dialogTop = Math.min(spriteTop + spriteHeight - overlap, latestDialogTop);
  }
  dialogTop = Math.max(0, Math.round(dialogTop));

  const composerTop = safeComposerHeight > 0
    ? Math.min(latestComposerTop, dialogTop + dialogHeight + 6)
    : safeStageHeight;
  return { dialogTop, dialogHeight, composerTop: Math.round(composerTop) };
}

export class PauseReasonGate<Reason extends string> {
  private readonly reasons = new Set<Reason>();

  get paused(): boolean {
    return this.reasons.size > 0;
  }

  has(reason: Reason): boolean {
    return this.reasons.has(reason);
  }

  pause(reason: Reason): boolean {
    const shouldPause = this.reasons.size === 0;
    this.reasons.add(reason);
    return shouldPause;
  }

  resume(reason: Reason): boolean {
    const removed = this.reasons.delete(reason);
    return removed && this.reasons.size === 0;
  }

  clear(): void {
    this.reasons.clear();
  }
}

interface PlayableAudio {
  addEventListener: (name: "ended" | "error", listener: () => void, options: { once: boolean }) => void;
  play: () => Promise<void>;
}

export async function waitForAudioEnd(
  audio: PlayableAudio,
  registerFinisher: (finish: () => void) => void,
): Promise<void> {
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    registerFinisher(finish);
    audio.addEventListener("ended", finish, { once: true });
    audio.addEventListener("error", finish, { once: true });
    void audio.play().catch(finish);
  });
}
