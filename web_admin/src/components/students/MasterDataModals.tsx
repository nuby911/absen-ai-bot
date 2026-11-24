"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  Info,
  Search,
  UserPlus,
  Users,
} from "lucide-react";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ApiError,
  createClass,
  createParent,
  createSchedule,
  createStudent,
  createTeacher,
  updateClass,
  updateParent,
  updateSchedule,
  updateStudent,
  updateTeacher,
  type Parent,
  type Schedule,
  type SchoolClass,
  type Student,
  type TeacherUpdate,
  type UserProfile,
} from "@/lib/api";
import {
  DAY_NAMES_ID,
  formatTimeShort,
  formatWaPhoneDisplay,
  formatWaPhonePreview,
  isValidWaPhone,
  matchesPhoneQuery,
  normalizeWaPhoneForMatch,
} from "@/lib/format";

export interface TeacherOption {
  id: string;
  name: string;
  nip?: string | null;
}

type StudentParentMode = "new" | "existing" | "edit_linked";

interface StudentModalProps {
  open: boolean;
  editing: Student | null;
  classes: SchoolClass[];
  parents: Parent[];
  students?: Student[];
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function StudentFormModal({
  open,
  editing,
  classes,
  parents,
  students = [],
  onClose,
  onSaved,
}: StudentModalProps) {
  const [nis, setNis] = useState(editing?.nis ?? "");
  const [name, setName] = useState(editing?.name ?? "");
  // Never default classId or parentId to [0]?.id on create
  const [classId, setClassId] = useState(editing?.class_id ?? "");
  const [parentMode, setParentMode] = useState<StudentParentMode>(
    editing ? "edit_linked" : "new"
  );

  // Mode "new" (inline parent creation / auto-link by phone)
  const [newParentName, setNewParentName] = useState("");
  const [newParentPhone, setNewParentPhone] = useState("");

  // Mode "edit_linked" (edit currently linked parent inline)
  const [linkedParentName, setLinkedParentName] = useState(
    editing?.parent_name ?? ""
  );
  const [linkedParentPhone, setLinkedParentPhone] = useState(
    editing?.parent_phone_wa ?? ""
  );

  // Mode "existing" (searchable picker for siblings / switching parent)
  const [parentId, setParentId] = useState(editing?.parent_id ?? "");
  const [parentSearch, setParentSearch] = useState("");

  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parentStudentCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const st of students) {
      counts.set(st.parent_id, (counts.get(st.parent_id) ?? 0) + 1);
    }
    return counts;
  }, [students]);

  const linkedStudentsCount = editing
    ? parentStudentCounts.get(editing.parent_id) ?? 1
    : 0;

  const newPhonePreview = useMemo(
    () => formatWaPhonePreview(newParentPhone),
    [newParentPhone]
  );

  const linkedPhonePreview = useMemo(
    () => formatWaPhonePreview(linkedParentPhone),
    [linkedParentPhone]
  );

  const matchedExistingParent = useMemo(() => {
    if (!isValidWaPhone(newParentPhone)) return null;
    const normalized = normalizeWaPhoneForMatch(newParentPhone);
    return (
      parents.find((p) => normalizeWaPhoneForMatch(p.phone_wa) === normalized) ??
      null
    );
  }, [parents, newParentPhone]);

  const filteredParents = useMemo(() => {
    const q = parentSearch.trim().toLowerCase();
    if (!q) return parents;
    return parents.filter(
      (p) =>
        p.name.toLowerCase().includes(q) || matchesPhoneQuery(p.phone_wa, q)
    );
  }, [parents, parentSearch]);

  const selectedParentObj = useMemo(
    () => parents.find((p) => p.id === parentId) ?? null,
    [parents, parentId]
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!nis.trim() || !name.trim() || !classId) {
      setError("NIS, Nama Siswa, dan Kelas wajib diisi.");
      return;
    }

    if (parentMode === "new") {
      if (!newParentPhone.trim() || !isValidWaPhone(newParentPhone)) {
        setError(
          "Nomor WhatsApp orang tua tidak valid. Gunakan format Indonesia (contoh: 081234567890)."
        );
        return;
      }
      const effectiveParentName =
        newParentName.trim() || matchedExistingParent?.name || "";
      if (!effectiveParentName) {
        setError("Nama orang tua / wali wajib diisi.");
        return;
      }

      setSubmitting(true);
      try {
        if (editing) {
          await updateStudent(editing.id, {
            nis: nis.trim(),
            name: name.trim(),
            class_id: classId,
            parent_name: effectiveParentName,
            parent_phone_wa: newParentPhone.trim(),
            update_linked_parent: false,
            is_active: isActive,
          });
          onSaved(`Data siswa "${name.trim()}" berhasil diperbarui.`);
        } else {
          await createStudent({
            nis: nis.trim(),
            name: name.trim(),
            class_id: classId,
            parent_name: effectiveParentName,
            parent_phone_wa: newParentPhone.trim(),
            is_active: isActive,
          });
          onSaved(`Siswa "${name.trim()}" berhasil ditambahkan.`);
        }
        onClose();
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Gagal menyimpan data siswa."
        );
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (parentMode === "edit_linked" && editing) {
      if (!linkedParentName.trim()) {
        setError("Nama orang tua / wali wajib diisi.");
        return;
      }
      if (!linkedParentPhone.trim() || !isValidWaPhone(linkedParentPhone)) {
        setError(
          "Nomor WhatsApp orang tua tidak valid. Gunakan format Indonesia (contoh: 081234567890)."
        );
        return;
      }

      setSubmitting(true);
      try {
        await updateStudent(editing.id, {
          nis: nis.trim(),
          name: name.trim(),
          class_id: classId,
          parent_name: linkedParentName.trim(),
          parent_phone_wa: linkedParentPhone.trim(),
          update_linked_parent: true,
          is_active: isActive,
        });
        onSaved(`Data siswa "${name.trim()}" & kontak orang tua berhasil diperbarui.`);
        onClose();
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "Gagal menyimpan data siswa."
        );
      } finally {
        setSubmitting(false);
      }
      return;
    }

    // Mode "existing"
    if (!parentId) {
      setError("Pilih orang tua / wali yang terdaftar terlebih dahulu.");
      return;
    }

    setSubmitting(true);
    try {
      if (editing) {
        await updateStudent(editing.id, {
          nis: nis.trim(),
          name: name.trim(),
          class_id: classId,
          parent_id: parentId,
          is_active: isActive,
        });
        onSaved(`Data siswa "${name.trim()}" berhasil diperbarui.`);
      } else {
        await createStudent({
          nis: nis.trim(),
          name: name.trim(),
          class_id: classId,
          parent_id: parentId,
          is_active: isActive,
        });
        onSaved(`Siswa "${name.trim()}" berhasil ditambahkan.`);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal menyimpan data siswa."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={submitting}
      maxWidthClass="max-w-xl"
      title={editing ? "Edit Data Siswa" : "Tambah Siswa Baru"}
      subtitle="Siswa terhubung ke kelas dan kontak WhatsApp orang tua untuk notifikasi otomatis."
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

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label
              htmlFor="student-nis"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              NIS
            </label>
            <input
              id="student-nis"
              type="text"
              required
              value={nis}
              onChange={(e) => setNis(e.target.value)}
              placeholder="Contoh: 24781025"
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="student-class"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Kelas
            </label>
            <select
              id="student-class"
              required
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            >
              <option value="">-- Pilih Kelas --</option>
              {classes.map((cls) => (
                <option key={cls.id} value={cls.id}>
                  {cls.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="student-name"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nama Lengkap Siswa
          </label>
          <input
            id="student-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Contoh: Rubby Ibnu Anantara"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
        </div>

        {/* Parent / Guardian Dual-Mode (Create) or Tri-Mode (Edit) Selector */}
        <div className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-4 space-y-3.5">
          <div className="space-y-2">
            <p className="text-xs font-bold text-[#0F172A]">
              Orang Tua / Wali Murid (WhatsApp)
            </p>
            <div
              className={`grid gap-1.5 ${
                editing ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-2"
              }`}
            >
              {editing ? (
                <button
                  type="button"
                  onClick={() => {
                    setParentMode("edit_linked");
                    setError(null);
                  }}
                  className={`rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${
                    parentMode === "edit_linked"
                      ? "border-[#1D4ED8] bg-[#EFF6FF] text-[#1D4ED8]"
                      : "border-[#E2E8F0] bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  Edit Kontak Terhubung
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  setParentMode("new");
                  setError(null);
                }}
                className={`inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${
                  parentMode === "new"
                    ? "border-[#1D4ED8] bg-[#EFF6FF] text-[#1D4ED8]"
                    : "border-[#E2E8F0] bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                <UserPlus className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>
                  {editing ? "Buat / Hubungkan Baru" : "Input Baru / Langsung"}
                </span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setParentMode("existing");
                  setError(null);
                }}
                className={`inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${
                  parentMode === "existing"
                    ? "border-[#1D4ED8] bg-[#EFF6FF] text-[#1D4ED8]"
                    : "border-[#E2E8F0] bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                <Users className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>Pilih Terdaftar ({parents.length})</span>
              </button>
            </div>
          </div>

          {parentMode === "new" ? (
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label
                    htmlFor="student-new-parent-name"
                    className="block text-xs font-semibold text-[#0F172A]"
                  >
                    Nama Orang Tua / Wali
                  </label>
                  <input
                    id="student-new-parent-name"
                    type="text"
                    required={!matchedExistingParent}
                    value={newParentName}
                    onChange={(e) => setNewParentName(e.target.value)}
                    placeholder={
                      matchedExistingParent
                        ? matchedExistingParent.name
                        : "Contoh: Bapak Anantara"
                    }
                    className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                  />
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor="student-new-parent-phone"
                    className="block text-xs font-semibold text-[#0F172A]"
                  >
                    Nomor WhatsApp
                  </label>
                  <input
                    id="student-new-parent-phone"
                    type="tel"
                    required
                    value={newParentPhone}
                    onChange={(e) => setNewParentPhone(e.target.value)}
                    placeholder="0812-xxxx-xxxx"
                    className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 font-mono text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                  />
                </div>
              </div>

              {newParentPhone.trim() ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  {newPhonePreview ? (
                    <span className="text-slate-600">
                      Preview WA:{" "}
                      <strong className="font-mono text-[#059669]">
                        {newPhonePreview}
                      </strong>
                      {isValidWaPhone(newParentPhone) ? " ✓" : " (minimal 10 digit)"}
                    </span>
                  ) : (
                    <span className="text-[#D97706]">
                      Masukkan nomor HP Indonesia yang diawali 08xx atau +628xx.
                    </span>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-slate-500">
                  Orang tua akan otomatis dibuat atau dihubungkan apabila nomor
                  WhatsApp sudah terdaftar.
                </p>
              )}

              {matchedExistingParent ? (
                <div
                  role="status"
                  className="flex items-start gap-2 rounded-xl border border-blue-200 bg-[#EFF6FF] p-3 text-xs text-[#1D4ED8]"
                >
                  <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>
                    Nomor ini sudah terdaftar atas nama{" "}
                    <strong>{matchedExistingParent.name}</strong> — akan
                    otomatis dihubungkan ke orang tua tersebut.
                  </span>
                </div>
              ) : null}
            </div>
          ) : parentMode === "edit_linked" && editing ? (
            <div className="space-y-3">
              {linkedStudentsCount > 1 ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-xl border border-amber-200 bg-[#FFFBEB] p-3 text-xs text-[#92400E]"
                >
                  <AlertTriangle
                    className="mt-0.5 h-4 w-4 shrink-0 text-[#D97706]"
                    aria-hidden="true"
                  />
                  <span>
                    Terhubung ke <strong>{linkedStudentsCount} siswa</strong> —
                    mengubah nomor akan memperbarui kontak semua anak.
                  </span>
                </div>
              ) : null}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label
                    htmlFor="student-linked-parent-name"
                    className="block text-xs font-semibold text-[#0F172A]"
                  >
                    Nama Orang Tua / Wali
                  </label>
                  <input
                    id="student-linked-parent-name"
                    type="text"
                    required
                    value={linkedParentName}
                    onChange={(e) => setLinkedParentName(e.target.value)}
                    className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                  />
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor="student-linked-parent-phone"
                    className="block text-xs font-semibold text-[#0F172A]"
                  >
                    Nomor WhatsApp
                  </label>
                  <input
                    id="student-linked-parent-phone"
                    type="tel"
                    required
                    value={linkedParentPhone}
                    onChange={(e) => setLinkedParentPhone(e.target.value)}
                    placeholder="0812-xxxx-xxxx"
                    className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 font-mono text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                  />
                </div>
              </div>

              {linkedPhonePreview ? (
                <p className="text-[11px] text-slate-600">
                  Preview WA:{" "}
                  <strong className="font-mono text-[#059669]">
                    {linkedPhonePreview}
                  </strong>
                  {isValidWaPhone(linkedParentPhone) ? " ✓" : " (minimal 10 digit)"}
                </p>
              ) : null}
            </div>
          ) : (
            <div className="space-y-2.5">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
                  aria-hidden="true"
                />
                <input
                  type="search"
                  aria-label="Cari orang tua berdasarkan nama atau nomor WhatsApp"
                  value={parentSearch}
                  onChange={(e) => setParentSearch(e.target.value)}
                  placeholder="Cari nama atau nomor WA (08xx / 628xx)..."
                  className="w-full rounded-xl border border-[#E2E8F0] bg-white py-2 pl-9 pr-3 text-xs focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
                />
              </div>

              {selectedParentObj ? (
                <div className="flex items-center justify-between rounded-xl border border-blue-200 bg-[#EFF6FF] px-3 py-2 text-xs">
                  <span className="text-[#1D4ED8]">
                    Dipilih: <strong>{selectedParentObj.name}</strong> (
                    <span className="font-mono">
                      {formatWaPhoneDisplay(selectedParentObj.phone_wa)}
                    </span>
                    )
                  </span>
                  <button
                    type="button"
                    onClick={() => setParentId("")}
                    className="text-[11px] font-semibold text-slate-500 hover:text-slate-700"
                  >
                    Ubah
                  </button>
                </div>
              ) : null}

              {parents.length === 0 ? (
                <p className="rounded-xl border border-amber-200 bg-[#FFFBEB] p-3 text-xs text-[#92400E]">
                  Belum ada orang tua terdaftar. Gunakan tab{" "}
                  <strong>Input Baru / Langsung</strong> untuk langsung mengisi
                  nama dan nomor WA orang tua.
                </p>
              ) : filteredParents.length === 0 ? (
                <p className="py-4 text-center text-xs text-slate-500">
                  Tidak ada orang tua yang cocok dengan pencarian &ldquo;
                  {parentSearch}&rdquo;.
                </p>
              ) : (
                <div
                  role="listbox"
                  aria-label="Daftar orang tua terdaftar"
                  className="max-h-44 overflow-y-auto divide-y divide-[#E2E8F0] rounded-xl border border-[#E2E8F0] bg-white"
                >
                  {filteredParents.map((parent) => {
                    const selected = parent.id === parentId;
                    const count = parentStudentCounts.get(parent.id) ?? 0;
                    return (
                      <button
                        key={parent.id}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        onClick={() => setParentId(parent.id)}
                        className={`flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-xs transition-colors ${
                          selected
                            ? "bg-[#EFF6FF] text-[#1D4ED8]"
                            : "hover:bg-[#F8FAFC] text-[#0F172A]"
                        }`}
                      >
                        <div className="min-w-0">
                          <p className="truncate font-semibold">{parent.name}</p>
                          <p className="font-mono text-[11px] text-[#059669]">
                            {formatWaPhoneDisplay(parent.phone_wa)}
                          </p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {count > 0 ? (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                              {count} anak
                            </span>
                          ) : null}
                          {selected ? (
                            <Check className="h-4 w-4 text-[#1D4ED8]" aria-hidden="true" />
                          ) : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        <label className="flex items-center gap-2.5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] px-3.5 py-2.5 text-xs font-semibold text-[#0F172A] cursor-pointer">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-[#1D4ED8] focus:ring-[#1D4ED8]"
          />
          <span>Siswa aktif mengikuti Kiosk Face Recognition</span>
        </label>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting
              ? "Menyimpan..."
              : editing
                ? "Simpan Perubahan"
                : "Tambah Siswa"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ParentModalProps {
  open: boolean;
  editing: Parent | null;
  sharedStudentsCount?: number;
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function ParentFormModal({
  open,
  editing,
  sharedStudentsCount = 0,
  onClose,
  onSaved,
}: ParentModalProps) {
  const [name, setName] = useState(editing?.name ?? "");
  const [phoneWa, setPhoneWa] = useState(editing?.phone_wa ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phonePreview = useMemo(() => formatWaPhonePreview(phoneWa), [phoneWa]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim() || !phoneWa.trim()) {
      setError("Nama orang tua dan nomor WhatsApp wajib diisi.");
      return;
    }
    if (!isValidWaPhone(phoneWa)) {
      setError(
        "Nomor WhatsApp tidak valid. Gunakan format nomor Indonesia (contoh: 081234567890)."
      );
      return;
    }

    setSubmitting(true);
    try {
      if (editing) {
        await updateParent(editing.id, {
          name: name.trim(),
          phone_wa: phoneWa.trim(),
        });
        onSaved(`Data orang tua "${name.trim()}" berhasil diperbarui.`);
      } else {
        await createParent({
          name: name.trim(),
          phone_wa: phoneWa.trim(),
        });
        onSaved(`Orang tua "${name.trim()}" berhasil ditambahkan.`);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal menyimpan data orang tua."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={submitting}
      title={editing ? "Edit Data Orang Tua (WA)" : "Tambah Orang Tua (WA)"}
      subtitle="Nomor WhatsApp otomatis dinormalisasi ke format kanonis 628xxxxxxxxxx."
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

        {editing && sharedStudentsCount > 1 ? (
          <div
            role="status"
            className="flex items-start gap-2 rounded-xl border border-amber-200 bg-[#FFFBEB] p-3 text-xs text-[#92400E]"
          >
            <AlertTriangle
              className="mt-0.5 h-4 w-4 shrink-0 text-[#D97706]"
              aria-hidden="true"
            />
            <span>
              Kontak ini terhubung ke <strong>{sharedStudentsCount} siswa</strong>.
              Perubahan nama/nomor akan berlaku untuk seluruh anak terkait.
            </span>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label
            htmlFor="parent-name"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nama Orang Tua / Wali Murid
          </label>
          <input
            id="parent-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Contoh: Bapak Anantara"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="parent-phone"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nomor WhatsApp Aktif
          </label>
          <input
            id="parent-phone"
            type="tel"
            required
            value={phoneWa}
            onChange={(e) => setPhoneWa(e.target.value)}
            placeholder="0812-xxxx-xxxx"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm font-mono focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
          {phonePreview ? (
            <p className="text-[11px] text-slate-600">
              Preview format WA:{" "}
              <strong className="font-mono text-[#059669]">{phonePreview}</strong>
              {isValidWaPhone(phoneWa) ? " ✓" : " (minimal 10 digit)"}
            </p>
          ) : (
            <p className="text-[11px] text-slate-500">
              Mendukung format <code className="font-mono">08xx</code>,{" "}
              <code className="font-mono">+628xx</code>, atau{" "}
              <code className="font-mono">628xx</code>.
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting
              ? "Menyimpan..."
              : editing
                ? "Simpan Perubahan"
                : "Tambah Orang Tua"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface TeacherModalProps {
  open: boolean;
  editing: UserProfile | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function TeacherFormModal({
  open,
  editing,
  onClose,
  onSaved,
}: TeacherModalProps) {
  const [name, setName] = useState(editing?.name ?? "");
  const [email, setEmail] = useState(editing?.email ?? "");
  const [nip, setNip] = useState(editing?.nip ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [kioskPin, setKioskPin] = useState("");
  const [resetKioskPin, setResetKioskPin] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!name.trim() || !email.trim()) {
      setError("Nama guru dan email wajib diisi.");
      return;
    }

    if (!editing && password.length < 6) {
      setError("Kata sandi wajib diisi minimal 6 karakter.");
      return;
    }

    if (editing && password.length > 0 && password.length < 6) {
      setError("Kata sandi baru minimal 6 karakter.");
      return;
    }

    const trimmedPin = kioskPin.trim();
    if (!resetKioskPin && trimmedPin && !/^\d{4,6}$/.test(trimmedPin)) {
      setError("PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.");
      return;
    }

    setSubmitting(true);
    try {
      if (editing) {
        const payload: TeacherUpdate = {
          name: name.trim(),
          email: email.trim(),
          nip: nip.trim() || null,
        };
        if (password) {
          payload.password = password;
        }
        if (resetKioskPin) {
          payload.reset_kiosk_pin = true;
        } else if (trimmedPin) {
          payload.kiosk_pin = trimmedPin;
        }
        await updateTeacher(editing.id, payload);
        onSaved(`Data guru "${name.trim()}" berhasil diperbarui.`);
      } else {
        await createTeacher({
          name: name.trim(),
          email: email.trim(),
          password,
          nip: nip.trim() || null,
          kiosk_pin: trimmedPin || null,
        });
        onSaved(`Akun guru "${name.trim()}" berhasil ditambahkan.`);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal menyimpan data guru."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={submitting}
      title={editing ? "Edit Akun Guru" : "Tambah Guru Baru"}
      subtitle="Akun guru digunakan untuk login aplikasi Mobile Guru, Kiosk Presensi, dan verifikasi izin."
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
            htmlFor="teacher-name"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nama Lengkap Guru
          </label>
          <input
            id="teacher-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Contoh: Ibu Siti Aminah, S.Pd."
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label
              htmlFor="teacher-email"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Email Login
            </label>
            <input
              id="teacher-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="guru@sekolah.sch.id"
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="teacher-nip"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              NIP (Opsional)
            </label>
            <input
              id="teacher-nip"
              type="text"
              value={nip}
              onChange={(e) => setNip(e.target.value)}
              placeholder="Contoh: 198801012015032001"
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 font-mono text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="teacher-password"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            {editing ? "Kata Sandi Baru (Opsional)" : "Kata Sandi"}
          </label>
          <div className="relative">
            <input
              id="teacher-password"
              type={showPassword ? "text" : "password"}
              required={!editing}
              minLength={editing ? undefined : 6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={
                editing
                  ? "Kosongkan jika tidak ingin mengubah kata sandi"
                  : "Minimal 6 karakter"
              }
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 pr-10 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={
                showPassword ? "Sembunyikan kata sandi" : "Tampilkan kata sandi"
              }
              className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-slate-400 hover:text-slate-700"
            >
              {showPassword ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-[#E2E8F0] bg-[#F8FAFC] p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <label
              htmlFor="teacher-kiosk-pin"
              className="text-xs font-bold text-[#0F172A]"
            >
              {editing ? "Pengaturan PIN Kiosk" : "PIN Kiosk Awal (Opsional)"}
            </label>
            {editing ? (
              <StatusBadge tone={editing.has_kiosk_pin ? "success" : "warning"}>
                {editing.has_kiosk_pin ? "Sudah Diatur" : "Belum Diatur"}
              </StatusBadge>
            ) : null}
          </div>

          <input
            id="teacher-kiosk-pin"
            type="password"
            inputMode="numeric"
            maxLength={6}
            disabled={resetKioskPin}
            value={kioskPin}
            onChange={(e) => setKioskPin(e.target.value.replace(/\D/g, ""))}
            placeholder={
              editing
                ? "Isi 4–6 digit untuk mengganti / mengatur PIN baru"
                : "4–6 digit angka (opsional, guru dapat mengatur sendiri nanti)"
            }
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 font-mono text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20 disabled:bg-slate-100 disabled:text-slate-400"
          />

          {editing && editing.has_kiosk_pin ? (
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer">
              <input
                type="checkbox"
                checked={resetKioskPin}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setResetKioskPin(checked);
                  if (checked) setKioskPin("");
                }}
                className="h-4 w-4 rounded border-slate-300 text-[#EF4444] focus:ring-[#EF4444]"
              />
              <span>
                Reset / hapus PIN Kiosk (guru harus mengatur ulang PIN di aplikasi)
              </span>
            </label>
          ) : null}
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting
              ? "Menyimpan..."
              : editing
                ? "Simpan Perubahan"
                : "Tambah Guru"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ClassModalProps {
  open: boolean;
  editing: SchoolClass | null;
  teachers: TeacherOption[];
  onClose: () => void;
  onSaved: (message: string) => void;
  onGoToTeachers?: () => void;
}

export function ClassFormModal({
  open,
  editing,
  teachers,
  onClose,
  onSaved,
  onGoToTeachers,
}: ClassModalProps) {
  const [name, setName] = useState(editing?.name ?? "");
  const [homeroomTeacherId, setHomeroomTeacherId] = useState(
    editing?.homeroom_teacher_id ?? ""
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Nama kelas wajib diisi.");
      return;
    }

    const teacherValue = homeroomTeacherId.trim() || null;
    setSubmitting(true);
    try {
      if (editing) {
        await updateClass(editing.id, {
          name: name.trim(),
          homeroom_teacher_id: teacherValue,
        });
        onSaved(`Data kelas "${name.trim()}" berhasil diperbarui.`);
      } else {
        await createClass({
          name: name.trim(),
          homeroom_teacher_id: teacherValue,
        });
        onSaved(`Kelas "${name.trim()}" berhasil ditambahkan.`);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal menyimpan data kelas."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={submitting}
      title={editing ? "Edit Kelas" : "Tambah Kelas Baru"}
      subtitle="Atur nama rombongan belajar dan wali kelas (opsional)."
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
            htmlFor="class-name"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nama Kelas
          </label>
          <input
            id="class-name"
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Contoh: XI IPA 1"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="class-teacher"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Wali Kelas (Opsional)
          </label>

          <select
            id="class-teacher"
            value={homeroomTeacherId}
            onChange={(e) => setHomeroomTeacherId(e.target.value)}
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          >
            <option value="">-- Tanpa Wali Kelas --</option>
            {teachers.map((teacher) => (
              <option key={teacher.id} value={teacher.id}>
                {teacher.nip
                  ? `${teacher.name} (NIP ${teacher.nip})`
                  : teacher.name}
              </option>
            ))}
          </select>

          {teachers.length === 0 ? (
            <p className="text-[11px] text-[#D97706]">
              Belum ada akun guru terdaftar.{" "}
              {onGoToTeachers ? (
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onGoToTeachers();
                  }}
                  className="font-semibold text-[#1D4ED8] underline hover:text-[#1E3A8A]"
                >
                  Tambah guru di tab Guru →
                </button>
              ) : (
                "Tambahkan guru di tab Guru terlebih dahulu."
              )}
            </p>
          ) : null}
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting
              ? "Menyimpan..."
              : editing
                ? "Simpan Perubahan"
                : "Tambah Kelas"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ScheduleModalProps {
  open: boolean;
  editing: Schedule | null;
  classes: SchoolClass[];
  teachers: TeacherOption[];
  onClose: () => void;
  onSaved: (message: string) => void;
  onGoToTeachers?: () => void;
}

export function ScheduleFormModal({
  open,
  editing,
  classes,
  teachers,
  onClose,
  onSaved,
  onGoToTeachers,
}: ScheduleModalProps) {
  // Never default classId or teacherId to [0]?.id on create
  const [classId, setClassId] = useState(editing?.class_id ?? "");
  const [teacherId, setTeacherId] = useState(editing?.teacher_id ?? "");
  const [subjectName, setSubjectName] = useState(editing?.subject_name ?? "");
  const [dayOfWeek, setDayOfWeek] = useState<number>(editing?.day_of_week ?? 1);
  const [startTime, setStartTime] = useState(
    editing ? formatTimeShort(editing.start_time) : "07:30"
  );
  const [endTime, setEndTime] = useState(
    editing ? formatTimeShort(editing.end_time) : "09:00"
  );
  const [lateTolerance, setLateTolerance] = useState<string>(
    String(editing?.late_tolerance_minutes ?? 15)
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!classId || !teacherId.trim() || !subjectName.trim()) {
      setError("Kelas, Guru Pengampu, dan Mata Pelajaran wajib diisi.");
      return;
    }

    if (!startTime || !endTime || endTime <= startTime) {
      setError("Jam selesai harus lebih lambat dari jam mulai.");
      return;
    }

    const trimmedTol = lateTolerance.trim();
    if (!trimmedTol || !/^\d+$/.test(trimmedTol)) {
      setError("Toleransi keterlambatan harus berupa bilangan bulat (0–120 menit).");
      return;
    }
    const parsedTolerance = Number.parseInt(trimmedTol, 10);
    if (
      !Number.isInteger(parsedTolerance) ||
      parsedTolerance < 0 ||
      parsedTolerance > 120
    ) {
      setError("Toleransi keterlambatan harus bernilai antara 0 hingga 120 menit.");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        class_id: classId,
        teacher_id: teacherId.trim(),
        subject_name: subjectName.trim(),
        day_of_week: dayOfWeek,
        start_time: startTime,
        end_time: endTime,
        late_tolerance_minutes: parsedTolerance,
      };
      if (editing) {
        await updateSchedule(editing.id, payload);
        onSaved(`Jadwal "${subjectName.trim()}" berhasil diperbarui.`);
      } else {
        await createSchedule(payload);
        onSaved(`Jadwal "${subjectName.trim()}" berhasil ditambahkan.`);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Gagal menyimpan jadwal pelajaran."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      preventClose={submitting}
      title={editing ? "Edit Jadwal Pelajaran" : "Tambah Jadwal Pelajaran"}
      subtitle="Digunakan untuk sesi presensi guru & jawaban chatbot jadwal WA."
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
            htmlFor="sched-subject"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Nama Mata Pelajaran
          </label>
          <input
            id="sched-subject"
            type="text"
            required
            value={subjectName}
            onChange={(e) => setSubjectName(e.target.value)}
            placeholder="Contoh: Pemrograman Mobile"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label
              htmlFor="sched-class"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Kelas
            </label>
            <select
              id="sched-class"
              required
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            >
              <option value="">-- Pilih Kelas --</option>
              {classes.map((cls) => (
                <option key={cls.id} value={cls.id}>
                  {cls.name}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="sched-day"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Hari
            </label>
            <select
              id="sched-day"
              value={dayOfWeek}
              onChange={(e) => setDayOfWeek(Number(e.target.value))}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            >
              {Object.entries(DAY_NAMES_ID).map(([num, label]) => (
                <option key={num} value={Number(num)}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="sched-teacher"
            className="block text-xs font-semibold text-[#0F172A]"
          >
            Guru Pengampu
          </label>

          <select
            id="sched-teacher"
            required
            value={teacherId}
            onChange={(e) => setTeacherId(e.target.value)}
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          >
            <option value="">-- Pilih Guru --</option>
            {teachers.map((teacher) => (
              <option key={teacher.id} value={teacher.id}>
                {teacher.nip
                  ? `${teacher.name} (NIP ${teacher.nip})`
                  : teacher.name}
              </option>
            ))}
          </select>

          {teachers.length === 0 ? (
            <div className="rounded-xl border border-amber-200 bg-[#FFFBEB] p-3 text-xs text-[#92400E]">
              Belum ada akun guru terdaftar untuk dipilih.{" "}
              {onGoToTeachers ? (
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onGoToTeachers();
                  }}
                  className="font-semibold text-[#1D4ED8] underline hover:text-[#1E3A8A]"
                >
                  Buka tab Guru untuk menambah guru →
                </button>
              ) : (
                "Tambahkan guru di tab Guru terlebih dahulu."
              )}
            </div>
          ) : null}
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <label
              htmlFor="sched-start"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Jam Mulai
            </label>
            <input
              id="sched-start"
              type="time"
              required
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="sched-end"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Jam Selesai
            </label>
            <input
              id="sched-end"
              type="time"
              required
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="sched-tol"
              className="block text-xs font-semibold text-[#0F172A]"
            >
              Toleransi (mnt)
            </label>
            <input
              id="sched-tol"
              type="number"
              inputMode="numeric"
              min={0}
              max={120}
              step={1}
              required
              value={lateTolerance}
              onChange={(e) => setLateTolerance(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            disabled={submitting}
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting || teachers.length === 0}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting
              ? "Menyimpan..."
              : editing
                ? "Simpan Perubahan"
                : "Tambah Jadwal"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
