final RegExp _isoDateTimePattern = RegExp(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}');
final RegExp _timezoneSuffixPattern = RegExp(r'(?:[zZ]|[+-]\d{2}:?\d{2})$');

/// Mengurai timestamp ISO dari backend secara aman.
/// String date-time tanpa penanda zona waktu (`Z` atau offset `±HH:MM`)
/// diperlakukan sebagai UTC dengan menambahkan `'Z'` sebelum `DateTime.tryParse`
/// agar konversi ke WIB (`UTC+7`) tidak meleset -7 jam.
DateTime? parseNullableDateTime(dynamic value) {
  if (value == null) return null;
  if (value is DateTime) return value;
  final raw = value.toString().trim();
  if (raw.isEmpty) return null;
  var candidate = raw;
  if (_isoDateTimePattern.hasMatch(candidate) &&
      !_timezoneSuffixPattern.hasMatch(candidate)) {
    candidate = '${candidate.replaceFirst(' ', 'T')}Z';
  }
  return DateTime.tryParse(candidate);
}

DateTime? _parseNullableDateTime(dynamic value) => parseNullableDateTime(value);

DateTime _parseRequiredDateTime(dynamic value) {
  final parsed = _parseNullableDateTime(value);
  return parsed ?? DateTime.now().toUtc();
}

int _asInt(dynamic value, [int fallback = 0]) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? fallback;
}

double _asDouble(dynamic value, [double fallback = 0.0]) {
  if (value is double) return value;
  if (value is num) return value.toDouble();
  return double.tryParse(value?.toString() ?? '') ?? fallback;
}

double? _asNullableDouble(dynamic value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

/// Profil pengguna terautentikasi (`UserResponse` di `backend/app/schemas.py`).
class UserProfile {
  const UserProfile({
    required this.id,
    required this.name,
    required this.email,
    required this.role,
    required this.nip,
    required this.hasKioskPin,
  });

  final String id;
  final String name;
  final String email;
  final String role;
  final String? nip;
  final bool hasKioskPin;

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      id: json['id'] as String,
      name: json['name'] as String,
      email: json['email'] as String,
      role: json['role'] as String,
      nip: json['nip'] as String?,
      hasKioskPin: json['has_kiosk_pin'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'email': email,
      'role': role,
      'nip': nip,
      'has_kiosk_pin': hasKioskPin,
    };
  }

  UserProfile copyWith({
    String? id,
    String? name,
    String? email,
    String? role,
    String? nip,
    bool? hasKioskPin,
  }) {
    return UserProfile(
      id: id ?? this.id,
      name: name ?? this.name,
      email: email ?? this.email,
      role: role ?? this.role,
      nip: nip ?? this.nip,
      hasKioskPin: hasKioskPin ?? this.hasKioskPin,
    );
  }
}

/// Respons login (`LoginResponse` di `backend/app/schemas.py`).
class LoginResult {
  const LoginResult({
    required this.accessToken,
    required this.tokenType,
    required this.user,
  });

  final String accessToken;
  final String tokenType;
  final UserProfile user;

  factory LoginResult.fromJson(Map<String, dynamic> json) {
    return LoginResult(
      accessToken: json['access_token'] as String,
      tokenType: json['token_type'] as String? ?? 'bearer',
      user: UserProfile.fromJson(json['user'] as Map<String, dynamic>),
    );
  }
}

/// Hasil verifikasi PIN Kiosk (`VerifyPinResponse` di `backend/app/schemas.py`).
class VerifyPinResult {
  const VerifyPinResult({
    required this.valid,
    required this.hasKioskPin,
  });

  final bool valid;
  final bool hasKioskPin;

  factory VerifyPinResult.fromJson(Map<String, dynamic> json) {
    return VerifyPinResult(
      valid: json['valid'] as bool? ?? false,
      hasKioskPin: json['has_kiosk_pin'] as bool? ?? true,
    );
  }
}

/// Data siswa aktif (`StudentResponse` dari `GET /api/v1/students`).
class StudentListItem {
  const StudentListItem({
    required this.id,
    required this.nis,
    required this.name,
    required this.classId,
    required this.className,
    required this.parentId,
    required this.parentName,
    required this.parentPhoneWa,
    required this.isActive,
    required this.faceCount,
    required this.createdAt,
  });

