import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';
import 'home_screen.dart';

/// Layar 03 Figma: Detail Sesi Presensi, CTA Mode Kiosk, Daftar Siswa & Aksi Guru.
class SessionDetailScreen extends StatefulWidget {
  const SessionDetailScreen({
    super.key,
    required this.apiClient,
    required this.sessionId,
    this.kioskScannerBuilder,
    this.pinPromptBuilder,
  });

  final ApiClient apiClient;
  final String sessionId;
  final KioskScannerBuilder? kioskScannerBuilder;
  final ManualPinPromptBuilder? pinPromptBuilder;

  @override
  State<SessionDetailScreen> createState() => _SessionDetailScreenState();
}

class _SessionDetailScreenState extends State<SessionDetailScreen> {
  SessionDetail? _detail;
  bool _isLoading = true;
  bool _isMutating = false;
  String? _errorMessage;
  String _statusFilter = 'all';
  String _searchQuery = '';
  final Set<String> _resendingIds = {};

  @override
  void initState() {
    super.initState();
    _loadSessionDetail();
  }

  Future<void> _loadSessionDetail() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final detail = await widget.apiClient.getSessionDetail(widget.sessionId);
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _isLoading = false;
      });
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = exc.message;
        _isLoading = false;
      });
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Gagal memuat detail sesi: $exc';
        _isLoading = false;
      });
    }
  }

  Future<void> _launchKioskMode() async {
    final detail = _detail;
    if (detail == null) return;

    if (!detail.isOpen) {
      _showSnackBar('Sesi sudah ditutup. Buka sesi baru untuk memindai wajah.', isError: true);
      return;
    }

    if (widget.kioskScannerBuilder == null) {
      _showSnackBar('Mode Kiosk kamera belum terhubung pada build ini.');
      return;
    }

    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (ctx) => widget.kioskScannerBuilder!(ctx, detail, _loadSessionDetail),
      ),
    );
    if (mounted) {
      await _loadSessionDetail();
    }
  }

  Future<void> _openManualAttendanceModal({StudentAttendanceItem? presetStudent}) async {
    final detail = _detail;
    if (detail == null) return;

    if (detail.students.isEmpty) {
      _showSnackBar('Belum ada daftar siswa di sesi ini untuk input manual.', isError: true);
      return;
    }

    final selection = await showDialog<_ManualAttendanceSelection>(
      context: context,
      builder: (dialogContext) => _ManualAttendanceDialog(
        students: detail.students,
        presetStudent: presetStudent,
        requireInlinePin: widget.pinPromptBuilder == null,
      ),
    );

    if (selection == null || !mounted) return;

    String? pin = selection.inlinePin;
    if (widget.pinPromptBuilder != null) {
      pin = await widget.pinPromptBuilder!(
        context,
        title: 'Konfirmasi Absen Manual',
        subtitle:
            'Masukkan PIN Kiosk Guru untuk mencatat status "${AppFormatters.attendanceStatusLabel(selection.status)}" bagi ${selection.studentName}.',
        confirmLabel: 'Konfirmasi Absen Manual',
      );
      if (pin == null || pin.isEmpty || !mounted) return;
    }

    if (pin == null || pin.isEmpty) return;

    setState(() => _isMutating = true);
    try {
      final result = await widget.apiClient.submitManualAttendance(
        sessionId: detail.id,
        studentId: selection.studentId,
        status: selection.status,
        kioskPin: pin,
        notifyWa: selection.notifyWa,
      );
      if (!mounted) return;
      _showSnackBar(result.message);
      await _loadSessionDetail();
    } on ApiException catch (exc) {
      if (!mounted) return;
      _showSnackBar(exc.message, isError: true);
    } finally {
      if (mounted) {
        setState(() => _isMutating = false);
      }
    }
  }

  Future<void> _confirmCloseSession() async {
    final detail = _detail;
    if (detail == null || !detail.isOpen) return;

    final unrecorded = detail.summary.unrecordedCount;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Tutup Sesi Kelas?'),
          content: Text(
            unrecorded > 0
                ? 'Masih ada $unrecorded siswa yang belum tercatat. Menutup sesi akan otomatis menandai mereka sebagai ALFA dan menghentikan scan Kiosk.'
                : 'Semua siswa telah tercatat. Menutup sesi akan mengunci presensi kelas ini.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Batal'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: AppColors.danger),
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('Ya, Tutup Sesi'),
            ),
          ],
        );
      },
    );

    if (confirmed != true || !mounted) return;

    setState(() => _isMutating = true);
    try {
      final updated = await widget.apiClient.closeSession(detail.id);
      if (!mounted) return;
      setState(() => _detail = updated);
      _showSnackBar('Sesi presensi berhasil ditutup.');
    } on ApiException catch (exc) {
      if (!mounted) return;
      _showSnackBar(exc.message, isError: true);
    } finally {
      if (mounted) {
        setState(() => _isMutating = false);
      }
    }
  }

  Future<void> _resendWa(StudentAttendanceItem item) async {
    final attendanceId = item.attendanceId;
    if (attendanceId == null || _resendingIds.contains(attendanceId)) return;

    setState(() => _resendingIds.add(attendanceId));
    try {
      final res = await widget.apiClient.resendWa(attendanceId);
      if (!mounted) return;
      _showSnackBar(res.message, isError: !res.waSent);
      await _loadSessionDetail();
    } on ApiException catch (exc) {
      if (!mounted) return;
      _showSnackBar(exc.message, isError: true);
    } finally {
      if (mounted) {
        setState(() => _resendingIds.remove(attendanceId));
      }
    }
  }

  void _showSnackBar(String message, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? AppColors.danger : AppColors.success,
      ),
    );
  }

  List<StudentAttendanceItem> _filteredStudents(SessionDetail detail) {
    final query = _searchQuery.trim().toLowerCase();
    return detail.students.where((student) {
      if (_statusFilter == 'permit_sick') {
        if (student.status != 'permit' && student.status != 'sick') return false;
      } else if (_statusFilter != 'all' && student.status != _statusFilter) {
        return false;
      }

      if (query.isEmpty) return true;
      return student.studentName.toLowerCase().contains(query) ||
          student.nis.toLowerCase().contains(query);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final detail = _detail;

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text(detail?.displayTitle ?? 'Detail Sesi Presensi'),
        actions: [
          IconButton(
            tooltip: 'Muat Ulang',
            onPressed: _isLoading ? null : _loadSessionDetail,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: _isLoading && detail == null
          ? const Center(child: CircularProgressIndicator())
          : detail == null
              ? _buildErrorState()
              : RefreshIndicator(
                  onRefresh: _loadSessionDetail,
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                    children: [
                      _buildSessionHeaderCard(detail),
                      const SizedBox(height: 14),
                      _buildKioskCtaButton(detail),
                      const SizedBox(height: 14),
                      _buildSummaryStrip(detail.summary),
                      const SizedBox(height: 14),
                      _buildSearchAndFilterBar(),
                      const SizedBox(height: 12),
                      ..._buildStudentList(detail),
                    ],
                  ),
                ),
      bottomNavigationBar: detail == null || !detail.isOpen
          ? null
          : SafeArea(
              child: Container(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                decoration: const BoxDecoration(
                  color: AppColors.card,
                  border: Border(top: BorderSide(color: AppColors.border)),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _isMutating ? null : () => _openManualAttendanceModal(),
                        icon: const Icon(Icons.edit_note_rounded, size: 20),
                        label: const Text('Input Manual (PIN)'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.danger,
                        ),
                        onPressed: _isMutating ? null : _confirmCloseSession,
                        icon: const Icon(Icons.lock_clock_outlined, size: 18),
                        label: const Text('Tutup Sesi Kelas'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 42, color: AppColors.danger),
            const SizedBox(height: 12),
            Text(
              _errorMessage ?? 'Sesi tidak ditemukan.',
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textPrimary),
            ),
            const SizedBox(height: 14),
            ElevatedButton(
              onPressed: _loadSessionDetail,
              child: const Text('Muat Ulang'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSessionHeaderCard(SessionDetail detail) {
    final isOpen = detail.isOpen;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  detail.displayClassName,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: isOpen ? AppColors.successTint : const Color(0xFFF1F5F9),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  isOpen ? 'SESI AKTIF' : 'SESI DITUTUP',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                    color: isOpen ? AppColors.success : AppColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${AppFormatters.sessionTypeLabel(detail.sessionType)} • ${AppFormatters.formatIndonesianDate(detail.sessionDate)}',
            style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 10,
            runSpacing: 6,
            children: [
              _InfoPill(
                icon: Icons.schedule_rounded,
                label: detail.expectedStartTime != null
                    ? 'Mulai ${AppFormatters.formatTimeShort(detail.expectedStartTime)} WIB'
                    : 'Dibuka ${AppFormatters.formatWibTime(detail.openedAt)}',
              ),
              _InfoPill(
                icon: Icons.timer_outlined,
                label: 'Toleransi telat ${detail.lateToleranceMinutes} mnt',
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildKioskCtaButton(SessionDetail detail) {
    return SizedBox(
      width: double.infinity,
      height: 54,
      child: ElevatedButton.icon(
        style: ElevatedButton.styleFrom(
          backgroundColor: detail.isOpen ? AppColors.primary : AppColors.textMuted,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
        onPressed: detail.isOpen ? _launchKioskMode : null,
        icon: const Icon(Icons.face_retouching_natural_rounded, size: 22),
        label: const Text(
          'Mulai Mode Kiosk Scan Wajah →',
          style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700),
        ),
      ),
    );
  }

  Widget _buildSummaryStrip(SessionSummaryCounters summary) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _SummaryCounterChip(
            label: 'Hadir',
            count: summary.presentCount,
            fg: AppColors.success,
            bg: AppColors.successTint,
          ),
          const SizedBox(width: 8),
          _SummaryCounterChip(
            label: 'Telat',
            count: summary.lateCount,
            fg: AppColors.warning,
            bg: AppColors.warningTint,
          ),
          const SizedBox(width: 8),
          _SummaryCounterChip(
            label: 'Izin/Sakit',
            count: summary.permitOrSickCount,
            fg: AppColors.primary,
            bg: AppColors.primaryTint,
          ),
          const SizedBox(width: 8),
          _SummaryCounterChip(
            label: 'Alfa',
            count: summary.absentCount,
            fg: AppColors.danger,
            bg: AppColors.dangerTint,
          ),
          const SizedBox(width: 8),
          _SummaryCounterChip(
            label: 'Belum',
            count: summary.unrecordedCount,
            fg: AppColors.textSecondary,
            bg: const Color(0xFFF1F5F9),
          ),
        ],
      ),
    );
  }

  Widget _buildSearchAndFilterBar() {
    const filters = [
      (key: 'all', label: 'Semua'),
      (key: 'present', label: 'Hadir'),
      (key: 'late', label: 'Telat'),
      (key: 'permit_sick', label: 'Izin/Sakit'),
      (key: 'unrecorded', label: 'Belum'),
      (key: 'absent', label: 'Alfa'),
    ];

    return Column(
      children: [
        TextField(
          onChanged: (value) => setState(() => _searchQuery = value),
          decoration: const InputDecoration(
            hintText: 'Cari nama siswa atau NIS...',
            prefixIcon: Icon(Icons.search_rounded),
          ),
        ),
        const SizedBox(height: 10),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: filters.map((f) {
              final selected = _statusFilter == f.key;
              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(f.label),
                  selected: selected,
                  selectedColor: AppColors.primaryTint,
                  labelStyle: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: selected ? AppColors.primary : AppColors.textSecondary,
                  ),
                  onSelected: (_) => setState(() => _statusFilter = f.key),
                ),
              );
            }).toList(),
          ),
        ),
      ],
    );
  }

  List<Widget> _buildStudentList(SessionDetail detail) {
    final students = _filteredStudents(detail);
    if (students.isEmpty) {
      return [
        Container(
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            color: AppColors.card,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppColors.border),
          ),
          child: const Text(
            'Belum ada data siswa yang sesuai dengan filter.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textSecondary),
          ),
        ),
      ];
    }

    return students
        .map(
          (student) => Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _StudentAttendanceTile(
              item: student,
              isSessionOpen: detail.isOpen,
              isResending: student.attendanceId != null &&
                  _resendingIds.contains(student.attendanceId),
              onResendWa: () => _resendWa(student),
              onTapManual: detail.isOpen
                  ? () => _openManualAttendanceModal(presetStudent: student)
                  : null,
            ),
          ),
        )
        .toList();
  }
}

