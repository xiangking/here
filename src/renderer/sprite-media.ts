import type { ResolvedSprite } from "../shared/backend-types";

export const isVideoSprite = (sprite: Pick<ResolvedSprite, "path">): boolean => /\.(mp4|webm|m4v)$/i.test(sprite.path);

export function selectDisplaySprite(sprites: ResolvedSprite[], videoCallEnabled: boolean,
  emotion = "neutral", assetId?: string | number | null): ResolvedSprite | undefined {
  const call = sprites.find((sprite) => sprite.state_name === "video_call");
  if (call && videoCallEnabled) return call;
  const normal = sprites.filter((sprite) => sprite.state_name !== "video_call");
  // A disabled call stays on a still neutral portrait, including after replies.
  if (call && !videoCallEnabled) {
    const neutral = normal.find((sprite) => sprite.state_name === "neutral") || normal[0];
    return neutral ? { ...neutral, frames: [], spritesheet_path: "" } : undefined;
  }
  const index = Number(assetId) - 1;
  return (Number.isInteger(index) && index >= 0 ? normal.find((sprite) => sprite.index === index) : undefined)
    || normal.find((sprite) => sprite.state_name === emotion)
    || normal.find((sprite) => sprite.state_name === "neutral") || normal[0];
}