  final String id;
  final String nis;
  final String name;
  final String classId;
  final String className;
  final String parentId;
  final String parentName;
  final String parentPhoneWa;
  final bool isActive;
  final int faceCount;
  final DateTime createdAt;

  factory StudentListItem.fromJson(Map<String, dynamic> json) {
    return StudentListItem(
      id: json['id'] as String,
      nis: json['nis'] as String,
      name: json['name'] as String,
      classId: json['class_id'] as String,
      className: json['class_name'] as String,
      parentId: json['parent_id'] as String,
      parentName: json['parent_name'] as String,
      parentPhoneWa: json['parent_phone_wa'] as String,
      isActive: json['is_active'] as bool? ?? true,
      faceCount: _asInt(json['face_count']),
      createdAt: _parseRequiredDateTime(json['created_at']),
    );
  }

  /// Mengonversi data master siswa menjadi item presensi `unrecorded` untuk picker manual.
  StudentAttendanceItem toUnrecordedAttendanceItem() {
    return StudentAttendanceItem(
      studentId: id,
      nis: nis,
      studentName: name,
      classId: classId,
      className: className,
      parentPhoneWa: parentPhoneWa,
      attendanceId: null,
      status: 'unrecorded',
      verificationMethod: null,
      scannedAt: null,
      similarityScore: null,
      waStatus: null,
      waNotifiedAt: null,
    );
  }
}

/// Data kelas akademik (`SchoolClassResponse`).
class SchoolClassItem {
  const SchoolClassItem({
    required this.id,
    required this.name,
    required this.homeroomTeacherId,
    required this.homeroomTeacherName,
    required this.studentCount,
    required this.createdAt,
  });

  final String id;
  final String name;
  final String? homeroomTeacherId;
  final String? homeroomTeacherName;
  final int studentCount;
  final DateTime createdAt;

  factory SchoolClassItem.fromJson(Map<String, dynamic> json) {
    return SchoolClassItem(
      id: json['id'] as String,
      name: json['name'] as String,
      homeroomTeacherId: json['homeroom_teacher_id'] as String?,
      homeroomTeacherName: json['homeroom_teacher_name'] as String?,
      studentCount: _asInt(json['student_count']),
      createdAt: _parseRequiredDateTime(json['created_at']),
    );
  }
}

/// Jadwal mata pelajaran mingguan (`ScheduleResponse`).
class ScheduleItem {
  const ScheduleItem({
    required this.id,
    required this.classId,
    required this.className,
    required this.teacherId,
    required this.teacherName,
    required this.subjectName,
    required this.dayOfWeek,
    required this.startTime,
    required this.endTime,
    required this.lateToleranceMinutes,
  });

  final String id;
  final String classId;
  final String className;
  final String teacherId;
  final String teacherName;
  final String subjectName;
  final int dayOfWeek;
  final String startTime;
  final String endTime;
  final int lateToleranceMinutes;

  factory ScheduleItem.fromJson(Map<String, dynamic> json) {
    return ScheduleItem(
      id: json['id'] as String,
      classId: json['class_id'] as String,
      className: json['class_name'] as String,
      teacherId: json['teacher_id'] as String,
      teacherName: json['teacher_name'] as String,
      subjectName: json['subject_name'] as String,
      dayOfWeek: _asInt(json['day_of_week'], 1),
      startTime: json['start_time'] as String,
      endTime: json['end_time'] as String,
      lateToleranceMinutes: _asInt(json['late_tolerance_minutes'], 15),
    );
  }
}

/// Penghitung ringkas status kehadiran sesi (`SessionSummaryCounters`).
class SessionSummaryCounters {
  const SessionSummaryCounters({
    required this.totalStudents,
    required this.presentCount,
    required this.lateCount,
    required this.permitCount,
    required this.sickCount,
    required this.absentCount,
    required this.unrecordedCount,
    required this.recordedCount,
  });

  final int totalStudents;
  final int presentCount;
  final int lateCount;
  final int permitCount;
  final int sickCount;
  final int absentCount;
  final int unrecordedCount;
  final int recordedCount;

  int get permitOrSickCount => permitCount + sickCount;

