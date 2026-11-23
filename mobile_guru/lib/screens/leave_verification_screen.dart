import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';

/// Layar 07 Figma: Verifikasi Pengajuan Izin & Sakit Siswa dari WhatsApp Orang Tua.
class LeaveVerificationScreen extends StatefulWidget {
  const LeaveVerificationScreen({
    super.key,
    required this.apiClient,
    this.onLeaveChanged,
    this.initialLeaves,
    this.onVerify,
    this.refreshTrigger = 0,
  });

  final ApiClient apiClient;
  final VoidCallback? onLeaveChanged;
  final List<LeaveRequestItem>? initialLeaves;
  final Future<void> Function(String leaveId, String decision)? onVerify;
  final int refreshTrigger;

  @override
  State<LeaveVerificationScreen> createState() => _LeaveVerificationScreenState();
}

class _LeaveVerificationScreenState extends State<LeaveVerificationScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  List<LeaveRequestItem> _leaves = const [];
  bool _isLoading = false;
  String? _errorMessage;
  final Set<String> _processingIds = {};

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    if (widget.initialLeaves != null) {
      _leaves = List<LeaveRequestItem>.of(widget.initialLeaves!);
    } else {
      _loadLeaves();
    }
  }

  @override
  void didUpdateWidget(covariant LeaveVerificationScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialLeaves != null &&
        widget.initialLeaves != oldWidget.initialLeaves) {
      _leaves = List<LeaveRequestItem>.of(widget.initialLeaves!);
    } else if (widget.initialLeaves == null &&
        widget.refreshTrigger != oldWidget.refreshTrigger) {
      _loadLeaves();
    }
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _loadLeaves() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final items = await widget.apiClient.getLeaveRequests();
      if (!mounted) return;
      setState(() {
        _leaves = items;
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
        _errorMessage = 'Gagal memuat pengajuan izin: $exc';
        _isLoading = false;
      });
    }
  }

  Future<void> _handleDecision(LeaveRequestItem item, String decision) async {
    if (_processingIds.contains(item.id)) return;

    setState(() {
      _processingIds.add(item.id);
    });

    try {
      if (widget.onVerify != null) {
        await widget.onVerify!(item.id, decision);
        widget.onLeaveChanged?.call();
        if (!mounted) return;
        setState(() {
          _processingIds.remove(item.id);
        });
        return;
      }

      final result = await widget.apiClient.verifyLeaveRequest(
        leaveId: item.id,
        decision: decision,
      );
      if (!mounted) return;

      final waNote = result.waSent
          ? 'Notifikasi WA orang tua terkirim.'
          : 'Keputusan tersimpan (notifikasi WA tertunda).';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${result.message} $waNote'),
          backgroundColor:
              decision == 'approved' ? AppColors.success : AppColors.warning,
        ),
      );
      widget.onLeaveChanged?.call();
      await _loadLeaves();
    } on ApiException catch (exc) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(exc.message), backgroundColor: AppColors.danger),
      );
    } finally {
      if (mounted) {
        setState(() {
          _processingIds.remove(item.id);
        });
      }
    }
  }

  void _openAttachmentPreview(LeaveRequestItem item) {
    final resolvedUrl = widget.apiClient.resolveAssetUrl(item.attachmentUrl);
    if (resolvedUrl == null) return;

    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('Lampiran • ${item.studentName}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.network(
                resolvedUrl,
                height: 280,
                fit: BoxFit.contain,
                errorBuilder: (_, _, _) => Container(
                  height: 160,
                  width: double.infinity,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: AppColors.background,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: const Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.broken_image_outlined,
                        size: 36,
                        color: AppColors.textMuted,
                      ),
                      SizedBox(height: 8),
                      Text(
                        'Pratinjau gambar tidak tersedia.',
                        style: TextStyle(color: AppColors.textSecondary),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              _extractAttachmentName(item.attachmentUrl!),
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Tutup'),
          ),
        ],
      ),
    );
  }

  List<LeaveRequestItem> _byStatus(String status) {
    return _leaves.where((item) => item.status == status).toList();
  }

  @override
  Widget build(BuildContext context) {
    final pendingList = _byStatus('pending');
    final approvedList = _byStatus('approved');
    final rejectedList = _byStatus('rejected');

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text('Verifikasi Izin & Sakit'),
        actions: [
          IconButton(
            tooltip: 'Muat Ulang',
            onPressed: _isLoading ? null : _loadLeaves,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: Column(
        children: [
          Material(
            color: AppColors.card,
            child: Container(
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AppColors.border)),
              ),
              child: TabBar(
                controller: _tabController,
                labelColor: AppColors.primary,
                unselectedLabelColor: AppColors.textSecondary,
                indicatorColor: AppColors.primary,
                indicatorWeight: 3,
                tabs: [
                  _TabLabelWithCount(
                    label: 'Menunggu',
                    count: pendingList.length,
                    badgeColor: AppColors.warning,
                  ),
                  _TabLabelWithCount(
                    label: 'Disetujui',
                    count: approvedList.length,
                    badgeColor: AppColors.success,
                  ),
                  _TabLabelWithCount(
                    label: 'Ditolak',
                    count: rejectedList.length,
                    badgeColor: AppColors.danger,
                  ),
                ],
              ),
            ),
          ),
          if (_errorMessage != null)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.dangerTint,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: AppColors.danger.withValues(alpha: 0.35),
                ),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline, color: AppColors.danger, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _errorMessage!,
                      style: const TextStyle(color: AppColors.danger, fontSize: 12.5),
                    ),
                  ),
                  TextButton(
                    onPressed: _loadLeaves,
                    child: const Text('Coba Lagi'),
                  ),
                ],
              ),
            ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _buildLeaveList(
                  items: pendingList,
                  emptyTitle: 'Tidak ada pengajuan izin menunggu',
                  emptySubtitle:
                      'Pengajuan izin/sakit yang dikirim orang tua lewat WhatsApp akan tampil di sini.',
                ),
                _buildLeaveList(
                  items: approvedList,
                  emptyTitle: 'Belum ada pengajuan yang disetujui',
                  emptySubtitle:
                      'Izin yang Anda setujui otomatis menyinkronkan data presensi kelas.',
                ),
                _buildLeaveList(
                  items: rejectedList,
                  emptyTitle: 'Tidak ada pengajuan yang ditolak',
                  emptySubtitle:
                      'Riwayat pengajuan izin yang ditolak akan tercatat di tab ini.',
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLeaveList({
    required List<LeaveRequestItem> items,
    required String emptyTitle,
    required String emptySubtitle,
  }) {
    if (_isLoading && _leaves.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: widget.initialLeaves != null
          ? () async {}
          : _loadLeaves,
      child: items.isEmpty
          ? ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(20),
              children: [
                Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    color: AppColors.card,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: Column(
                    children: [
                      const Icon(
                        Icons.inbox_outlined,
                        size: 42,
                        color: AppColors.textMuted,
                      ),
                      const SizedBox(height: 10),
                      Text(
                        emptyTitle,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 15,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        emptySubtitle,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            )
          : ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
              itemCount: items.length,
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemBuilder: (context, index) {
                final item = items[index];
                return _LeaveRequestCard(
                  item: item,
                  isProcessing: _processingIds.contains(item.id),
                  onApprove: () => _handleDecision(item, 'approved'),
                  onReject: () => _handleDecision(item, 'rejected'),
                  onTapAttachment: item.attachmentUrl != null &&
                          item.attachmentUrl!.trim().isNotEmpty
                      ? () => _openAttachmentPreview(item)
                      : null,
                );
              },
            ),
    );
  }
}

class _TabLabelWithCount extends StatelessWidget {
  const _TabLabelWithCount({
    required this.label,
    required this.count,
    required this.badgeColor,
  });

  final String label;
  final int count;
  final Color badgeColor;

  @override
  Widget build(BuildContext context) {
    return Tab(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Flexible(
            child: Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
            ),
          ),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: badgeColor.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              '$count',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w800,
                color: badgeColor,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _LeaveRequestCard extends StatelessWidget {
  const _LeaveRequestCard({
    required this.item,
    required this.isProcessing,
    required this.onApprove,
    required this.onReject,
    this.onTapAttachment,
  });

  final LeaveRequestItem item;
  final bool isProcessing;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  final VoidCallback? onTapAttachment;

  @override
  Widget build(BuildContext context) {
    final isSick = item.requestType == 'sick';
    final typeLabel = isSick ? 'SAKIT' : 'IZIN';
    final typeFg = isSick ? AppColors.warning : AppColors.primary;
    final typeBg = isSick ? AppColors.warningTint : AppColors.primaryTint;

    final dateRangeText = item.startDate == item.endDate
        ? AppFormatters.formatIndonesianDate(item.startDate)
        : '${AppFormatters.formatIndonesianDate(item.startDate)} – ${AppFormatters.formatIndonesianDate(item.endDate)}';

    final attachmentName = item.attachmentUrl != null &&
            item.attachmentUrl!.trim().isNotEmpty
        ? _extractAttachmentName(item.attachmentUrl!)
        : null;

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
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                radius: 21,
                backgroundColor: typeBg,
                child: Text(
                  AppFormatters.initials(item.studentName),
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800,
                    color: typeFg,
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
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${item.className} • NIS ${item.studentNis}',
                      style: const TextStyle(
                        fontSize: 12.5,
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: typeBg,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  typeLabel,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                    color: typeFg,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              const Icon(
                Icons.date_range_rounded,
                size: 15,
                color: AppColors.textMuted,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  dateRangeText,
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              const Icon(
                Icons.chat_bubble_outline_rounded,
                size: 14,
                color: AppColors.textMuted,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'Dari ${item.parentName} (${item.parentPhoneWa})',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.background,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              item.reason,
              style: const TextStyle(
                fontSize: 13.5,
                height: 1.4,
                color: AppColors.textPrimary,
              ),
            ),
          ),
          if (attachmentName != null) ...[
            const SizedBox(height: 10),
            InkWell(
              onTap: onTapAttachment,
              borderRadius: BorderRadius.circular(999),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: AppColors.primaryTint,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(
                    color: AppColors.primary.withValues(alpha: 0.25),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.attach_file_rounded,
                      size: 15,
                      color: AppColors.primary,
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        attachmentName,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 14),
          if (item.status == 'pending')
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.danger,
                      side: const BorderSide(color: AppColors.danger),
                    ),
                    onPressed: isProcessing ? null : onReject,
                    icon: const Icon(Icons.close_rounded, size: 18),
                    label: const Text('Tolak'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  flex: 2,
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.success,
                    ),
                    onPressed: isProcessing ? null : onApprove,
                    icon: isProcessing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.check_rounded, size: 18),
                    label: const Text('Setujui & Kabari WA'),
                  ),
                ),
              ],
            )
          else
            _buildDecisionFooter(),
        ],
      ),
    );
  }

  Widget _buildDecisionFooter() {
    final isApproved = item.status == 'approved';
    final badgeFg = isApproved ? AppColors.success : AppColors.danger;
    final badgeBg = isApproved ? AppColors.successTint : AppColors.dangerTint;
    final badgeLabel = isApproved ? 'DISETUJUI' : 'DITOLAK';

    return Row(
      children: [
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
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            item.verifiedByName != null
                ? 'Oleh ${item.verifiedByName} • ${AppFormatters.formatWibDateTime(item.verifiedAt)}'
                : AppFormatters.formatWibDateTime(item.verifiedAt),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 11.5,
              color: AppColors.textSecondary,
            ),
          ),
        ),
      ],
    );
  }
}

String _extractAttachmentName(String rawUrl) {
  final parsed = Uri.tryParse(rawUrl);
  if (parsed != null && parsed.pathSegments.isNotEmpty) {
    final nonEmpty = parsed.pathSegments.where((seg) => seg.isNotEmpty).toList();
    if (nonEmpty.isNotEmpty) return nonEmpty.last;
  }
  final parts = rawUrl.split('/').where((part) => part.isNotEmpty).toList();
  return parts.isNotEmpty ? parts.last : rawUrl;
}
