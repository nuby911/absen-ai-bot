import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';

/// Data pilihan guru pada modal input presensi manual.
class ManualAttendanceSelection {
  const ManualAttendanceSelection({
    required this.studentId,
    required this.studentName,
    required this.status,
    required this.notifyWa,
  });

  final String studentId;
  final String studentName;
  final String status;
  final bool notifyWa;
}

/// Memuat daftar kandidat siswa untuk input manual.
/// Pada sesi Gerbang Umum (`classId == null`), menggabungkan `detail.students`
/// dengan seluruh siswa aktif dari `GET /api/v1/students?is_active=true`.
Future<List<StudentAttendanceItem>> loadManualAttendanceCandidates(
  ApiClient apiClient,
  SessionDetail detail,
) async {
  final merged = <String, StudentAttendanceItem>{
    for (final item in detail.students) item.studentId: item,
  };

  if (detail.classId == null) {
    try {
      final activeStudents = await apiClient.getStudents(isActive: true);
      for (final student in activeStudents) {
        merged.putIfAbsent(
          student.id,
          () => student.toUnrecordedAttendanceItem(),
        );
      }
    } catch (_) {
      if (merged.isEmpty) rethrow;
    }
  }

  final list = merged.values.toList()
    ..sort(
      (a, b) => a.studentName.toLowerCase().compareTo(b.studentName.toLowerCase()),
    );
  return list;
}

/// Modal input presensi manual dengan dukungan pencarian siswa (termasuk Gerbang Umum).
class ManualAttendanceDialog extends StatefulWidget {
  const ManualAttendanceDialog({
    super.key,
    required this.students,
    this.presetStudent,
    this.isGeneralGate = false,
  });

  final List<StudentAttendanceItem> students;
  final StudentAttendanceItem? presetStudent;
  final bool isGeneralGate;

  @override
  State<ManualAttendanceDialog> createState() => _ManualAttendanceDialogState();
}

class _ManualAttendanceDialogState extends State<ManualAttendanceDialog> {
  late String _selectedStudentId;
  late String _selectedStatus;
  bool _notifyWa = true;
  String _searchQuery = '';

  @override
  void initState() {
    super.initState();
    final initialStudent = widget.presetStudent ?? widget.students.first;
    _selectedStudentId = initialStudent.studentId;
    _selectedStatus = _resolveInitialStatus(initialStudent);
  }

  String _resolveInitialStatus(StudentAttendanceItem student) {
    const validManualStatuses = {'present', 'late', 'permit', 'sick', 'absent'};
    if (validManualStatuses.contains(student.status)) {
      return student.status;
    }
    return 'present';
  }

  void _selectStudent(StudentAttendanceItem student) {
    setState(() {
      _selectedStudentId = student.studentId;
      _selectedStatus = _resolveInitialStatus(student);
    });
  }

  List<StudentAttendanceItem> _filteredStudents() {
    final query = _searchQuery.trim().toLowerCase();
    if (query.isEmpty) return widget.students;
    return widget.students.where((s) {
      return s.studentName.toLowerCase().contains(query) ||
          s.nis.toLowerCase().contains(query) ||
          s.className.toLowerCase().contains(query);
    }).toList();
  }