  factory SessionSummaryCounters.fromJson(Map<String, dynamic> json) {
    return SessionSummaryCounters(
      totalStudents: _asInt(json['total_students']),
      presentCount: _asInt(json['present_count']),
      lateCount: _asInt(json['late_count']),
      permitCount: _asInt(json['permit_count']),
      sickCount: _asInt(json['sick_count']),
      absentCount: _asInt(json['absent_count']),
      unrecordedCount: _asInt(json['unrecorded_count']),
      recordedCount: _asInt(json['recorded_count']),
    );
  }
}

/// Ringkasan satu sesi presensi (`AttendanceSessionSummary`).
class SessionSummary {
  const SessionSummary({
    required this.id,
    required this.classId,
    required this.className,
    required this.teacherId,
    required this.teacherName,
    required this.scheduleId,
    required this.subjectName,
    required this.sessionType,
    required this.sessionDate,
    required this.expectedStartTime,
    required this.lateToleranceMinutes,
    required this.openedAt,
    required this.closedAt,
    required this.status,
    required this.totalStudents,
    required this.presentCount,
    required this.lateCount,
    required this.permitCount,
    required this.sickCount,
    required this.absentCount,
    required this.unrecordedCount,
    required this.recordedCount,
  });

  final String id;
  final String? classId;
  final String? className;
  final String teacherId;
  final String? teacherName;
  final String? scheduleId;
  final String? subjectName;
  final String sessionType;
  final String sessionDate;
  final String? expectedStartTime;
  final int lateToleranceMinutes;
  final DateTime openedAt;
  final DateTime? closedAt;
  final String status;
  final int totalStudents;
  final int presentCount;
  final int lateCount;
  final int permitCount;
  final int sickCount;
  final int absentCount;
  final int unrecordedCount;
  final int recordedCount;

  bool get isOpen => status == 'open';

  String get displayTitle {
    if (subjectName != null && subjectName!.trim().isNotEmpty) {
      return subjectName!;
    }
    switch (sessionType) {
      case 'gate_in':
        return 'Presensi Gerbang Masuk';
      case 'gate_out':
        return 'Presensi Gerbang Pulang';
      default:
        return 'Sesi Presensi Kelas';
    }
  }

  String get displayClassName => className ?? 'Semua Kelas (Gerbang)';

  factory SessionSummary.fromJson(Map<String, dynamic> json) {
    return SessionSummary(
      id: json['id'] as String,
      classId: json['class_id'] as String?,
      className: json['class_name'] as String?,
      teacherId: json['teacher_id'] as String,
      teacherName: json['teacher_name'] as String?,
      scheduleId: json['schedule_id'] as String?,
      subjectName: json['subject_name'] as String?,
      sessionType: json['session_type'] as String,
      sessionDate: json['session_date'] as String,
      expectedStartTime: json['expected_start_time'] as String?,
      lateToleranceMinutes: _asInt(json['late_tolerance_minutes'], 15),
      openedAt: _parseRequiredDateTime(json['opened_at']),
      closedAt: _parseNullableDateTime(json['closed_at']),
      status: json['status'] as String,
      totalStudents: _asInt(json['total_students']),
      presentCount: _asInt(json['present_count']),
      lateCount: _asInt(json['late_count']),
      permitCount: _asInt(json['permit_count']),
      sickCount: _asInt(json['sick_count']),
      absentCount: _asInt(json['absent_count']),
      unrecordedCount: _asInt(json['unrecorded_count']),
      recordedCount: _asInt(json['recorded_count']),
    );
  }
}

/// Status kehadiran satu siswa dalam sesi (`SessionStudentAttendanceItem`).
class StudentAttendanceItem {
  const StudentAttendanceItem({
    required this.studentId,
    required this.nis,
    required this.studentName,
    required this.classId,
    required this.className,
    required this.parentPhoneWa,
    required this.attendanceId,
    required this.status,
    required this.verificationMethod,
    required this.scannedAt,
    required this.similarityScore,
    required this.waStatus,
    required this.waNotifiedAt,
  });

  final String studentId;
  final String nis;
  final String studentName;
  final String classId;
  final String className;
  final String parentPhoneWa;
  final String? attendanceId;
  final String status;
  final String? verificationMethod;
  final DateTime? scannedAt;
  final double? similarityScore;
  final String? waStatus;
  final DateTime? waNotifiedAt;

