import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../widgets/kiosk_pin_setup_dialog.dart';
import 'leave_verification_screen.dart';
import 'login_screen.dart';
import 'session_detail_screen.dart';

/// Builder opsional untuk menghubungkan `KioskScannerScreen` di Task 10.
typedef KioskScannerBuilder = Widget Function(
  BuildContext context,
  SessionDetail session,
  VoidCallback onAttendanceChanged,
);

/// Builder opsional untuk menghubungkan `LeaveVerificationScreen` di Task 10.
typedef LeaveVerificationTabBuilder = Widget Function(
  BuildContext context,
  VoidCallback onLeaveChanged,
  int refreshTrigger, {
  ValueChanged<int>? onPendingCountLoaded,
});

/// Callback opsional untuk menampilkan modal PIN Kiosk (`KioskPinSheet`) di Task 10.
typedef ManualPinPromptBuilder = Future<String?> Function(
  BuildContext context, {
  required String title,
  required String subtitle,
  required String confirmLabel,
});

/// Layar 02 Figma: Beranda Guru, 3 KPI, Sesi Hari Ini, & Navigasi 3 Tab.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.apiClient,
    required this.initialUser,
    this.kioskScannerBuilder,
    this.leaveVerificationBuilder,
    this.pinPromptBuilder,
  });

  final ApiClient apiClient;
  final UserProfile initialUser;
  final KioskScannerBuilder? kioskScannerBuilder;
  final LeaveVerificationTabBuilder? leaveVerificationBuilder;
  final ManualPinPromptBuilder? pinPromptBuilder;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentTab = 0;
  int _leaveRefreshTick = 0;
  int? _livePendingLeavesCount;
  late UserProfile _user;
  TeacherDashboardData? _dashboard;
  bool _isLoading = true;
  bool _isOpeningCreateDialog = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _user = widget.initialUser;
    _loadDashboard();
  }

  Future<void> _loadDashboard() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final dashboard = await widget.apiClient.getTeacherDashboard();
      final latestUser = widget.apiClient.currentUser;
      if (!mounted) return;
      setState(() {
        _dashboard = dashboard;
        _livePendingLeavesCount = dashboard.stats.pendingLeavesCount;
        if (latestUser != null) {
          _user = latestUser;
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
        _errorMessage = 'Gagal memuat data beranda: $exc';
        _isLoading = false;
      });
    }
  }

  void _handlePendingLeavesCountLoaded(int count) {
    if (!mounted || _livePendingLeavesCount == count) return;
    setState(() {
      _livePendingLeavesCount = count;
    });
  }

  Future<void> _openSessionDetail(String sessionId) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => SessionDetailScreen(
          apiClient: widget.apiClient,
          sessionId: sessionId,
          kioskScannerBuilder: widget.kioskScannerBuilder,
          pinPromptBuilder: widget.pinPromptBuilder,
        ),
      ),
    );
    if (mounted) {
      final latestUser = widget.apiClient.currentUser;
      if (latestUser != null && latestUser.hasKioskPin != _user.hasKioskPin) {
        setState(() => _user = latestUser);
      }
      _loadDashboard();
    }
  }

  Future<void> _showCreateSessionDialog({ScheduleItem? presetSchedule}) async {
    if (_isOpeningCreateDialog) return;
    _isOpeningCreateDialog = true;

    try {
      List<SchoolClassItem> classes = [];
      try {
        classes = await widget.apiClient.getClasses();
      } on ApiException catch (exc) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(exc.message), backgroundColor: AppColors.danger),
        );
        return;
      } catch (exc) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Gagal memuat daftar kelas: $exc'),
            backgroundColor: AppColors.danger,
          ),
        );
        return;
      }

      if (!mounted) return;

      final created = await showDialog<SessionSummary>(
        context: context,
        builder: (dialogContext) => _CreateSessionDialog(
          apiClient: widget.apiClient,
          classes: classes,
          todaySchedules: _dashboard?.todaySchedules ?? const [],
          presetSchedule: presetSchedule,
        ),
      );

      if (created != null && mounted) {
        await _loadDashboard();
        if (!mounted) return;
        await _openSessionDetail(created.id);
      }
    } finally {
      _isOpeningCreateDialog = false;
    }
  }

  void _selectTab(int index) {
    setState(() {
      _currentTab = index;
      if (index == 1) {
        _leaveRefreshTick += 1;
      }
    });
    if (index == 0) {
      _loadDashboard();
    }
  }

  Future<void> _logout() async {
    await widget.apiClient.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute<void>(
        builder: (_) => LoginScreen(
          apiClient: widget.apiClient,
          kioskScannerBuilder: widget.kioskScannerBuilder,
          leaveVerificationBuilder: widget.leaveVerificationBuilder,
          pinPromptBuilder: widget.pinPromptBuilder,
        ),
      ),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final pendingCount =
        _livePendingLeavesCount ?? _dashboard?.stats.pendingLeavesCount ?? 0;

    return Scaffold(
      backgroundColor: AppColors.background,
      body: IndexedStack(
        index: _currentTab,
        children: [
          _buildDashboardTab(),
          _buildLeaveTab(),
          _ProfilePinTab(
            apiClient: widget.apiClient,
            user: _user,
            onUserUpdated: (updated) => setState(() => _user = updated),
            onServerUrlUpdated: _loadDashboard,
            onLogout: _logout,
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentTab,
        backgroundColor: AppColors.card,
        indicatorColor: AppColors.primaryTint,
        onDestinationSelected: _selectTab,
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded, color: AppColors.primary),
            label: 'Beranda',
          ),
          NavigationDestination(
            icon: _PendingBadgeIcon(
              count: pendingCount,
              icon: Icons.fact_check_outlined,
            ),
            selectedIcon: _PendingBadgeIcon(
              count: pendingCount,
              icon: Icons.fact_check_rounded,
              color: AppColors.primary,
            ),
            label: 'Verifikasi Izin',
          ),
          const NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person_rounded, color: AppColors.primary),
            label: 'Profil & PIN',
          ),
        ],
      ),
    );
  }

  Widget _buildLeaveTab() {
    if (widget.leaveVerificationBuilder != null) {
      return widget.leaveVerificationBuilder!(
        context,
        _loadDashboard,
        _leaveRefreshTick,
        onPendingCountLoaded: _handlePendingLeavesCountLoaded,
      );
    }

    return LeaveVerificationScreen(
      apiClient: widget.apiClient,
      onLeaveChanged: _loadDashboard,
      onPendingCountLoaded: _handlePendingLeavesCountLoaded,
      refreshTrigger: _leaveRefreshTick,
    );
  }

  Widget _buildDashboardTab() {
    final stats = _dashboard?.stats;
    final sessions = _dashboard?.sessions ?? const <SessionSummary>[];
    final schedules = _dashboard?.todaySchedules ?? const <ScheduleItem>[];
    final openedScheduleIds = sessions
        .map((s) => s.scheduleId)
        .whereType<String>()
        .toSet();
    final unopenedSchedules = schedules
        .where((sch) => !openedScheduleIds.contains(sch.id))
        .toList();

    return RefreshIndicator(
      onRefresh: _loadDashboard,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(child: _buildHeader(context)),
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            sliver: SliverList(
              delegate: SliverChildListDelegate([
                if (!_user.hasKioskPin) ...[
                  _buildPinWarningBanner(),
                  const SizedBox(height: 14),
                ],
                if (_errorMessage != null) ...[
                  _buildErrorCard(_errorMessage!),
                  const SizedBox(height: 14),
                ],
                _buildKpiRow(stats),
                const SizedBox(height: 18),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _isLoading ? null : () => _showCreateSessionDialog(),
                    icon: const Icon(Icons.add_circle_outline),
                    label: const Text('+ Buka Sesi Presensi Baru'),
                  ),
                ),
                const SizedBox(height: 22),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Sesi Presensi Hari Ini',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    Text(
                      '${sessions.length} sesi',
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                if (_isLoading && _dashboard == null)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 32),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else if (sessions.isEmpty && unopenedSchedules.isEmpty)
                  _buildEmptySessionsCard()
                else ...[
                  ...sessions.map(
                    (session) => Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: _SessionCard(
                        session: session,
                        onTap: () => _openSessionDetail(session.id),
                      ),
                    ),
                  ),
                  if (unopenedSchedules.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    const Text(
                      'Jadwal Mengajar Belum Dibuka',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    ...unopenedSchedules.map(
                      (sch) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _UnopenedScheduleCard(
                          schedule: sch,
                          onOpenSession: () =>
                              _showCreateSessionDialog(presetSchedule: sch),
                        ),
                      ),
                    ),
                  ],
                ],
              ]),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    final topInset = MediaQuery.of(context).padding.top;
    final teacherName = _dashboard?.teacherName ?? _user.name;
    final dateLabel = AppFormatters.formatIndonesianDate(_dashboard?.todayDate);

    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(20, topInset + 18, 20, 22),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppColors.primary, AppColors.primaryDark],
        ),
        borderRadius: BorderRadius.only(
          bottomLeft: Radius.circular(24),
          bottomRight: Radius.circular(24),
        ),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 25,
            backgroundColor: Colors.white.withValues(alpha: 0.2),
            child: Text(
              AppFormatters.initials(teacherName),
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                fontSize: 16,
              ),
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Selamat Bertugas,',
                  style: TextStyle(
                    fontSize: 12,
                    color: Colors.white.withValues(alpha: 0.85),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  teacherName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(
                      Icons.calendar_today_outlined,
                      size: 13,
                      color: Colors.white.withValues(alpha: 0.85),
                    ),
                    const SizedBox(width: 5),
                    Flexible(
                      child: Text(
                        dateLabel,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.white.withValues(alpha: 0.9),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Muat Ulang',
            onPressed: _isLoading ? null : _loadDashboard,
            icon: const Icon(Icons.refresh_rounded, color: Colors.white),
          ),
        ],
      ),
    );
  }

  Widget _buildPinWarningBanner() {
    return InkWell(
      onTap: () async {
        await KioskPinSetupDialog.show(
          context,
          widget.apiClient,
          onUserUpdated: (updated) {
            if (mounted) {
              setState(() => _user = updated);
            }
          },
        );
      },
      borderRadius: BorderRadius.circular(14),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.warningTint,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.warning.withValues(alpha: 0.4)),
        ),
        child: const Row(
          children: [
            Icon(Icons.lock_outline, color: AppColors.warning, size: 20),
            SizedBox(width: 10),
            Expanded(
              child: Text(
                'PIN Kiosk belum diatur. Ketuk untuk mengatur PIN 4–6 digit sebelum menggunakan Mode Kiosk.',
                style: TextStyle(
                  fontSize: 12.5,
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
            Icon(Icons.chevron_right, color: AppColors.textSecondary),
          ],
        ),
      ),
    );
  }

  Widget _buildErrorCard(String message) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.dangerTint,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.danger.withValues(alpha: 0.35)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline, color: AppColors.danger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: AppColors.danger, fontSize: 13),
            ),
          ),
          TextButton(
            onPressed: _loadDashboard,
            child: const Text('Coba Lagi'),
          ),
        ],
      ),
    );
  }

  Widget _buildKpiRow(TeacherDashboardStats? stats) {
    final presentRate = stats == null ? '-' : '${stats.presentRate.toStringAsFixed(0)}%';
    final lateCount = stats == null ? '-' : '${stats.lateCount}';
    final resolvedPending = _livePendingLeavesCount ?? stats?.pendingLeavesCount;
    final pendingCount = resolvedPending == null ? '-' : '$resolvedPending';

    return Row(
      children: [
        Expanded(
          child: _KpiCard(
            title: 'Hadir',
            value: presentRate,
            subtitle: stats == null ? '' : '${stats.presentCount} tepat waktu',
            accentColor: AppColors.success,
            tintColor: AppColors.successTint,
            icon: Icons.check_circle_outline,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _KpiCard(
            title: 'Terlambat',
            value: lateCount,
            subtitle: 'siswa hari ini',
            accentColor: AppColors.warning,
            tintColor: AppColors.warningTint,
            icon: Icons.schedule_rounded,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: InkWell(
            onTap: () => _selectTab(1),
            borderRadius: BorderRadius.circular(16),
            child: _KpiCard(
              title: 'Izin Pending',
              value: pendingCount,
              subtitle: 'perlu verifikasi',
              accentColor: AppColors.danger,
              tintColor: AppColors.dangerTint,
              icon: Icons.mark_email_unread_outlined,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildEmptySessionsCard() {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
      ),
      child: const Column(
        children: [
          Icon(Icons.event_note_outlined, size: 40, color: AppColors.textMuted),
          SizedBox(height: 10),
          Text(
            'Belum ada sesi presensi hari ini',
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          SizedBox(height: 4),
          Text(
            'Tekan tombol "+ Buka Sesi Presensi Baru" untuk memulai absensi kelas atau gerbang.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
          ),
        ],
      ),
    );
  }
}

class _PendingBadgeIcon extends StatelessWidget {
  const _PendingBadgeIcon({
    required this.count,
    required this.icon,
    this.color,
  });

  final int count;
  final IconData icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final baseIcon = Icon(icon, color: color);
    if (count <= 0) return baseIcon;
    return Badge(
      label: Text(count > 99 ? '99+' : '$count'),
      backgroundColor: AppColors.danger,
      child: baseIcon,
    );
  }
}

class _KpiCard extends StatelessWidget {
  const _KpiCard({
    required this.title,
    required this.value,
    required this.subtitle,
    required this.accentColor,
    required this.tintColor,
    required this.icon,
  });

  final String title;
  final String value;
  final String subtitle;
  final Color accentColor;
  final Color tintColor;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: tintColor,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 18, color: accentColor),
          ),
          const SizedBox(height: 10),
          Text(
            value,
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: accentColor,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            title,
            style: const TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
          if (subtitle.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(
              subtitle,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
          ],
        ],
      ),
    );
  }
}

class _SessionCard extends StatelessWidget {
  const _SessionCard({required this.session, required this.onTap});

  final SessionSummary session;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isOpen = session.isOpen;
    final badgeFg = isOpen ? AppColors.success : AppColors.textSecondary;
    final badgeBg = isOpen ? AppColors.successTint : const Color(0xFFF1F5F9);
    final badgeLabel = isOpen ? 'AKTIF' : 'SELESAI';

    final progress = session.totalStudents > 0
        ? (session.recordedCount / session.totalStudents).clamp(0.0, 1.0)
        : 0.0;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(18),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: AppColors.card,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(
            color: isOpen
                ? AppColors.primary.withValues(alpha: 0.3)
                : AppColors.border,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        session.displayTitle,
                        style: const TextStyle(
                          fontSize: 15.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        '${session.displayClassName} • ${AppFormatters.sessionTypeLabel(session.sessionType)}',
                        style: const TextStyle(
                          fontSize: 12.5,
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
                    color: badgeBg,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    badgeLabel,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: badgeFg,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                const Icon(Icons.access_time, size: 14, color: AppColors.textMuted),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    session.expectedStartTime != null
                        ? 'Mulai ${AppFormatters.formatTimeShort(session.expectedStartTime)} (toleransi ${session.lateToleranceMinutes} mnt)'
                        : 'Dibuka ${AppFormatters.formatWibTime(session.openedAt)}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                value: progress,
                minHeight: 7,
                backgroundColor: const Color(0xFFE2E8F0),
                color: isOpen ? AppColors.primary : AppColors.success,
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Hadir ${session.presentCount} • Telat ${session.lateCount} • Izin/Sakit ${session.permitCount + session.sickCount}${session.absentCount > 0 ? ' • Alfa ${session.absentCount}' : ''}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.textSecondary,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  '${session.recordedCount}/${session.totalStudents}',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primary,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _UnopenedScheduleCard extends StatelessWidget {
  const _UnopenedScheduleCard({
    required this.schedule,
    required this.onOpenSession,
  });

  final ScheduleItem schedule;
  final VoidCallback onOpenSession;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.warningTint,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: const Text(
                        'BELUM',
                        style: TextStyle(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w800,
                          color: AppColors.warning,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        schedule.subjectName,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '${schedule.className} • ${AppFormatters.formatTimeShort(schedule.startTime)}–${AppFormatters.formatTimeShort(schedule.endTime)}',
                  style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          OutlinedButton(
            onPressed: onOpenSession,
            child: const Text('Buka Sesi'),
          ),
        ],
      ),
    );
  }
}

class _CreateSessionDialog extends StatefulWidget {
  const _CreateSessionDialog({
    required this.apiClient,
    required this.classes,
    required this.todaySchedules,
    this.presetSchedule,
  });

  final ApiClient apiClient;
  final List<SchoolClassItem> classes;
  final List<ScheduleItem> todaySchedules;
  final ScheduleItem? presetSchedule;

  @override
  State<_CreateSessionDialog> createState() => _CreateSessionDialogState();
}

class _CreateSessionDialogState extends State<_CreateSessionDialog> {
  late String _sessionType;
  String? _selectedClassId;
  String? _selectedScheduleId;
  TimeOfDay? _expectedStartTime;
  late final TextEditingController _toleranceController;
  bool _isSaving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final preset = widget.presetSchedule;
    _sessionType = 'subject';

    final presetClassValid =
        preset != null && _resolveValidClassId(preset.classId) != null;
    final presetScheduleValid = preset != null &&
        widget.todaySchedules.any((s) => s.id == preset.id) &&
        presetClassValid;

    _selectedScheduleId = presetScheduleValid ? preset.id : null;
    _selectedClassId = presetClassValid
        ? preset.classId
        : (widget.classes.isNotEmpty ? widget.classes.first.id : null);
    _expectedStartTime = _parseTimeOfDay(preset?.startTime) ?? TimeOfDay.now();
    _toleranceController = TextEditingController(
      text: '${preset?.lateToleranceMinutes ?? 15}',
    );
  }

  String? _resolveValidClassId(String? candidate) {
    if (candidate == null || candidate.isEmpty) return null;
    final exists = widget.classes.any((c) => c.id == candidate);
    return exists ? candidate : null;
  }

  String? _resolveValidScheduleId(String? candidate) {
    if (candidate == null || candidate.isEmpty) return null;
    final exists = widget.todaySchedules.any((s) => s.id == candidate);
    return exists ? candidate : null;
  }

  @override
  void dispose() {
    _toleranceController.dispose();
    super.dispose();
  }

  TimeOfDay? _parseTimeOfDay(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    final parts = raw.split(':');
    if (parts.length < 2) return null;
    final hour = int.tryParse(parts[0]);
    final minute = int.tryParse(parts[1]);
    if (hour == null || minute == null) return null;
    return TimeOfDay(hour: hour, minute: minute);
  }

  String _formatTimeForApi(TimeOfDay t) {
    final hh = t.hour.toString().padLeft(2, '0');
    final mm = t.minute.toString().padLeft(2, '0');
    return '$hh:$mm:00';
  }

  String _formatTimeDisplay(TimeOfDay t) {
    final hh = t.hour.toString().padLeft(2, '0');
    final mm = t.minute.toString().padLeft(2, '0');
    return '$hh:$mm';
  }

  void _onScheduleChanged(String? scheduleId) {
    setState(() {
      _selectedScheduleId = _resolveValidScheduleId(scheduleId);
      _error = null;
      if (_selectedScheduleId != null) {
        final match = widget.todaySchedules.where((s) => s.id == _selectedScheduleId);
        if (match.isNotEmpty) {
          final sch = match.first;
          final validClass = _resolveValidClassId(sch.classId);
          if (validClass != null) {
            _selectedClassId = validClass;
          } else {
            _selectedScheduleId = null;
            _selectedClassId =
                widget.classes.isNotEmpty ? widget.classes.first.id : null;
            _error = 'Kelas dari jadwal tidak ditemukan di daftar kelas.';
          }
          _expectedStartTime = _parseTimeOfDay(sch.startTime);
          _toleranceController.text = '${sch.lateToleranceMinutes}';
        }
      }
    });
  }

  Future<void> _submit() async {
    final validClassId = _resolveValidClassId(_selectedClassId);
    if (_sessionType == 'subject' && validClassId == null) {
      setState(
        () => _error = widget.classes.isEmpty
            ? 'Belum ada kelas terdaftar. Tambahkan kelas di Web Admin atau pilih sesi Gerbang.'
            : 'Pilih kelas terlebih dahulu untuk sesi mata pelajaran.',
      );
      return;
    }

    final tolerance = int.tryParse(_toleranceController.text.trim());
    if (tolerance == null || tolerance < 0 || tolerance > 120) {
      setState(() => _error = 'Toleransi keterlambatan harus antara 0 dan 120 menit.');
      return;
    }

    setState(() {
      _isSaving = true;
      _error = null;
    });

    try {
      final created = await widget.apiClient.createSession(
        sessionType: _sessionType,
        classId: validClassId,
        scheduleId: _sessionType == 'subject'
            ? _resolveValidScheduleId(_selectedScheduleId)
            : null,
        expectedStartTime:
            _expectedStartTime != null ? _formatTimeForApi(_expectedStartTime!) : null,
        lateToleranceMinutes: tolerance,
      );
      if (!mounted) return;
      Navigator.of(context).pop(created);
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = exc.message;
        _isSaving = false;
      });
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        _error = 'Gagal membuat sesi presensi: $exc';
        _isSaving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final validClassId = _resolveValidClassId(_selectedClassId);
    final validScheduleId = _resolveValidScheduleId(_selectedScheduleId);
    final missingClassesForSubject =
        _sessionType == 'subject' && widget.classes.isEmpty;

    return AlertDialog(
      title: const Text('Buka Sesi Presensi Baru'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_error != null) ...[
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.dangerTint,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  _error!,
                  style: const TextStyle(color: AppColors.danger, fontSize: 12.5),
                ),
              ),
              const SizedBox(height: 12),
            ],
            DropdownButtonFormField<String>(
              initialValue: _sessionType,
              decoration: const InputDecoration(labelText: 'Jenis Sesi'),
              items: const [
                DropdownMenuItem(value: 'subject', child: Text('Mata Pelajaran')),
                DropdownMenuItem(value: 'gate_in', child: Text('Gerbang Masuk')),
                DropdownMenuItem(value: 'gate_out', child: Text('Gerbang Pulang')),
              ],
              onChanged: (val) {
                if (val == null) return;
                setState(() {
                  _sessionType = val;
                  _error = null;
                  if (val == 'gate_in' || val == 'gate_out') {
                    _selectedScheduleId = null;
                    _selectedClassId = null;
                    if (val == 'gate_out') {
                      _expectedStartTime = null;
                    }
                  } else if (_resolveValidClassId(_selectedClassId) == null &&
                      widget.classes.isNotEmpty) {
                    _selectedClassId = widget.classes.first.id;
                  }
                });
              },
            ),
            if (_sessionType == 'subject' && widget.todaySchedules.isNotEmpty) ...[
              const SizedBox(height: 12),
              DropdownButtonFormField<String?>(
                key: ValueKey('schedule_${validScheduleId ?? "none"}'),
                initialValue: validScheduleId,
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: 'Jadwal Hari Ini (Opsional)',
                ),
                items: [
                  const DropdownMenuItem<String?>(
                    value: null,
                    child: Text('Tanpa Jadwal Khusus'),
                  ),
                  ...widget.todaySchedules.map(
                    (s) => DropdownMenuItem<String?>(
                      value: s.id,
                      child: Text(
                        '${s.subjectName} (${s.className})',
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                ],
                onChanged: _onScheduleChanged,
              ),
            ],
            const SizedBox(height: 12),
            if (missingClassesForSubject)
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.warningTint,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: AppColors.warning.withValues(alpha: 0.4),
                  ),
                ),
                child: const Text(
                  'Belum ada data kelas tersedia. Tambahkan kelas melalui Web Admin atau pilih jenis sesi Gerbang.',
                  style: TextStyle(fontSize: 12.5, color: AppColors.textPrimary),
                ),
              )
            else
              DropdownButtonFormField<String?>(
                key: ValueKey('class_${_sessionType}_${validClassId ?? "all"}'),
                initialValue: validClassId,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Kelas'),
                items: [
                  if (_sessionType != 'subject')
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('Semua Kelas (Gerbang Umum)'),
                    ),
                  ...widget.classes.map(
                    (c) => DropdownMenuItem<String?>(
                      value: c.id,
                      child: Text('${c.name} (${c.studentCount} siswa)'),
                    ),
                  ),
                ],
                onChanged: (val) {
                  setState(() {
                    _selectedClassId = val;
                    if (_selectedScheduleId != null) {
                      final match = widget.todaySchedules.where(
                        (s) => s.id == _selectedScheduleId,
                      );
                      if (match.isNotEmpty && match.first.classId != val) {
                        _selectedScheduleId = null;
                      }
                    }
                  });
                },
              ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () async {
                      final picked = await showTimePicker(
                        context: context,
                        initialTime: _expectedStartTime ?? TimeOfDay.now(),
                      );
                      if (picked != null) {
                        setState(() => _expectedStartTime = picked);
                      }
                    },
                    child: InputDecorator(
                      decoration: InputDecoration(
                        labelText: 'Jam Mulai',
                        suffixIcon: _expectedStartTime != null
                            ? IconButton(
                                key: const Key('clear_expected_start_time_button'),
                                tooltip: 'Hapus jam mulai (Tidak dibatasi)',
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints(),
                                icon: const Icon(Icons.close_rounded, size: 18),
                                onPressed: () =>
                                    setState(() => _expectedStartTime = null),
                              )
                            : null,
                      ),
                      child: Text(
                        _expectedStartTime != null
                            ? _formatTimeDisplay(_expectedStartTime!)
                            : 'Tidak dibatasi',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: _toleranceController,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    decoration: const InputDecoration(
                      labelText: 'Toleransi (mnt)',
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.of(context).pop(),
          child: const Text('Batal'),
        ),
        ElevatedButton(
          onPressed: (_isSaving || missingClassesForSubject) ? null : _submit,
          child: _isSaving
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              : const Text('Buka Sesi'),
        ),
      ],
    );
  }
}

