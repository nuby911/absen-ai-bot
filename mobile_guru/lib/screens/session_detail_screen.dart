import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../widgets/kiosk_pin_setup_dialog.dart';
import '../widgets/kiosk_pin_sheet.dart';
import '../widgets/manual_attendance_dialog.dart';
import 'home_screen.dart';
import 'kiosk_scanner_screen.dart';

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
      final stillHasWaFailed =
          detail.students.any((student) => student.waStatus == 'failed');
      setState(() {
        _detail = detail;
        if (_statusFilter == 'wa_failed' && !stillHasWaFailed) {
          _statusFilter = 'all';
        }
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
      _showSnackBar(
        'Sesi sudah ditutup. Buka sesi baru untuk memindai wajah.',
        isError: true,
      );
      return;
    }

    final hasPin = await KioskPinSetupDialog.ensureKioskPin(
      context,
      widget.apiClient,
    );
    if (!hasPin || !mounted) return;

    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (ctx) => widget.kioskScannerBuilder != null
            ? widget.kioskScannerBuilder!(ctx, detail, _loadSessionDetail)
            : KioskScannerScreen(
                apiClient: widget.apiClient,
                session: detail,
                onAttendanceRecorded: _loadSessionDetail,
              ),
      ),
    );
    if (mounted) {
      await _loadSessionDetail();
    }
  }

  Future<String?> _defaultPinPrompt(
    BuildContext context, {
    required String title,
    required String subtitle,
    required String confirmLabel,
  }) {
    return KioskPinSheet.show(
      context,
      title: title,
      subtitle: subtitle,
      confirmLabel: confirmLabel,
      cancelLabel: 'Batal',
      onVerify: widget.apiClient.verifyKioskPin,
    );
  }

  Future<void> _openManualAttendanceModal({
    StudentAttendanceItem? presetStudent,
  }) async {
    final detail = _detail;
    if (detail == null || _isMutating) return;

    final hasPin = await KioskPinSetupDialog.ensureKioskPin(
      context,
      widget.apiClient,
    );
    if (!hasPin || !mounted) return;

    List<StudentAttendanceItem> candidates = detail.students;
    if (detail.classId == null) {
      setState(() => _isMutating = true);
      try {
        candidates = await loadManualAttendanceCandidates(
          widget.apiClient,
          detail,
        );
      } on ApiException catch (exc) {
        if (!mounted) return;
        _showSnackBar(exc.message, isError: true);
        return;
      } catch (exc) {
        if (!mounted) return;
        _showSnackBar('Gagal memuat daftar siswa aktif: $exc', isError: true);
        return;
      } finally {
        if (mounted) {
          setState(() => _isMutating = false);
        }
      }
    }

    if (!mounted) return;
    if (candidates.isEmpty) {
      _showSnackBar(
        'Belum ada daftar siswa di sesi ini untuk input manual.',
        isError: true,
      );
      return;
    }

    final selection = await showDialog<ManualAttendanceSelection>(
      context: context,
      builder: (dialogContext) => ManualAttendanceDialog(
        students: candidates,
        presetStudent: presetStudent,
        isGeneralGate: detail.classId == null,
      ),
    );

    if (selection == null || !mounted) return;

    final pinPrompt = widget.pinPromptBuilder ?? _defaultPinPrompt;
    final pin = await pinPrompt(
      context,
      title: 'Konfirmasi Absen Manual',
      subtitle:
          'Masukkan PIN Kiosk Guru untuk mencatat status "${AppFormatters.attendanceStatusLabel(selection.status)}" bagi ${selection.studentName}.',
      confirmLabel: 'Konfirmasi Absen Manual',
    );
    if (pin == null || pin.isEmpty || !mounted) return;

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
    } catch (exc) {
      if (!mounted) return;
      _showSnackBar('Gagal menyimpan presensi manual: $exc', isError: true);
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
    final isGeneralGate = detail.classId == null;
    final isGateOut = detail.sessionType == 'gate_out';

    final dialogTitle = isGeneralGate ? 'Tutup Sesi Gerbang?' : 'Tutup Sesi Kelas?';
    final String dialogContent;
    if (isGateOut) {
      dialogContent =
          'Menutup sesi Gerbang Pulang akan menghentikan pemindaian Kiosk. Siswa yang tidak memindai pulang tidak akan ditandai ALFA.';
    } else if (isGeneralGate) {
      dialogContent = unrecorded > 0
          ? 'Masih ada $unrecorded siswa aktif di seluruh sekolah yang belum tercatat. Menutup sesi Gerbang Umum akan otomatis menandai mereka sebagai ALFA (kecuali yang memiliki izin disetujui) dan menghentikan scan Kiosk.'
          : 'Semua siswa aktif telah tercatat. Menutup sesi akan mengunci presensi Gerbang Umum ini.';
    } else {
      dialogContent = unrecorded > 0
          ? 'Masih ada $unrecorded siswa yang belum tercatat. Menutup sesi akan otomatis menandai mereka sebagai ALFA dan menghentikan scan Kiosk.'
          : 'Semua siswa telah tercatat. Menutup sesi akan mengunci presensi kelas ini.';
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: Text(dialogTitle),
          content: Text(dialogContent),
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
    } catch (exc) {
      if (!mounted) return;
      _showSnackBar('Gagal menutup sesi presensi: $exc', isError: true);
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
    } catch (exc) {
      if (!mounted) return;
      _showSnackBar('Gagal mengirim ulang WA: $exc', isError: true);
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
      } else if (_statusFilter == 'wa_failed') {
        if (student.waStatus != 'failed') return false;
      } else if (_statusFilter != 'all' && student.status != _statusFilter) {
        return false;
      }

      if (query.isEmpty) return true;
      return student.studentName.toLowerCase().contains(query) ||
          student.nis.toLowerCase().contains(query) ||
          student.className.toLowerCase().contains(query);
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
                      _buildSearchAndFilterBar(detail),
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
                        onPressed:
                            _isMutating ? null : () => _openManualAttendanceModal(),
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
                        label: Text(
                          detail.classId == null
                              ? 'Tutup Sesi Gerbang'
                              : 'Tutup Sesi Kelas',
                        ),
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

  Widget _buildSearchAndFilterBar(SessionDetail detail) {
    final failedWaCount =
        detail.students.where((student) => student.waStatus == 'failed').length;
    final filters = [
      (key: 'all', label: 'Semua'),
      (key: 'present', label: 'Hadir'),
      (key: 'late', label: 'Telat'),
      (key: 'permit_sick', label: 'Izin/Sakit'),
      (key: 'unrecorded', label: 'Belum'),
      (key: 'absent', label: 'Alfa'),
      if (failedWaCount > 0) (key: 'wa_failed', label: 'WA Gagal ($failedWaCount)'),
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
              final isWaFailedChip = f.key == 'wa_failed';
              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(f.label),
                  selected: selected,
                  selectedColor:
                      isWaFailedChip ? AppColors.dangerTint : AppColors.primaryTint,
                  labelStyle: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: selected
                        ? (isWaFailedChip ? AppColors.danger : AppColors.primary)
                        : (isWaFailedChip
                            ? AppColors.danger
                            : AppColors.textSecondary),
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
              showClassName: detail.classId == null,
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
    required this.showClassName,
    required this.isSessionOpen,
    required this.isResending,
    required this.onResendWa,
    this.onTapManual,
  });

  final StudentAttendanceItem item;
  final bool showClassName;
  final bool isSessionOpen;
  final bool isResending;
  final VoidCallback onResendWa;
  final VoidCallback? onTapManual;

  String _buildMetadataLine() {
    final parts = <String>[
      if (showClassName) item.className,
      'NIS ${item.nis}',
    ];
    if (item.scannedAt != null) {
      parts.add(AppFormatters.formatWibTime(item.scannedAt));
    }
    if (item.verificationMethod != null && item.verificationMethod!.isNotEmpty) {
      parts.add(AppFormatters.verificationMethodLabel(item.verificationMethod));
    } else if (item.status == 'unrecorded') {
      parts.add('Belum tercatat');
    }
    return parts.join(' • ');
  }

  @override
  Widget build(BuildContext context) {
    final statusColors = AppFormatters.attendanceStatusColors(item.status);
    final statusLabel = AppFormatters.attendanceStatusLabel(item.status);
    final canRetryWa =
        (item.waStatus == 'failed' || item.waStatus == 'pending') &&
        item.attendanceId != null;

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
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        _buildMetadataLine(),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
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
                  if (canRetryWa)
                    TextButton.icon(
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 4,
                        ),
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
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
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
