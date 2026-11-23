"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Edit3,
  GraduationCap,
  MessageCircle,
  Plus,
  RefreshCw,
  ScanFace,
  School,
  Search,
  Trash2,
  Users,
} from "lucide-react";
import { AdminShell } from "@/components/AdminShell";
import { Modal } from "@/components/Modal";
import { StatusBadge } from "@/components/StatusBadge";
import {
  ClassFormModal,
  ParentFormModal,
  ScheduleFormModal,
  StudentFormModal,
  type TeacherOption,
} from "@/components/students/MasterDataModals";
import {
  ApiError,
  deleteClass,
  deleteParent,
  deleteSchedule,
  deleteStudent,
  getClasses,
  getParents,
  getSchedules,
  getStudents,
  type Parent,
  type Schedule,
  type SchoolClass,
  type Student,
} from "@/lib/api";
import {
  DAY_NAMES_ID,
  formatDayOfWeek,
  formatTimeShort,
  formatWaPhoneDisplay,
  formatWibDateTime,
} from "@/lib/format";

type ActiveTab = "students" | "parents" | "classes" | "schedules";

interface DeleteTarget {
  type: ActiveTab;
  id: string;
  label: string;
}

export default function MasterDataPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("students");
  const [students, setStudents] = useState<Student[]>([]);
  const [parents, setParents] = useState<Parent[]>([]);
  const [classes, setClasses] = useState<SchoolClass[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [classFilter, setClassFilter] = useState("");
  const [dayFilter, setDayFilter] = useState<string>("");

  // Create / Edit Modal state
  const [modalMode, setModalMode] = useState<
    | { type: "student"; item: Student | null }
    | { type: "parent"; item: Parent | null }
    | { type: "class"; item: SchoolClass | null }
    | { type: "schedule"; item: Schedule | null }
    | null
  >(null);

  // Delete confirmation modal
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchAllMasterData = useCallback(async () => {
    const [studentsRes, parentsRes, classesRes, schedulesRes] =
      await Promise.all([
        getStudents(),
        getParents(),
        getClasses(),
        getSchedules(),
      ]);
    return { studentsRes, parentsRes, classesRes, schedulesRes };
  }, []);

  const loadAllData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { studentsRes, parentsRes, classesRes, schedulesRes } =
        await fetchAllMasterData();
      setStudents(studentsRes);
      setParents(parentsRes);
      setClasses(classesRes);
      setSchedules(schedulesRes);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Gagal memuat data master sekolah."
      );
    } finally {
      setLoading(false);
    }
  }, [fetchAllMasterData]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const { studentsRes, parentsRes, classesRes, schedulesRes } =
          await fetchAllMasterData();
        if (cancelled) return;
        setStudents(studentsRes);
        setParents(parentsRes);
        setClasses(classesRes);
        setSchedules(schedulesRes);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : "Gagal memuat data master sekolah."
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void init();
    return () => {
      cancelled = true;
    };
  }, [fetchAllMasterData]);

  // Derive known teachers from existing classes and schedules
  const knownTeachers = useMemo<TeacherOption[]>(() => {
    const map = new Map<string, string>();
    for (const cls of classes) {
      if (cls.homeroom_teacher_id && cls.homeroom_teacher_name) {
        map.set(cls.homeroom_teacher_id, cls.homeroom_teacher_name);
      }
    }
    for (const sched of schedules) {
      if (sched.teacher_id && sched.teacher_name) {
        map.set(sched.teacher_id, sched.teacher_name);
      }
    }
    return Array.from(map.entries())
      .map(([id, name]) => ({ id, name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [classes, schedules]);

  const filteredStudents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return students.filter((s) => {
      if (classFilter && s.class_id !== classFilter) return false;
      if (!q) return true;
      return (
        s.name.toLowerCase().includes(q) ||
        s.nis.toLowerCase().includes(q) ||
        s.parent_name.toLowerCase().includes(q)
      );
    });
  }, [students, classFilter, searchQuery]);

  const filteredParents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return parents;
    return parents.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.phone_wa.toLowerCase().includes(q)
    );
  }, [parents, searchQuery]);

  const filteredClasses = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return classes;
    return classes.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.homeroom_teacher_name ?? "").toLowerCase().includes(q)
    );
  }, [classes, searchQuery]);

  const filteredSchedules = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return schedules.filter((sch) => {
      if (classFilter && sch.class_id !== classFilter) return false;
      if (dayFilter && sch.day_of_week !== Number(dayFilter)) return false;
      if (!q) return true;
      return (
        sch.subject_name.toLowerCase().includes(q) ||
        sch.teacher_name.toLowerCase().includes(q) ||
        sch.class_name.toLowerCase().includes(q)
      );
    });
  }, [schedules, classFilter, dayFilter, searchQuery]);

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    setSuccessMsg(null);

    try {
      if (deleteTarget.type === "students") {
        await deleteStudent(deleteTarget.id);
      } else if (deleteTarget.type === "parents") {
        await deleteParent(deleteTarget.id);
      } else if (deleteTarget.type === "classes") {
        await deleteClass(deleteTarget.id);
      } else {
        await deleteSchedule(deleteTarget.id);
      }
      setSuccessMsg(`"${deleteTarget.label}" berhasil dihapus.`);
      setDeleteTarget(null);
      await loadAllData();
    } catch (err) {
      setDeleteTarget(null);
      setError(
        err instanceof ApiError ? err.message : "Gagal menghapus data."
      );
    } finally {
      setDeleting(false);
    }
  }

  function handleSaved(message: string) {
    setSuccessMsg(message);
    void loadAllData();
  }

  const tabs: Array<{
    key: ActiveTab;
    label: string;
    count: number;
    icon: typeof Users;
  }> = [
    { key: "students", label: "Siswa", count: students.length, icon: GraduationCap },
    {
      key: "parents",
      label: "Orang Tua (WA)",
      count: parents.length,
      icon: MessageCircle,
    },
    { key: "classes", label: "Kelas", count: classes.length, icon: School },
    {
      key: "schedules",
      label: "Jadwal Pelajaran",
      count: schedules.length,
      icon: CalendarClock,
    },
  ];

  function openAddModalForCurrentTab() {
    setSuccessMsg(null);
    if (activeTab === "students") {
      setModalMode({ type: "student", item: null });
    } else if (activeTab === "parents") {
      setModalMode({ type: "parent", item: null });
    } else if (activeTab === "classes") {
      setModalMode({ type: "class", item: null });
    } else {
      setModalMode({ type: "schedule", item: null });
    }
  }

  const addButtonLabel =
    activeTab === "students"
      ? "Tambah Siswa"
      : activeTab === "parents"
        ? "Tambah Orang Tua"
        : activeTab === "classes"
          ? "Tambah Kelas"
          : "Tambah Jadwal";

  return (
    <AdminShell
      title="Data Siswa & Master"
      subtitle="Kelola data master Siswa, Orang Tua (WhatsApp), Kelas, dan Jadwal Pelajaran."
      headerActions={
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadAllData()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#E2E8F0] bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={openAddModalForCurrentTab}
            className="inline-flex items-center gap-1.5 rounded-xl bg-[#1D4ED8] px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#1E3A8A]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            <span>{addButtonLabel}</span>
          </button>
        </div>
      }
    >
      {/* Alerts */}
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

      {error ? (
        <div
          role="alert"
          className="mb-5 flex items-center justify-between gap-3 rounded-2xl border border-red-200 bg-[#FEF2F2] px-4 py-3 text-sm text-[#DC2626]"
        >
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-xs font-semibold underline"
          >
            Tutup
          </button>
        </div>
      ) : null}

      {/* Main Card Container */}
      <div className="rounded-2xl border border-[#E2E8F0] bg-white shadow-2xs overflow-hidden">
        {/* Tabs Bar */}
        <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-4 pt-3 sm:px-6">
          <div
            role="tablist"
            aria-label="Kategori Data Master"
            className="flex flex-wrap gap-2"
          >
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const selected = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  role="tab"
                  type="button"
                  aria-selected={selected}
                  onClick={() => {
                    setActiveTab(tab.key);
                    setSearchQuery("");
                  }}
                  className={`inline-flex items-center gap-2 rounded-t-xl border border-b-0 px-4 py-2.5 text-sm font-semibold transition-colors ${
                    selected
                      ? "border-[#E2E8F0] bg-white text-[#1D4ED8] shadow-2xs"
                      : "border-transparent text-slate-600 hover:bg-slate-200/50 hover:text-[#0F172A]"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  <span>{tab.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums ${
                      selected
                        ? "bg-[#EFF6FF] text-[#1D4ED8]"
                        : "bg-slate-200 text-slate-600"
                    }`}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Filter Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E2E8F0] px-4 py-4 sm:px-6">
          <div className="relative w-full sm:max-w-xs">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
              aria-hidden="true"
            />
            <input
              type="search"
              aria-label="Cari data"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={
                activeTab === "students"
                  ? "Cari nama, NIS, atau orang tua..."
                  : activeTab === "parents"
                    ? "Cari nama atau nomor WhatsApp..."
                    : activeTab === "classes"
                      ? "Cari nama kelas atau wali kelas..."
                      : "Cari mapel, guru, atau kelas..."
              }
              className="w-full rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] py-2 pl-9 pr-3 text-sm focus:border-[#1D4ED8] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#1D4ED8]/20"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {(activeTab === "students" || activeTab === "schedules") && (
              <select
                aria-label="Filter kelas"
                value={classFilter}
                onChange={(e) => setClassFilter(e.target.value)}
                className="rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-slate-700 focus:border-[#1D4ED8] focus:outline-none"
              >
                <option value="">Semua Kelas</option>
                {classes.map((cls) => (
                  <option key={cls.id} value={cls.id}>
                    {cls.name}
                  </option>
                ))}
              </select>
            )}

            {activeTab === "schedules" && (
              <select
                aria-label="Filter hari"
                value={dayFilter}
                onChange={(e) => setDayFilter(e.target.value)}
                className="rounded-xl border border-[#E2E8F0] bg-white px-3 py-2 text-xs font-semibold text-slate-700 focus:border-[#1D4ED8] focus:outline-none"
              >
                <option value="">Semua Hari</option>
                {Object.entries(DAY_NAMES_ID).map(([num, label]) => (
                  <option key={num} value={num}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Tab Tables */}
        <div className="overflow-x-auto">
          {activeTab === "students" ? (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
                <tr>
                  <th className="px-6 py-3.5">NIS</th>
                  <th className="px-4 py-3.5">Nama Siswa</th>
                  <th className="px-4 py-3.5">Kelas</th>
                  <th className="px-4 py-3.5">Orang Tua & WhatsApp</th>
                  <th className="px-4 py-3.5">Dataset Wajah</th>
                  <th className="px-4 py-3.5">Status</th>
                  <th className="px-6 py-3.5 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-10 text-center text-sm text-slate-500">
                      Memuat data siswa...
                    </td>
                  </tr>
                ) : filteredStudents.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-10 text-center text-sm text-slate-500">
                      Tidak ada data siswa yang cocok dengan filter.
                    </td>
                  </tr>
                ) : (
                  filteredStudents.map((student) => (
                    <tr key={student.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-6 py-3.5 font-mono text-xs font-semibold text-slate-700">
                        {student.nis}
                      </td>
                      <td className="px-4 py-3.5 font-semibold text-[#0F172A]">
                        {student.name}
                      </td>
                      <td className="px-4 py-3.5">
                        <StatusBadge tone="primary">{student.class_name}</StatusBadge>
                      </td>
                      <td className="px-4 py-3.5">
                        <p className="text-xs font-semibold text-[#0F172A]">
                          {student.parent_name}
                        </p>
                        <p className="font-mono text-[11px] text-[#059669]">
                          {formatWaPhoneDisplay(student.parent_phone_wa)}
                        </p>
                      </td>
                      <td className="px-4 py-3.5">
                        <Link
                          href={`/faces?studentId=${encodeURIComponent(student.id)}`}
                          className="inline-flex items-center gap-1.5 hover:opacity-80"
                        >
                          <StatusBadge
                            tone={
                              student.face_count >= 3
                                ? "success"
                                : student.face_count > 0
                                  ? "warning"
                                  : "danger"
                            }
                          >
                            <ScanFace className="h-3 w-3" aria-hidden="true" />
                            <span>{student.face_count}/5 Foto</span>
                          </StatusBadge>
                        </Link>
                      </td>
                      <td className="px-4 py-3.5">
                        <StatusBadge tone={student.is_active ? "success" : "neutral"}>
                          {student.is_active ? "Aktif" : "Nonaktif"}
                        </StatusBadge>
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() =>
                              setModalMode({ type: "student", item: student })
                            }
                            aria-label={`Edit ${student.name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:bg-slate-100 hover:text-[#1D4ED8]"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setDeleteTarget({
                                type: "students",
                                id: student.id,
                                label: student.name,
                              })
                            }
                            aria-label={`Hapus ${student.name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:border-red-200 hover:bg-[#FEF2F2] hover:text-[#DC2626]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          ) : activeTab === "parents" ? (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
                <tr>
                  <th className="px-6 py-3.5">Nama Orang Tua / Wali</th>
                  <th className="px-4 py-3.5">Nomor WhatsApp Kanonis</th>
                  <th className="px-4 py-3.5">Siswa Terhubung</th>
                  <th className="px-4 py-3.5">Terdaftar Sejak</th>
                  <th className="px-6 py-3.5 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-sm text-slate-500">
                      Memuat data orang tua...
                    </td>
                  </tr>
                ) : filteredParents.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-sm text-slate-500">
                      Belum ada data orang tua yang sesuai.
                    </td>
                  </tr>
                ) : (
                  filteredParents.map((parent) => {
                    const linked = students.filter((s) => s.parent_id === parent.id);
                    return (
                      <tr key={parent.id} className="hover:bg-[#F8FAFC]">
                        <td className="px-6 py-3.5 font-semibold text-[#0F172A]">
                          {parent.name}
                        </td>
                        <td className="px-4 py-3.5">
                          <StatusBadge tone="success">
                            <span className="font-mono">
                              {formatWaPhoneDisplay(parent.phone_wa)}
                            </span>
                          </StatusBadge>
                        </td>
                        <td className="px-4 py-3.5 text-xs text-slate-600">
                          {linked.length > 0
                            ? linked.map((s) => `${s.name} (${s.class_name})`).join(", ")
                            : "Belum terhubung siswa"}
                        </td>
                        <td className="px-4 py-3.5 text-xs text-slate-500">
                          {formatWibDateTime(parent.created_at)}
                        </td>
                        <td className="px-6 py-3.5 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() =>
                                setModalMode({ type: "parent", item: parent })
                              }
                              aria-label={`Edit ${parent.name}`}
                              className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:bg-slate-100 hover:text-[#1D4ED8]"
                            >
                              <Edit3 className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                setDeleteTarget({
                                  type: "parents",
                                  id: parent.id,
                                  label: parent.name,
                                })
                              }
                              aria-label={`Hapus ${parent.name}`}
                              className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:border-red-200 hover:bg-[#FEF2F2] hover:text-[#DC2626]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          ) : activeTab === "classes" ? (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
                <tr>
                  <th className="px-6 py-3.5">Nama Kelas</th>
                  <th className="px-4 py-3.5">Wali Kelas</th>
                  <th className="px-4 py-3.5">Jumlah Siswa</th>
                  <th className="px-4 py-3.5">Dibuat Pada</th>
                  <th className="px-6 py-3.5 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-sm text-slate-500">
                      Memuat data kelas...
                    </td>
                  </tr>
                ) : filteredClasses.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-10 text-center text-sm text-slate-500">
                      Belum ada data kelas yang sesuai.
                    </td>
                  </tr>
                ) : (
                  filteredClasses.map((cls) => (
                    <tr key={cls.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-6 py-3.5 font-bold text-[#0F172A]">
                        {cls.name}
                      </td>
                      <td className="px-4 py-3.5 text-xs text-slate-600">
                        {cls.homeroom_teacher_name || "Belum ditentukan"}
                      </td>
                      <td className="px-4 py-3.5">
                        <StatusBadge tone="primary">
                          {cls.student_count} Siswa
                        </StatusBadge>
                      </td>
                      <td className="px-4 py-3.5 text-xs text-slate-500">
                        {formatWibDateTime(cls.created_at)}
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() =>
                              setModalMode({ type: "class", item: cls })
                            }
                            aria-label={`Edit ${cls.name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:bg-slate-100 hover:text-[#1D4ED8]"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setDeleteTarget({
                                type: "classes",
                                id: cls.id,
                                label: cls.name,
                              })
                            }
                            aria-label={`Hapus ${cls.name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:border-red-200 hover:bg-[#FEF2F2] hover:text-[#DC2626]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC] text-xs font-semibold text-slate-500">
                <tr>
                  <th className="px-6 py-3.5">Hari</th>
                  <th className="px-4 py-3.5">Jam</th>
                  <th className="px-4 py-3.5">Kelas</th>
                  <th className="px-4 py-3.5">Mata Pelajaran</th>
                  <th className="px-4 py-3.5">Guru Pengampu</th>
                  <th className="px-4 py-3.5">Toleransi</th>
                  <th className="px-6 py-3.5 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-10 text-center text-sm text-slate-500">
                      Memuat jadwal pelajaran...
                    </td>
                  </tr>
                ) : filteredSchedules.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-10 text-center text-sm text-slate-500">
                      Tidak ada jadwal pelajaran yang sesuai filter.
                    </td>
                  </tr>
                ) : (
                  filteredSchedules.map((sch) => (
                    <tr key={sch.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-6 py-3.5 font-semibold text-[#0F172A]">
                        {formatDayOfWeek(sch.day_of_week)}
                      </td>
                      <td className="px-4 py-3.5 font-mono text-xs text-slate-700">
                        {formatTimeShort(sch.start_time)} –{" "}
                        {formatTimeShort(sch.end_time)}
                      </td>
                      <td className="px-4 py-3.5">
                        <StatusBadge tone="primary">{sch.class_name}</StatusBadge>
                      </td>
                      <td className="px-4 py-3.5 font-semibold text-[#0F172A]">
                        {sch.subject_name}
                      </td>
                      <td className="px-4 py-3.5 text-xs text-slate-600">
                        {sch.teacher_name}
                      </td>
                      <td className="px-4 py-3.5 text-xs text-slate-600 tabular-nums">
                        {sch.late_tolerance_minutes} menit
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() =>
                              setModalMode({ type: "schedule", item: sch })
                            }
                            aria-label={`Edit ${sch.subject_name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:bg-slate-100 hover:text-[#1D4ED8]"
                          >
                            <Edit3 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              setDeleteTarget({
                                type: "schedules",
                                id: sch.id,
                                label: `${sch.subject_name} (${sch.class_name})`,
                              })
                            }
                            aria-label={`Hapus ${sch.subject_name}`}
                            className="rounded-lg border border-[#E2E8F0] p-1.5 text-slate-600 hover:border-red-200 hover:bg-[#FEF2F2] hover:text-[#DC2626]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Create / Edit Modals */}
      {modalMode?.type === "student" ? (
        <StudentFormModal
          key={modalMode.item?.id ?? "new-student"}
          open
          editing={modalMode.item}
          classes={classes}
          parents={parents}
          onClose={() => setModalMode(null)}
          onSaved={handleSaved}
        />
      ) : null}

      {modalMode?.type === "parent" ? (
        <ParentFormModal
          key={modalMode.item?.id ?? "new-parent"}
          open
          editing={modalMode.item}
          onClose={() => setModalMode(null)}
          onSaved={handleSaved}
        />
      ) : null}

      {modalMode?.type === "class" ? (
        <ClassFormModal
          key={modalMode.item?.id ?? "new-class"}
          open
          editing={modalMode.item}
          teachers={knownTeachers}
          onClose={() => setModalMode(null)}
          onSaved={handleSaved}
        />
      ) : null}

      {modalMode?.type === "schedule" ? (
        <ScheduleFormModal
          key={modalMode.item?.id ?? "new-schedule"}
          open
          editing={modalMode.item}
          classes={classes}
          teachers={knownTeachers}
          onClose={() => setModalMode(null)}
          onSaved={handleSaved}
        />
      ) : null}

      {/* Delete Confirmation Modal */}
      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Konfirmasi Hapus Data"
        subtitle="Tindakan ini permanen apabila tidak terikat relasi presensi."
        maxWidthClass="max-w-md"
      >
        <div className="space-y-5">
          <p className="text-sm text-slate-600">
            Apakah Anda yakin ingin menghapus{" "}
            <strong className="text-[#0F172A]">{deleteTarget?.label}</strong>?
          </p>
          <div className="flex justify-end gap-2.5">
            <button
              type="button"
              onClick={() => setDeleteTarget(null)}
              className="rounded-xl border border-[#E2E8F0] px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Batal
            </button>
            <button
              type="button"
              disabled={deleting}
              onClick={() => void handleConfirmDelete()}
              className="rounded-xl bg-[#EF4444] px-4 py-2 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-60"
            >
              {deleting ? "Menghapus..." : "Ya, Hapus"}
            </button>
          </div>
        </div>
      </Modal>
    </AdminShell>
  );
}
