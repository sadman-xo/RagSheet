import { create } from "zustand";
import type { QuerySpec } from "@/api/types";

export interface SavedView {
  id: string;
  name: string;
  path: string;
  search: string;
  created: string;
}

interface UiState {
  chatOpen: boolean;
  chatSeed: { text: string; nonce: number } | null;
  sidebarCollapsed: boolean;
  savedViews: SavedView[];
  openChat: (text?: string) => void;
  closeChat: () => void;
  toggleSidebar: () => void;
  saveView: (v: Omit<SavedView, "id" | "created">) => void;
  deleteView: (id: string) => void;
  reset: () => void;
}

const VIEWS_KEY = "panorama.savedViews";

function loadViews(): SavedView[] {
  try {
    return JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export const useUi = create<UiState>((set, get) => ({
  chatOpen: false,
  chatSeed: null,
  sidebarCollapsed: false,
  savedViews: loadViews(),
  openChat: (text) => set({ chatOpen: true, chatSeed: text ? { text, nonce: Date.now() } : get().chatSeed }),
  closeChat: () => set({ chatOpen: false }),
  toggleSidebar: () => set({ sidebarCollapsed: !get().sidebarCollapsed }),
  saveView: (v) => {
    const views = [{ ...v, id: crypto.randomUUID(), created: new Date().toISOString() }, ...get().savedViews].slice(0, 30);
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
    } catch {
      /* storage not available */
    }
    set({ savedViews: views });
  },
  deleteView: (id) => {
    const views = get().savedViews.filter((x) => x.id !== id);
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
    } catch {
      /* storage not available */
    }
    set({ savedViews: views });
  },
  reset: () => set({ chatOpen: false, chatSeed: null }),
}));

/** A question for the assistant about a widget's data. */
export function askAboutSpec(title: string, spec?: QuerySpec): string {
  void spec;
  return `Explain this: ${title}`;
}
