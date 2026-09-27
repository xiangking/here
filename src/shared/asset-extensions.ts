// Single source of truth for the asset extensions that may flow between the
// Electron file pickers and the here-local:// serving layer. Character asset
// pickers must never offer an extension that is absent from
// LOCAL_ASSET_EXTENSIONS, otherwise a user can select a file that the serving
// layer later rejects.

export const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "gif", "bmp"] as const;
export const VIDEO_EXTENSIONS = ["mp4", "mov", "m4v", "avi", "mkv", "webm"] as const;
export const AUDIO_EXTENSIONS = ["wav", "mp3", "ogg", "m4a", "aac", "flac"] as const;

// Character state asset pickers. These are intentionally narrower than the
// full allow-list (for example character_image is a single still image), but
// every entry here must remain a subset of LOCAL_ASSET_EXTENSIONS.
export const CHARACTER_ASSETS_EXTENSIONS: string[] = [...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS];
export const CHARACTER_IMAGE_EXTENSIONS: string[] = ["png", "jpg", "jpeg", "webp", "bmp"];
export const CHARACTER_ANIMATION_EXTENSIONS: string[] = [
  "png", "jpg", "jpeg", "webp", "bmp",
  "mp4", "mov", "webm", "m4v", "avi",
];

export const LOCAL_ASSET_EXTENSIONS = new Set<string>(
  [...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS, ...AUDIO_EXTENSIONS].map((extension) => `.${extension}`),
);

export function isLocalAssetExtension(extension: string): boolean {
  return LOCAL_ASSET_EXTENSIONS.has(extension.toLowerCase());
}
