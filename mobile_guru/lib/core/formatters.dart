import 'package:flutter/material.dart';

import 'theme.dart';

const List<String> _indonesianDays = [
  'Senin',
  'Selasa',
  'Rabu',
  'Kamis',
  'Jumat',
  'Sabtu',
  'Minggu',
];

const List<String> _indonesianMonthsShort = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'Mei',
  'Jun',
  'Jul',
  'Agu',
  'Sep',
  'Okt',
  'Nov',
  'Des',
];

/// Utilitas pemformatan tanggal, waktu WIB, inisial nama, dan label status Bahasa Indonesia.
abstract final class AppFormatters {
  /// Mengonversi tanggal ISO (`YYYY-MM-DD`) menjadi format `Senin, 23 Nov 2026`.
  static String formatIndonesianDate(String? isoDate) {
    if (isoDate == null || isoDate.trim().isEmpty) return '-';
    final parsed = DateTime.tryParse(isoDate);
    if (parsed == null) return isoDate;
    final dayName = _indonesianDays[(parsed.weekday - 1).clamp(0, 6)];
    final monthName = _indonesianMonthsShort[(parsed.month - 1).clamp(0, 11)];
    return '$dayName, ${parsed.day} $monthName ${parsed.year}';
  }

  /// Memotong string waktu (`HH:MM:SS`) menjadi `HH:MM`.
  static String formatTimeShort(String? timeStr) {
    if (timeStr == null || timeStr.trim().isEmpty) return '-';
    final parts = timeStr.split(':');
    if (parts.length >= 2) {
      return '${parts[0].padLeft(2, '0')}:${parts[1].padLeft(2, '0')}';
    }
    return timeStr;
  }

  /// Mengonversi timestamp ke waktu WIB (`UTC+7`) berformat `HH:mm WIB`.
  static String formatWibTime(DateTime? dt) {
    if (dt == null) return '-';
    final wib = dt.toUtc().add(const Duration(hours: 7));
    final hh = wib.hour.toString().padLeft(2, '0');
    final mm = wib.minute.toString().padLeft(2, '0');
    return '$hh:$mm WIB';
  }

  /// Mengonversi timestamp ke tanggal + jam WIB berformat `dd MMM yyyy, HH:mm WIB`.
  static String formatWibDateTime(DateTime? dt) {
    if (dt == null) return '-';
    final wib = dt.toUtc().add(const Duration(hours: 7));
    final dd = wib.day.toString().padLeft(2, '0');
    final monthName = _indonesianMonthsShort[(wib.month - 1).clamp(0, 11)];
    final hh = wib.hour.toString().padLeft(2, '0');
    final mm = wib.minute.toString().padLeft(2, '0');
    return '$dd $monthName ${wib.year}, $hh:$mm WIB';
  }

  /// Mengambil maksimal 2 huruf inisial nama untuk avatar.
  static String initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+')).where((e) => e.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    if (parts.length == 1) {
      return parts.first.substring(0, parts.first.length >= 2 ? 2 : 1).toUpperCase();
    }
    return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
  }

  static String sessionTypeLabel(String sessionType) {
    switch (sessionType) {
      case 'gate_in':
        return 'Gerbang Masuk';
      case 'gate_out':
        return 'Gerbang Pulang';
      case 'subject':
        return 'Mata Pelajaran';
      default:
        return sessionType;
    }
  }

  static String attendanceStatusLabel(String status) {
    switch (status) {
      case 'present':
        return 'Hadir';
      case 'late':
        return 'Terlambat';
      case 'permit':
        return 'Izin';
      case 'sick':
        return 'Sakit';
      case 'absent':
        return 'Alfa';
      case 'unrecorded':
        return 'Belum';
      default:
        return status;
    }
  }

  static String verificationMethodLabel(String? method) {
    switch (method) {
      case 'face_kiosk':
      case 'face_recognition':
        return 'Scan Wajah Kiosk';
      case 'manual_teacher':
        return 'Manual Guru';
      case 'leave_approved':
      case 'chatbot_leave':
        return 'Izin Disetujui';
      default:
        return '-';
    }
  }

  static ({Color fg, Color bg}) attendanceStatusColors(String status) {
    switch (status) {
      case 'present':
        return (fg: AppColors.success, bg: AppColors.successTint);
      case 'late':
        return (fg: AppColors.warning, bg: AppColors.warningTint);
      case 'permit':
      case 'sick':
        return (fg: AppColors.primary, bg: AppColors.primaryTint);
      case 'absent':
        return (fg: AppColors.danger, bg: AppColors.dangerTint);
      case 'unrecorded':
      default:
        return (fg: AppColors.textSecondary, bg: const Color(0xFFF1F5F9));
    }
  }
}
