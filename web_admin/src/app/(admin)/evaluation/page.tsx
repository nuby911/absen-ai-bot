"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bot,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Eye,
  FlaskConical,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Tag,
} from "lucide-react";
import { AdminPageHeader } from "@/components/AdminShell";
import { StatusBadge, type BadgeTone } from "@/components/StatusBadge";
import { ChatbotLogDetailModal } from "@/components/evaluation/ChatbotLogDetailModal";
import { ChatbotSimulatorModal } from "@/components/evaluation/ChatbotSimulatorModal";
import { FaceLogLabelModal } from "@/components/evaluation/FaceLogLabelModal";
import {
  ApiError,
  downloadAttendanceCsv,
  getClasses,
  getEvaluationChatbotLogs,
  getEvaluationFaceLogs,
  getEvaluationMetrics,
  getParents,
  getStudents,
  updateFaceThreshold,
  type ChatbotDomainFilter,
  type ChatbotLogItem,
  type EvaluationDashboardResponse,
  type FaceLogStatusFilter,
  type FaceRecognitionLogItem,
  type PaginatedChatbotLogsResponse,
  type PaginatedFaceLogsResponse,
  type Parent,
  type SchoolClass,
  type Student,
} from "@/lib/api";
import {
  formatWaPhoneDisplay,
  formatWibDate,
  formatWibDateTime,
} from "@/lib/format";

const PAGE_SIZE = 20;

const FACE_FILTER_PILLS: Array<{ key: FaceLogStatusFilter; label: string }> = [
  { key: "all", label: "Semua" },
  { key: "unlabeled", label: "Belum Dilabeli" },
  { key: "labeled", label: "Sudah Dilabeli" },
  { key: "errors", label: "Salah / FP & FN" },
];

const CHATBOT_FILTER_PILLS: Array<{
  key: ChatbotDomainFilter;
  label: string;
}> = [
  { key: "all", label: "Semua" },
  { key: "true", label: "In-Domain" },
  { key: "false", label: "Out-of-Domain" },
];

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

function formatRangeSummary(
  offset: number,
  itemCount: number,
  total: number
): string {
  if (total === 0 || itemCount === 0) {
    return "Menampilkan 0 dari 0 log";
  }
  const start = offset + 1;
  const end = Math.min(offset + itemCount, total);
  return `Menampilkan ${start}–${end} dari ${total} log`;
}

