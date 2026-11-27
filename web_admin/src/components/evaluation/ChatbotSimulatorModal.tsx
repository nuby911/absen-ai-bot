"use client";

import { useState, type FormEvent } from "react";
import {
  AlertCircle,
  Bot,
  Clock,
  FlaskConical,
  Send,
  Wrench,
} from "lucide-react";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  simulateChatbot,
  type Parent,
  type WhatsAppWebhookResponse,
} from "@/lib/api";
import { formatWaPhoneDisplay } from "@/lib/format";

interface ChatbotSimulatorModalProps {
  open: boolean;
  parents: Parent[];
  onClose: () => void;
  onSimulated: () => void;
}

const SAMPLE_PROMPTS = [
  "Apakah anak saya sudah hadir di sekolah hari ini?",
  "Bagaimana jadwal pelajaran anak saya besok?",
  "Anak saya hari ini izin sakit demam, mohon dicatat.",
  "Siapa pemenang Piala Dunia terakhir?",
];

export function ChatbotSimulatorModal({
  open,
  parents,
  onClose,
  onSimulated,
}: ChatbotSimulatorModalProps) {
  const [selectedParentPhone, setSelectedParentPhone] = useState<string>("");
  const [messageText, setMessageText] = useState<string>("");
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WhatsAppWebhookResponse | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!selectedParentPhone) {
      setError("Pilih orang tua terdaftar terlebih dahulu.");
      return;
    }
    if (!messageText.trim()) {
      setError("Pesan uji simulasi wajib diisi.");
      return;
    }

    setSimulating(true);
    try {
      const response = await simulateChatbot({
        phone_wa: selectedParentPhone,
        message_text: messageText.trim(),
      });
      setResult(response);
      onSimulated();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Gagal menjalankan simulasi chatbot."
      );
    } finally {
      setSimulating(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={simulating}
      maxWidthClass="max-w-2xl"
      title="Tes Bot WhatsApp"
      subtitle="Coba kirim pesan seperti orang tua untuk mengecek balasan bot tanpa mengirim pesan WhatsApp asli."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label
            htmlFor="sim-parent"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Pilih Orang Tua (Pengirim Tes)
          </label>
          <select
            id="sim-parent"
            required
            value={selectedParentPhone}
            onChange={(e) => setSelectedParentPhone(e.target.value)}
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          >
            <option value="">-- Pilih Orang Tua --</option>
            {parents.map((parent) => (
              <option key={parent.id} value={parent.phone_wa}>
                {parent.name} ({formatWaPhoneDisplay(parent.phone_wa)})
              </option>
            ))}
          </select>
          {parents.length === 0 ? (
            <p className="text-[11px] text-[#D97706]">
              Belum ada data orang tua terdaftar. Tambahkan orang tua di menu
              Data Sekolah terlebih dahulu.
            </p>
          ) : null}
        </div>

        <div className="space-y-2">
          <label
            htmlFor="sim-message"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Pesan Uji Orang Tua
          </label>
          <textarea
            id="sim-message"
            rows={3}
            required
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            placeholder="Ketik pertanyaan atau pengajuan izin seperti pesan WhatsApp orang tua..."
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm text-[#0F172A] focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />

          <div className="flex flex-wrap gap-1.5">
            {SAMPLE_PROMPTS.map((sample) => (
              <button
                key={sample}
                type="button"
                disabled={simulating}
                onClick={() => setMessageText(sample)}
                className="rounded-full border border-[#E2E8F0] bg-[#F8FAFC] px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:border-[#1D4ED8] hover:text-[#1D4ED8]"
              >
                {sample}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2.5 pt-1">
          <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <FlaskConical className="h-3.5 w-3.5 text-[#1D4ED8]" aria-hidden="true" />
            <span>
              Mode tes: tidak mengirim WA asli, namun tercatat di riwayat bot.
            </span>
          </p>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={simulating}
              onClick={onClose}
              className="rounded-xl border border-[#E2E8F0] bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Tutup
            </button>
            <button
              type="submit"
              disabled={simulating || parents.length === 0}
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#1D4ED8] px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:opacity-60"
            >
              <Send className="h-3.5 w-3.5" aria-hidden="true" />
              <span>{simulating ? "Memproses..." : "Kirim Pesan Tes"}</span>
            </button>
          </div>
        </div>

        {/* Simulation Response Output */}
        {result ? (
          <div className="mt-4 rounded-2xl border border-emerald-200 bg-[#ECFDF5]/60 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs font-bold text-[#065F46]">
                <Bot className="h-4 w-4 text-[#10B981]" aria-hidden="true" />
                <span>Balasan Bot WhatsApp</span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <StatusBadge tone={result.is_in_domain ? "success" : "danger"}>
                  {result.is_in_domain ? "Topik Sekolah" : "Di Luar Topik"}
                </StatusBadge>
                <StatusBadge tone={result.is_fallback ? "warning" : "neutral"}>
                  {result.is_fallback ? "Balasan Cadangan" : "Normal"}
                </StatusBadge>
                <span className="inline-flex items-center gap-1 rounded-full border border-[#E2E8F0] bg-white px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700">
                  <Clock className="h-3 w-3 text-slate-400" aria-hidden="true" />
                  {result.latency_ms} ms
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-lg bg-white px-2.5 py-1 text-slate-600 ring-1 ring-[#E2E8F0]">
                Intent:{" "}
                <strong className="font-mono text-[#0F172A]">
                  {result.detected_intent || "-"}
                </strong>
              </span>
              <span className="inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1 text-[#1D4ED8] ring-1 ring-blue-200">
                <Wrench className="h-3 w-3" aria-hidden="true" />
                <strong className="font-mono">
                  {result.tool_called ? `${result.tool_called}()` : "Tanpa tool call"}
                </strong>
              </span>
            </div>

            <div className="rounded-xl border border-emerald-200 bg-white p-3.5 text-sm leading-relaxed text-[#0F172A] whitespace-pre-wrap break-words">
              {result.reply_text || "(Tidak ada balasan teks)"}
            </div>
          </div>
        ) : null}
      </form>
    </Modal>
  );
}
