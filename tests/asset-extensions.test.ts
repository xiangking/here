import { describe, expect, it } from "vitest";
import {
  CHARACTER_ANIMATION_EXTENSIONS,
  CHARACTER_ASSETS_EXTENSIONS,
  CHARACTER_IMAGE_EXTENSIONS,
  isLocalAssetExtension,
  LOCAL_ASSET_EXTENSIONS,
} from "../src/shared/asset-extensions";


describe("asset extension allow-list", () => {
  it("allows every character asset picker extension", () => {
    const pickerExtensions = [
      ...CHARACTER_ASSETS_EXTENSIONS,
      ...CHARACTER_IMAGE_EXTENSIONS,
      ...CHARACTER_ANIMATION_EXTENSIONS,
    ];
    for (const extension of pickerExtensions) {
      expect(isLocalAssetExtension(`.${extension}`), `${extension} should be allowed`).toBe(true);
    }
  });

  it("keeps call-video formats available in the allow-list", () => {
    for (const extension of [".mp4", ".webm", ".m4v"]) {
      expect(LOCAL_ASSET_EXTENSIONS.has(extension)).toBe(true);
    }
  });

  it("normalizes extension casing", () => {
    expect(isLocalAssetExtension(".PNG")).toBe(true);
    expect(isLocalAssetExtension(".Mkv")).toBe(true);
  });
});
