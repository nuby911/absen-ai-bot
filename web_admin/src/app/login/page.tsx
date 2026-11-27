"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  Eye,
  EyeOff,
  KeyRound,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  ApiError,
  clearAuthSession,
  getAccessToken,
  getMe,
  loginAdmin,
  setAuthSession,
} from "@/lib/api";

const SHOW_DEMO_HINT =
  process.env.NODE_ENV !== "production" ||
  process.env.NEXT_PUBLIC_SHOW_DEMO_HINT === "true";

export default function LoginPage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function checkExistingSession() {
      const token = getAccessToken();
      if (!token) {
        if (!cancelled) setCheckingSession(false);
        return;
      }
      try {
        const user = await getMe({ skipAuthRedirect: true });
        if (cancelled) return;
        if (user.role === "admin") {
          setAuthSession(token, user);
          router.replace("/");
          return;
        }
        clearAuthSession();
      } catch (err) {
        if (!cancelled) {
          if (
            err instanceof ApiError &&
            (err.status === 401 || err.status === 403)
          ) {
            clearAuthSession();
          }
        }
      }
      if (!cancelled) setCheckingSession(false);
    }
    void checkExistingSession();
    return () => {
      cancelled = true;
    };
  }, [router]);

  function handleFillDemo() {
    setIdentifier("admin@sekolah.sch.id");
    setPassword("admin123");
    setErrorMessage(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);

    if (!identifier.trim() || !password) {
      setErrorMessage("Email/NIP dan kata sandi wajib diisi.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await loginAdmin({
        identifier: identifier.trim(),
        password,
      });

      if (response.user.role !== "admin") {
        clearAuthSession();
        setErrorMessage(
          `Akses ditolak. Akun "${response.user.name}" memiliki peran "${response.user.role}", bukan Admin Sekolah. Gunakan aplikasi Mobile Guru untuk akun guru.`
        );
        return;
      }

      setAuthSession(response.access_token, response.user);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage(
          "Terjadi kesalahan saat memproses login. Silakan coba lagi."
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  if (checkingSession) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-6">
        <div className="w-full max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-8 shadow-xs text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
            <ShieldCheck className="h-6 w-6 animate-pulse" aria-hidden="true" />
          </div>
          <div className="space-y-1">
            <h1 className="text-base font-bold text-[#0F172A]">
              Memeriksa Sesi Admin
            </h1>
            <p className="text-sm text-slate-500">
              Mohon tunggu sebentar...
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
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col lg:flex-row">
      {/* Left Brand Panel */}
      <div className="bg-[#0F172A] text-white px-6 py-10 sm:px-12 lg:w-[44%] lg:flex lg:flex-col lg:justify-between lg:py-14">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#1D4ED8] shadow-sm ring-1 ring-blue-400/30">
            <ShieldCheck className="h-6 w-6 text-white" aria-hidden="true" />
          </div>
          <div>
            <p className="text-lg font-bold tracking-tight">SmartSchool AI</p>
            <p className="text-xs font-medium text-slate-400">
              Admin Panel • Politeknik Negeri Lampung
            </p>
          </div>
        </div>

        <div className="my-10 space-y-6 lg:my-0">
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs font-semibold text-blue-300">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Absensi Wajah & Bot WhatsApp Sekolah</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl leading-tight">
            Panel Admin Absensi Sekolah Cerdas
          </h1>
          <p className="max-w-md text-sm leading-relaxed text-slate-300">
            Kelola data siswa, kontak WhatsApp orang tua, jadwal kelas, foto
            wajah siswa, serta laporan kehadiran harian secara terpusat.
          </p>

          <div className="grid grid-cols-2 gap-3 pt-2 max-w-md">
            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3.5">
              <p className="text-xs font-medium text-slate-400">Absensi Wajah</p>
              <p className="mt-1 text-sm font-bold text-white">
                Kamera Kiosk Guru
              </p>
              <p className="text-[11px] text-emerald-400">Anti-Foto & Cepat</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3.5">
              <p className="text-xs font-medium text-slate-400">
                Info Orang Tua
              </p>
              <p className="mt-1 text-sm font-bold text-white">
                Bot WhatsApp Otomatis
              </p>
              <p className="text-[11px] text-blue-300">
                Notifikasi & Izin Online
              </p>
            </div>
          </div>
        </div>

        <p className="text-xs text-slate-500">
          © 2026 SmartSchool Attendance System • Akses terbatas khusus Admin
          Sekolah
        </p>
      </div>

      {/* Right Login Card */}
      <div className="flex flex-1 items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md rounded-2xl border border-[#E2E8F0] bg-white p-7 shadow-sm sm:p-9">
          <div className="space-y-1.5">
            <h2 className="text-2xl font-bold tracking-tight text-[#0F172A]">
              Masuk Panel Admin
            </h2>
            <p className="text-sm text-slate-500">
              Gunakan akun administrator sekolah untuk mengakses dashboard.
            </p>
          </div>

          {errorMessage ? (
            <div
              role="alert"
              className="mt-5 flex items-start gap-2.5 rounded-xl border border-red-200 bg-[#FEF2F2] p-3.5 text-sm text-[#DC2626]"
            >
              <AlertCircle
                className="mt-0.5 h-4 w-4 shrink-0"
                aria-hidden="true"
              />
              <span>{errorMessage}</span>
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="mt-6 space-y-5">
            <div className="space-y-1.5">
              <label
                htmlFor="identifier"
                className="block text-sm font-semibold text-[#0F172A]"
              >
                Email atau NIP
              </label>
              <div className="relative">
                <Mail
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                  aria-hidden="true"
                />
                <input
                  id="identifier"
                  name="identifier"
                  type="text"
                  autoComplete="username"
                  required
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="admin@sekolah.sch.id"
                  className="w-full rounded-xl border border-[#E2E8F0] bg-white py-2.5 pl-10 pr-4 text-sm text-[#0F172A] placeholder:text-slate-400 focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="password"
                className="block text-sm font-semibold text-[#0F172A]"
              >
                Kata Sandi
              </label>
              <div className="relative">
                <Lock
                  className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                  aria-hidden="true"
                />
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Masukkan kata sandi"
                  className="w-full rounded-xl border border-[#E2E8F0] bg-white py-2.5 pl-10 pr-11 text-sm text-[#0F172A] placeholder:text-slate-400 focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={
                    showPassword
                      ? "Sembunyikan kata sandi"
                      : "Tampilkan kata sandi"
                  }
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-slate-400 hover:text-slate-700"
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#1D4ED8] px-4 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#1E3A8A] disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-[#1D4ED8] focus:ring-offset-2"
            >
              {isSubmitting ? "Memverifikasi..." : "Masuk ke Dashboard Admin"}
            </button>
          </form>

          {/* Demo Account Hint (gated for non-production or explicit env flag) */}
          {SHOW_DEMO_HINT ? (
            <div className="mt-6 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <p className="flex items-center gap-1.5 text-xs font-bold text-[#0F172A]">
                    <KeyRound
                      className="h-3.5 w-3.5 text-[#1D4ED8]"
                      aria-hidden="true"
                    />
                    <span>Akun Demo Seeder</span>
                  </p>
                  <p className="font-mono text-xs text-slate-600">
                    admin@sekolah.sch.id / admin123
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleFillDemo}
                  className="shrink-0 rounded-lg border border-blue-200 bg-[#EFF6FF] px-2.5 py-1.5 text-xs font-semibold text-[#1D4ED8] transition-colors hover:bg-blue-100"
                >
                  Isi Otomatis
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