  factory StudentAttendanceItem.fromJson(Map<String, dynamic> json) {
    return StudentAttendanceItem(
      studentId: json['student_id'] as String,
      nis: json['nis'] as String,
      studentName: json['student_name'] as String,
      classId: json['class_id'] as String,
      className: json['class_name'] as String,
      parentPhoneWa: json['parent_phone_wa'] as String,
      attendanceId: json['attendance_id'] as String?,
      status: json['status'] as String,
      verificationMethod: json['verification_method'] as String?,
      scannedAt: _parseNullableDateTime(json['scanned_at']),
      similarityScore: _asNullableDouble(json['similarity_score']),
      waStatus: json['wa_status'] as String?,
      waNotifiedAt: _parseNullableDateTime(json['wa_notified_at']),
    );
  }
}

/// Detail lengkap sesi presensi beserta daftar siswa (`AttendanceSessionDetailResponse`).
class SessionDetail {
  const SessionDetail({
    required this.id,
    required this.classId,
    required this.className,
    required this.teacherId,
    required this.teacherName,
    required this.scheduleId,
    required this.subjectName,
    required this.sessionType,
    required this.sessionDate,
    required this.expectedStartTime,
    required this.lateToleranceMinutes,
    required this.openedAt,
    required this.closedAt,
    required this.status,
    required this.summary,
    required this.students,
  });

  final String id;
  final String? classId;
  final String? className;
  final String teacherId;
  final String? teacherName;
  final String? scheduleId;
  final String? subjectName;
  final String sessionType;
  final String sessionDate;
  final String? expectedStartTime;
  final int lateToleranceMinutes;
  final DateTime openedAt;
  final DateTime? closedAt;
  final String status;
  final SessionSummaryCounters summary;
  final List<StudentAttendanceItem> students;

  bool get isOpen => status == 'open';

  String get displayTitle {
    if (subjectName != null && subjectName!.trim().isNotEmpty) {
      return subjectName!;
    }
    switch (sessionType) {
      case 'gate_in':
        return 'Presensi Gerbang Masuk';
      case 'gate_out':
        return 'Presensi Gerbang Pulang';
      default:
        return 'Sesi Presensi Kelas';
    }
  }

  String get displayClassName => className ?? 'Semua Kelas (Gerbang)';

  SessionSummary toSummary() {
    return SessionSummary(
      id: id,
      classId: classId,
      className: className,
      teacherId: teacherId,
      teacherName: teacherName,
      scheduleId: scheduleId,
      subjectName: subjectName,
      sessionType: sessionType,
      sessionDate: sessionDate,
      expectedStartTime: expectedStartTime,
      lateToleranceMinutes: lateToleranceMinutes,
      openedAt: openedAt,
      closedAt: closedAt,
      status: status,
      totalStudents: summary.totalStudents,
      presentCount: summary.presentCount,
      lateCount: summary.lateCount,
      permitCount: summary.permitCount,
      sickCount: summary.sickCount,
      absentCount: summary.absentCount,
      unrecordedCount: summary.unrecordedCount,
      recordedCount: summary.recordedCount,
    );
  }

