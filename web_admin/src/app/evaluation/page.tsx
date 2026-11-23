"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Tag,
} from "lucide-react";
import { AdminShell } from "@/components/AdminShell";
import { StatusBadge, type BadgeTone } from "@/components/StatusBadge";
import { FaceLogLabelModal } from "@/components/evaluation/FaceLogLabelModal";
import {
  ApiError,
  downloadAttendanceCsv,
  getEvaluationMetrics,
  getStudents,
  updateFaceThreshold,
  type EvaluationDashboardResponse,
  type FaceRecognitionLogItem,
  type Student,
} from "@/lib/api";
import {
  formatWaPhoneDisplay,
  formatWibTime,
} from "@/lib/format";

function getClassificationBadgeTone(classification: string): BadgeTone {
  switch (classification) {
    case "TP":
      return "success";
    case "FP":
      return "danger";
    case "FN":
      return "warning";
    case "TN":
      return "primary";
    default:
      return "neutral";
  }
}

export default function EvaluationPage() {
  const [recapDate, setRecapDate] = useState<string>("");
  const [evaluation, setEvaluation] =
    useState<EvaluationDashboardResponse | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [thresholdDraft, setThresholdDraft] = useState<number>(0.55);

  const [loading, setLoading] = useState(true);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);
  const [labelingLog, setLabelingLog] = useState<FaceRecognitionLogItem | null>(
    null
  );

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchEvaluationBundle = useCallback(async (targetDate: string) => {
    const [evalRes, studentsRes] = await Promise.all([
      getEvaluationMetrics(targetDate || undefined),
      getStudents(),
    ]);
    return { evalRes, studentsRes };
  }, []);

  const loadEvaluationData = useCallback(
    async (targetDate: string) => {
      setLoading(true);
      setErrorMsg(null);
      try {
        const { evalRes, studentsRes } = await fetchEvaluationBundle(targetDate);
        setEvaluation(evalRes);
        setStudents(studentsRes);
        setThresholdDraft(
          Math.min(0.85, Math.max(0.3, evalRes.face_metrics.threshold))
        );
      } catch (err) {
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat metrik evaluasi sistem."
        );
      } finally {
        setLoading(false);
      }
    },
    [fetchEvaluationBundle]
  );

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const { evalRes, studentsRes } = await fetchEvaluationBundle(recapDate);
        if (cancelled) return;
        setEvaluation(evalRes);
        setStudents(studentsRes);
        setThresholdDraft(
          Math.min(0.85, Math.max(0.3, evalRes.face_metrics.threshold))
        );
        setErrorMsg(null);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat metrik evaluasi sistem."
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [recapDate, fetchEvaluationBundle]);

  async function handleSaveThreshold() {
    setSavingThreshold(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const res = await updateFaceThreshold(Number(thresholdDraft.toFixed(2)));
      setSuccessMsg(
        `Threshold Cosine Similarity berhasil diperbarui menjadi ${res.threshold.toFixed(2)}.`
      );
      await loadEvaluationData(recapDate);
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError
          ? err.message
          : "Gagal menyimpan threshold Cosine Similarity."
      );
    } finally {
      setSavingThreshold(false);
    }
  }

  async function handleExportCsv() {
    setExportingCsv(true);
    setErrorMsg(null);
    try {
      await downloadAttendanceCsv();
      setSuccessMsg("Laporan rekap absensi (rekap-absensi.csv) berhasil diunduh.");
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError ? err.message : "Gagal mengekspor laporan CSV."
      );
    } finally {
      setExportingCsv(false);
    }
  }

  const face = evaluation?.face_metrics;
  const chatbot = evaluation?.chatbot_metrics;

  return (
    <AdminShell
      title="Laporan & Evaluasi FAR/FRR"
      subtitle="Metrik ilmiah Confusion Matrix pengenalan wajah, evaluasi AI Chatbot WhatsApp, dan rekap kehadiran kelas."
      headerActions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3 py-1.5">
            <Calendar className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
            <input
              type="date"
              aria-label="Tanggal rekap harian"
              value={recapDate || evaluation?.recap_date || ""}
              onChange={(e) => {
                setLoading(true);
                setRecapDate(e.target.value);
              }}
              className="text-xs font-semibold text-[#0F172A] focus:outline-none"
            />
          </div>

          <button
            type="button"
            onClick={() => void loadEvaluationData(recapDate)}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            <span>Muat Ulang</span>
          </button>

          <button
            type="button"
            onClick={() => void handleExportCsv()}
            disabled={exportingCsv}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#10B981] px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-emerald-600 disabled:opacity-60"
          >
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{exportingCsv ? "Mengunduh..." : "Ekspor CSV"}</span>
          </button>
        </div>
      }
    >
      {/* Status Notifications */}
      {successMsg ? (
        <div
          role="status"
          className="mb-5 flex items-center justify-between gap-3 rounded-2xl border border-emerald-200 bg-[#ECFDF5] px-4 py-3 text-sm text-[#059669]"
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{successMsg}</span>
          </div>
          <button
            type="button"
            onClick={() => setSuccessMsg(null)}
            className="text-xs font-semibold underline"
          >
            Tutup
          </button>
        </div>
      ) : null}

      {errorMsg ? (
        <div
          role="alert"
          className="mb-5 flex items-center justify-between gap-3 rounded-2xl border border-red-200 bg-[#FEF2F2] px-4 py-3 text-sm text-[#DC2626]"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{errorMsg}</span>
          </div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            className="text-xs font-semibold underline"
          >
            Tutup
          </button>
        </div>
      ) : null}

      {/* 4 Scientific KPI Cards (Screen 11) */}
      <section
        aria-label="KPI Evaluasi Ilmiah"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Face Recognition Accuracy
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#EFF6FF] text-[#1D4ED8]">
              <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-[#0F172A] tabular-nums">
            {loading ? "—" : `${(face?.accuracy ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            (TP+TN) / Total Label: {(face?.tp ?? 0) + (face?.tn ?? 0)} /{" "}
            {face?.total_labeled ?? 0} log
          </p>
        </div>

        <div className="rounded-2xl border border-red-200/80 bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              FAR (False Acceptance Rate)
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#FEF2F2] text-[#EF4444]">
              <ShieldAlert className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-[#EF4444] tabular-nums">
            {loading ? "—" : `${(face?.far ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            FP / (FP+TN): {face?.fp ?? 0} impostor lolos dari{" "}
            {(face?.fp ?? 0) + (face?.tn ?? 0)}
          </p>
        </div>

        <div className="rounded-2xl border border-amber-200/80 bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              FRR (False Rejection Rate)
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#FFFBEB] text-[#F59E0B]">
              <Activity className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-[#F59E0B] tabular-nums">
            {loading ? "—" : `${(face?.frr ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            FN / (FN+TP): {face?.fn ?? 0} siswa ditolak dari{" "}
            {(face?.fn ?? 0) + (face?.tp ?? 0)}
          </p>
        </div>

        <div className="rounded-2xl border border-emerald-200/80 bg-white p-5 shadow-2xs">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Avg WA Chatbot Latency
            </p>
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#ECFDF5] text-[#10B981]">
              <Clock className="h-4 w-4" aria-hidden="true" />
            </div>
          </div>
          <p className="mt-3 text-3xl font-extrabold text-[#10B981] tabular-nums">
            {loading ? "—" : `${Math.round(chatbot?.avg_latency_ms ?? 0)} ms`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Rata-rata scan wajah:{" "}
            {Math.round(face?.avg_scan_latency_ms ?? 0)} ms ({face?.total_scans ?? 0}{" "}
            scan)
          </p>
        </div>
      </section>

      {/* Main 2-Column Section: Confusion Matrix + Threshold Slider | Chatbot Logs */}
      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-12">
        {/* Left Panel: Confusion Matrix + Threshold Slider */}
        <section className="xl:col-span-5 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-[#0F172A]">
                Confusion Matrix Pengenalan Wajah
              </h2>
              <p className="text-xs text-slate-500">
                Total {face?.total_scans ?? 0} scan ({face?.total_labeled ?? 0}{" "}
                sudah berlabel ground-truth)
              </p>
            </div>
            <StatusBadge tone="primary">
              Threshold {(face?.threshold ?? 0.55).toFixed(2)}
            </StatusBadge>
          </div>

          {/* 2x2 Matrix Grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-emerald-200 bg-[#ECFDF5] p-4">
              <p className="text-xs font-bold text-[#059669]">
                True Positive (TP)
              </p>
              <p className="mt-2 text-3xl font-extrabold text-[#065F46] tabular-nums">
                {face?.tp ?? 0}
              </p>
              <p className="mt-1 text-[11px] text-emerald-800/80">
                Siswa teridentifikasi sesuai identitas asli
              </p>
            </div>

            <div className="rounded-2xl border border-red-200 bg-[#FEF2F2] p-4">
              <p className="text-xs font-bold text-[#DC2626]">
                False Positive (FP)
              </p>
              <p className="mt-2 text-3xl font-extrabold text-[#991B1B] tabular-nums">
                {face?.fp ?? 0}
              </p>
              <p className="mt-1 text-[11px] text-red-800/80">
                Impostor / siswa lain keliru diterima (FAR)
              </p>
            </div>

            <div className="rounded-2xl border border-amber-200 bg-[#FFFBEB] p-4">
              <p className="text-xs font-bold text-[#D97706]">
                False Negative (FN)
              </p>
              <p className="mt-2 text-3xl font-extrabold text-[#92400E] tabular-nums">
                {face?.fn ?? 0}
              </p>
              <p className="mt-1 text-[11px] text-amber-800/80">
                Siswa terdaftar gagal dikenali sistem (FRR)
              </p>
            </div>

            <div className="rounded-2xl border border-blue-200 bg-[#EFF6FF] p-4">
              <p className="text-xs font-bold text-[#1D4ED8]">
                True Negative (TN)
              </p>
              <p className="mt-2 text-3xl font-extrabold text-[#1E3A8A] tabular-nums">
                {face?.tn ?? 0}
              </p>
              <p className="mt-1 text-[11px] text-blue-900/80">
                Non-siswa / impostor ditolak dengan tepat
              </p>
            </div>
          </div>

          {/* Threshold Cosine Similarity Slider */}
          <div className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-5 space-y-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <SlidersHorizontal
                  className="h-4 w-4 text-[#1D4ED8]"
                  aria-hidden="true"
                />
                <h3 className="text-sm font-bold text-[#0F172A]">
                  Slider Threshold Cosine Similarity
                </h3>
              </div>
              <span className="rounded-lg bg-white px-2.5 py-1 font-mono text-sm font-extrabold text-[#1D4ED8] ring-1 ring-[#E2E8F0]">
                {thresholdDraft.toFixed(2)}
              </span>
            </div>

            <input
              type="range"
              aria-label="Threshold Cosine Similarity"
              min={0.3}
              max={0.85}
              step={0.01}
              value={thresholdDraft}
              onChange={(e) => setThresholdDraft(Number(e.target.value))}
              className="threshold-slider w-full cursor-pointer"
            />

            <div className="flex justify-between text-[11px] font-medium text-slate-500">
              <span>0.30 (Longgar • FRR ↓)</span>
              <span>0.55 (Standar)</span>
              <span>0.85 (Ketat • FAR ↓)</span>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <div className="flex items-center gap-1.5">
                {[0.45, 0.55, 0.68].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setThresholdDraft(preset)}
                    className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold ring-1 transition-colors ${
                      Math.abs(thresholdDraft - preset) < 0.005
                        ? "bg-[#EFF6FF] text-[#1D4ED8] ring-[#1D4ED8]"
                        : "bg-white text-slate-600 ring-[#E2E8F0] hover:bg-slate-50"
                    }`}
                  >
                    {preset.toFixed(2)}
                  </button>
                ))}
              </div>

              <button
                type="button"
                disabled={savingThreshold}
                onClick={() => void handleSaveThreshold()}
                className="rounded-xl bg-[#1D4ED8] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:opacity-60"
              >
                {savingThreshold ? "Menyimpan..." : "Simpan Threshold"}
              </button>
            </div>
          </div>
        </section>

        {/* Right Panel: AI Chatbot WhatsApp Evaluation Logs */}
        <section className="xl:col-span-7 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs flex flex-col space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#ECFDF5] text-[#10B981]">
                <Bot className="h-5 w-5" aria-hidden="true" />
              </div>
              <div>
                <h2 className="text-base font-bold text-[#0F172A]">
                  Log Evaluasi AI Chatbot WhatsApp (Function Calling)
                </h2>
                <p className="text-xs text-slate-500">
                  Akurasi respons domain sekolah, pemanggilan tool, dan fallback
                  menu
                </p>
              </div>
            </div>
          </div>

          {/* Chatbot Summary Pills */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Total Pesan WA
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#0F172A] tabular-nums">
                {chatbot?.total_messages ?? 0}
              </p>
            </div>

            <div className="rounded-xl border border-emerald-200 bg-[#ECFDF5] p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#059669]">
                In-Domain / Response Rate
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#065F46] tabular-nums">
                {(chatbot?.in_domain_rate ?? 0).toFixed(1)}%
              </p>
              <p className="text-[11px] text-emerald-800">
                {chatbot?.in_domain_count ?? 0} dari {chatbot?.total_messages ?? 0}{" "}
                pesan
              </p>
            </div>

            <div className="rounded-xl border border-amber-200 bg-[#FFFBEB] p-3.5">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#D97706]">
                Fallback Rate
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#92400E] tabular-nums">
                {(chatbot?.fallback_rate ?? 0).toFixed(1)}%
              </p>
              <p className="text-[11px] text-amber-800">
                {chatbot?.fallback_count ?? 0} fallback / di luar domain
              </p>
            </div>
          </div>

          {/* Chatbot Table */}
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] font-semibold text-slate-500">
                <tr>
                  <th className="px-3 py-2.5">Waktu & Pengirim</th>
                  <th className="px-3 py-2.5">Pesan Orang Tua</th>
                  <th className="px-3 py-2.5">Intent / Function Call</th>
                  <th className="px-3 py-2.5">Status</th>
                  <th className="px-3 py-2.5 text-right">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-500">
                      Memuat log chatbot WhatsApp...
                    </td>
                  </tr>
                ) : (chatbot?.recent_logs.length ?? 0) === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-500">
                      Belum ada riwayat interaksi AI Chatbot WhatsApp.
                    </td>
                  </tr>
                ) : (
                  chatbot?.recent_logs.map((log) => (
                    <tr key={log.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-3 py-3 align-top whitespace-nowrap">
                        <p className="font-mono font-semibold text-[#0F172A]">
                          {formatWaPhoneDisplay(log.phone_wa)}
                        </p>
                        <p className="text-[11px] text-slate-400">
                          {formatWibTime(log.created_at)}
                        </p>
                      </td>
                      <td className="px-3 py-3 align-top max-w-xs">
                        <p className="text-slate-700 line-clamp-2">
                          {log.user_message}
                        </p>
                      </td>
                      <td className="px-3 py-3 align-top">
                        <p className="font-semibold text-[#0F172A]">
                          {log.detected_intent || "-"}
                        </p>
                        {log.tool_called ? (
                          <code className="mt-0.5 inline-block rounded bg-[#EFF6FF] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#1D4ED8]">
                            {log.tool_called}()
                          </code>
                        ) : (
                          <span className="text-[11px] text-slate-400">
                            Tanpa tool call
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 align-top">
                        <div className="flex flex-col items-start gap-1">
                          <StatusBadge
                            tone={log.is_in_domain ? "success" : "danger"}
                          >
                            {log.is_in_domain ? "In-Domain" : "Out-of-Domain"}
                          </StatusBadge>
                          {log.is_fallback ? (
                            <StatusBadge tone="warning">Fallback</StatusBadge>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-3 py-3 align-top text-right font-mono font-semibold text-slate-700 whitespace-nowrap">
                        {log.latency_ms} ms
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Daily Attendance Recap per Class */}
      <section className="mt-6 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-base font-bold text-[#0F172A]">
              Rekap Kehadiran Harian Per Kelas
            </h2>
            <p className="text-xs text-slate-500">
              Tanggal rekap aktif:{" "}
              <strong className="text-[#0F172A]">
                {evaluation?.recap_date ?? recapDate}
              </strong>
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
              <tr>
                <th className="px-4 py-3">Kelas</th>
                <th className="px-4 py-3">Wali Kelas</th>
                <th className="px-4 py-3 text-center">Hadir</th>
                <th className="px-4 py-3 text-center">Terlambat</th>
                <th className="px-4 py-3 text-center">Izin / Sakit</th>
                <th className="px-4 py-3 text-center">Alfa</th>
                <th className="px-4 py-3 text-right">Notifikasi WA Orang Tua</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {(evaluation?.class_recaps.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-500">
                    Belum ada data kelas.
                  </td>
                </tr>
              ) : (
                evaluation?.class_recaps.map((recap) => (
                  <tr key={recap.class_id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-3 font-bold text-[#0F172A]">
                      {recap.class_name}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {recap.homeroom_teacher_name || "-"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge tone="success">
                        {recap.present_count}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge tone="warning">
                        {recap.late_count}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge tone="primary">
                        {recap.permit_or_sick_count}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <StatusBadge tone="danger">
                        {recap.absent_count}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs font-semibold text-slate-700">
                      {recap.wa_sent_count} / {recap.wa_total_count} Terkirim
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Recent Face Recognition Logs + Quick Lab Labeling */}
      <section className="mt-6 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-base font-bold text-[#0F172A]">
              Log Pemindaian Wajah & Pelabelan Lab (Confusion Matrix)
            </h2>
            <p className="text-xs text-slate-500">
              Klik <strong>Labeli Log</strong> untuk menandai ground-truth siswa
              atau impostor sehingga metrik TP/FP/FN/TN, FAR, dan FRR terhitung
              otomatis.
            </p>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] font-semibold text-slate-500">
              <tr>
                <th className="px-4 py-3">Waktu Scan</th>
                <th className="px-4 py-3">Prediksi Sistem</th>
                <th className="px-4 py-3">Ground Truth</th>
                <th className="px-4 py-3">Similarity / Thr</th>
                <th className="px-4 py-3">Liveness</th>
                <th className="px-4 py-3">Klasifikasi</th>
                <th className="px-4 py-3">Catatan Kondisi</th>
                <th className="px-4 py-3 text-right">Latency</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {(evaluation?.recent_face_logs.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    Belum ada log pemindaian wajah Kiosk.
                  </td>
                </tr>
              ) : (
                evaluation?.recent_face_logs.map((log) => (
                  <tr key={log.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-3 whitespace-nowrap text-slate-600">
                      {formatWibTime(log.created_at)}
                    </td>
                    <td className="px-4 py-3 font-semibold text-[#0F172A]">
                      {log.predicted_student_name ?? (
                        <span className="text-slate-400 italic">Tidak Cocok</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {log.is_impostor ? (
                        <StatusBadge tone="danger">Impostor</StatusBadge>
                      ) : log.actual_student_name ? (
                        <span className="font-semibold text-[#0F172A]">
                          {log.actual_student_name}
                        </span>
                      ) : (
                        <span className="text-slate-400">Belum dilabeli</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <span className="font-bold text-[#0F172A]">
                        {log.top_similarity_score.toFixed(3)}
                      </span>{" "}
                      <span className="text-slate-400">
                        / {log.threshold_used.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        tone={log.liveness_passed ? "success" : "danger"}
                      >
                        {log.liveness_passed ? "Lolos" : "Gagal"}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge
                        tone={getClassificationBadgeTone(log.classification)}
                      >
                        {log.classification === "unlabeled"
                          ? "Belum Dilabeli"
                          : log.classification}
                      </StatusBadge>
                    </td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-600">
                      {log.condition_note || "-"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-700 whitespace-nowrap">
                      {log.latency_ms} ms
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => setLabelingLog(log)}
                        className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1.5 text-[11px] font-semibold text-[#1D4ED8] hover:border-[#1D4ED8] hover:bg-[#EFF6FF]"
                      >
                        <Tag className="h-3 w-3" aria-hidden="true" />
                        <span>Labeli Log</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Lab Labeling Modal */}
      {labelingLog ? (
        <FaceLogLabelModal
          key={labelingLog.id}
          log={labelingLog}
          students={students}
          onClose={() => setLabelingLog(null)}
          onLabeled={() => {
            setSuccessMsg(
              "Label ground-truth log wajah berhasil disimpan dan Confusion Matrix diperbarui."
            );
            void loadEvaluationData(recapDate);
          }}
        />
      ) : null}
    </AdminShell>
  );
}
