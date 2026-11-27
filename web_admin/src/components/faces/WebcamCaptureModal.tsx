"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  RefreshCw,
  RotateCcw,
  Save,
  Upload,
  Video,
} from "lucide-react";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";

const POSE_GUIDES = [
  "Hadap Depan (Netral)",
  "Miring Ringan Kiri (~10°)",
  "Miring Ringan Kanan (~10°)",
  "Ekspresi Senyum Alami",
  "Variasi Pencahayaan",
];

interface WebcamCaptureModalProps {
  open: boolean;
  studentName: string;
  currentFaceCount: number;
  maxFaces?: number;
  isUploading: boolean;
  uploadError: string | null;
  uploadSuccess: string | null;
  onClearFeedback?: () => void;
  onClose: () => void;
  onCapture: (blob: Blob) => Promise<boolean>;
}

export function WebcamCaptureModal({
  open,
  studentName,
  currentFaceCount,
  maxFaces = 5,
  isUploading,
  uploadError,
  uploadSuccess,
  onClearFeedback,
  onClose,
  onCapture,
}: WebcamCaptureModalProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const [cameraState, setCameraState] = useState<
    "starting" | "ready" | "error"
  >("starting");
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>("");
  const [activeDeviceId, setActiveDeviceId] = useState<string>("");
  const [retryCounter, setRetryCounter] = useState(0);

  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  const [capturedPreviewUrl, setCapturedPreviewUrl] = useState<string | null>(
    null
  );

  const isFull = currentFaceCount >= maxFaces;
  const activeSlotNumber = Math.min(currentFaceCount + 1, maxFaces);
  const activePoseGuide =
    POSE_GUIDES[Math.min(currentFaceCount, POSE_GUIDES.length - 1)];

  const revokePreview = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setCapturedPreviewUrl(null);
    setCapturedBlob(null);
  }, []);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  useEffect(() => {
    if (!open || isFull) {
      stopStream();
      return;
    }

    let cancelled = false;

    async function initCamera() {
      stopStream();

      if (
        typeof navigator === "undefined" ||
        !navigator.mediaDevices ||
        !navigator.mediaDevices.getUserMedia
      ) {
        if (!cancelled) {
          setCameraState("error");
          setCameraError(
            "Browser Anda tidak mendukung akses webcam (getUserMedia). Gunakan tombol Upload File Foto sebagai alternatif."
          );
        }
        return;
      }

      if (!cancelled) {
        setCameraState("starting");
        setCameraError(null);
      }

      const videoConstraints: MediaTrackConstraints = selectedDeviceId
        ? {
            deviceId: { exact: selectedDeviceId },
            width: { ideal: 720 },
            height: { ideal: 540 },
          }
        : {
            facingMode: "user",
            width: { ideal: 720 },
            height: { ideal: 540 },
          };

      let mediaStream: MediaStream;
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: videoConstraints,
          audio: false,
        });
      } catch (err) {
        if (cancelled) return;
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
        return;
      }

      // Immediately release hardware tracks if modal closed or restarted while awaiting getUserMedia
      if (cancelled) {
        mediaStream.getTracks().forEach((track) => track.stop());
        return;
      }

      streamRef.current = mediaStream;

      const activeTrackDeviceId =
        mediaStream.getVideoTracks()[0]?.getSettings().deviceId ?? "";

      try {
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
          await videoRef.current.play();
        }
      } catch {
        // play() can be interrupted on rapid restart; handled by cancelled check below
      }

      if (cancelled) {
        mediaStream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === mediaStream) {
          streamRef.current = null;
        }
        return;
      }

      // Enumerate available video input devices once permission is granted
      if (navigator.mediaDevices.enumerateDevices) {
        try {
          const allDevices = await navigator.mediaDevices.enumerateDevices();
          if (!cancelled) {
            const cameras = allDevices.filter((d) => d.kind === "videoinput");
            setVideoDevices(cameras);
            if (activeTrackDeviceId) {
              setActiveDeviceId(activeTrackDeviceId);
            }
          }
        } catch {
          // Non-fatal: continue with active stream
        }
      }

      if (!cancelled) {
        setCameraError(null);
        setCameraState("ready");
      }
    }

    void initCamera();

    return () => {
      cancelled = true;
      stopStream();
    };
  }, [open, isFull, selectedDeviceId, retryCounter, stopStream]);

  // Clean up object URL on unmount
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
        previewUrlRef.current = null;
      }
    };
  }, []);

  async function handleTakeSnapshot() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    if (video.readyState < 2 || video.videoWidth === 0 || video.videoHeight === 0) {
      setCameraError(
        "Frame kamera belum siap. Tunggu sesaat hingga gambar terlihat jelas lalu coba lagi."
      );
      return;
    }

    onClearFeedback?.();
    setCameraError(null);

    // Match visible aspect-4/3 object-cover crop
    const targetAspect = 4 / 3;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    const videoAspect = vw / vh;

    let sx = 0;
    let sy = 0;
    let sw = vw;
    let sh = vh;

    if (videoAspect > targetAspect) {
      sw = Math.round(vh * targetAspect);
      sx = Math.round((vw - sw) / 2);
    } else if (videoAspect < targetAspect) {
      sh = Math.round(vw / targetAspect);
      sy = Math.round((vh - sh) / 2);
    }

    canvas.width = sw;
    canvas.height = sh;

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setCameraError("Browser gagal menyiapkan kanvas gambar.");
      return;
    }

    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/jpeg", 0.92);
    });

    if (!blob) {
      setCameraError("Gagal mengambil frame gambar dari kamera.");
      return;
    }

    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
    }
    const nextUrl = URL.createObjectURL(blob);
    previewUrlRef.current = nextUrl;
    setCapturedBlob(blob);
    setCapturedPreviewUrl(nextUrl);
  }

  function handleRetake() {
    revokePreview();
    onClearFeedback?.();
    setCameraError(null);
  }

  async function handleSaveCaptured() {
    if (!capturedBlob) return;
    const ok = await onCapture(capturedBlob);
    if (ok) {
      // Clear preview and keep modal open for next consecutive pose until 5/5 or "Selesai"
      revokePreview();
    }
  }

  function handleSafeClose() {
    if (isUploading) return;
    revokePreview();
    stopStream();
    onClose();
  }

  return (
    <Modal
      open={open}
      onClose={handleSafeClose}
      preventClose={isUploading}
      title="Foto Wajah Pakai Kamera"
      subtitle={`Siswa: ${studentName} • Posisikan tepat 1 wajah di dalam bingkai oval`}
      maxWidthClass="max-w-xl"
    >
      <div className="space-y-4">
        {/* Progress & Camera Selector Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3.5 py-2.5">
          <div className="flex items-center gap-2">
            <StatusBadge tone={isFull ? "success" : "primary"}>
              {isFull
                ? `Selesai ${maxFaces}/${maxFaces} Slot`
                : `Slot ${activeSlotNumber} / ${maxFaces}`}
            </StatusBadge>
            <span className="text-xs font-medium text-slate-600">
              {isFull ? "Semua slot penuh" : `Pose: ${activePoseGuide}`}
            </span>
          </div>

          {!isFull && videoDevices.length > 1 ? (
            <div className="flex items-center gap-1.5">
              <Video className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
              <select
                aria-label="Pilih perangkat kamera"
                value={selectedDeviceId || activeDeviceId}
                disabled={isUploading || Boolean(capturedPreviewUrl)}
                onChange={(e) => {
                  setSelectedDeviceId(e.target.value);
                  onClearFeedback?.();
                }}
                className="max-w-[190px] truncate rounded-lg border border-[#E2E8F0] bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 focus:border-[#1D4ED8] focus:outline-none disabled:opacity-50"
              >
                {videoDevices.map((device, index) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label || `Kamera #${index + 1}`}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>

        {/* Inline Upload Error & Success Banners (never hidden behind modal backdrop) */}
        {uploadError ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-[#FEF2F2] p-3.5 text-xs font-medium text-[#DC2626]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{uploadError}</span>
          </div>
        ) : null}

        {uploadSuccess ? (
          <div
            role="status"
            className="flex items-start gap-2.5 rounded-xl border border-emerald-200 bg-[#ECFDF5] p-3.5 text-xs font-medium text-[#059669]"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{uploadSuccess}</span>
          </div>
        ) : null}

        {cameraError && cameraState !== "error" ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-xl border border-amber-200 bg-[#FFFBEB] p-3 text-xs text-[#92400E]"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{cameraError}</span>
          </div>
        ) : null}

        {/* Main Viewport */}
        {isFull ? (
          <div className="rounded-2xl border border-emerald-200 bg-[#ECFDF5] p-8 text-center space-y-3">
            <CheckCircle2
              className="mx-auto h-12 w-12 text-[#10B981]"
              aria-hidden="true"
            />
            <p className="text-base font-bold text-[#065F46]">
              Foto Wajah Lengkap ({maxFaces}/{maxFaces} Foto)
            </p>
            <p className="text-xs text-emerald-800">
              Seluruh 5 sampel foto wajah untuk <strong>{studentName}</strong>{" "}
              telah tersimpan dan siap digunakan pada Kiosk Presensi.
            </p>
          </div>
        ) : cameraState === "error" && !capturedPreviewUrl ? (
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
              onClick={() => setRetryCounter((prev) => prev + 1)}
              className="inline-flex items-center gap-2 rounded-xl bg-[#1D4ED8] px-4 py-2 text-xs font-semibold text-white hover:bg-[#1E3A8A]"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Coba Buka Kamera Lagi</span>
            </button>
          </div>
        ) : (
          <div className="relative overflow-hidden rounded-2xl border border-[#E2E8F0] bg-[#0F172A] aspect-4/3">
            {/* Keep video mounted so clicking Ulangi resumes instantly without re-acquiring stream */}
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className={`h-full w-full -scale-x-100 object-cover ${
                capturedPreviewUrl ? "invisible" : "visible"
              }`}
            />

            {capturedPreviewUrl ? (
              <>
                <Image
                  src={capturedPreviewUrl}
                  alt="Pratinjau foto wajah yang diambil"
                  fill
                  unoptimized
                  className="object-cover"
                />
                <div className="pointer-events-none absolute top-3 left-3">
                  <span className="rounded-full bg-slate-950/80 px-3 py-1 text-xs font-semibold text-white backdrop-blur-xs">
                    Pratinjau Foto — Periksa kejernihan wajah
                  </span>
                </div>
              </>
            ) : (
              <>
                {/* Face Oval Framing Guide */}
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <div className="h-56 w-44 rounded-[999px] border-2 border-dashed border-emerald-400/90 shadow-[0_0_0_9999px_rgba(15,23,42,0.38)]" />
                </div>
                <div className="pointer-events-none absolute bottom-3 inset-x-0 flex justify-center">
                  <span className="rounded-full bg-slate-950/80 px-3.5 py-1 text-xs font-medium text-white backdrop-blur-xs">
                    {cameraState === "starting"
                      ? "Mengaktifkan kamera..."
                      : `Arahkan wajah ke oval • ${activePoseGuide}`}
                  </span>
                </div>
              </>
            )}
          </div>
        )}

        <canvas ref={canvasRef} className="hidden" />

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-2.5 pt-1">
          <button
            type="button"
            disabled={isUploading}
            onClick={handleSafeClose}
            className="rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Selesai
          </button>

          {!isFull ? (
            <div className="flex flex-wrap items-center gap-2.5">
              {capturedPreviewUrl ? (
                <>
                  <button
                    type="button"
                    disabled={isUploading}
                    onClick={handleRetake}
                    className="inline-flex items-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    <RotateCcw className="h-4 w-4" aria-hidden="true" />
                    <span>Ulangi</span>
                  </button>
                  <button
                    type="button"
                    disabled={isUploading}
                    onClick={() => void handleSaveCaptured()}
                    className="inline-flex items-center gap-2 rounded-xl bg-[#10B981] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isUploading ? (
                      <>
                        <RefreshCw
                          className="h-4 w-4 animate-spin"
                          aria-hidden="true"
                        />
                        <span>Memvalidasi & Menyimpan...</span>
                      </>
                    ) : (
                      <>
                        <Save className="h-4 w-4" aria-hidden="true" />
                        <span>Simpan Foto</span>
                      </>
                    )}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleTakeSnapshot()}
                  disabled={cameraState !== "ready" || isUploading}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#1D4ED8] px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-[#1E3A8A] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Camera className="h-4 w-4" aria-hidden="true" />
                  <span>Ambil Foto</span>
                </button>
              )}
            </div>
          ) : null}
        </div>

        <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <Upload className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>
            Foto divalidasi oleh InsightFace server (tepat 1 wajah, skor
            kualitas ≥ 0.50). Modal tetap terbuka agar Anda dapat mendaftarkan
            3–5 pose berturut-turut.
          </span>
        </p>
      </div>
    </Modal>
  );
}
