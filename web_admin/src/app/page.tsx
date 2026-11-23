"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ClipboardList,
  MessageSquare,
  RefreshCw,
  ScanFace,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { AdminShell } from "@/components/AdminShell";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  getClasses,
  getEvaluationMetrics,
  getLeaveRequests,
  getStudents,
  type EvaluationDashboardResponse,
  type LeaveRequestItem,
  type SchoolClass,
  type Student,
} from "@/lib/api";

export default function DashboardPage() {
  const [students, setStudents] = useState<Student[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [evaluation, setEvaluation] =
    useState<EvaluationDashboardResponse | null>(null);
  const [pendingLeaves, setPendingLeaves] = useState<LeaveRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    const [studentsRes, classesRes, evalRes, leavesRes] = await Promise.all([
      getStudents(),
      getClasses(),
      getEvaluationMetrics(),
      getLeaveRequests("pending"),
    ]);
    return { studentsRes, classesRes, evalRes, leavesRes };
  }, []);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { studentsRes, classesRes, evalRes, leavesRes } =
        await fetchDashboard();
      setStudents(studentsRes);
      setClasses(classesRes);
      setEvaluation(evalRes);
      setPendingLeaves(leavesRes);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Gagal memuat ringkasan dashboard."
      );
    } finally {
      setLoading(false);
    }
  }, [fetchDashboard]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const { studentsRes, classesRes, evalRes, leavesRes } =
          await fetchDashboard();
        if (cancelled) return;
        setStudents(studentsRes);
        setClasses(classesRes);
        setEvaluation(evalRes);
        setPendingLeaves(leavesRes);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat ringkasan dashboard."
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [fetchDashboard]);

  const activeStudents = students.filter((s) => s.is_active);
  const readyDatasetStudents = students.filter((s) => s.face_count >= 3);
  const anyFaceStudents = students.filter((s) => s.face_count > 0);
  const datasetReadinessPct =
    students.length > 0
      ? Math.round((readyDatasetStudents.length / students.length) * 100)
      : 0;

  const totalPresent =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.present_count, 0) ?? 0;
  const totalLate =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.late_count, 0) ?? 0;
  const totalPermitSick =
    evaluation?.class_recaps.reduce(
      (sum, c) => sum + c.permit_or_sick_count,
      0
    ) ?? 0;
  const totalAbsent =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.absent_count, 0) ?? 0;
  const totalWaSent =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.wa_sent_count, 0) ?? 0;
  const totalWaQueued =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.wa_total_count, 0) ?? 0;

  const faceMetrics = evaluation?.face_metrics;
  const chatbotMetrics = evaluation?.chatbot_metrics;

  return (
    <AdminShell
      title="Dashboard Ringkasan"
      subtitle="Pemantauan kesiapan dataset biometrik, kehadiran harian, dan layanan AI WhatsApp."
      headerActions={
        <button
          type="button"
          onClick={() => void loadDashboard()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
          <span>Muat Ulang</span>
        </button>
      }
    >
      {error ? (
        <div
          role="alert"
          className="mb-6 flex items-center justify-between gap-4 rounded-2xl border border-red-200 bg-[#FEF2F2] p-4 text-sm text-[#DC2626]"
        >
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => void loadDashboard()}
            className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-[#DC2626] ring-1 ring-red-200 hover:bg-red-50"
          >
            Coba Lagi
          </button>
        </div>
      ) : null}

      {/* 4 KPI Cards */}
      <section aria-label="Indikator Utama" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Total Siswa Terdaftar
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
              <Users className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
            {loading ? "—" : students.length}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {activeStudents.length} aktif di {classes.length} rombongan kelas
          </p>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Kesiapan Dataset Wajah
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#ECFDF5] text-[#10B981]">
              <ScanFace className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <p className="text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
              {loading ? "—" : `${datasetReadinessPct}%`}
            </p>
            <span className="text-xs font-semibold text-[#10B981]">
              {readyDatasetStudents.length}/{students.length} siswa (≥3 foto)
            </span>
          </div>
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-[#10B981] transition-all"
              style={{ width: `${datasetReadinessPct}%` }}
            />
          </div>
          <p className="mt-1.5 text-[11px] text-slate-500">
            {anyFaceStudents.length} siswa sudah memiliki minimal 1 foto wajah
          </p>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Kehadiran Hari Ini
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
            {loading ? "—" : totalPresent + totalLate}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {totalPresent} Hadir • {totalLate} Terlambat • {totalPermitSick} Izin/Sakit
          </p>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Akurasi Biometrik
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#FFFBEB] text-[#F59E0B]">
              <Activity className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
            {loading
              ? "—"
              : `${(faceMetrics?.accuracy ?? 0).toFixed(1)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            FAR {(faceMetrics?.far ?? 0).toFixed(1)}% • FRR{" "}
            {(faceMetrics?.frr ?? 0).toFixed(1)}% ({faceMetrics?.total_labeled ?? 0}{" "}
            log berlabel)
          </p>
        </div>
      </section>

      {/* Status Layanan & Quick Actions */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Service Status & Threshold */}
        <section className="lg:col-span-5 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-[#0F172A]">
                Status Layanan & Parameter
              </h2>
              <p className="text-xs text-slate-500">
                Konfigurasi aktif engine pengenalan wajah & WhatsApp
              </p>
            </div>
            <StatusBadge tone="success">Operasional</StatusBadge>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#1D4ED8]">
                  <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-[#0F172A]">
                    Threshold Cosine Similarity
                  </p>
                  <p className="text-[11px] text-slate-500">
                    InsightFace 512-d embedding match
                  </p>
                </div>
              </div>
              <span className="rounded-lg bg-white px-2.5 py-1 font-mono text-sm font-bold text-[#1D4ED8] ring-1 ring-[#E2E8F0]">
                {(faceMetrics?.threshold ?? 0.55).toFixed(2)}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#ECFDF5] text-[#10B981]">
                  <MessageSquare className="h-4 w-4" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-[#0F172A]">
                    Notifikasi & AI Chatbot WhatsApp
                  </p>
                  <p className="text-[11px] text-slate-500">
                    In-Domain {(chatbotMetrics?.in_domain_rate ?? 0).toFixed(1)}% •
                    Rata-rata {Math.round(chatbotMetrics?.avg_latency_ms ?? 0)} ms
                  </p>
                </div>
              </div>
              <span className="rounded-lg bg-white px-2.5 py-1 text-xs font-bold text-[#059669] ring-1 ring-[#E2E8F0]">
                {totalWaSent}/{totalWaQueued} Terkirim
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#FFFBEB] text-[#F59E0B]">
                  <ClipboardList className="h-4 w-4" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-[#0F172A]">
                    Pengajuan Izin/Sakit Menunggu
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Diverifikasi melalui aplikasi Mobile Guru
                  </p>
                </div>
              </div>
              <StatusBadge tone={pendingLeaves.length > 0 ? "warning" : "success"}>
                {pendingLeaves.length} Pending
              </StatusBadge>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="pt-2 space-y-2.5">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Tautan Cepat Admin
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Link
                href="/faces"
                className="flex items-center justify-between rounded-xl bg-[#1D4ED8] px-4 py-3 text-xs font-semibold text-white transition-colors hover:bg-[#1E3A8A]"
              >
                <span>Registrasi Wajah</span>
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="/evaluation"
                className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-white px-4 py-3 text-xs font-semibold text-[#0F172A] transition-colors hover:bg-slate-50"
              >
                <span>Evaluasi FAR/FRR</span>
                <BarChart3 className="h-4 w-4 text-[#1D4ED8]" aria-hidden="true" />
              </Link>
            </div>
            <Link
              href="/students"
              className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-4 py-2.5 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-100"
            >
              <span>Kelola Data Master (Siswa, Orang Tua, Kelas, Jadwal)</span>
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>
        </section>

        {/* Class Recap Table Today */}
        <section className="lg:col-span-7 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs flex flex-col">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-base font-bold text-[#0F172A]">
                Ringkasan Kehadiran Kelas Hari Ini
              </h2>
              <p className="text-xs text-slate-500">
                Tanggal rekap: {evaluation?.recap_date ?? "Hari ini"} • Total Alfa:{" "}
                {totalAbsent}
              </p>
            </div>
            <Link
              href="/evaluation"
              className="text-xs font-semibold text-[#1D4ED8] hover:underline"
            >
              Lihat Laporan Lengkap →
            </Link>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-xs font-semibold text-slate-500">
                  <th className="pb-3 pr-4">Kelas</th>
                  <th className="pb-3 pr-4">Wali Kelas</th>
                  <th className="pb-3 px-2 text-center">Hadir</th>
                  <th className="pb-3 px-2 text-center">Telat</th>
                  <th className="pb-3 px-2 text-center">Izin/Sakit</th>
                  <th className="pb-3 px-2 text-center">Alfa</th>
                  <th className="pb-3 pl-2 text-right">Notif WA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}>
                      <td colSpan={7} className="py-3">
                        <div className="h-5 w-full animate-pulse rounded bg-slate-100" />
                      </td>
                    </tr>
                  ))
                ) : (evaluation?.class_recaps.length ?? 0) === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="py-8 text-center text-sm text-slate-500"
                    >
                      Belum ada data kelas terdaftar.
                    </td>
                  </tr>
                ) : (
                  evaluation?.class_recaps.map((recap) => (
                    <tr key={recap.class_id} className="hover:bg-[#F8FAFC]">
                      <td className="py-3 pr-4 font-semibold text-[#0F172A]">
                        {recap.class_name}
                      </td>
                      <td className="py-3 pr-4 text-xs text-slate-600">
                        {recap.homeroom_teacher_name || "-"}
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className="inline-flex min-w-7 justify-center rounded-md bg-[#ECFDF5] px-2 py-0.5 text-xs font-bold text-[#059669] tabular-nums">
                          {recap.present_count}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className="inline-flex min-w-7 justify-center rounded-md bg-[#FFFBEB] px-2 py-0.5 text-xs font-bold text-[#D97706] tabular-nums">
                          {recap.late_count}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className="inline-flex min-w-7 justify-center rounded-md bg-[#EFF6FF] px-2 py-0.5 text-xs font-bold text-[#1D4ED8] tabular-nums">
                          {recap.permit_or_sick_count}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className="inline-flex min-w-7 justify-center rounded-md bg-[#FEF2F2] px-2 py-0.5 text-xs font-bold text-[#DC2626] tabular-nums">
                          {recap.absent_count}
                        </span>
                      </td>
                      <td className="py-3 pl-2 text-right text-xs font-semibold text-slate-700 tabular-nums">
                        {recap.wa_sent_count}/{recap.wa_total_count}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {pendingLeaves.length > 0 ? (
            <div className="mt-5 rounded-xl border border-amber-200 bg-[#FFFBEB] p-4">
              <p className="text-xs font-bold text-[#D97706]">
                Pengajuan Izin/Sakit Terbaru ({pendingLeaves.length} menunggu guru):
              </p>
              <ul className="mt-2 space-y-1.5">
                {pendingLeaves.slice(0, 3).map((leave) => (
                  <li
                    key={leave.id}
                    className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-700"
                  >
                    <span>
                      <strong className="text-[#0F172A]">
                        {leave.student_name}
                      </strong>{" "}
                      ({leave.class_name}) —{" "}
                      {leave.request_type === "sick" ? "Sakit" : "Izin"}:{" "}
                      {leave.reason}
                    </span>
                    <span className="font-mono text-[11px] text-slate-500">
                      {leave.start_date}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </AdminShell>
  );
}