  void _confirm() {
    final student = widget.students.firstWhere(
      (s) => s.studentId == _selectedStudentId,
      orElse: () => widget.students.first,
    );
    Navigator.of(context).pop(
      ManualAttendanceSelection(
        studentId: student.studentId,
        studentName: student.studentName,
        status: _selectedStatus,
        notifyWa: _notifyWa,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final useSearchablePicker = widget.isGeneralGate || widget.students.length > 8;
    final filtered = _filteredStudents();
    final selectedStudent = widget.students.firstWhere(
      (s) => s.studentId == _selectedStudentId,
      orElse: () => widget.students.first,
    );

    return AlertDialog(
      title: const Text('Input Presensi Manual'),
      content: SizedBox(
        width: double.maxFinite,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (useSearchablePicker) ...[
                TextField(
                  key: const Key('manual_student_search_field'),
                  onChanged: (value) => setState(() => _searchQuery = value),
                  decoration: InputDecoration(
                    labelText: widget.isGeneralGate
                        ? 'Cari Siswa Aktif (Nama / NIS / Kelas)'
                        : 'Cari Siswa (Nama / NIS)',
                    prefixIcon: const Icon(Icons.search_rounded),
                    isDense: true,
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                  decoration: BoxDecoration(
                    color: AppColors.primaryTint,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    'Dipilih: ${selectedStudent.studentName} (${selectedStudent.className} • ${selectedStudent.nis})',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.primary,
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  constraints: const BoxConstraints(maxHeight: 190),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: filtered.isEmpty
                      ? const Padding(
                          padding: EdgeInsets.all(16),
                          child: Text(
                            'Siswa tidak ditemukan.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 12.5,
                              color: AppColors.textSecondary,
                            ),
                          ),
                        )
                      : ListView.separated(
                          shrinkWrap: true,
                          itemCount: filtered.length,
                          separatorBuilder: (_, _) => const Divider(height: 1),
                          itemBuilder: (ctx, idx) {
                            final item = filtered[idx];
                            final isSelected = item.studentId == _selectedStudentId;
                            final statusColors =
                                AppFormatters.attendanceStatusColors(item.status);
                            return ListTile(
                              dense: true,
                              selected: isSelected,
                              selectedTileColor: AppColors.primaryTint,
                              onTap: () => _selectStudent(item),
                              title: Text(
                                item.studentName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              subtitle: Text(
                                '${item.className} • NIS ${item.nis}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 11.5),
                              ),
                              trailing: Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 7,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: statusColors.bg,
                                  borderRadius: BorderRadius.circular(999),
                                ),
                                child: Text(
                                  AppFormatters.attendanceStatusLabel(item.status),
                                  style: TextStyle(
                                    fontSize: 10.5,
                                    fontWeight: FontWeight.w700,
                                    color: statusColors.fg,
                                  ),
                                ),
                              ),
                            );
                          },
                        ),
                ),
              ] else
                DropdownButtonFormField<String>(
                  key: ValueKey('manual_student_$_selectedStudentId'),
                  initialValue: _selectedStudentId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Pilih Siswa'),
                  items: widget.students
                      .map(
                        (s) => DropdownMenuItem<String>(
                          value: s.studentId,
                          child: Text(
                            '${s.studentName} (${s.nis})',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: (val) {
                    if (val == null) return;
                    final match = widget.students.where((s) => s.studentId == val);
                    if (match.isNotEmpty) {
                      _selectStudent(match.first);
                    }
                  },
                ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                key: ValueKey('manual_status_$_selectedStatus'),
                initialValue: _selectedStatus,
                decoration: const InputDecoration(labelText: 'Status Kehadiran'),
                items: const [
                  DropdownMenuItem(value: 'present', child: Text('Hadir')),
                  DropdownMenuItem(value: 'late', child: Text('Terlambat')),
                  DropdownMenuItem(value: 'permit', child: Text('Izin')),
                  DropdownMenuItem(value: 'sick', child: Text('Sakit')),
                  DropdownMenuItem(value: 'absent', child: Text('Alfa')),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _selectedStatus = val);
                },
              ),
              const SizedBox(height: 10),
              CheckboxListTile(
                value: _notifyWa,
                contentPadding: EdgeInsets.zero,
                title: const Text(
                  'Kirim notifikasi WhatsApp ke orang tua',
                  style: TextStyle(fontSize: 13),
                ),
                onChanged: (val) => setState(() => _notifyWa = val ?? true),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Batal'),
        ),
        ElevatedButton(
          onPressed: _confirm,
          child: const Text('Simpan Presensi'),
        ),
      ],
    );
  }
}
