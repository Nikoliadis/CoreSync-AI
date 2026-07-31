import { create } from "zustand";
import { persist } from "zustand/middleware";

type UiState = {
  /** Desktop rail collapse. Persisted — it is a workspace preference. */
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;

  /** Mobile drawer. Never persisted: reopening the app inside a drawer is wrong. */
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),

      mobileNavOpen: false,
      setMobileNavOpen: (mobileNavOpen) => set({ mobileNavOpen }),
    }),
    {
      name: "coresync-ui",
      // Zustand owns only what never comes from the server (docs/07 §3.1), and
      // of that, only the durable half is written to storage.
      partialize: (state) => ({ sidebarCollapsed: state.sidebarCollapsed }),
    },
  ),
);
