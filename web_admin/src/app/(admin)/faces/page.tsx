"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  Camera,
  CheckCircle2,
  Cpu,
  Edit3,
  ImagePlus,
  Info,
  MessageCircle,
  RefreshCw,
  ScanFace,
  Search,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { AdminPageHeader } from "@/components/AdminShell";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import { WebcamCaptureModal } from "@/components/faces/WebcamCaptureModal";
import { ParentFormModal } from "@/components/students/MasterDataModals";
import {
  ApiError,
  deleteStudentFace,
  getClasses,
  getStudentFaces,
  getStudents,
  resolveAssetUrl,
  uploadStudentFace,
  type FaceEmbedding,
  type SchoolClass,
  type Student,
} from "@/lib/api";
import {
  formatWaPhoneDisplay,
  formatWibDateTime,
  getInitials,
} from "@/lib/format";

const MAX_FACES = 5;
const MAX_FACE_FILE_BYTES = 10 * 1024 * 1024; // 10 MB

const SLOT_GUIDES = [
  "Hadap Depan (Netral)",
  "Miring Ringan Kiri (~10°)",
  "Miring Ringan Kanan (~10°)",
  "Ekspresi Senyum Alami",
  "Variasi Pencahayaan",
];

function FaceSlotSkeleton({ slotIndex }: { slotIndex: number }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-2xs">
      <div className="relative aspect-square w-full animate-pulse bg-slate-200">
        <span className="absolute left-2.5 top-2.5 rounded-lg bg-slate-300/90 px-2 py-0.5 text-[11px] font-bold text-slate-600">
          Slot #{slotIndex + 1}
        </span>
      </div>
      <div className="p-3 space-y-2.5">
        <div className="h-3.5 w-3/4 animate-pulse rounded bg-slate-200" />
        <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
        <div className="h-2.5 w-1/2 animate-pulse rounded bg-slate-100" />
      </div>
    </div>
  );
}

