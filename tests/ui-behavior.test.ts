import { describe, expect, it } from "vitest";
import {
  normalizeThemeColor,
  PauseReasonGate,
  qtDialogBackground,
  qtDialogLayout,
  qtOverlayWidthPx,
  qtDialogResizeSize,
  waitForAudioEnd,
} from "../src/renderer/ui-behavior";


describe("normalizeThemeColor", () => {
  it("converts Qt's 0-255 alpha to CSS alpha", () => {
    expect(normalizeThemeColor("rgba(50, 100, 150, 200)")).toBe("rgba(50, 100, 150, 0.7843137254901961)");
  });

  it("accepts CSS colors and rejects arbitrary values", () => {
    expect(normalizeThemeColor("#f2a7bb")).toBe("#f2a7bb");
    expect(normalizeThemeColor("not-a-color")).toBeNull();
  });
});

describe("qtDialogBackground", () => {
  it("matches Qt's top-to-bottom alpha gradient", () => {
    expect(qtDialogBackground("rgba(50,50,50,200)")).toBe(
      "linear-gradient(180deg, rgba(50, 50, 50, 0.7843137254901961) 0%, rgba(50, 50, 50, 0.39215686274509803) 100%)",
    );
  });
});

describe("qtOverlayWidthPx", () => {
  it("uses Qt's 16px compact-window inset instead of shrinking to 81%", () => {
    expect(qtOverlayWidthPx(356, 81)).toBe(320);
    expect(qtOverlayWidthPx(340, 81)).toBe(308);
  });

  it("preserves the configured percentage on wider windows", () => {
    expect(qtOverlayWidthPx(600, 81)).toBe(486);
  });
});

describe("qtDialogLayout", () => {
  it("uses the content height below the sprite-based limit", () => {
    expect(qtDialogLayout(560, 62, 10, 40, 400, 58)).toEqual({
      dialogTop: 382,
      dialogHeight: 58,
      composerTop: 446,
    });
  });

  it("caps long content at one third of the sprite height", () => {
    expect(qtDialogLayout(560, 62, 10, 40, 400, 400)).toEqual({
      dialogTop: 340,
      dialogHeight: 133,
      composerTop: 479,
    });
  });

  it("keeps the dialog and composer inside the stage", () => {
    expect(qtDialogLayout(560, 62, 10, 180, 360, 300)).toEqual({
      dialogTop: 362,
      dialogHeight: 120,
      composerTop: 488,
    });
  });

  it("places a minimum-height dialog above the composer without a sprite", () => {
    expect(qtDialogLayout(560, 62, 10, 0, 0, 40)).toEqual({
      dialogTop: 424,
      dialogHeight: 58,
      composerTop: 488,
    });
  });

  it("honors a configured height percentage within Qt bounds", () => {
    expect(qtDialogLayout(560, 62, 10, 0, 0, 400, 30)).toEqual({
      dialogTop: 336,
      dialogHeight: 146,
      composerTop: 488,
    });
  });
});

describe("qtDialogResizeSize", () => {
  it("clamps the dragged edges without allowing an invalid size", () => {
    expect(qtDialogResizeSize(
      400,
      120,
      -500,
      80,
      new Set(["left", "bottom"]),
      { minWidth: 260, maxWidth: 600, minHeight: 90, maxHeight: 260 },
    )).toEqual({ width: 600, height: 200 });
    expect(qtDialogResizeSize(
      400,
      120,
      500,
      -80,
      new Set(["right", "top"]),
      { minWidth: 260, maxWidth: 600, minHeight: 90, maxHeight: 260 },
    )).toEqual({ width: 600, height: 200 });
  });
});

describe("waitForAudioEnd", () => {
  it("can be settled explicitly when paused", async () => {
    let finish: (() => void) | undefined;
    const listeners = new Map<string, () => void>();
    const audio = {
      addEventListener: (name: "ended" | "error", listener: () => void) => listeners.set(name, listener),
      play: async () => undefined,
    };
    const waiting = waitForAudioEnd(audio, (value) => { finish = value; });
    finish?.();
    await expect(waiting).resolves.toBeUndefined();
  });
});

describe("PauseReasonGate", () => {
  it("does not resume ASR until reply and audio pauses have both ended", () => {
    const gate = new PauseReasonGate<"reply" | "audio">();

    expect(gate.pause("reply")).toBe(true);
    expect(gate.pause("audio")).toBe(false);
    expect(gate.resume("reply")).toBe(false);
    expect(gate.paused).toBe(true);
    expect(gate.resume("audio")).toBe(true);
    expect(gate.paused).toBe(false);
  });

  it("handles audio arriving after the reply has already completed", () => {
    const gate = new PauseReasonGate<"reply" | "audio">();

    expect(gate.pause("reply")).toBe(true);
    expect(gate.resume("reply")).toBe(true);
    expect(gate.pause("audio")).toBe(true);
    expect(gate.resume("audio")).toBe(true);
    expect(gate.paused).toBe(false);
  });
});
