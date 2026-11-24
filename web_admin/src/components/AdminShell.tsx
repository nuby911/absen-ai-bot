"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { Menu, RefreshCw, ShieldCheck, WifiOff } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import {
  ApiError,
  clearAuthSession,
  getAccessToken,
  getMe,
  getStoredUser,
  registerUnauthorizedHandler,
  setAuthSession,
  type UserProfile,
} from "@/lib/api";

export interface AdminHeaderConfig {
  title: string;
  subtitle?: string;
  headerActions?: ReactNode;
}

interface AdminHeaderStore {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => AdminHeaderConfig;
  setHeader: (next: AdminHeaderConfig) => void;
}

const DEFAULT_HEADER: AdminHeaderConfig = {
  title: "SmartSchool AI",
  subtitle: "Panel Administrasi Sekolah",
};

function createAdminHeaderStore(): AdminHeaderStore {
  let current: AdminHeaderConfig = DEFAULT_HEADER;
  const listeners = new Set<() => void>();

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot() {
      return current;
    },
    setHeader(next) {
      current = next;
      listeners.forEach((listener) => listener());
    },
  };
}

const AdminHeaderStoreContext = createContext<AdminHeaderStore | null>(null);

export function AdminPageHeader({
  title,
  subtitle,
  headerActions,
}: AdminHeaderConfig) {
  const store = useContext(AdminHeaderStoreContext);

  useEffect(() => {
    store?.setHeader({ title, subtitle, headerActions });
  }, [store, title, subtitle, headerActions]);

  return null;
}