function FaceSlotCard({
  slotIndex,
  face,
  deletingFaceId,
  disabledUpload,
  onRequestDelete,
  onTriggerUpload,
  onTriggerWebcam,
}: {
  slotIndex: number;
  face: FaceEmbedding | undefined;
  deletingFaceId: string | null;
  disabledUpload: boolean;
  onRequestDelete: (faceId: string, slotNumber: number) => void;
  onTriggerUpload: () => void;
  onTriggerWebcam: () => void;
}) {
  const imageUrl = face ? resolveAssetUrl(face.image_url) : null;
  // Automatically resets error state whenever imageUrl changes without triggering setState-in-effect
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);
  const imgError = Boolean(imageUrl && failedImageUrl === imageUrl);

  if (!face) {
    return (
      <div className="flex flex-col justify-between rounded-2xl border-2 border-dashed border-[#E2E8F0] bg-[#F8FAFC] p-4 transition-colors hover:border-[#1D4ED8]/50">
        <div className="flex items-center justify-between">
          <span className="rounded-lg bg-white px-2 py-0.5 text-[11px] font-bold text-slate-600 ring-1 ring-[#E2E8F0]">
            Slot #{slotIndex + 1}
          </span>
          <span className="text-[11px] font-medium text-slate-400">Kosong</span>
        </div>

        <div className="my-5 flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-slate-400 ring-1 ring-[#E2E8F0]">
            <ImagePlus className="h-5 w-5" aria-hidden="true" />
          </div>
          <p className="mt-2.5 text-xs font-semibold text-[#0F172A]">
            {SLOT_GUIDES[slotIndex]}
          </p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            1 wajah jelas, maks 10 MB
          </p>
        </div>

        <div className="grid grid-cols-2 gap-1.5">
          <button
            type="button"
            disabled={disabledUpload}
            onClick={onTriggerWebcam}
            className="inline-flex items-center justify-center gap-1 rounded-xl bg-white px-2.5 py-2 text-[11px] font-semibold text-[#1D4ED8] ring-1 ring-blue-200 transition-colors hover:bg-[#EFF6FF] disabled:opacity-50"
          >
            <Camera className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Kamera</span>
          </button>
          <button
            type="button"
            disabled={disabledUpload}
            onClick={onTriggerUpload}
            className="inline-flex items-center justify-center gap-1 rounded-xl bg-white px-2.5 py-2 text-[11px] font-semibold text-slate-700 ring-1 ring-[#E2E8F0] transition-colors hover:bg-slate-100 disabled:opacity-50"
          >
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Upload</span>
          </button>
        </div>
      </div>
    );
  }

  const qualityPct = Math.min(
    100,
    Math.max(0, Math.round(face.quality_score * 100))
  );
  const qualityHigh = face.quality_score >= 0.75;

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[#E2E8F0] bg-white shadow-2xs">
      <div className="relative aspect-square w-full bg-[#0F172A]">
        {imageUrl && !imgError ? (
          <Image
            src={imageUrl}
            alt={`Sampel wajah #${slotIndex + 1}`}
            fill
            unoptimized
            onError={() => setFailedImageUrl(imageUrl)}
            className="object-cover"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center p-3 text-center text-slate-300">
            <ScanFace className="h-8 w-8 text-[#10B981]" aria-hidden="true" />
            <p className="mt-2 text-[11px] font-semibold text-white">
              Vektor {face.embedding_dim}-d Aktif
            </p>
            <p className="mt-0.5 text-[10px] text-slate-400">
              Sampel tersimpan di database
            </p>
          </div>
        )}

        <div className="absolute left-2.5 top-2.5 flex items-center gap-1.5">
          <span className="rounded-lg bg-slate-950/75 px-2 py-0.5 text-[11px] font-bold text-white backdrop-blur-xs">
            Slot #{slotIndex + 1}
          </span>
        </div>

        <button
          type="button"
          onClick={() => onRequestDelete(face.id, slotIndex + 1)}
          disabled={deletingFaceId === face.id}
          aria-label={`Hapus sampel wajah slot ${slotIndex + 1}`}
          className="absolute right-2.5 top-2.5 inline-flex h-7 w-7 items-center justify-center rounded-lg bg-red-600/90 text-white shadow-sm transition-colors hover:bg-red-700 disabled:opacity-60"
        >
          {deletingFaceId === face.id ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Trash2 className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      <div className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-1.5 text-xs">
          <span className="whitespace-nowrap font-semibold text-slate-600">
            Kualitas Foto
          </span>
          <span
            className={`whitespace-nowrap font-mono font-bold ${
              qualityHigh ? "text-[#059669]" : "text-[#D97706]"
            }`}
          >
            {face.quality_score.toFixed(2)}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full ${
              qualityHigh ? "bg-[#10B981]" : "bg-[#F59E0B]"
            }`}
            style={{ width: `${qualityPct}%` }}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-[10px] text-slate-400">
          <span className="whitespace-nowrap font-medium text-emerald-600">
            Siap pakai
          </span>
          <span className="whitespace-nowrap">
            {formatWibDateTime(face.created_at).replace(" WIB", "")}
          </span>
        </div>
      </div>
    </div>
  );
}

function FaceDatasetContent() {
  const searchParams = useSearchParams();
  const initialStudentIdParam = searchParams.get("studentId");

  const [students, setStudents] = useState<Student[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [selectedStudentId, setSelectedStudentId] = useState<string>("");
  const [faces, setFaces] = useState<FaceEmbedding[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [classFilter, setClassFilter] = useState("");

  const [loadingMaster, setLoadingMaster] = useState(true);
  const [loadingFaces, setLoadingFaces] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingFaceId, setDeletingFaceId] = useState<string | null>(null);
  const [webcamOpen, setWebcamOpen] = useState(false);
  const [webcamError, setWebcamError] = useState<string | null>(null);
  const [webcamSuccess, setWebcamSuccess] = useState<string | null>(null);

  // Face delete confirmation modal
  const [pendingDeleteFace, setPendingDeleteFace] = useState<{
    id: string;
    slotNumber: number;
  } | null>(null);
  const [deleteFaceError, setDeleteFaceError] = useState<string | null>(null);

  // Inline parent WA contact edit modal
  const [editingParentOpen, setEditingParentOpen] = useState(false);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fetchMasterLists = useCallback(async () => {
    const [studentsRes, classesRes] = await Promise.all([
      getStudents(),
      getClasses(),
    ]);
    return { studentsRes, classesRes };
  }, []);

  const loadMasterData = useCallback(async () => {
    setLoadingMaster(true);
    setErrorMsg(null);
    try {
      const { studentsRes, classesRes } = await fetchMasterLists();
      setStudents(studentsRes);
      setClasses(classesRes);

      setSelectedStudentId((prev) => {
        if (prev && studentsRes.some((s) => s.id === prev)) return prev;
        if (
          initialStudentIdParam &&
          studentsRes.some((s) => s.id === initialStudentIdParam)
        ) {
          return initialStudentIdParam;
        }
        return studentsRes[0]?.id ?? "";
      });
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError ? err.message : "Gagal memuat daftar siswa."
      );
    } finally {
      setLoadingMaster(false);
    }
  }, [fetchMasterLists, initialStudentIdParam]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const { studentsRes, classesRes } = await fetchMasterLists();
        if (cancelled) return;
        setStudents(studentsRes);
        setClasses(classesRes);

        let nextId = "";
        if (
          initialStudentIdParam &&
          studentsRes.some((s) => s.id === initialStudentIdParam)
        ) {
          nextId = initialStudentIdParam;
        } else {
          nextId = studentsRes[0]?.id ?? "";
        }

        if (nextId) {
          setLoadingFaces(true);
        }
        setSelectedStudentId((prev) =>
          prev && studentsRes.some((s) => s.id === prev) ? prev : nextId
        );
        setErrorMsg(null);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError ? err.message : "Gagal memuat daftar siswa."
        );
      } finally {
        if (!cancelled) setLoadingMaster(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [fetchMasterLists, initialStudentIdParam]);

  const loadSelectedFaces = useCallback(async (studentId: string) => {
    if (!studentId) {
      setFaces([]);
      return;
    }
    setLoadingFaces(true);
    try {
      const list = await getStudentFaces(studentId);
      setFaces(list);
      setStudents((prev) =>
        prev.map((s) =>
          s.id === studentId ? { ...s, face_count: list.length } : s
        )
      );
    } catch (err) {
      setErrorMsg(
        err instanceof ApiError
          ? err.message
          : "Gagal memuat dataset wajah siswa."
      );
    } finally {
      setLoadingFaces(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedStudentId) return;
    let cancelled = false;
    async function syncFaces() {
      try {
        const list = await getStudentFaces(selectedStudentId);
        if (cancelled) return;
        setFaces(list);
        setStudents((prev) =>
          prev.map((s) =>
            s.id === selectedStudentId ? { ...s, face_count: list.length } : s
          )
        );
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat dataset wajah siswa."
        );
      } finally {
        if (!cancelled) setLoadingFaces(false);
      }
    }
    void syncFaces();
    return () => {
      cancelled = true;
    };
  }, [selectedStudentId]);

  const filteredStudents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return students.filter((s) => {
      if (classFilter && s.class_id !== classFilter) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        s.nis.toLowerCase().includes(q) ||
        s.class_name.toLowerCase().includes(q)
      );
    });
  }, [students, classFilter, searchQuery]);

  const selectedStudent = useMemo(
    () => students.find((s) => s.id === selectedStudentId) ?? null,
    [students, selectedStudentId]
  );

  const selectedParentSharedCount = useMemo(() => {
    if (!selectedStudent) return 0;
    return students.filter((s) => s.parent_id === selectedStudent.parent_id)
      .length;
  }, [students, selectedStudent]);

  async function processFaceUpload(
    blob: Blob,
    filename: string,
    fromWebcam = false
  ): Promise<boolean> {
    if (!selectedStudent) return false;
    setUploading(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    if (fromWebcam) {
      setWebcamError(null);
      setWebcamSuccess(null);
    }

    try {
      const created = await uploadStudentFace(
        selectedStudent.id,
        blob,
        filename
      );
      const okMsg = `Sampel wajah berhasil diekstrak (${created.embedding_dim}-d, skor kualitas ${created.quality_score.toFixed(2)}).`;
      setSuccessMsg(okMsg);
      if (fromWebcam) {
        setWebcamSuccess(okMsg);
      }
      await loadSelectedFaces(selectedStudent.id);
      return true;
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Gagal mengunggah foto wajah.";
      if (fromWebcam) {
        setWebcamError(message);
      } else {
        setErrorMsg(message);
      }
      return false;
    } finally {
      setUploading(false);
    }
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    if (file.size > MAX_FACE_FILE_BYTES) {
      setSuccessMsg(null);
      setErrorMsg(
        `Ukuran file "${file.name}" (${(file.size / (1024 * 1024)).toFixed(1)} MB) melebihi batas maksimal 10 MB.`
      );
      return;
    }

    await processFaceUpload(file, file.name, false);
  }

  async function handleConfirmDeleteFace() {
    if (!selectedStudent || !pendingDeleteFace) return;
    const faceId = pendingDeleteFace.id;
    setDeletingFaceId(faceId);
    setDeleteFaceError(null);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await deleteStudentFace(selectedStudent.id, faceId);
      setSuccessMsg(
        `Sampel foto wajah Slot #${pendingDeleteFace.slotNumber} berhasil dihapus.`
      );
      setPendingDeleteFace(null);
      await loadSelectedFaces(selectedStudent.id);
    } catch (err) {
      setDeleteFaceError(
        err instanceof ApiError
          ? err.message
          : "Gagal menghapus sampel foto wajah."
      );
    } finally {
      setDeletingFaceId(null);
    }
  }

  const maxReached = faces.length >= MAX_FACES;

  const headerActions = useMemo(
    () => (
      <button
        type="button"
        disabled={loadingMaster || loadingFaces}
        onClick={() => {
          void loadMasterData();
          if (selectedStudentId) void loadSelectedFaces(selectedStudentId);
        }}
        className="inline-flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
      >
        <RefreshCw
          className={`h-3.5 w-3.5 ${
            loadingMaster || loadingFaces ? "animate-spin" : ""
          }`}
          aria-hidden="true"
        />
        <span>Muat Ulang</span>
      </button>
    ),
    [
      loadMasterData,
      loadSelectedFaces,
      selectedStudentId,
      loadingMaster,
      loadingFaces,
    ]
  );

  return (
    <>
      <AdminPageHeader
        title="Foto Wajah Siswa"
        subtitle="Simpan 3–5 foto wajah per siswa agar kamera absensi mudah mengenali."
        headerActions={headerActions}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Panel: Student List + Class Filter */}
        <section className="lg:col-span-4 rounded-2xl border border-[#E2E8F0] bg-white shadow-2xs flex flex-col max-h-[calc(100vh-11rem)]">
          <div className="border-b border-[#E2E8F0] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-[#0F172A]">
                Daftar Siswa ({filteredStudents.length})
              </h2>
              <Link
                href="/students"
                className="text-xs font-semibold text-[#1D4ED8] hover:underline"
              >
                + Kelola Siswa
              </Link>
            </div>

            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                aria-hidden="true"
              />
              <input
                type="search"
                aria-label="Cari siswa untuk dataset wajah"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Cari nama atau NIS..."
                className="w-full rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] py-2 pl-9 pr-3 text-sm focus:border-[#1D4ED8] focus:bg-white focus:outline-none"
              />
            </div>

            <select
              aria-label="Filter berdasarkan kelas"
              value={classFilter}
              onChange={(e) => setClassFilter(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-slate-700 focus:border-[#1D4ED8] focus:outline-none"
            >
              <option value="">Semua Kelas ({classes.length})</option>
              {classes.map((cls) => (
                <option key={cls.id} value={cls.id}>
                  {cls.name} ({cls.student_count} siswa)
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-[#E2E8F0] p-2 space-y-1">
            {loadingMaster ? (
              <div className="p-6 text-center text-xs text-slate-500">
                Memuat daftar siswa...
              </div>
            ) : filteredStudents.length === 0 ? (
              <div className="p-6 text-center text-xs text-slate-500">
                Tidak ada siswa yang sesuai filter.
              </div>
            ) : (
              filteredStudents.map((student) => {
                const selected = student.id === selectedStudentId;
                const badgeTone =
                  student.face_count >= 3
                    ? "success"
                    : student.face_count > 0
                      ? "warning"
                      : "danger";
                const badgeText =
                  student.face_count >= 3
                    ? `${student.face_count}/5 Foto ✓`
                    : student.face_count > 0
                      ? `${student.face_count}/5 Foto`
                      : "0/5 Belum";

                return (
                  <button
                    key={student.id}
                    type="button"
                    onClick={() => {
                      if (student.id !== selectedStudentId) {
                        setFaces([]);
                        setLoadingFaces(true);
                        setSelectedStudentId(student.id);
                      }
                      setErrorMsg(null);
                      setSuccessMsg(null);
                    }}
                    className={`w-full rounded-xl border p-3 text-left transition-all ${
                      selected
                        ? "border-[#1D4ED8] bg-[#EFF6FF] shadow-2xs"
                        : "border-transparent hover:bg-[#F8FAFC]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <div
                          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                            selected
                              ? "bg-[#1D4ED8] text-white"
                              : "bg-slate-100 text-slate-700"
                          }`}
                        >
                          {getInitials(student.name)}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-bold text-[#0F172A]">
                            {student.name}
                          </p>
                          <p className="truncate text-[11px] text-slate-500">
                            {student.nis} • {student.class_name}
                          </p>
                        </div>
                      </div>
                      <StatusBadge tone={badgeTone} className="shrink-0">
                        {badgeText}
                      </StatusBadge>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        {/* Right Panel: Face Dataset Registration (Screen 10) */}
        <section className="lg:col-span-8 space-y-5">
          {!selectedStudent ? (
            <div className="rounded-2xl border border-[#E2E8F0] bg-white p-12 text-center">
              <ScanFace
                className="mx-auto h-12 w-12 text-slate-300"
                aria-hidden="true"
              />
              <h2 className="mt-3 text-base font-bold text-[#0F172A]">
                Pilih Siswa Terlebih Dahulu
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Pilih salah satu siswa di panel kiri untuk mengelola 5 slot foto
                dataset wajah.
              </p>
            </div>
          ) : (
            <>
              {/* Main Registration Card */}
              <div className="rounded-2xl border border-[#E2E8F0] bg-white p-6 shadow-2xs space-y-5">
                {/* Student Header & Action Buttons */}
                <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E2E8F0] pb-5">
                  <div className="flex items-center gap-4">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-[#1D4ED8] text-lg font-extrabold text-white shadow-sm">
                      {getInitials(selectedStudent.name)}
                    </div>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-lg font-bold text-[#0F172A]">
                          Foto Wajah — {selectedStudent.name}
                        </h2>
                        {!loadingFaces ? (
                          <StatusBadge
                            tone={
                              faces.length >= 3
                                ? "success"
                                : faces.length > 0
                                  ? "warning"
                                  : "danger"
                            }
                          >
                            {faces.length >= 3
                              ? `${faces.length}/5 Foto ✓ Siap Kiosk`
                              : faces.length > 0
                                ? `${faces.length}/5 Foto (Disarankan ≥3)`
                                : "0/5 Belum Terdaftar"}
                          </StatusBadge>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        NIS:{" "}
                        <span className="font-mono font-semibold text-slate-700">
                          {selectedStudent.nis}
                        </span>{" "}
                        • Kelas:{" "}
                        <strong className="text-slate-700">
                          {selectedStudent.class_name}
                        </strong>{" "}
                        • Status:{" "}
                        <strong className="text-slate-700">
                          {selectedStudent.is_active ? "Aktif" : "Nonaktif"}
                        </strong>
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2.5">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      onChange={(e) => void handleFileChange(e)}
                      className="hidden"
                    />
                    <button
                      type="button"
                      disabled={maxReached || uploading || loadingFaces}
                      onClick={() => {
                        setWebcamError(null);
                        setWebcamSuccess(null);
                        setWebcamOpen(true);
                      }}
                      className="inline-flex items-center gap-2 rounded-xl bg-[#1D4ED8] px-4 py-2.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-[#1E3A8A] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Camera className="h-4 w-4" aria-hidden="true" />
                      <span>Foto Pakai Kamera</span>
                    </button>
                    <button
                      type="button"
                      disabled={maxReached || uploading || loadingFaces}
                      onClick={() => fileInputRef.current?.click()}
                      className="inline-flex items-center gap-2 rounded-xl border border-[#E2E8F0] bg-white px-4 py-2.5 text-xs font-semibold text-[#0F172A] transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Upload
                        className="h-4 w-4 text-[#1D4ED8]"
                        aria-hidden="true"
                      />
                      <span>
                        {uploading ? "Mengunggah..." : "Pilih File Foto"}
                      </span>
                    </button>
                  </div>
                </div>

                {/* Inline Full Quota Note */}
                {!loadingFaces && maxReached ? (
                  <div
                    role="status"
                    className="flex items-center gap-2.5 rounded-xl border border-blue-200 bg-[#EFF6FF] p-3.5 text-xs font-medium text-[#1D4ED8]"
                  >
                    <Info className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>
                      Kuota maksimal <strong>5/5 sampel foto</strong> telah
                      terpenuhi. Hapus salah satu sampel terlebih dahulu apabila
                      ingin mengganti dengan foto baru.
                    </span>
                  </div>
                ) : null}

                {/* Inline Feedback Messages */}
                {successMsg ? (
                  <div
                    role="status"
                    className="flex items-center gap-2.5 rounded-xl border border-emerald-200 bg-[#ECFDF5] p-3.5 text-xs font-medium text-[#059669]"
                  >
                    <CheckCircle2
                      className="h-4 w-4 shrink-0"
                      aria-hidden="true"
                    />
                    <span>{successMsg}</span>
                  </div>
                ) : null}

                {errorMsg ? (
                  <div
                    role="alert"
                    className="flex items-center gap-2.5 rounded-xl border border-red-200 bg-[#FEF2F2] p-3.5 text-xs font-medium text-[#DC2626]"
                  >
                    <AlertCircle
                      className="h-4 w-4 shrink-0"
                      aria-hidden="true"
                    />
                    <span>{errorMsg}</span>
                  </div>
                ) : null}

                {/* 5-Slot Photo Grid */}
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase tracking-wide text-slate-500">
                      Foto Wajah Siswa (Maksimal 5 Foto)
                    </p>
                    {loadingFaces ? (
                      <span className="text-xs text-slate-400">
                        Memuat slot wajah...
                      </span>
                    ) : null}
                  </div>

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
                    {loadingFaces
                      ? Array.from({ length: MAX_FACES }).map((_, index) => (
                          <FaceSlotSkeleton key={index} slotIndex={index} />
                        ))
                      : Array.from({ length: MAX_FACES }).map((_, index) => (
                          <FaceSlotCard
                            key={
                              faces[index]?.id ??
                              `empty-${selectedStudent.id}-${index}`
                            }
                            slotIndex={index}
                            face={faces[index]}
                            deletingFaceId={deletingFaceId}
                            disabledUpload={maxReached || uploading}
                            onRequestDelete={(faceId, slotNumber) => {
                              setDeleteFaceError(null);
                              setPendingDeleteFace({ id: faceId, slotNumber });
                            }}
                            onTriggerUpload={() => fileInputRef.current?.click()}
                            onTriggerWebcam={() => {
                              setWebcamError(null);
                              setWebcamSuccess(null);
                              setWebcamOpen(true);
                            }}
                          />
                        ))}
                  </div>
                </div>

                {/* InsightFace 512-d Biometric Status Banner */}
                <div className="rounded-2xl border border-blue-200 bg-[#EFF6FF] p-4 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#1D4ED8] text-white">
                      <Cpu className="h-5 w-5" aria-hidden="true" />
                    </div>
                    <div>
                      <p className="flex items-center gap-1.5 text-sm font-bold text-[#0F172A]">
                        <span>Panduan Foto Wajah</span>
                        <Sparkles
                          className="h-3.5 w-3.5 text-[#1D4ED8]"
                          aria-hidden="true"
                        />
                      </p>
                      <p className="mt-0.5 text-xs text-slate-600">
                        Pastikan setiap foto menampilkan{" "}
                        <strong>tepat 1 wajah yang jelas</strong> dengan
                        pencahayaan cukup agar kamera absensi dapat mengenali
                        siswa dengan akurat.
                      </p>
                    </div>
                  </div>
                  <StatusBadge tone="primary">
                    {loadingFaces
                      ? "Memuat..."
                      : `${faces.length}/5 Foto Siap Pakai`}
                  </StatusBadge>
                </div>
              </div>

              {/* Parent WhatsApp Contact Card */}
              <div className="rounded-2xl border border-[#E2E8F0] bg-white p-5 shadow-2xs flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#ECFDF5] text-[#10B981]">
                    <MessageCircle className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Kontak WhatsApp Orang Tua
                    </p>
                    <p className="mt-0.5 text-sm font-bold text-[#0F172A]">
                      {selectedStudent.parent_name}{" "}
                      <span className="font-mono text-xs font-semibold text-[#059669]">
                        ({formatWaPhoneDisplay(selectedStudent.parent_phone_wa)})
                      </span>
                    </p>
                    <p className="text-xs text-slate-500">
                      Digunakan untuk pengiriman notifikasi kehadiran real-time
                      & akses AI Chatbot Wali Murid.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2.5">
                  <StatusBadge tone="success">Nomor WA Terdaftar</StatusBadge>
                  <button
                    type="button"
                    onClick={() => setEditingParentOpen(true)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 hover:text-[#1D4ED8]"
                  >
                    <Edit3 className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>Ubah Kontak WA</span>
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {/* Webcam Capture Modal (stays open after saving for consecutive 3-5 poses) */}
      {webcamOpen && selectedStudent ? (
        <WebcamCaptureModal
          open={webcamOpen}
          studentName={selectedStudent.name}
          currentFaceCount={faces.length}
          maxFaces={MAX_FACES}
          isUploading={uploading}
          uploadError={webcamError}
          uploadSuccess={webcamSuccess}
          onClearFeedback={() => {
            setWebcamError(null);
            setWebcamSuccess(null);
          }}
          onClose={() => {
            setWebcamOpen(false);
            setWebcamError(null);
            setWebcamSuccess(null);
          }}
          onCapture={(blob) =>
            processFaceUpload(blob, `webcam-${selectedStudent.nis}.jpg`, true)
          }
        />
      ) : null}

      {/* Delete Face Confirmation Modal */}
      <Modal
        open={Boolean(pendingDeleteFace)}
        onClose={() => {
          setPendingDeleteFace(null);
          setDeleteFaceError(null);
        }}
        preventClose={deletingFaceId !== null}
        title="Konfirmasi Hapus Sampel Wajah"
        subtitle="Vektor embedding 512-d dan file foto untuk slot ini akan dihapus permanen."
        maxWidthClass="max-w-md"
      >
        <div className="space-y-4">
          {deleteFaceError ? (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]"
            >
              <AlertCircle
                className="mt-0.5 h-4 w-4 shrink-0"
                aria-hidden="true"
              />
              <span>{deleteFaceError}</span>
            </div>
          ) : null}

          <p className="text-sm text-slate-600">
            Apakah Anda yakin ingin menghapus{" "}
            <strong className="text-[#0F172A]">
              Sampel Wajah Slot #{pendingDeleteFace?.slotNumber}
            </strong>{" "}
            milik{" "}
            <strong className="text-[#0F172A]">{selectedStudent?.name}</strong>?
          </p>

          <div className="flex justify-end gap-2.5 pt-1">
            <button
              type="button"
              disabled={deletingFaceId !== null}
              onClick={() => {
                setPendingDeleteFace(null);
                setDeleteFaceError(null);
              }}
              className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Batal
            </button>
            <button
              type="button"
              disabled={deletingFaceId !== null}
              onClick={() => void handleConfirmDeleteFace()}
              className="rounded-xl bg-[#EF4444] px-4 py-2 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-60"
            >
              {deletingFaceId !== null ? "Menghapus..." : "Ya, Hapus Foto"}
            </button>
          </div>
        </div>
      </Modal>

      {/* Inline Edit Parent WA Contact Modal */}
      {editingParentOpen && selectedStudent ? (
        <ParentFormModal
          key={`${selectedStudent.parent_id}-${selectedStudent.parent_phone_wa}`}
          open={editingParentOpen}
          editing={{
            id: selectedStudent.parent_id,
            name: selectedStudent.parent_name,
            phone_wa: selectedStudent.parent_phone_wa,
            created_at: selectedStudent.created_at,
          }}
          sharedStudentsCount={selectedParentSharedCount}
          onClose={() => setEditingParentOpen(false)}
          onSaved={(message) => {
            setSuccessMsg(message);
            void loadMasterData();
          }}
        />
      ) : null}
    </>
  );
}

export default function FacesPage() {
  return (
    <Suspense
      fallback={
        <div className="py-16 text-center text-sm text-slate-500">
          Memuat halaman Dataset Wajah Siswa...
        </div>
      }
    >
      <FaceDatasetContent />
    </Suspense>
  );
}