class _InfoPill extends StatelessWidget {
  const _InfoPill({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: AppColors.background,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: AppColors.textSecondary),
          const SizedBox(width: 5),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _SummaryCounterChip extends StatelessWidget {
  const _SummaryCounterChip({
    required this.label,
    required this.count,
    required this.fg,
    required this.bg,
  });

  final String label;
  final int count;
  final Color fg;
  final Color bg;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$count',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: fg),
          ),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: fg),
          ),
        ],
      ),
    );
  }
}

class _StudentAttendanceTile extends StatelessWidget {
  const _StudentAttendanceTile({
    required this.item,
    required this.isSessionOpen,
    required this.isResending,
    required this.onResendWa,
    this.onTapManual,
  });

  final StudentAttendanceItem item;
  final bool isSessionOpen;
  final bool isResending;
  final VoidCallback onResendWa;
  final VoidCallback? onTapManual;

  @override
  Widget build(BuildContext context) {
    final statusColors = AppFormatters.attendanceStatusColors(item.status);
    final statusLabel = AppFormatters.attendanceStatusLabel(item.status);

    return InkWell(
      onTap: onTapManual,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 20,
                  backgroundColor: statusColors.bg,
                  child: Text(
                    AppFormatters.initials(item.studentName),
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: statusColors.fg,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.studentName,
                        style: const TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        'NIS ${item.nis} • ${item.scannedAt != null ? AppFormatters.formatWibTime(item.scannedAt) : AppFormatters.verificationMethodLabel(item.verificationMethod)}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: statusColors.bg,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    statusLabel,
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: statusColors.fg,
                    ),
                  ),
                ),
              ],
            ),
            if (item.waStatus != null) ...[
              const SizedBox(height: 10),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  _buildWaBadge(),
                  if (item.waStatus == 'failed' && item.attendanceId != null)
                    TextButton.icon(
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        minimumSize: Size.zero,
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      onPressed: isResending ? null : onResendWa,
                      icon: isResending
                          ? const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.refresh_rounded, size: 15),
                      label: const Text(
                        'Kirim Ulang WA',
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildWaBadge() {
    switch (item.waStatus) {
      case 'sent':
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
          decoration: BoxDecoration(
            color: AppColors.successTint,
            borderRadius: BorderRadius.circular(999),
          ),
          child: const Text(
            'WA Ortu ✓',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppColors.success,
            ),
          ),
        );
      case 'failed':
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
          decoration: BoxDecoration(
            color: AppColors.dangerTint,
            borderRadius: BorderRadius.circular(999),
          ),
          child: const Text(
            'WA Gagal Terkirim',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppColors.danger,
            ),
          ),
        );
      case 'pending':
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
          decoration: BoxDecoration(
            color: AppColors.warningTint,
            borderRadius: BorderRadius.circular(999),
          ),
          child: const Text(
            'WA Menunggu',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppColors.warning,
            ),
          ),
        );
      default:
        return const Text(
          'Tanpa Notifikasi WA',
          style: TextStyle(fontSize: 11, color: AppColors.textMuted),
        );
    }
  }
}

