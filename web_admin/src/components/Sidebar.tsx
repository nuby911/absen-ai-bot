"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  LayoutDashboard,
  LogOut,
  ScanFace,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { clearAuthSession, type UserProfile } from "@/lib/api";
import { getInitials } from "@/lib/format";

interface SidebarProps {
  user: UserProfile | null;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}

const NAV_ITEMS = [
  {
    href: "/",
    label: "Beranda",
    description: "Ringkasan hari ini",
    icon: LayoutDashboard,
  },
  {
    href: "/students",
    label: "Data Sekolah",
    description: "Siswa, Ortu, Kelas, Guru & Jadwal",
    icon: Users,
  },
  {
    href: "/faces",
    label: "Foto Wajah Siswa",
    description: "Upload & atur foto wajah (maks 5)",
    icon: ScanFace,
  },
  {
    href: "/evaluation",
    label: "Laporan & Akurasi",
    description: "Rekap absen, ketepatan wajah & WA",
    icon: BarChart3,
  },
];

export function Sidebar({
  user,
  mobileOpen = false,
  onCloseMobile,
}: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const onCloseMobileRef = useRef(onCloseMobile);

  useEffect(() => {
    onCloseMobileRef.current = onCloseMobile;
  }, [onCloseMobile]);

  useEffect(() => {
    if (!mobileOpen) return;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onCloseMobileRef.current?.();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileOpen]);

  function handleLogout() {
    clearAuthSession();
    onCloseMobile?.();
    router.replace("/login");
  }

  function isActivePath(href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  const sidebarBody = (
    <div className="flex h-full flex-col bg-[#0F172A] text-white">
      {/* Brand Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 px-5 py-5">
        <Link
          href="/"
          onClick={onCloseMobile}
          className="flex items-center gap-3 focus:outline-none"
        >
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#1D4ED8] text-white shadow-sm ring-1 ring-blue-400/30">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-base font-bold tracking-tight text-white">
              SmartSchool AI
            </p>
            <p className="truncate text-xs font-medium text-slate-400">
              Admin Panel • Polinela
            </p>
          </div>
        </Link>

        {onCloseMobile ? (
          <button
            type="button"
            onClick={onCloseMobile}
            aria-label="Tutup menu navigasi"
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        ) : null}
      </div>

      {/* Navigation Links */}
      <nav
        aria-label="Navigasi Admin"
        className="flex-1 space-y-1.5 overflow-y-auto px-3 py-5"
      >
        <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
          Menu Utama
        </p>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = isActivePath(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onCloseMobile}
              aria-current={active ? "page" : undefined}
              className={`group flex items-start gap-3 rounded-xl px-3.5 py-2.5 text-sm transition-all ${
                active
                  ? "bg-[#1D4ED8] text-white shadow-sm ring-1 ring-blue-400/30"
                  : "text-slate-300 hover:bg-slate-800/80 hover:text-white"
              }`}
            >
              <Icon
                className={`mt-0.5 h-4 w-4 shrink-0 ${
                  active
                    ? "text-white"
                    : "text-slate-400 group-hover:text-slate-200"
                }`}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="truncate font-semibold leading-5">{item.label}</p>
                <p
                  className={`truncate text-[11px] leading-4 ${
                    active ? "text-blue-100" : "text-slate-400"
                  }`}
                >
                  {item.description}
                </p>
              </div>
            </Link>
          );
        })}
      </nav>

      {/* Engine Status Footer + Logout */}
      <div className="border-t border-slate-800/80 p-4 space-y-3">
        <div className="rounded-xl bg-slate-900/90 p-3 ring-1 ring-slate-800">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#1D4ED8]/20 text-xs font-bold text-blue-300 ring-1 ring-blue-500/30">
              {getInitials(user?.name ?? "Admin Sekolah")}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-white">
                {user?.name ?? "Admin Sekolah"}
              </p>
              <p className="truncate text-xs text-slate-400">
                {user?.email ?? "admin@sekolah.sch.id"}
              </p>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={handleLogout}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/60 px-3.5 py-2.5 text-sm font-semibold text-slate-200 transition-colors hover:border-red-500/40 hover:bg-red-500/15 hover:text-red-200 focus:outline-none focus:ring-2 focus:ring-red-500/50"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          <span>Keluar</span>
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Fixed Sidebar */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:flex lg:w-72 lg:flex-col">
        {sidebarBody}
      </aside>

      {/* Mobile Drawer Overlay */}
      {mobileOpen ? (
        <div
          className="fixed inset-0 z-50 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Menu navigasi seluler"
        >
          <div
            className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs"
            onClick={onCloseMobile}
          />
          <div className="relative z-10 flex w-72 max-w-[85vw] flex-col shadow-2xl">
            {sidebarBody}
          </div>
        </div>
      ) : null}
    </>
  );
}
