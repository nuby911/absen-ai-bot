"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Menu, ShieldCheck } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import {
  clearAuthSession,
  getAccessToken,
  getMe,
  getStoredUser,
  registerUnauthorizedHandler,
  setAuthSession,
  type UserProfile,
} from "@/lib/api";

interface AdminShellProps {
  title: string;
  subtitle?: string;
  headerActions?: ReactNode;
  children: ReactNode;
}

export function AdminShell({
  title,
  subtitle,
  headerActions,
  children,
}: AdminShellProps) {
  const router = useRouter();
  const [authStatus, setAuthStatus] = useState<"checking" | "authorized">(
    "checking"
  );
  const [user, setUser] = useState<UserProfile | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      router.replace("/login");
    });

    let cancelled = false;

    async function verifyAdminSession() {
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
        const profile = await getMe();
        if (cancelled) return;
        if (profile.role !== "admin") {
          clearAuthSession();
          router.replace("/login");
          return;
        }
        setAuthSession(token, profile);
        setUser(profile);
        setAuthStatus("authorized");
      } catch {
        if (cancelled) return;
        clearAuthSession();
        router.replace("/login");
      }
    }

    void verifyAdminSession();

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

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-[#0F172A]">
      <Sidebar
        user={user}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      <div className="lg:pl-72 flex min-h-screen flex-col">
        {/* Topbar */}
        <header className="sticky top-0 z-20 border-b border-[#E2E8F0] bg-white/95 backdrop-blur-sm">
          <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-4 px-4 py-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(true)}
                aria-label="Buka menu navigasi"
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-[#E2E8F0] bg-white text-slate-700 hover:bg-slate-50 lg:hidden"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div className="min-w-0">
                <h1 className="truncate text-xl font-bold tracking-tight text-[#0F172A] sm:text-2xl">
                  {title}
                </h1>
                {subtitle ? (
                  <p className="truncate text-xs text-slate-500 sm:text-sm">
                    {subtitle}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {headerActions}
              <div className="hidden sm:inline-flex items-center gap-2 rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-1.5 text-xs font-semibold text-slate-700">
                <span className="h-2 w-2 rounded-full bg-[#10B981]" />
                <span>Admin Aktif: {user?.name ?? "Admin"}</span>
              </div>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