class _ManualAttendanceSelection {
  const _ManualAttendanceSelection({
    required this.studentId,
    required this.studentName,
    required this.status,
    required this.notifyWa,
    this.inlinePin,
  });

  final String studentId;
  final String studentName;
  final String status;
  final bool notifyWa;
  final String? inlinePin;
}

class _ManualAttendanceDialog extends StatefulWidget {
  const _ManualAttendanceDialog({
    required this.students,
    required this.requireInlinePin,
    this.presetStudent,
  });

  final List<StudentAttendanceItem> students;
  final bool requireInlinePin;
  final StudentAttendanceItem? presetStudent;

  @override
  State<_ManualAttendanceDialog> createState() => _ManualAttendanceDialogState();
}

class _ManualAttendanceDialogState extends State<_ManualAttendanceDialog> {
  late String _selectedStudentId;
  late String _selectedStatus;
  bool _notifyWa = true;
  final _pinController = TextEditingController();
  String? _error;

  @override
  void initState() {
    super.initState();
    final initialStudent = widget.presetStudent ?? widget.students.first;
    _selectedStudentId = initialStudent.studentId;
    _selectedStatus =
        initialStudent.status == 'unrecorded' ? 'present' : initialStudent.status;
  }

  @override
  void dispose() {
    _pinController.dispose();
    super.dispose();
  }

