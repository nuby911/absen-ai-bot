"use client";

import { Bot, Clock, MessageSquare, Wrench } from "lucide-react";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import type { ChatbotLogItem } from "@/lib/api";
import { formatWaPhoneDisplay, formatWibDateTime } from "@/lib/format";

interface ChatbotLogDetailModalProps {
  log: ChatbotLogItem | null;
  onClose: () => void;
}

export function ChatbotLogDetailModal({
  log,
  onClose,
}: ChatbotLogDetailModalProps) {
  if (!log) return null;

  return (
    <Modal
      open={Boolean(log)}
      onClose={onClose}
      maxWidthClass="max-w-3xl"
      title="Detail Percakapan Bot WhatsApp"
      subtitle={`Pengirim: ${formatWaPhoneDisplay(log.phone_wa)} • ${formatWibDateTime(log.created_at)}`}
    >
      <div className="space-y-5">
        {/* Metadata Strip */}
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] p-3.5 text-xs">
          <StatusBadge tone={log.is_in_domain ? "success" : "danger"}>
            {log.is_in_domain ? "Topik Sekolah" : "Di Luar Topik"}
          </StatusBadge>
          {log.is_fallback ? (
            <StatusBadge tone="warning">Balasan Cadangan</StatusBadge>
          ) : null}

          <span className="inline-flex items-center gap-1 rounded-full border border-[#E2E8F0] bg-white px-2.5 py-0.5 text-xs font-semibold text-slate-700">
            <span>Tujuan:</span>
            <strong className="font-mono text-[#0F172A]">
              {log.detected_intent || "-"}
            </strong>
          </span>

          <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-[#EFF6FF] px-2.5 py-0.5 text-xs font-semibold text-[#1D4ED8]">
            <Wrench className="h-3 w-3" aria-hidden="true" />
            <span className="font-mono">
              {log.tool_called ? `${log.tool_called}()` : "Tanpa aksi sistem"}
            </span>
          </span>

          <span className="ml-auto inline-flex items-center gap-1 font-mono text-xs font-semibold text-slate-600">
            <Clock className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
            <span>{log.latency_ms} ms</span>
          </span>
        </div>

        {/* Side-by-Side User Message vs Bot Response */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="flex flex-col rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-4 space-y-2.5">
            <div className="flex items-center gap-2 text-xs font-bold text-[#0F172A]">
              <MessageSquare
                className="h-4 w-4 text-[#1D4ED8]"
                aria-hidden="true"
              />
              <span>Pesan Orang Tua</span>
            </div>
            <div className="flex-1 rounded-xl border border-[#E2E8F0] bg-white p-3.5 text-sm leading-relaxed text-[#0F172A] whitespace-pre-wrap break-words">
              {log.user_message || "-"}
            </div>
          </div>

          <div className="flex flex-col rounded-2xl border border-emerald-200 bg-[#ECFDF5]/60 p-4 space-y-2.5">
            <div className="flex items-center gap-2 text-xs font-bold text-[#065F46]">
              <Bot className="h-4 w-4 text-[#10B981]" aria-hidden="true" />
              <span>Balasan AI Chatbot</span>
            </div>
            <div className="flex-1 rounded-xl border border-emerald-200/80 bg-white p-3.5 text-sm leading-relaxed text-[#0F172A] whitespace-pre-wrap break-words">
              {log.bot_response ? (
                log.bot_response
              ) : (
                <span className="italic text-slate-400">
                  Tidak ada catatan teks balasan bot untuk log ini.
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A]"
          >
            Tutup
          </button>
        </div>
      </div>
    </Modal>
  );
}