class _ProfilePinTab extends StatefulWidget {
  const _ProfilePinTab({
    required this.apiClient,
    required this.user,
    required this.onUserUpdated,
    required this.onServerUrlUpdated,
    required this.onLogout,
  });

  final ApiClient apiClient;
  final UserProfile user;
  final ValueChanged<UserProfile> onUserUpdated;
  final VoidCallback onServerUrlUpdated;
  final VoidCallback onLogout;

  @override
  State<_ProfilePinTab> createState() => _ProfilePinTabState();
}

class _ProfilePinTabState extends State<_ProfilePinTab> {
  final _currentPinController = TextEditingController();
  final _pinController = TextEditingController();
  final _confirmPinController = TextEditingController();
  late final TextEditingController _serverController;
  bool _obscureCurrentPin = true;
  bool _obscureNewPin = true;
  bool _obscureConfirmPin = true;
  bool _savingPin = false;
  String? _serverUrlError;

  @override
  void initState() {
    super.initState();
    _serverController = TextEditingController(text: widget.apiClient.baseUrl);
  }

  @override
  void dispose() {
    _currentPinController.dispose();
    _pinController.dispose();
    _confirmPinController.dispose();
    _serverController.dispose();
    super.dispose();
  }

  void _showErrorSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: AppColors.danger),
    );
  }

  Future<void> _savePin() async {
    final currentPin = _currentPinController.text.trim();
    final pin = _pinController.text.trim();
    final confirmPin = _confirmPinController.text.trim();

    if (widget.user.hasKioskPin && !RegExp(r'^\d{4,6}$').hasMatch(currentPin)) {
      _showErrorSnackBar(
        'PIN Kiosk lama wajib diisi (4 hingga 6 digit angka).',
      );
      return;
    }

    if (!RegExp(r'^\d{4,6}$').hasMatch(pin)) {
      _showErrorSnackBar('PIN Kiosk baru harus terdiri dari 4 hingga 6 digit angka.');
      return;
    }

    if (pin != confirmPin) {
      _showErrorSnackBar('Konfirmasi PIN baru tidak sama dengan PIN baru.');
      return;
    }

    setState(() => _savingPin = true);
    try {
      await widget.apiClient.updateKioskPin(
        pin,
        currentPin: widget.user.hasKioskPin ? currentPin : null,
      );
      widget.onUserUpdated(widget.user.copyWith(hasKioskPin: true));
      _currentPinController.clear();
      _pinController.clear();
      _confirmPinController.clear();
      if (!mounted) return;
      FocusScope.of(context).unfocus();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('PIN Kiosk berhasil disimpan.'),
          backgroundColor: AppColors.success,
        ),
      );
    } on ApiException catch (exc) {
      if (!mounted) return;
      _showErrorSnackBar(exc.message);
    } catch (exc) {
      if (!mounted) return;
      _showErrorSnackBar('Gagal menyimpan PIN Kiosk: $exc');
    } finally {
      if (mounted) {
        setState(() => _savingPin = false);
      }
    }
  }

  Future<void> _saveServerUrl() async {
    final validated = ApiClient.validateAndNormalizeBaseUrl(_serverController.text);
    if (validated.url == null) {
      setState(() => _serverUrlError = validated.error);
      return;
    }

    setState(() => _serverUrlError = null);
    try {
      await widget.apiClient.setBaseUrl(validated.url!);
      _serverController.text = widget.apiClient.baseUrl;
      if (!mounted) return;
      FocusScope.of(context).unfocus();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('URL Server diperbarui: ${widget.apiClient.baseUrl}'),
          backgroundColor: AppColors.success,
        ),
      );
      widget.onServerUrlUpdated();
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() => _serverUrlError = exc.message);
    } catch (exc) {
      if (!mounted) return;
      _showErrorSnackBar('Gagal memperbarui URL server: $exc');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Profil Guru & PIN Kiosk')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AppColors.border),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 28,
                  backgroundColor: AppColors.primaryTint,
                  child: Text(
                    AppFormatters.initials(widget.user.name),
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                      color: AppColors.primary,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.user.name,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        widget.user.email,
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      if (widget.user.nip != null) ...[
                        const SizedBox(height: 2),
                        Text(
                          'NIP: ${widget.user.nip}',
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.textMuted,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AppColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Keamanan PIN Kiosk',
                      style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: widget.user.hasKioskPin
                            ? AppColors.successTint
                            : AppColors.warningTint,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        widget.user.hasKioskPin ? 'Sudah Diatur' : 'Belum Diatur',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                          color: widget.user.hasKioskPin
                              ? AppColors.success
                              : AppColors.warning,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  'PIN ini digunakan untuk membuka kunci saat keluar dari Mode Kiosk dan menyetujui absensi manual.',
                  style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
                ),
                const SizedBox(height: 14),
                if (widget.user.hasKioskPin) ...[
                  TextField(
                    key: const Key('profile_current_pin_field'),
                    controller: _currentPinController,
                    obscureText: _obscureCurrentPin,
                    maxLength: 6,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                    textInputAction: TextInputAction.next,
                    decoration: InputDecoration(
                      labelText: 'PIN Kiosk Lama',
                      hintText: 'Masukkan PIN Kiosk saat ini',
                      counterText: '',
                      prefixIcon: const Icon(Icons.lock_outline_rounded),
                      suffixIcon: IconButton(
                        tooltip: _obscureCurrentPin
                            ? 'Tampilkan PIN'
                            : 'Sembunyikan PIN',
                        onPressed: () => setState(
                          () => _obscureCurrentPin = !_obscureCurrentPin,
                        ),
                        icon: Icon(
                          _obscureCurrentPin
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                TextField(
                  key: const Key('profile_new_pin_field'),
                  controller: _pinController,
                  obscureText: _obscureNewPin,
                  maxLength: 6,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  textInputAction: TextInputAction.next,
                  decoration: InputDecoration(
                    labelText: 'PIN Kiosk Baru (4–6 Digit)',
                    hintText: 'Contoh: 1234',
                    counterText: '',
                    prefixIcon: const Icon(Icons.lock_reset_outlined),
                    suffixIcon: IconButton(
                      tooltip: _obscureNewPin ? 'Tampilkan PIN' : 'Sembunyikan PIN',
                      onPressed: () =>
                          setState(() => _obscureNewPin = !_obscureNewPin),
                      icon: Icon(
                        _obscureNewPin
                            ? Icons.visibility_outlined
                            : Icons.visibility_off_outlined,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('profile_confirm_pin_field'),
                  controller: _confirmPinController,
                  obscureText: _obscureConfirmPin,
                  maxLength: 6,
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _savingPin ? null : _savePin(),
                  decoration: InputDecoration(
                    labelText: 'Konfirmasi PIN Baru',
                    hintText: 'Ulangi PIN Kiosk baru',
                    counterText: '',
                    prefixIcon: const Icon(Icons.verified_user_outlined),
                    suffixIcon: IconButton(
                      tooltip: _obscureConfirmPin
                          ? 'Tampilkan PIN'
                          : 'Sembunyikan PIN',
                      onPressed: () => setState(
                        () => _obscureConfirmPin = !_obscureConfirmPin,
                      ),
                      icon: Icon(
                        _obscureConfirmPin
                            ? Icons.visibility_outlined
                            : Icons.visibility_off_outlined,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _savingPin ? null : _savePin,
                  child: _savingPin
                      ? const SizedBox(
                          height: 18,
                          width: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : Text(widget.user.hasKioskPin
                          ? 'Perbarui PIN Kiosk'
                          : 'Simpan PIN Kiosk'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AppColors.card,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AppColors.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Konfigurasi Server API',
                  style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _serverController,
                  keyboardType: TextInputType.url,
                  onChanged: (_) {
                    if (_serverUrlError != null) {
                      setState(() => _serverUrlError = null);
                    }
                  },
                  decoration: InputDecoration(
                    labelText: 'API Base URL',
                    hintText: 'http://10.0.2.2:8000/api/v1',
                    prefixIcon: const Icon(Icons.dns_outlined),
                    errorText: _serverUrlError,
                  ),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: _saveServerUrl,
                  child: const Text('Simpan Alamat Server'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.danger,
              side: const BorderSide(color: AppColors.danger),
            ),
            onPressed: widget.onLogout,
            icon: const Icon(Icons.logout_rounded),
            label: const Text('Keluar dari Akun Guru'),
          ),
        ],
      ),
    );
  }
}
