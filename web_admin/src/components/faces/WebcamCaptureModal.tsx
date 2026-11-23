"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Camera, RefreshCw, Upload } from "lucide-react";
import { Modal } from "@/components/Modal";

interface WebcamCaptureModalProps {
  open: boolean;
  studentName: string;
  isUploading: boolean;
  onClose: () => void;
  onCapture: (blob: Blob) => Promise<void>;
}

export function WebcamCaptureModal({
  open,
  studentName,
  isUploading,
  onClose,
  onCapture,
}: WebcamCaptureModalProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [cameraState, setCameraState] = useState<
    "starting" | "ready" | "error"
  >("starting");
  const [cameraError, setCameraError] = useState<string | null>(null);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const startCamera = useCallback(async () => {
    stopStream();

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia
    ) {
      setCameraState("error");
      setCameraError(
        "Browser Anda tidak mendukung akses webcam (getUserMedia). Gunakan tombol Upload File Foto sebagai alternatif."
      );
      return;
    }

    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 720 },
          height: { ideal: 540 },
        },
        audio: false,
      });
      streamRef.current = mediaStream;
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
        await videoRef.current.play();
      }
      setCameraError(null);
      setCameraState("ready");
    } catch (err) {
      setCameraState("error");
      const errorName = err instanceof Error ? err.name : "";
      if (errorName === "NotAllowedError") {
        setCameraError(
          "Izin kamera ditolak oleh browser. Izinkan akses kamera di bilah alamat lalu klik Coba Lagi."
        );
      } else if (errorName === "NotFoundError") {
        setCameraError(
          "Perangkat webcam tidak ditemukan. Hubungkan kamera atau gunakan Upload File Foto."
        );
      } else {
        setCameraError(
          "Gagal membuka kamera webcam. Pastikan kamera tidak sedang digunakan aplikasi lain."
        );
      }
    }
  }, [stopStream]);

  useEffect(() => {
    if (!open) {
      stopStream();
      return;
    }
    let cancelled = false;
    async function init() {
      if (!cancelled) {
        await startCamera();
      }
    }
    void init();

    return () => {
      cancelled = true;
      stopStream();
    };
  }, [open, startCamera, stopStream]);

  async function handleCaptureClick() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const width = video.videoWidth || 640;
    const height = video.videoHeight || 480;
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/jpeg", 0.92);
    });

    if (!blob) {
      setCameraError("Gagal mengambil frame gambar dari kamera.");
      return;
    }

    await onCapture(blob);
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        stopStream();
        onClose();
      }}
      title="Ambil Foto Wajah via Webcam"
      subtitle={`Siswa: ${studentName} • Posisikan tepat 1 wajah di dalam bingkai oval`}
      maxWidthClass="max-w-xl"
    >
      <div className="space-y-4">
        {cameraState === "error" ? (
          <div className="rounded-2xl border border-red-200 bg-[#FEF2F2] p-6 text-center space-y-3">
            <AlertCircle
              className="mx-auto h-10 w-10 text-[#EF4444]"
              aria-hidden="true"
            />
            <p className="text-sm font-semibold text-[#DC2626]">
              Kamera Tidak Dapat Diakses
            </p>
            <p className="text-xs text-slate-600">{cameraError}</p>
            <button
              type="button"
              onClick={() => {
                setCameraState("starting");
                void startCamera();
              }}
              className="inline-flex items-center gap-2 rounded-xl bg-[#1D4ED8] px-4 py-2 text-xs font-semibold text-white hover:bg-[#1E3A8A]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Coba Buka Kamera Lagi</span>
            </button>
          </div>
        ) : (
          <div className="relative overflow-hidden rounded-2xl border border-[#E2E8F0] bg-[#0F172A] aspect-4/3">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="h-full w-full -scale-x-100 object-cover"
            />
            {/* Face Oval Framing Guide */}
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <div className="h-56 w-44 rounded-[999px] border-2 border-dashed border-emerald-400/90 shadow-[0_0_0_9999px_rgba(15,23,42,0.38)]" />
            </div>
            <div className="pointer-events-none absolute bottom-3 inset-x-0 flex justify-center">
              <span className="rounded-full bg-slate-950/80 px-3.5 py-1 text-xs font-medium text-white backdrop-blur-xs">
                {cameraState === "starting"
                  ? "Mengaktifkan kamera..."
                  : "Arahkan wajah ke dalam oval & pastikan pencahayaan cukup"}
              </span>
            </div>
          </div>
        )}

        <canvas ref={canvasRef} className="hidden" />

        <div className="flex flex-wrap items-center justify-end gap-2.5 pt-1">
          <button
            type="button"
            onClick={() => {
              stopStream();
              onClose();
            }}
            className="rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Tutup
          </button>
          <button
            type="button"
            onClick={() => void handleCaptureClick()}
            disabled={cameraState !== "ready" || isUploading}
            className="inline-flex items-center gap-2 rounded-xl bg-[#1D4ED8] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isUploading ? (
              <>
                <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span>Mengunggah & Ekstrak Embedding...</span>
              </>
            ) : (
              <>
                <Camera className="h-4 w-4" aria-hidden="true" />
                <span>Tangkap & Simpan Foto</span>
              </>
            )}
          </button>
        </div>

        <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <Upload className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Foto akan langsung divalidasi oleh InsightFace server (tepat 1
            wajah, skor kualitas ≥ 0.50).
          </span>
        </p>
      </div>
    </Modal>
  );
}
