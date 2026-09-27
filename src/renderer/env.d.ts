/// <reference types="vite/client" />

import type { HereDesktopApi } from "../shared/types";

declare global {
  interface Window {
    hereDesktop?: HereDesktopApi;
  }
}

declare module "*.css";

export {};
