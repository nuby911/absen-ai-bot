"use client";

import { useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";
import { Modal } from "@/components/Modal";
import {
  ApiError,
  createClass,
  createParent,
  createSchedule,
  createStudent,
  updateClass,
  updateParent,
  updateSchedule,
  updateStudent,
  type Parent,
  type Schedule,
  type SchoolClass,
  type Student,
} from "@/lib/api";
import { DAY_NAMES_ID, formatTimeShort } from "@/lib/format";

export interface TeacherOption {
  id: string;
  name: string;
}

interface StudentModalProps {
  open: boolean;
  editing: Student | null;
  classes: SchoolClass[];
  parents: Parent[];
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function StudentFormModal({
  open,
  editing,
  classes,
  parents,
  onClose,
  onSaved,
}: StudentModalProps) {
  const [nis, setNis] = useState(editing?.nis ?? "");
  const [name, setName] = useState(editing?.name ?? "");
  const [classId, setClassId] = useState(
    editing?.class_id ?? classes[0]?.id ?? ""
  );
  const [parentId, setParentId] = useState(
    editing?.parent_id ?? parents[0]?.id ?? ""
  );
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!nis.trim() || !name.trim() || !classId || !parentId) {
      setError("NIS, Nama Siswa, Kelas, dan Orang Tua wajib diisi.");
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
      setError(err instanceof ApiError ? err.message : "Gagal menyimpan data siswa.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Edit Data Siswa" : "Tambah Siswa Baru"}
      subtitle="Siswa terhubung ke kelas dan kontak WhatsApp orang tua."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="student-nis" className="block text-xs font-semibold text-[#0F172A]">
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
            <label htmlFor="student-class" className="block text-xs font-semibold text-[#0F172A]">
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
          <label htmlFor="student-name" className="block text-xs font-semibold text-[#0F172A]">
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

        <div className="space-y-1.5">
          <label htmlFor="student-parent" className="block text-xs font-semibold text-[#0F172A]">
            Orang Tua / Wali (WhatsApp)
          </label>
          <select
            id="student-parent"
            required
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          >
            <option value="">-- Pilih Orang Tua --</option>
            {parents.map((parent) => (
              <option key={parent.id} value={parent.id}>
                {parent.name} (+{parent.phone_wa})
              </option>
            ))}
          </select>
          {parents.length === 0 ? (
            <p className="text-[11px] text-[#D97706]">
              Belum ada data orang tua. Tambahkan di tab Orang Tua (WA) terlebih dahulu.
            </p>
          ) : null}
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
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting ? "Menyimpan..." : editing ? "Simpan Perubahan" : "Tambah Siswa"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ParentModalProps {
  open: boolean;
  editing: Parent | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}

export function ParentFormModal({
  open,
  editing,
  onClose,
  onSaved,
}: ParentModalProps) {
  const [name, setName] = useState(editing?.name ?? "");
  const [phoneWa, setPhoneWa] = useState(editing?.phone_wa ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!name.trim() || !phoneWa.trim()) {
      setError("Nama orang tua dan nomor WhatsApp wajib diisi.");
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
      title={editing ? "Edit Data Orang Tua (WA)" : "Tambah Orang Tua (WA)"}
      subtitle="Nomor WhatsApp otomatis dinormalisasi ke format kanonis 628xxxxxxxxxx."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label htmlFor="parent-name" className="block text-xs font-semibold text-[#0F172A]">
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
          <label htmlFor="parent-phone" className="block text-xs font-semibold text-[#0F172A]">
            Nomor WhatsApp Aktif
          </label>
          <input
            id="parent-phone"
            type="text"
            required
            value={phoneWa}
            onChange={(e) => setPhoneWa(e.target.value)}
            placeholder="Contoh: 081279001234 atau +62 812-7900-1234"
            className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm font-mono focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
          />
          <p className="text-[11px] text-slate-500">
            Mendukung format <code className="font-mono">08xx</code>,{" "}
            <code className="font-mono">+628xx</code>, atau{" "}
            <code className="font-mono">628xx</code>.
          </p>
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting ? "Menyimpan..." : editing ? "Simpan Perubahan" : "Tambah Orang Tua"}
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
}

export function ClassFormModal({
  open,
  editing,
  teachers,
  onClose,
  onSaved,
}: ClassModalProps) {
  const [name, setName] = useState(editing?.name ?? "");
  const [teacherMode, setTeacherMode] = useState<"list" | "manual">(
    editing?.homeroom_teacher_id &&
      !teachers.some((t) => t.id === editing.homeroom_teacher_id)
      ? "manual"
      : "list"
  );
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
      setError(err instanceof ApiError ? err.message : "Gagal menyimpan data kelas.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Edit Kelas" : "Tambah Kelas Baru"}
      subtitle="Atur nama rombongan belajar dan wali kelas (opsional)."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label htmlFor="class-name" className="block text-xs font-semibold text-[#0F172A]">
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

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label htmlFor="class-teacher" className="block text-xs font-semibold text-[#0F172A]">
              Wali Kelas (Opsional)
            </label>
            <button
              type="button"
              onClick={() =>
                setTeacherMode((prev) => (prev === "list" ? "manual" : "list"))
              }
              className="text-[11px] font-semibold text-[#1D4ED8] hover:underline"
            >
              {teacherMode === "list" ? "Input UUID Manual" : "Pilih dari Daftar"}
            </button>
          </div>

          {teacherMode === "list" ? (
            <select
              id="class-teacher"
              value={homeroomTeacherId}
              onChange={(e) => setHomeroomTeacherId(e.target.value)}
              className="w-full rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            >
              <option value="">-- Tanpa Wali Kelas --</option>
              {teachers.map((teacher) => (
                <option key={teacher.id} value={teacher.id}>
                  {teacher.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="class-teacher"
              type="text"
              value={homeroomTeacherId}
              onChange={(e) => setHomeroomTeacherId(e.target.value)}
              placeholder="UUID Guru (kosongkan jika tanpa wali kelas)"
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm font-mono focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          )}
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting ? "Menyimpan..." : editing ? "Simpan Perubahan" : "Tambah Kelas"}
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
}

export function ScheduleFormModal({
  open,
  editing,
  classes,
  teachers,
  onClose,
  onSaved,
}: ScheduleModalProps) {
  const [classId, setClassId] = useState(editing?.class_id ?? classes[0]?.id ?? "");
  const [teacherMode, setTeacherMode] = useState<"list" | "manual">(
    teachers.length === 0 ? "manual" : "list"
  );
  const [teacherId, setTeacherId] = useState(
    editing?.teacher_id ?? teachers[0]?.id ?? ""
  );
  const [subjectName, setSubjectName] = useState(editing?.subject_name ?? "");
  const [dayOfWeek, setDayOfWeek] = useState<number>(editing?.day_of_week ?? 1);
  const [startTime, setStartTime] = useState(
    editing ? formatTimeShort(editing.start_time) : "07:30"
  );
  const [endTime, setEndTime] = useState(
    editing ? formatTimeShort(editing.end_time) : "09:00"
  );
  const [lateTolerance, setLateTolerance] = useState<number>(
    editing?.late_tolerance_minutes ?? 15
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

    if (endTime <= startTime) {
      setError("Jam selesai harus lebih lambat dari jam mulai.");
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
        late_tolerance_minutes: lateTolerance,
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
      title={editing ? "Edit Jadwal Pelajaran" : "Tambah Jadwal Pelajaran"}
      subtitle="Digunakan untuk sesi presensi guru & jawaban chatbot jadwal WA."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error ? (
          <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-[#FEF2F2] p-3 text-xs text-[#DC2626]">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label htmlFor="sched-subject" className="block text-xs font-semibold text-[#0F172A]">
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
            <label htmlFor="sched-class" className="block text-xs font-semibold text-[#0F172A]">
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
            <label htmlFor="sched-day" className="block text-xs font-semibold text-[#0F172A]">
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
          <div className="flex items-center justify-between">
            <label htmlFor="sched-teacher" className="block text-xs font-semibold text-[#0F172A]">
              Guru Pengampu
            </label>
            {teachers.length > 0 ? (
              <button
                type="button"
                onClick={() =>
                  setTeacherMode((prev) => (prev === "list" ? "manual" : "list"))
                }
                className="text-[11px] font-semibold text-[#1D4ED8] hover:underline"
              >
                {teacherMode === "list" ? "Input UUID Manual" : "Pilih dari Daftar"}
              </button>
            ) : null}
          </div>

          {teacherMode === "list" && teachers.length > 0 ? (
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
                  {teacher.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="sched-teacher"
              type="text"
              required
              value={teacherId}
              onChange={(e) => setTeacherId(e.target.value)}
              placeholder="Masukkan UUID Guru"
              className="w-full rounded-xl border border-[#E2E8F0] px-3.5 py-2.5 text-sm font-mono focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          )}
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <label htmlFor="sched-start" className="block text-xs font-semibold text-[#0F172A]">
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
            <label htmlFor="sched-end" className="block text-xs font-semibold text-[#0F172A]">
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
            <label htmlFor="sched-tol" className="block text-xs font-semibold text-[#0F172A]">
              Toleransi (mnt)
            </label>
            <input
              id="sched-tol"
              type="number"
              min={0}
              max={120}
              required
              value={lateTolerance}
              onChange={(e) => setLateTolerance(Number(e.target.value))}
              className="w-full rounded-xl border border-[#E2E8F0] px-3 py-2.5 text-sm focus:border-[#1D4ED8] focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2.5 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Batal
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-[#1D4ED8] px-5 py-2 text-sm font-semibold text-white hover:bg-[#1E3A8A] disabled:opacity-60"
          >
            {submitting ? "Menyimpan..." : editing ? "Simpan Perubahan" : "Tambah Jadwal"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