function AdminTopbar({
  user,
  onOpenMobileMenu,
}: {
  user: UserProfile | null;
  onOpenMobileMenu: () => void;
}) {
  const store = useContext(AdminHeaderStoreContext);
  const header = useSyncExternalStore(
    store ? store.subscribe : () => () => {},
    store ? store.getSnapshot : () => DEFAULT_HEADER,
    () => DEFAULT_HEADER
  );

  return (
    <header className="sticky top-0 z-20 border-b border-[#E2E8F0] bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={onOpenMobileMenu}
            aria-label="Buka menu navigasi"
            className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[#E2E8F0] bg-white text-slate-700 hover:bg-slate-50 lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-xl font-bold tracking-tight text-[#0F172A] sm:text-2xl">
              {header.title}
            </h1>
            {header.subtitle ? (
              <p className="truncate text-xs text-slate-500 sm:text-sm">
                {header.subtitle}
              </p>
            ) : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {header.headerActions}
          <div className="hidden sm:inline-flex items-center gap-2 rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-1.5 text-xs font-semibold text-slate-700">
            <span className="h-2 w-2 rounded-full bg-[#10B981]" />
            <span>Admin Aktif: {user?.name ?? "Admin"}</span>
          </div>
        </div>
      </div>
    </header>
  );
}

interface AdminShellProps {
  children: ReactNode;
}

export function AdminShell({ children }: AdminShellProps) {
  const router = useRouter();
  const headerStore = useMemo(() => createAdminHeaderStore(), []);

  const [authStatus, setAuthStatus] = useState<
    "checking" | "authorized" | "error"
  >("checking");
  const [authError, setAuthError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const verifyAdminSession = useCallback(
    async (isManualRetry = false): Promise<void> => {
      if (isManualRetry) {
        setRetrying(true);
      }
      const token = getAccessToken();
      if (!token) {
        router.replace("/login");
        return;
      }

      const cached = getStoredUser();
      if (cached && cached.role !== "admin") {
        clearAuthSession();
        router.replace("/login");
        return;
      }

      try {
        const profile = await getMe({ skipAuthRedirect: true });
        if (profile.role !== "admin") {
          clearAuthSession();
          router.replace("/login");
          return;
        }
        setAuthSession(token, profile);
        setUser(profile);
        setAuthError(null);
        setAuthStatus("authorized");
      } catch (err) {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearAuthSession();
          router.replace("/login");
          return;
        }
        // Keep existing token on network errors (status === 0) or 5xx outages
        setAuthError(
          err instanceof ApiError
            ? err.message
            : "Tidak dapat terhubung ke server. Periksa koneksi jaringan Anda lalu coba lagi."
        );
        setAuthStatus("error");
      } finally {
        if (isManualRetry) {
          setRetrying(false);
        }
      }
    },
    [router]
  );

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      router.replace("/login");
    });

    let cancelled = false;
    async function init() {
      const token = getAccessToken();
      if (!token) {
        router.replace("/login");
        return;
      }

      const cached = getStoredUser();
      if (cached && cached.role !== "admin") {
        clearAuthSession();
        router.replace("/login");
        return;
      }

      try {
        const profile = await getMe({ skipAuthRedirect: true });
        if (cancelled) return;
        if (profile.role !== "admin") {
          clearAuthSession();
          router.replace("/login");
          return;
        }
        setAuthSession(token, profile);
        setUser(profile);
        setAuthError(null);
        setAuthStatus("authorized");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          clearAuthSession();
          router.replace("/login");
          return;
        }
        setAuthError(
          err instanceof ApiError
            ? err.message
            : "Tidak dapat terhubung ke server. Periksa koneksi jaringan Anda lalu coba lagi."
        );
        setAuthStatus("error");
      }
    }

    void init();

    return () => {
      cancelled = true;
      registerUnauthorizedHandler(null);
    };
  }, [router]);

  if (authStatus === "checking") {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-6">
        <div className="w-full max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-8 shadow-xs text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
            <ShieldCheck className="h-6 w-6 animate-pulse" aria-hidden="true" />
          </div>
          <div className="space-y-1">
            <h2 className="text-base font-bold text-[#0F172A]">
              Memverifikasi Sesi Admin
            </h2>
            <p className="text-sm text-slate-500">
              Menyiapkan panel kontrol SmartSchool AI...
            </p>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-[#1D4ED8]" />
          </div>
        </div>
      </div>
    );
  }

  if (authStatus === "error") {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-6">
        <div
          role="alert"
          className="w-full max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-8 shadow-xs text-center space-y-5"
        >
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[#FEF2F2] text-[#DC2626]">
            <WifiOff className="h-6 w-6" aria-hidden="true" />
          </div>
          <div className="space-y-1.5">
            <h2 className="text-base font-bold text-[#0F172A]">
              Gagal Terhubung ke Server
            </h2>
            <p className="text-sm text-slate-600">
              {authError ||
                "Server backend sedang tidak merespons. Sesi login Anda tetap disimpan."}
            </p>
          </div>
          <div className="flex flex-col gap-2.5 sm:flex-row sm:justify-center">
            <button
              type="button"
              disabled={retrying}
              onClick={() => void verifyAdminSession(true)}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#1D4ED8] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:opacity-60"
            >
              <RefreshCw
                className={`h-4 w-4 ${retrying ? "animate-spin" : ""}`}
                aria-hidden="true"
              />
              <span>{retrying ? "Menghubungkan..." : "Coba Lagi"}</span>
            </button>
            <button
              type="button"
              disabled={retrying}
              onClick={() => {
                clearAuthSession();
                router.replace("/login");
              }}
              className="rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              Ganti Akun
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <AdminHeaderStoreContext.Provider value={headerStore}>
      <div className="min-h-screen bg-[#F8FAFC] text-[#0F172A]">
        <Sidebar
          user={user}
          mobileOpen={mobileMenuOpen}
          onCloseMobile={() => setMobileMenuOpen(false)}
        />

        <div className="lg:pl-72 flex min-h-screen flex-col">
          <AdminTopbar
            user={user}
            onOpenMobileMenu={() => setMobileMenuOpen(true)}
          />

          <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </main>
        </div>
      </div>
    </AdminHeaderStoreContext.Provider>
  );
}
