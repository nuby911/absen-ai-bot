"use client";

import { useState, type FormEvent } from "react";
import { AlertCircle, RotateCcw, ShieldAlert, UserCheck } from "lucide-react";
import { Modal } from "@/components/Modal";
import {
  ApiError,
  labelFaceLog,
  type FaceRecognitionLogItem,
  type Student,
} from "@/lib/api";

interface FaceLogLabelModalProps {
  log: FaceRecognitionLogItem | null;
  students: Student[];
  onClose: () => void;
  onLabeled: (
    updatedLog: FaceRecognitionLogItem,
    action: "labeled" | "unlabeled"
  ) => void;
}

const CONDITION_PRESETS = [
  "pencahayaan_normal",
  "cahaya_redup",
  "kacamata",
  "jarak_50cm",
  "kemiripan_tinggi",
  "non_siswa",
  "foto_cetak",
];

function stripImpostorPrefix(note: string | null | undefined): string {
  if (!note) return "";
  return note.trim().replace(/^impostor:?\s*/i, "").trim();
}

export function FaceLogLabelModal({
  log,
  students,
  onClose,
  onLabeled,
}: FaceLogLabelModalProps) {
  const [identityType, setIdentityType] = useState<"student" | "impostor">(
    log?.is_impostor ? "impostor" : "student"
  );
  // NEVER fall back to students[0]?.id
  const [actualStudentId, setActualStudentId] = useState<string>(
    log?.actual_student_id ?? log?.predicted_student_id ?? ""
  );
  const [conditionNote, setConditionNote] = useState<string>(
    stripImpostorPrefix(log?.condition_note)
  );
  const [submitting, setSubmitting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!log) return null;

  const isAlreadyLabeled = log.classification !== "unlabeled";
  const busy = submitting || resetting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!log) return;
    setError(null);

    if (identityType === "student" && !actualStudentId) {
      setError("Pilih siswa asli (ground-truth) terlebih dahulu.");
      return;
    }

    const cleanedNote = stripImpostorPrefix(conditionNote);

    setSubmitting(true);
    try {
      const updated = await labelFaceLog(log.id, {
        actual_student_id: identityType === "student" ? actualStudentId : null,
        is_impostor: identityType === "impostor",
        condition_note: cleanedNote || null,
      });
      onLabeled(updated, "labeled");
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Gagal menyimpan label pengujian."
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResetToUnlabeled() {
    if (!log) return;
    setError(null);
    setResetting(true);
    try {
      const updated = await labelFaceLog(log.id, {
        actual_student_id: null,
        is_impostor: false,
        condition_note: null,
      });
      onLabeled(updated, "unlabeled");
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Gagal mereset label pengujian."
      );
    } finally {
      setResetting(false);
    }
  }

  return (
    <Modal
      open={Boolean(log)}
      onClose={onClose}
      preventClose={busy}
      title={
        isAlreadyLabeled
          ? "Edit Ground-Truth Log Wajah"
          : "Pelabelan Ground-Truth Log Wajah"
      }
      subtitle={`Skor similarity: ${log.top_similarity_score.toFixed(3)} • Threshold: ${log.threshold_used.toFixed(2)} • Prediksi: ${log.predicted_student_name ?? "Tidak Cocok"}`}
    >
      <form onSubmit={handleSubmit} className="space-y-5">
        {error ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="space-y-2">
          <p className="text-xs font-semibold text-[#0F172A]">
            Identitas Sebenarnya Saat Pengujian Lab
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setIdentityType("student");
                setConditionNote((prev) => stripImpostorPrefix(prev));
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 rounded-xl border p-3 text-xs font-semibold transition-colors ${
                identityType === "student"
                  ? "border-[#1D4ED8] bg-[#EFF6FF] text-[#1D4ED8]"
                  : "border-[#E2E8F0] bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              <UserCheck className="h-4 w-4" aria-hidden="true" />
              <span>Siswa Terdaftar</span>
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setIdentityType("impostor");
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 rounded-xl border p-3 text-xs font-semibold transition-colors ${
                identityType === "impostor"
                  ? "border-[#EF4444] bg-[#FEF2F2] text-[#DC2626]"
                  : "border-[#E2E8F0] bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              <ShieldAlert className="h-4 w-4" aria-hidden="true" />
              <span>Impostor / Non-Siswa</span>
            </button>
          </div>
        </div>

        {identityType === "student" ? (
          <div className="space-y-1.5">
            <label
              htmlFor="actual-student"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Pilih Siswa Asli (Ground Truth)
            </label>
            <select
              id="actual-student"
              value={actualStudentId}
              onChange={(e) => setActualStudentId(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            >
              <option value="">-- Pilih Siswa --</option>
              {students.map((student) => (
                <option key={student.id} value={student.id}>
                  {student.name} ({student.nis} — {student.class_name})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-slate-700">
            Log ini akan diklasifikasikan sebagai pengujian negatif/impostor:
            <strong className="text-[#DC2626]"> FP</strong> jika sistem sempat
            mencocokkan, atau <strong className="text-[#1D4ED8]">TN</strong>{" "}
            jika ditolak dengan benar.
          </div>
        )}

        <div className="space-y-2">
          <label
            htmlFor="condition-note"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Catatan Kondisi Pengujian (Opsional)
          </label>
          <input
            id="condition-note"
            type="text"
            value={conditionNote}
            onChange={(e) => setConditionNote(e.target.value)}
            placeholder="Contoh: pencahayaan_normal, kacamata, cahaya_redup"
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
          <div className="flex flex-wrap gap-1.5">
            {CONDITION_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                disabled={busy}
                onClick={() => setConditionNote(preset)}
                className="rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:border-[#1D4ED8] hover:text-[#1D4ED8]"
              >
                {preset}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2.5 pt-2">
          <div>
            {isAlreadyLabeled ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleResetToUnlabeled()}
                className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-[#FEF2F2] px-3.5 py-2 text-xs font-semibold text-[#DC2626] hover:bg-red-100 disabled:opacity-60"
              >
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                <span>
                  {resetting ? "Mereset..." : "Reset ke Belum Dilabeli"}
                </span>
              </button>
            ) : null}
          </div>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              disabled={busy}
              onClick={onClose}
              className="rounded-xl border border-[#E2E8F0] bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Batal
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
            >
              {submitting ? "Menyimpan..." : "Simpan Label"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}