  void _confirm() {
    if (widget.requireInlinePin) {
      final pin = _pinController.text.trim();
      if (!RegExp(r'^\d{4,6}$').hasMatch(pin)) {
        setState(() => _error = 'Masukkan PIN Kiosk 4–6 digit angka.');
        return;
      }
    }

    final student = widget.students.firstWhere((s) => s.studentId == _selectedStudentId);
    Navigator.of(context).pop(
      _ManualAttendanceSelection(
        studentId: _selectedStudentId,
        studentName: student.studentName,
        status: _selectedStatus,
        notifyWa: _notifyWa,
        inlinePin: widget.requireInlinePin ? _pinController.text.trim() : null,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Input Presensi Manual'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_error != null) ...[
              Text(
                _error!,
                style: const TextStyle(color: AppColors.danger, fontSize: 12.5),
              ),
              const SizedBox(height: 10),
            ],
            DropdownButtonFormField<String>(
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
                if (val != null) setState(() => _selectedStudentId = val);
              },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
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
            if (widget.requireInlinePin) ...[
              const SizedBox(height: 8),
              TextField(
                controller: _pinController,
                obscureText: true,
                maxLength: 6,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(
                  labelText: 'PIN Kiosk Guru',
                  hintText: '4–6 digit angka',
                  counterText: '',
                  prefixIcon: Icon(Icons.pin_outlined),
                ),
              ),
            ],
          ],
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
