import { describe, expect, it } from "vitest";
import type { ResolvedSprite } from "../src/shared/backend-types";
import { isVideoSprite, selectDisplaySprite } from "../src/renderer/sprite-media";

const sprite = (path: string, overrides: Partial<ResolvedSprite> = {}): ResolvedSprite => ({
  index: 0, path, frames: [], state_name: "neutral", ...overrides,
});

describe("video call display", () => {
  const neutral = sprite("/neutral.png");
  const happy = sprite("/happy.png", { index: 1, state_name: "happy" });
  const call = sprite("/video_call.mp4", { index: 2, state_name: "video_call" });
  const sprites = [neutral, happy, call];
  it("holds the dedicated video state during replies while enabled", () => {
    expect(selectDisplaySprite(sprites, true, "happy", 2)).toBe(call);
  });
  it("returns to a still neutral rather than a paused video when disabled", () => {
    expect(selectDisplaySprite(sprites, false, "happy", 3)).toMatchObject({ path: "/neutral.png", frames: [] });
  });
  it("preserves normal emotion selection for characters without a call state", () => {
    expect(selectDisplaySprite([neutral, happy], true, "happy")).toBe(happy);
    expect(selectDisplaySprite([neutral, happy], false, "happy")).toBe(happy);
    expect(selectDisplaySprite([], false)).toBeUndefined();
  });
  it("does not mutate a saved frame sequence when showing its still portrait", () => {
    const animated = { ...neutral, frames: ["/a.png", "/b.png"] };
    expect(selectDisplaySprite([animated, call], false)?.frames).toEqual([]);
    expect(animated.frames).toHaveLength(2);
  });
  it("detects native video files without treating neutral PNGs as video", () => {
    expect(isVideoSprite(call)).toBe(true);
    expect(isVideoSprite(sprite("C:\\video.WEBM"))).toBe(true);
    expect(isVideoSprite(neutral)).toBe(false);
  });
});
