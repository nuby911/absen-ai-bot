"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ClipboardList,
  ExternalLink,
  MessageSquare,
  Paperclip,
  RefreshCw,
  ScanFace,
  SlidersHorizontal,
  Users,
} from "lucide-react";
import { AdminPageHeader } from "@/components/AdminShell";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  getClasses,
  getEvaluationMetrics,
  getLeaveRequests,
  getStudents,
  resolveAssetUrl,
  type EvaluationDashboardResponse,
  type LeaveRequestItem,
  type SchoolClass,
  type Student,
} from "@/lib/api";
import {
  formatWaPhoneDisplay,
  formatWibDate,
  formatWibDateTime,
} from "@/lib/format";

function formatLeaveDateRange(startDate: string, endDate: string): string {
  if (!endDate || startDate === endDate) {
    return formatWibDate(startDate);
  }
  return `${formatWibDate(startDate)} – ${formatWibDate(endDate)}`;
}

export default function DashboardPage() {
  const [students, setStudents] = useState<Student[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [evaluation, setEvaluation] =
    useState<EvaluationDashboardResponse | null>(null);
  const [pendingLeaves, setPendingLeaves] = useState<LeaveRequestItem[]>([]);
  const [leavesModalOpen, setLeavesModalOpen] = useState(false);
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

  // Compute dataset readiness strictly over active students
  const activeStudents = useMemo(
    () => students.filter((s) => s.is_active),
    [students]
  );
  const readyDatasetStudents = useMemo(
    () => activeStudents.filter((s) => s.face_count >= 3),
    [activeStudents]
  );
  const anyFaceStudents = useMemo(
    () => activeStudents.filter((s) => s.face_count > 0),
    [activeStudents]
  );
  const datasetReadinessPct =
    activeStudents.length > 0
      ? Math.round((readyDatasetStudents.length / activeStudents.length) * 100)
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
  const totalAttendanceRecords =
    totalPresent + totalLate + totalPermitSick + totalAbsent;
  const totalWaSent =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.wa_sent_count, 0) ?? 0;
  const totalWaQueued =
    evaluation?.class_recaps.reduce((sum, c) => sum + c.wa_total_count, 0) ?? 0;

  const faceMetrics = evaluation?.face_metrics;
  const chatbotMetrics = evaluation?.chatbot_metrics;
  const hasLabeledFaceLogs = (faceMetrics?.total_labeled ?? 0) > 0;

  const headerActions = useMemo(
    () => (
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
    ),
    [loadDashboard, loading]
  );

  return (
    <>
      <AdminPageHeader
        title="Beranda"
        subtitle="Pantau kesiapan foto wajah, absensi harian, dan layanan WhatsApp sekolah."
        headerActions={headerActions}
      />

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
      <section
        aria-label="Indikator Utama"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
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
              Siap Absen Wajah
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
              {readyDatasetStudents.length}/{activeStudents.length} siswa aktif
              (≥3 foto)
            </span>
          </div>
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-[#10B981] transition-all"
              style={{ width: `${datasetReadinessPct}%` }}
            />
          </div>
          <p className="mt-1.5 text-[11px] text-slate-500">
            {anyFaceStudents.length} siswa aktif sudah memiliki minimal 1 foto
            wajah
          </p>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Total Presensi Hari Ini (Semua Sesi)
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
            {loading ? "—" : totalAttendanceRecords}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {totalPresent} Hadir • {totalLate} Terlambat • {totalPermitSick}{" "}
            Izin/Sakit • {totalAbsent} Alfa
          </p>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Ketepatan Kenal Wajah
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#FFFBEB] text-[#F59E0B]">
              <Activity className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold tracking-tight text-[#0F172A] tabular-nums">
            {loading || !hasLabeledFaceLogs
              ? "—"
              : `${(faceMetrics?.accuracy ?? 0).toFixed(1)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {hasLabeledFaceLogs ? (
              <>
                Salah orang {(faceMetrics?.far ?? 0).toFixed(1)}% • Gagal kenali{" "}
                {(faceMetrics?.frr ?? 0).toFixed(1)}% (
                {faceMetrics?.total_labeled ?? 0} data)
              </>
            ) : (
              "Belum ada data uji yang dikoreksi"
            )}
          </p>
        </div>
      </section>

      {/* Status Layanan & Quick Actions */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Service Status & Threshold */}
        <section className="lg:col-span-5 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-5">
          <div className="flex items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-[#0F172A]">
                Status Layanan & Parameter
              </h2>
              <p className="text-xs text-slate-500">
                Konfigurasi aktif engine pengenalan wajah & WhatsApp
              </p>
            </div>
            <StatusBadge tone={error ? "danger" : "success"}>
              {error ? "Gangguan Koneksi" : "Operasional"}
            </StatusBadge>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#EFF6FF] text-[#1D4ED8]">
                  <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-xs font-semibold text-[#0F172A]">
                    Tingkat Ketelitian Wajah
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Batas kemiripan minimal saat scan kamera
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
                    Notifikasi & Bot WhatsApp
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Topik Sekolah {(chatbotMetrics?.in_domain_rate ?? 0).toFixed(1)}%
                    • Balas rata-rata {Math.round(chatbotMetrics?.avg_latency_ms ?? 0)}{" "}
                    ms
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
              <div className="flex items-center gap-2">
                <StatusBadge
                  tone={pendingLeaves.length > 0 ? "warning" : "success"}
                >
                  {pendingLeaves.length} Pending
                </StatusBadge>
                {pendingLeaves.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => setLeavesModalOpen(true)}
                    className="text-xs font-semibold text-[#1D4ED8] hover:underline"
                  >
                    Lihat
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="pt-2 space-y-2.5">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Menu Cepat
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <Link
                href="/faces"
                className="flex items-center justify-between rounded-xl bg-[#1D4ED8] px-4 py-3 text-xs font-semibold text-white transition-colors hover:bg-[#1E3A8A]"
              >
                <span>Atur Foto Wajah</span>
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
              <Link
                href="/evaluation"
                className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-white px-4 py-3 text-xs font-semibold text-[#0F172A] transition-colors hover:bg-slate-50"
              >
                <span>Lihat Laporan</span>
                <BarChart3
                  className="h-4 w-4 text-[#1D4ED8]"
                  aria-hidden="true"
                />
              </Link>
            </div>
            <Link
              href="/students"
              className="flex items-center justify-between rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-4 py-2.5 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-100"
            >
              <span>Kelola Siswa, Guru & Kelas</span>
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
                Tanggal rekap:{" "}
                <strong className="text-[#0F172A]">
                  {evaluation?.recap_date
                    ? formatWibDate(evaluation.recap_date)
                    : "Hari ini"}
                </strong>{" "}
                • Total Alfa: {totalAbsent}
              </p>
            </div>
            <Link
              href="/evaluation"
              className="text-xs font-semibold text-[#1D4ED8] hover:underline"
            >
              Lihat Laporan Lengkap →
            </Link>
          </div>

          <div className="-mx-2 overflow-x-auto px-2 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[540px] text-left text-sm">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-xs font-semibold text-slate-500">
                  <th className="pb-3 pr-4 whitespace-nowrap">Kelas</th>
                  <th className="pb-3 pr-4 whitespace-nowrap">Wali Kelas</th>
                  <th className="pb-3 px-2 text-center whitespace-nowrap">Sesi</th>
                  <th className="pb-3 px-2 text-center whitespace-nowrap">Hadir</th>
                  <th className="pb-3 px-2 text-center whitespace-nowrap">Telat</th>
                  <th className="pb-3 px-2 text-center whitespace-nowrap">Izin/Sakit</th>
                  <th className="pb-3 px-2 text-center whitespace-nowrap">Alfa</th>
                  <th className="pb-3 pl-2 text-right whitespace-nowrap">Notif WA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}>
                      <td colSpan={8} className="py-3">
                        <div className="h-5 w-full animate-pulse rounded bg-slate-100" />
                      </td>
                    </tr>
                  ))
                ) : (evaluation?.class_recaps.length ?? 0) === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
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
                      <td className="py-3 px-2 text-center text-xs font-semibold text-slate-600 tabular-nums">
                        {recap.session_count}
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
            <div className="mt-5 rounded-xl border border-amber-200 bg-[#FFFBEB] p-4 space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-bold text-[#D97706]">
                  Pengajuan Izin/Sakit Terbaru ({pendingLeaves.length} menunggu
                  verifikasi guru):
                </p>
                <button
                  type="button"
                  onClick={() => setLeavesModalOpen(true)}
                  className="text-xs font-semibold text-[#1D4ED8] hover:underline"
                >
                  {pendingLeaves.length > 3
                    ? `+${pendingLeaves.length - 3} lainnya • Lihat Semua`
                    : "Lihat Semua"}
                </button>
              </div>
              <ul className="space-y-2">
                {pendingLeaves.slice(0, 3).map((leave) => {
                  const attachmentHref = resolveAssetUrl(leave.attachment_url);
                  return (
                    <li
                      key={leave.id}
                      className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-700"
                    >
                      <span className="min-w-0">
                        <strong className="text-[#0F172A]">
                          {leave.student_name}
                        </strong>{" "}
                        ({leave.class_name}) —{" "}
                        {leave.request_type === "sick" ? "Sakit" : "Izin"}:{" "}
                        {leave.reason}
                      </span>
                      <div className="flex items-center gap-2 shrink-0">
                        {attachmentHref ? (
                          <a
                            href={attachmentHref}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-[#1D4ED8] ring-1 ring-blue-200 hover:bg-[#EFF6FF]"
                          >
                            <Paperclip className="h-3 w-3" aria-hidden="true" />
                            <span>Lampiran</span>
                          </a>
                        ) : null}
                        <span className="font-mono text-[11px] text-slate-600">
                          {formatLeaveDateRange(
                            leave.start_date,
                            leave.end_date
                          )}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </section>
      </div>

      {/* All Pending Leaves Modal */}
      <Modal
        open={leavesModalOpen}
        onClose={() => setLeavesModalOpen(false)}
        maxWidthClass="max-w-3xl"
        title={`Semua Pengajuan Izin / Sakit Menunggu (${pendingLeaves.length})`}
        subtitle="Daftar seluruh pengajuan izin orang tua yang belum diverifikasi oleh guru melalui Mobile Guru."
      >
        {pendingLeaves.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            Tidak ada pengajuan izin yang sedang menunggu verifikasi.
          </p>
        ) : (
          <div className="space-y-3">
            {pendingLeaves.map((leave) => {
              const attachmentHref = resolveAssetUrl(leave.attachment_url);
              return (
                <div
                  key={leave.id}
                  className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-4 space-y-2.5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-bold text-[#0F172A]">
                          {leave.student_name}
                        </p>
                        <StatusBadge tone="primary">
                          {leave.class_name}
                        </StatusBadge>
                        <StatusBadge
                          tone={
                            leave.request_type === "sick" ? "danger" : "warning"
                          }
                        >
                          {leave.request_type === "sick" ? "Sakit" : "Izin"}
                        </StatusBadge>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        NIS: <span className="font-mono">{leave.student_nis}</span>{" "}
                        • Orang Tua: <strong>{leave.parent_name}</strong> (
                        <span className="font-mono text-[#059669]">
                          {formatWaPhoneDisplay(leave.parent_phone_wa)}
                        </span>
                        )
                      </p>
                    </div>
                    <span className="rounded-lg bg-white px-2.5 py-1 text-xs font-semibold text-[#0F172A] ring-1 ring-[#E2E8F0]">
                      {formatLeaveDateRange(leave.start_date, leave.end_date)}
                    </span>
                  </div>

                  <p className="rounded-xl border border-[#E2E8F0] bg-white p-3 text-xs leading-relaxed text-slate-700">
                    {leave.reason}
                  </p>

                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
                    <span>
                      Diajukan pada {formatWibDateTime(leave.created_at)}
                    </span>
                    {attachmentHref ? (
                      <a
                        href={attachmentHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-[#EFF6FF] px-3 py-1 text-xs font-semibold text-[#1D4ED8] hover:bg-blue-100"
                      >
                        <Paperclip className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>Lihat Lampiran Surat</span>
                        <ExternalLink className="h-3 w-3" aria-hidden="true" />
                      </a>
                    ) : (
                      <span className="italic text-slate-400">
                        Tanpa lampiran
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Modal>
    </>
  );
}