export default function EvaluationPage() {
  const [recapDate, setRecapDate] = useState<string>("");
  const [evaluation, setEvaluation] =
    useState<EvaluationDashboardResponse | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [parents, setParents] = useState<Parent[]>([]);

  // Threshold state — never reset when recapDate changes
  const thresholdInitializedRef = useRef(false);
  const [thresholdDraft, setThresholdDraft] = useState<number>(0.55);

  // CSV Export filters (defaulted once recap_date arrives)
  const csvDatesInitializedRef = useRef(false);
  const [csvClassId, setCsvClassId] = useState<string>("");
  const [csvStartDate, setCsvStartDate] = useState<string>("");
  const [csvEndDate, setCsvEndDate] = useState<string>("");

  // Paginated Face Logs state
  const [faceStatusFilter, setFaceStatusFilter] =
    useState<FaceLogStatusFilter>("all");
  const [faceOffset, setFaceOffset] = useState<number>(0);
  const [faceLogsPage, setFaceLogsPage] =
    useState<PaginatedFaceLogsResponse | null>(null);
  const [loadingFaceLogs, setLoadingFaceLogs] = useState(true);

  // Paginated Chatbot Logs state
  const [chatbotDomainFilter, setChatbotDomainFilter] =
    useState<ChatbotDomainFilter>("all");
  const [chatbotOffset, setChatbotOffset] = useState<number>(0);
  const [chatbotLogsPage, setChatbotLogsPage] =
    useState<PaginatedChatbotLogsResponse | null>(null);
  const [loadingChatbotLogs, setLoadingChatbotLogs] = useState(true);

  // Modals
  const [labelingLog, setLabelingLog] = useState<FaceRecognitionLogItem | null>(
    null
  );
  const [selectedChatbotLog, setSelectedChatbotLog] =
    useState<ChatbotLogItem | null>(null);
  const [simulatorOpen, setSimulatorOpen] = useState(false);

  const [loadingMetrics, setLoadingMetrics] = useState(true);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const [exportingCsv, setExportingCsv] = useState(false);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Load master lists once on mount
  useEffect(() => {
    let cancelled = false;
    async function loadMasters() {
      try {
        const [studentsRes, classesRes, parentsRes] = await Promise.all([
          getStudents(),
          getClasses(),
          getParents(),
        ]);
        if (cancelled) return;
        setStudents(studentsRes);
        setClasses(classesRes);
        setParents(parentsRes);
      } catch {
        // Primary evaluation fetch surfaces main errors
      }
    }
    void loadMasters();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadMetrics = useCallback(async (targetDate: string) => {
    setLoadingMetrics(true);
    try {
      const evalRes = await getEvaluationMetrics(targetDate || undefined);
      setEvaluation(evalRes);
      if (!thresholdInitializedRef.current) {
        thresholdInitializedRef.current = true;
        setThresholdDraft(
          Math.min(0.95, Math.max(0.2, evalRes.face_metrics.threshold))
        );
      }
      if (!csvDatesInitializedRef.current) {
        csvDatesInitializedRef.current = true;
        setCsvStartDate(evalRes.recap_date);
        setCsvEndDate(evalRes.recap_date);
      }
      setErrorMsg(null);
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError
          ? err.message
          : "Gagal memuat metrik evaluasi sistem."
      );
    } finally {
      setLoadingMetrics(false);
    }
  }, []);

  const loadFaceLogs = useCallback(
    async (statusFilter: FaceLogStatusFilter, offset: number) => {
      setLoadingFaceLogs(true);
      try {
        const page = await getEvaluationFaceLogs({
          status: statusFilter,
          limit: PAGE_SIZE,
          offset,
        });
        if (page.items.length === 0 && offset > 0 && page.total > 0) {
          const prevValidOffset =
            Math.floor((page.total - 1) / PAGE_SIZE) * PAGE_SIZE;
          setFaceOffset(prevValidOffset);
          return;
        }
        setFaceLogsPage(page);
      } catch (err) {
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat log pemindaian wajah."
        );
      } finally {
        setLoadingFaceLogs(false);
      }
    },
    []
  );

  const loadChatbotLogs = useCallback(
    async (inDomain: ChatbotDomainFilter, offset: number) => {
      setLoadingChatbotLogs(true);
      try {
        const page = await getEvaluationChatbotLogs({
          in_domain: inDomain,
          limit: PAGE_SIZE,
          offset,
        });
        setChatbotLogsPage(page);
      } catch (err) {
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat log chatbot WhatsApp."
        );
      } finally {
        setLoadingChatbotLogs(false);
      }
    },
    []
  );

  // Metrics effect — re-runs when recapDate changes (does NOT reset thresholdDraft)
  useEffect(() => {
    let cancelled = false;
    async function syncMetrics() {
      try {
        const evalRes = await getEvaluationMetrics(recapDate || undefined);
        if (cancelled) return;
        setEvaluation(evalRes);
        if (!thresholdInitializedRef.current) {
          thresholdInitializedRef.current = true;
          setThresholdDraft(
            Math.min(0.95, Math.max(0.2, evalRes.face_metrics.threshold))
          );
        }
        if (!csvDatesInitializedRef.current) {
          csvDatesInitializedRef.current = true;
          setCsvStartDate(evalRes.recap_date);
          setCsvEndDate(evalRes.recap_date);
        }
        setErrorMsg(null);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat metrik evaluasi sistem."
        );
      } finally {
        if (!cancelled) setLoadingMetrics(false);
      }
    }
    void syncMetrics();
    return () => {
      cancelled = true;
    };
  }, [recapDate]);

  // Paginated Face Logs effect
  useEffect(() => {
    let cancelled = false;
    async function syncFaceLogs() {
      try {
        const page = await getEvaluationFaceLogs({
          status: faceStatusFilter,
          limit: PAGE_SIZE,
          offset: faceOffset,
        });
        if (cancelled) return;
        setFaceLogsPage(page);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat log pemindaian wajah."
        );
      } finally {
        if (!cancelled) setLoadingFaceLogs(false);
      }
    }
    void syncFaceLogs();
    return () => {
      cancelled = true;
    };
  }, [faceStatusFilter, faceOffset]);

  // Paginated Chatbot Logs effect
  useEffect(() => {
    let cancelled = false;
    async function syncChatbotLogs() {
      try {
        const page = await getEvaluationChatbotLogs({
          in_domain: chatbotDomainFilter,
          limit: PAGE_SIZE,
          offset: chatbotOffset,
        });
        if (cancelled) return;
        setChatbotLogsPage(page);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat log chatbot WhatsApp."
        );
      } finally {
        if (!cancelled) setLoadingChatbotLogs(false);
      }
    }
    void syncChatbotLogs();
    return () => {
      cancelled = true;
    };
  }, [chatbotDomainFilter, chatbotOffset]);

  const handleRefreshAll = useCallback(async () => {
    await Promise.all([
      loadMetrics(recapDate),
      loadFaceLogs(faceStatusFilter, faceOffset),
      loadChatbotLogs(chatbotDomainFilter, chatbotOffset),
    ]);
  }, [
    loadMetrics,
    loadFaceLogs,
    loadChatbotLogs,
    recapDate,
    faceStatusFilter,
    faceOffset,
    chatbotDomainFilter,
    chatbotOffset,
  ]);

  const face = evaluation?.face_metrics;
  const chatbot = evaluation?.chatbot_metrics;

  const isThresholdDirty =
    face !== undefined && Math.abs(thresholdDraft - face.threshold) >= 0.001;

  const csvDateInvalid = Boolean(
    csvStartDate && csvEndDate && csvEndDate < csvStartDate
  );

  async function handleSaveThreshold() {
    if (!isThresholdDirty) return;
    setSavingThreshold(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const res = await updateFaceThreshold(Number(thresholdDraft.toFixed(2)));
      setThresholdDraft(res.threshold);
      setSuccessMsg(
        `Threshold Cosine Similarity berhasil diperbarui menjadi ${res.threshold.toFixed(2)} untuk pemindaian Kiosk berikutnya.`
      );
      await loadMetrics(recapDate);
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
    if (csvDateInvalid) {
      setErrorMsg("Tanggal akhir CSV tidak boleh lebih awal dari tanggal mulai.");
      return;
    }
    setExportingCsv(true);
    setErrorMsg(null);
    try {
      await downloadAttendanceCsv({
        class_id: csvClassId || undefined,
        start_date: csvStartDate || undefined,
        end_date: csvEndDate || undefined,
      });
      setSuccessMsg("Laporan rekap absensi CSV berhasil diunduh.");
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError ? err.message : "Gagal mengekspor laporan CSV."
      );
    } finally {
      setExportingCsv(false);
    }
  }

  const anyLoading = loadingMetrics || loadingFaceLogs || loadingChatbotLogs;

  const headerActions = useMemo(
    () => (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setSimulatorOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-xl bg-[#1D4ED8] px-3.5 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#1E3A8A]"
        >
          <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Simulator Chatbot WA</span>
        </button>

        <button
          type="button"
          onClick={() => void handleRefreshAll()}
          disabled={anyLoading}
          className="inline-flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${anyLoading ? "animate-spin" : ""}`}
            aria-hidden="true"
          />
          <span>Muat Ulang</span>
        </button>
      </div>
    ),
    [handleRefreshAll, anyLoading]
  );

  const hasLabeledFaceLogs = (face?.total_labeled ?? 0) > 0;
  const domainDenominator =
    (chatbot?.in_domain_count ?? 0) + (chatbot?.out_of_domain_count ?? 0);

  const faceItems = faceLogsPage?.items ?? [];
  const faceTotal = faceLogsPage?.total ?? 0;
  const canFacePrev = faceOffset > 0;
  const canFaceNext = faceOffset + PAGE_SIZE < faceTotal;

  const chatbotItems = chatbotLogsPage?.items ?? [];
  const chatbotTotal = chatbotLogsPage?.total ?? 0;
  const canChatPrev = chatbotOffset > 0;
  const canChatNext = chatbotOffset + PAGE_SIZE < chatbotTotal;

  return (
    <>
      <AdminPageHeader
        title="Laporan & Evaluasi FAR/FRR"
        subtitle="Metrik ilmiah Confusion Matrix pengenalan wajah, evaluasi AI Chatbot WhatsApp, dan rekap kehadiran kelas."
        headerActions={headerActions}
      />

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
            {loadingMetrics || !hasLabeledFaceLogs
              ? "—"
              : `${(face?.accuracy ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {hasLabeledFaceLogs ? (
              <>
                (TP+TN) / Total Label: {(face?.tp ?? 0) + (face?.tn ?? 0)} /{" "}
                {face?.total_labeled ?? 0} log
              </>
            ) : (
              "Belum ada log berlabel ground-truth"
            )}
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
            {loadingMetrics || !hasLabeledFaceLogs
              ? "—"
              : `${(face?.far ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {hasLabeledFaceLogs ? (
              <>
                FP / (FP+TN): {face?.fp ?? 0} impostor lolos dari{" "}
                {(face?.fp ?? 0) + (face?.tn ?? 0)}
              </>
            ) : (
              "Belum ada log berlabel ground-truth"
            )}
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
            {loadingMetrics || !hasLabeledFaceLogs
              ? "—"
              : `${(face?.frr ?? 0).toFixed(2)}%`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {hasLabeledFaceLogs ? (
              <>
                FN / (FN+TP): {face?.fn ?? 0} siswa ditolak dari{" "}
                {(face?.fn ?? 0) + (face?.tp ?? 0)}
              </>
            ) : (
              "Belum ada log berlabel ground-truth"
            )}
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
            {loadingMetrics
              ? "—"
              : `${Math.round(chatbot?.avg_latency_ms ?? 0)} ms`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Rata-rata scan wajah:{" "}
            {Math.round(face?.avg_scan_latency_ms ?? 0)} ms (
            {face?.total_scans ?? 0} scan)
          </p>
        </div>
      </section>

      {/* Main 2-Column Section: Confusion Matrix + Threshold Slider | Chatbot Logs */}
      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-12">
        {/* Left Panel: Confusion Matrix + Threshold Slider */}
        <section className="xl:col-span-5 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-6">
          <div className="flex items-center justify-between gap-2">
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

          {/* Threshold Cosine Similarity Slider (0.20 - 0.95) */}
          <div className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <SlidersHorizontal
                  className="h-4 w-4 text-[#1D4ED8]"
                  aria-hidden="true"
                />
                <h3 className="text-sm font-bold text-[#0F172A]">
                  Slider Threshold Cosine Similarity
                </h3>
              </div>
              <div className="flex items-center gap-2">
                {isThresholdDirty ? (
                  <StatusBadge tone="warning">
                    Perubahan belum disimpan
                  </StatusBadge>
                ) : null}
                <span className="rounded-lg bg-white px-2.5 py-1 font-mono text-sm font-extrabold text-[#1D4ED8] ring-1 ring-[#E2E8F0]">
                  {thresholdDraft.toFixed(2)}
                </span>
              </div>
            </div>

            <input
              type="range"
              aria-label="Threshold Cosine Similarity"
              min={0.2}
              max={0.95}
              step={0.01}
              value={thresholdDraft}
              onChange={(e) => setThresholdDraft(Number(e.target.value))}
              className="threshold-slider w-full cursor-pointer"
            />

            <div className="flex justify-between text-[11px] font-medium text-slate-500">
              <span>0.20 (Longgar • FRR ↓)</span>
              <span>0.55 (Standar)</span>
              <span>0.95 (Ketat • FAR ↓)</span>
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
                disabled={!isThresholdDirty || savingThreshold}
                onClick={() => void handleSaveThreshold()}
                className="rounded-xl bg-[#1D4ED8] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {savingThreshold ? "Menyimpan..." : "Simpan Threshold"}
              </button>
            </div>

            <p className="text-[11px] text-slate-500">
              Threshold baru berlaku untuk pemindaian Kiosk berikutnya dan tidak
              mengubah hasil klasifikasi log historis secara surut.
            </p>
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
                  Klik baris untuk membaca percakapan penuh & balasan bot
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setSimulatorOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 bg-[#EFF6FF] px-3 py-1.5 text-xs font-semibold text-[#1D4ED8] hover:bg-blue-100"
            >
              <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Uji Simulator</span>
            </button>
          </div>

          {/* 4-Card Chatbot Summary (Separating In-Domain, Out-of-Domain, and Fallback) */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Total Pesan
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#0F172A] tabular-nums">
                {chatbot?.total_messages ?? 0}
              </p>
              <p className="text-[11px] text-slate-500">Semua interaksi WA</p>
            </div>

            <div className="rounded-xl border border-emerald-200 bg-[#ECFDF5] p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#059669]">
                In-Domain
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#065F46] tabular-nums">
                {domainDenominator > 0
                  ? `${(chatbot?.in_domain_rate ?? 0).toFixed(1)}%`
                  : "—"}
              </p>
              <p className="text-[11px] text-emerald-800">
                {chatbot?.in_domain_count ?? 0} pesan relevan
              </p>
            </div>

            <div className="rounded-xl border border-red-200 bg-[#FEF2F2] p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#DC2626]">
                Out-of-Domain
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#991B1B] tabular-nums">
                {chatbot?.out_of_domain_count ?? 0}
              </p>
              <p className="text-[11px] text-red-800">Di luar topik sekolah</p>
            </div>

            <div className="rounded-xl border border-amber-200 bg-[#FFFBEB] p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#D97706]">
                Fallback Rate
              </p>
              <p className="mt-1 text-2xl font-extrabold text-[#92400E] tabular-nums">
                {(chatbot?.total_messages ?? 0) > 0
                  ? `${(chatbot?.fallback_rate ?? 0).toFixed(1)}%`
                  : "—"}
              </p>
              <p className="text-[11px] text-amber-800">
                {chatbot?.fallback_count ?? 0} pesan fallback
              </p>
            </div>
          </div>

          {/* Chatbot Filter Pills */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              {CHATBOT_FILTER_PILLS.map((pill) => {
                const active = chatbotDomainFilter === pill.key;
                return (
                  <button
                    key={pill.key}
                    type="button"
                    onClick={() => {
                      if (pill.key === chatbotDomainFilter) return;
                      setLoadingChatbotLogs(true);
                      setChatbotDomainFilter(pill.key);
                      setChatbotOffset(0);
                    }}
                    className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                      active
                        ? "bg-[#1D4ED8] text-white shadow-2xs"
                        : "border border-[#E2E8F0] bg-[#F8FAFC] text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {pill.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Chatbot Table */}
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] font-semibold text-slate-500">
                <tr>
                  <th className="px-3 py-2.5">Waktu & Pengirim</th>
                  <th className="px-3 py-2.5">Pesan Orang Tua</th>
                  <th className="px-3 py-2.5">Intent / Tool</th>
                  <th className="px-3 py-2.5">Status</th>
                  <th className="px-3 py-2.5 text-right">Latency</th>
                  <th className="px-3 py-2.5 text-right">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loadingChatbotLogs ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-500">
                      Memuat log chatbot WhatsApp...
                    </td>
                  </tr>
                ) : chatbotItems.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-500">
                      Tidak ada riwayat interaksi AI Chatbot yang sesuai filter.
                    </td>
                  </tr>
                ) : (
                  chatbotItems.map((log) => (
                    <tr
                      key={log.id}
                      onClick={() => setSelectedChatbotLog(log)}
                      className="cursor-pointer hover:bg-[#F8FAFC]"
                    >
                      <td className="px-3 py-3 align-top whitespace-nowrap">
                        <p className="font-mono font-semibold text-[#0F172A]">
                          {formatWaPhoneDisplay(log.phone_wa)}
                        </p>
                        <p className="text-[11px] text-slate-400">
                          {formatWibDateTime(log.created_at)}
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
                      <td className="px-3 py-3 align-top text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedChatbotLog(log);
                          }}
                          className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1 text-[11px] font-semibold text-[#1D4ED8] hover:border-[#1D4ED8] hover:bg-[#EFF6FF]"
                        >
                          <Eye className="h-3 w-3" aria-hidden="true" />
                          <span>Lihat</span>
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Chatbot Pagination Footer */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E2E8F0] pt-3 text-xs text-slate-500">
            <span>
              {formatRangeSummary(
                chatbotOffset,
                chatbotItems.length,
                chatbotTotal
              )}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={!canChatPrev || loadingChatbotLogs}
                onClick={() => {
                  setLoadingChatbotLogs(true);
                  setChatbotOffset((prev) => Math.max(0, prev - PAGE_SIZE));
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Sebelumnya</span>
              </button>
              <button
                type="button"
                disabled={!canChatNext || loadingChatbotLogs}
                onClick={() => {
                  setLoadingChatbotLogs(true);
                  setChatbotOffset((prev) => prev + PAGE_SIZE);
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>Berikutnya</span>
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          </div>
        </section>
      </div>

      {/* Daily Attendance Recap per Class + Inline CSV Export Filters */}
      <section className="mt-6 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-[#0F172A]">
              Rekap Kehadiran Harian Per Kelas
            </h2>
            <p className="text-xs text-slate-500">
              Tanggal rekap aktif:{" "}
              <strong className="text-[#0F172A]">
                {formatWibDate(evaluation?.recap_date ?? recapDate)}
              </strong>
            </p>
          </div>

          {/* Recap Date Picker inside Card Header */}
          <div className="flex items-center gap-2">
            <label
              htmlFor="recap-date-picker"
              className="text-xs font-semibold text-slate-600"
            >
              Tanggal Rekap:
            </label>
            <div className="flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-1.5">
              <Calendar
                className="h-3.5 w-3.5 text-slate-400"
                aria-hidden="true"
              />
              <input
                id="recap-date-picker"
                type="date"
                value={recapDate || evaluation?.recap_date || ""}
                onChange={(e) => {
                  const next = e.target.value;
                  if (next === recapDate) return;
                  setLoadingMetrics(true);
                  setRecapDate(next);
                }}
                className="bg-transparent text-xs font-semibold text-[#0F172A] focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Inline CSV Export Filter Bar */}
        <div className="rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-4 space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="space-y-1">
                <label
                  htmlFor="csv-class-filter"
                  className="block text-[11px] font-semibold text-slate-600"
                >
                  Filter Kelas (CSV)
                </label>
                <select
                  id="csv-class-filter"
                  value={csvClassId}
                  onChange={(e) => setCsvClassId(e.target.value)}
                  className="rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-slate-700 focus:border-[#1D4ED8] focus:outline-none"
                >
                  <option value="">Semua Kelas</option>
                  {classes.map((cls) => (
                    <option key={cls.id} value={cls.id}>
                      {cls.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="csv-start-date"
                  className="block text-[11px] font-semibold text-slate-600"
                >
                  Tanggal Mulai
                </label>
                <input
                  id="csv-start-date"
                  type="date"
                  value={csvStartDate}
                  onChange={(e) => setCsvStartDate(e.target.value)}
                  className="rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <label
                  htmlFor="csv-end-date"
                  className="block text-[11px] font-semibold text-slate-600"
                >
                  Tanggal Akhir
                </label>
                <input
                  id="csv-end-date"
                  type="date"
                  value={csvEndDate}
                  onChange={(e) => setCsvEndDate(e.target.value)}
                  className="rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none"
                />
              </div>
            </div>

            <button
              type="button"
              onClick={() => void handleExportCsv()}
              disabled={exportingCsv || csvDateInvalid}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#10B981] px-4 py-2 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{exportingCsv ? "Mengunduh..." : "Ekspor CSV"}</span>
            </button>
          </div>

          {csvDateInvalid ? (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-xs font-medium text-[#DC2626]"
            >
              <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>
                Tanggal akhir tidak boleh lebih awal dari tanggal mulai.
              </span>
            </p>
          ) : null}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
              <tr>
                <th className="px-4 py-3">Kelas</th>
                <th className="px-4 py-3">Wali Kelas</th>
                <th className="px-4 py-3 text-center">Sesi</th>
                <th className="px-4 py-3 text-center">Hadir</th>
                <th className="px-4 py-3 text-center">Terlambat</th>
                <th className="px-4 py-3 text-center">Izin / Sakit</th>
                <th className="px-4 py-3 text-center">Alfa</th>
                <th className="px-4 py-3 text-right">
                  Notifikasi WA Orang Tua
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0]">
              {loadingMetrics ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
                    Memuat rekap kehadiran harian...
                  </td>
                </tr>
              ) : (evaluation?.class_recaps.length ?? 0) === 0 ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
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
                    <td className="px-4 py-3 text-center text-xs font-semibold text-slate-700 tabular-nums">
                      {recap.session_count}
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

      {/* Paginated & Filterable Face Recognition Logs + Quick Lab Labeling */}
      <section className="mt-6 rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-[#0F172A]">
              Log Pemindaian Wajah & Pelabelan Lab (Confusion Matrix)
            </h2>
            <p className="text-xs text-slate-500">
              Tandai ground-truth siswa atau impostor agar metrik TP/FP/FN/TN,
              FAR, dan FRR terhitung otomatis.
            </p>
          </div>

          {/* Face Log Filter Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            {FACE_FILTER_PILLS.map((pill) => {
              const active = faceStatusFilter === pill.key;
              return (
                <button
                  key={pill.key}
                  type="button"
                  onClick={() => {
                    if (pill.key === faceStatusFilter) return;
                    setLoadingFaceLogs(true);
                    setFaceStatusFilter(pill.key);
                    setFaceOffset(0);
                  }}
                  className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                    active
                      ? "bg-[#1D4ED8] text-white shadow-2xs"
                      : "border border-[#E2E8F0] bg-[#F8FAFC] text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {pill.label}
                </button>
              );
            })}
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
              {loadingFaceLogs ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    Memuat log pemindaian wajah...
                  </td>
                </tr>
              ) : faceItems.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-8 text-center text-slate-500">
                    Tidak ada log pemindaian wajah yang sesuai filter.
                  </td>
                </tr>
              ) : (
                faceItems.map((log) => {
                  const isLabeled = log.classification !== "unlabeled";
                  return (
                    <tr key={log.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-4 py-3 whitespace-nowrap text-slate-600">
                        {formatWibDateTime(log.created_at)}
                      </td>
                      <td className="px-4 py-3 font-semibold text-[#0F172A]">
                        {log.predicted_student_name ?? (
                          <span className="text-slate-400 italic">
                            Tidak Cocok
                          </span>
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
                          <span>{isLabeled ? "Edit Label" : "Labeli Log"}</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Face Logs Pagination Footer */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E2E8F0] pt-3 text-xs text-slate-500">
          <span>
            {formatRangeSummary(faceOffset, faceItems.length, faceTotal)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canFacePrev || loadingFaceLogs}
              onClick={() => {
                setLoadingFaceLogs(true);
                setFaceOffset((prev) => Math.max(0, prev - PAGE_SIZE));
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Sebelumnya</span>
            </button>
            <button
              type="button"
              disabled={!canFaceNext || loadingFaceLogs}
              onClick={() => {
                setLoadingFaceLogs(true);
                setFaceOffset((prev) => prev + PAGE_SIZE);
              }}
              className="inline-flex items-center gap-1 rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span>Berikutnya</span>
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </section>

      {/* Lab Labeling Modal */}
      {labelingLog ? (
        <FaceLogLabelModal
          key={labelingLog.id}
          log={labelingLog}
          students={students}
          onClose={() => setLabelingLog(null)}
          onLabeled={(_updated, action) => {
            setSuccessMsg(
              action === "unlabeled"
                ? "Label log wajah berhasil direset ke Belum Dilabeli dan Confusion Matrix diperbarui."
                : "Label ground-truth log wajah berhasil disimpan dan Confusion Matrix diperbarui."
            );
            void loadMetrics(recapDate);
            void loadFaceLogs(faceStatusFilter, faceOffset);
          }}
        />
      ) : null}

      {/* Full Chatbot Conversation Detail Modal */}
      <ChatbotLogDetailModal
        log={selectedChatbotLog}
        onClose={() => setSelectedChatbotLog(null)}
      />

      {/* Chatbot Dry-Run Simulator Modal */}
      {simulatorOpen ? (
        <ChatbotSimulatorModal
          open={simulatorOpen}
          parents={parents}
          onClose={() => setSimulatorOpen(false)}
          onSimulated={() => {
            void loadMetrics(recapDate);
            void loadChatbotLogs(chatbotDomainFilter, 0);
            setChatbotOffset(0);
          }}
        />
      ) : null}
    </>
  );
}