  factory SessionDetail.fromJson(Map<String, dynamic> json) {
    final rawSummary = json['summary'] as Map<String, dynamic>?;
    final summary = rawSummary != null
        ? SessionSummaryCounters.fromJson(rawSummary)
        : SessionSummaryCounters.fromJson(json);
    final rawStudents = json['students'] as List<dynamic>? ?? const [];

    return SessionDetail(
      id: json['id'] as String,
      classId: json['class_id'] as String?,
      className: json['class_name'] as String?,
      teacherId: json['teacher_id'] as String,
      teacherName: json['teacher_name'] as String?,
      scheduleId: json['schedule_id'] as String?,
      subjectName: json['subject_name'] as String?,
      sessionType: json['session_type'] as String,
      sessionDate: json['session_date'] as String,
      expectedStartTime: json['expected_start_time'] as String?,
      lateToleranceMinutes: _asInt(json['late_tolerance_minutes'], 15),
      openedAt: _parseRequiredDateTime(json['opened_at']),
      closedAt: _parseNullableDateTime(json['closed_at']),
      status: json['status'] as String,
      summary: summary,
      students: rawStudents
          .map((item) => StudentAttendanceItem.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// Statistik ringkas beranda guru (`TeacherDashboardStats`).
class TeacherDashboardStats {
  const TeacherDashboardStats({
    required this.presentRate,
    required this.presentCount,
    required this.lateCount,
    required this.pendingLeavesCount,
  });

  final double presentRate;
  final int presentCount;
  final int lateCount;
  final int pendingLeavesCount;

  factory TeacherDashboardStats.fromJson(Map<String, dynamic> json) {
    return TeacherDashboardStats(
      presentRate: _asDouble(json['present_rate']),
      presentCount: _asInt(json['present_count']),
      lateCount: _asInt(json['late_count']),
      pendingLeavesCount: _asInt(json['pending_leaves_count']),
    );
  }
}

/// Payload beranda guru (`TeacherDashboardResponse`).
class TeacherDashboardData {
  const TeacherDashboardData({
    required this.teacherName,
    required this.todayDate,
    required this.stats,
    required this.sessions,
    required this.todaySchedules,
  });

  final String teacherName;
  final String todayDate;
  final TeacherDashboardStats stats;
  final List<SessionSummary> sessions;
  final List<ScheduleItem> todaySchedules;

  factory TeacherDashboardData.fromJson(Map<String, dynamic> json) {
    final rawSessions = json['sessions'] as List<dynamic>? ?? const [];
    final rawSchedules = json['today_schedules'] as List<dynamic>? ?? const [];
    return TeacherDashboardData(
      teacherName: json['teacher_name'] as String,
      todayDate: json['today_date'] as String,
      stats: TeacherDashboardStats.fromJson(json['stats'] as Map<String, dynamic>),
      sessions: rawSessions
          .map((item) => SessionSummary.fromJson(item as Map<String, dynamic>))
          .toList(),
      todaySchedules: rawSchedules
          .map((item) => ScheduleItem.fromJson(item as Map<String, dynamic>))
          .toList(),
    );
  }
}

/// Hasil scan wajah Kiosk (`AttendanceScanResponse`).
class ScanResult {
  const ScanResult({
    required this.matched,
    required this.alreadyRecorded,
    required this.attendanceId,
    required this.studentId,
    required this.studentName,
    required this.nis,
    required this.className,
    required this.status,
    required this.scannedAt,
    required this.similarityScore,
    required this.thresholdUsed,
    required this.waStatus,
    required this.waQueued,
    required this.message,
  });

  final bool matched;
  final bool alreadyRecorded;
  final String? attendanceId;
  final String? studentId;
  final String? studentName;
  final String? nis;
  final String? className;
  final String? status;
  final DateTime? scannedAt;
  final double similarityScore;
  final double thresholdUsed;
  final String? waStatus;
  final bool waQueued;
  final String message;

  factory ScanResult.fromJson(Map<String, dynamic> json) {
    return ScanResult(
      matched: json['matched'] as bool? ?? false,
      alreadyRecorded: json['already_recorded'] as bool? ?? false,
      attendanceId: json['attendance_id'] as String?,
      studentId: json['student_id'] as String?,
      studentName: json['student_name'] as String?,
      nis: json['nis'] as String?,
      className: json['class_name'] as String?,
      status: json['status'] as String?,
      scannedAt: _parseNullableDateTime(json['scanned_at']),
      similarityScore: _asDouble(json['similarity_score']),
      thresholdUsed: _asDouble(json['threshold_used']),
      waStatus: json['wa_status'] as String?,
      waQueued: json['wa_queued'] as bool? ?? false,
      message: json['message'] as String? ?? '',
    );
  }
}

/// Hasil input presensi manual oleh guru (`ManualAttendanceResponse`).
class ManualAttendanceResult {
  const ManualAttendanceResult({
    required this.attendanceId,
    required this.sessionId,
    required this.studentId,
    required this.studentName,
    required this.nis,
    required this.className,
    required this.status,
    required this.verificationMethod,
    required this.scannedAt,
    required this.waStatus,
    required this.waNotifiedAt,
    required this.message,
  });

  final String attendanceId;
  final String sessionId;
  final String studentId;
  final String studentName;
  final String nis;
  final String className;
  final String status;
  final String verificationMethod;
  final DateTime? scannedAt;
  final String waStatus;
  final DateTime? waNotifiedAt;
  final String message;

  factory ManualAttendanceResult.fromJson(Map<String, dynamic> json) {
    return ManualAttendanceResult(
      attendanceId: json['attendance_id'] as String,
      sessionId: json['session_id'] as String,
      studentId: json['student_id'] as String,
      studentName: json['student_name'] as String,
      nis: json['nis'] as String,
      className: json['class_name'] as String,
      status: json['status'] as String,
      verificationMethod: json['verification_method'] as String,
      scannedAt: _parseNullableDateTime(json['scanned_at']),
      waStatus: json['wa_status'] as String,
      waNotifiedAt: _parseNullableDateTime(json['wa_notified_at']),
      message: json['message'] as String,
    );
  }
}

/// Hasil pengiriman ulang notifikasi WA orang tua (`ResendWaResponse`).
class ResendWaResult {
  const ResendWaResult({
    required this.attendanceId,
    required this.waStatus,
    required this.waSent,
    required this.waNotifiedAt,
    required this.message,
  });

  final String attendanceId;
  final String waStatus;
  final bool waSent;
  final DateTime? waNotifiedAt;
  final String message;

  factory ResendWaResult.fromJson(Map<String, dynamic> json) {
    return ResendWaResult(
      attendanceId: json['attendance_id'] as String,
      waStatus: json['wa_status'] as String,
      waSent: json['wa_sent'] as bool? ?? false,
      waNotifiedAt: _parseNullableDateTime(json['wa_notified_at']),
      message: json['message'] as String,
    );
  }
}

/// Pengajuan izin/sakit siswa (`LeaveRequestResponse`).
class LeaveRequestItem {
  const LeaveRequestItem({
    required this.id,
    required this.studentId,
    required this.studentName,
    required this.studentNis,
    required this.classId,
    required this.className,
    required this.parentId,
    required this.parentName,
    required this.parentPhoneWa,
    required this.requestType,
    required this.startDate,
    required this.endDate,
    required this.reason,
    required this.attachmentUrl,
    required this.status,
    required this.verifiedBy,
    required this.verifiedByName,
    required this.verifiedAt,
    this.verificationNote,
    required this.createdAt,
  });

  final String id;
  final String studentId;
  final String studentName;
  final String studentNis;
  final String classId;
  final String className;
  final String parentId;
  final String parentName;
  final String parentPhoneWa;
  final String requestType;
  final String startDate;
  final String endDate;
  final String reason;
  final String? attachmentUrl;
  final String status;
  final String? verifiedBy;
  final String? verifiedByName;
  final DateTime? verifiedAt;
  final String? verificationNote;
  final DateTime createdAt;

  factory LeaveRequestItem.fromJson(Map<String, dynamic> json) {
    return LeaveRequestItem(
      id: json['id'] as String,
      studentId: json['student_id'] as String,
      studentName: json['student_name'] as String,
      studentNis: json['student_nis'] as String,
      classId: json['class_id'] as String,
      className: json['class_name'] as String,
      parentId: json['parent_id'] as String,
      parentName: json['parent_name'] as String,
      parentPhoneWa: json['parent_phone_wa'] as String,
      requestType: json['request_type'] as String,
      startDate: json['start_date'] as String,
      endDate: json['end_date'] as String,
      reason: json['reason'] as String,
      attachmentUrl: json['attachment_url'] as String?,
      status: json['status'] as String,
      verifiedBy: json['verified_by'] as String?,
      verifiedByName: json['verified_by_name'] as String?,
      verifiedAt: _parseNullableDateTime(json['verified_at']),
      verificationNote: json['verification_note'] as String?,
      createdAt: _parseRequiredDateTime(json['created_at']),
    );
  }
}

/// Hasil verifikasi izin/sakit (`LeaveVerifyResponse`).
class LeaveVerifyResult {
  const LeaveVerifyResult({
    required this.leave,
    required this.syncedSessionsCount,
    required this.waSent,
    required this.message,
  });

  final LeaveRequestItem leave;
  final int syncedSessionsCount;
  final bool waSent;
  final String message;

  factory LeaveVerifyResult.fromJson(Map<String, dynamic> json) {
    return LeaveVerifyResult(
      leave: LeaveRequestItem.fromJson(json['leave'] as Map<String, dynamic>),
      syncedSessionsCount: _asInt(json['synced_sessions_count']),
      waSent: json['wa_sent'] as bool? ?? false,
      message: json['message'] as String,
    );
  }
}
