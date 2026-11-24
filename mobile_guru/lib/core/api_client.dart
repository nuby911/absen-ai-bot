import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../models/models.dart';

/// Abstraksi penyimpanan key-value agar client dapat diuji tanpa platform channel.
abstract class KeyValueStorage {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

/// Penyimpanan terenkripsi berbasis `FlutterSecureStorage`.
class SecureKeyValueStorage implements KeyValueStorage {
  SecureKeyValueStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(String key, String value) async {
    try {
      await _storage.write(key: key, value: value);
    } catch (_) {
      // Abaikan kegagalan platform channel saat lingkungan uji.
    }
  }

  @override
  Future<void> delete(String key) async {
    try {
      await _storage.delete(key: key);
    } catch (_) {
      // Abaikan kegagalan platform channel saat lingkungan uji.
    }
  }
}

/// Penyimpanan in-memory untuk pengujian unit dan widget.
class MemoryKeyValueStorage implements KeyValueStorage {
  final Map<String, String> _data = {};

  @override
  Future<String?> read(String key) async => _data[key];

  @override
  Future<void> write(String key, String value) async {
    _data[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    _data.remove(key);
  }
}

/// Pengecualian terstruktur untuk seluruh kesalahan HTTP dan jaringan API FastAPI.
class ApiException implements Exception {
  const ApiException({
    required this.statusCode,
    required this.message,
    this.detail,
  });

  final int statusCode;
  final String message;
  final dynamic detail;

  @override
  String toString() => message;
}

/// Client REST API terketik untuk layanan backend SmartSchool AI.
class ApiClient {
  ApiClient({
    String? baseUrl,
    Dio? dio,
    KeyValueStorage? storage,
    this.onUnauthorized,
  })  : _baseUrl = _normalizeBaseUrl(baseUrl ?? defaultBaseUrl),
        _storage = storage ?? SecureKeyValueStorage(),
        _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: _normalizeBaseUrl(baseUrl ?? defaultBaseUrl),
                connectTimeout: const Duration(seconds: 15),
                receiveTimeout: const Duration(seconds: 30),
                sendTimeout: const Duration(seconds: 30),
                headers: const {'Accept': 'application/json'},
              ),
            ) {
    _dio.options.baseUrl = _baseUrl;
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = _accessToken;
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) {
          if (error.response?.statusCode == 401 &&
              !_isRestoringSession &&
              !error.requestOptions.path.endsWith('/auth/login')) {
            onUnauthorized?.call();
          }
          handler.next(error);
        },
      ),
    );
  }

  static const String defaultBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );

  static const String _tokenKey = 'smartschool_guru_token';
  static const String _userKey = 'smartschool_guru_user';
  static const String _baseUrlKey = 'smartschool_guru_base_url';

  final Dio _dio;
  final KeyValueStorage _storage;
  VoidCallback? onUnauthorized;

  String _baseUrl;
  String? _accessToken;
  UserProfile? _currentUser;
  bool _isRestoringSession = false;

  String get baseUrl => _baseUrl;
  String? get accessToken => _accessToken;
  UserProfile? get currentUser => _currentUser;

  /// Mengambil origin server (tanpa `/api/v1`) untuk memuat lampiran `/uploads/...`.
  String get apiOrigin {
    if (_baseUrl.endsWith('/api/v1')) {
      return _baseUrl.substring(0, _baseUrl.length - '/api/v1'.length);
    }
    return _baseUrl;
  }

  String? resolveAssetUrl(String? pathOrUrl) {
    if (pathOrUrl == null) return null;
    final trimmed = pathOrUrl.trim();
    if (trimmed.isEmpty) return null;
    final lower = trimmed.toLowerCase();
    if (lower.startsWith('http://') || lower.startsWith('https://')) {
      return trimmed;
    }
    final normalized = trimmed.startsWith('/') ? trimmed : '/$trimmed';
    return '$apiOrigin$normalized';
  }

  /// Memvalidasi URL API (`http`/`https` + host tidak kosong) dan menambahkan `/api/v1` bila belum ada.
  static ({String? url, String? error}) validateAndNormalizeBaseUrl(String raw) {
    var trimmed = raw.trim();
    if (trimmed.isEmpty) {
      return (url: null, error: 'Alamat server API wajib diisi.');
    }
    while (trimmed.endsWith('/')) {
      trimmed = trimmed.substring(0, trimmed.length - 1);
    }
    final uri = Uri.tryParse(trimmed);
    if (uri == null ||
        (uri.scheme.toLowerCase() != 'http' && uri.scheme.toLowerCase() != 'https') ||
        uri.host.trim().isEmpty) {
      return (
        url: null,
        error:
            'URL server tidak valid. Gunakan format http:// atau https:// disertai alamat host (contoh: http://10.0.2.2:8000/api/v1).',
      );
    }
    if (!trimmed.toLowerCase().endsWith('/api/v1')) {
      trimmed = '$trimmed/api/v1';
    }
    return (url: trimmed, error: null);
  }

  static String _normalizeBaseUrl(String raw) {
    var trimmed = raw.trim();
    while (trimmed.endsWith('/')) {
      trimmed = trimmed.substring(0, trimmed.length - 1);
    }
    if (trimmed.isEmpty) {
      return defaultBaseUrl;
    }
    final validated = validateAndNormalizeBaseUrl(trimmed);
    return validated.url ?? trimmed;
  }

  /// Mengubah alamat server API saat runtime dan menyimpannya secara persisten.
  Future<void> setBaseUrl(String newBaseUrl) async {
    final validated = validateAndNormalizeBaseUrl(newBaseUrl);
    if (validated.url == null) {
      throw ApiException(
        statusCode: 0,
        message: validated.error ?? 'URL server tidak valid.',
      );
    }
    final normalized = validated.url!;
    _baseUrl = normalized;
    _dio.options.baseUrl = normalized;
    await _storage.write(_baseUrlKey, normalized);
  }

  /// Memulihkan token, profil pengguna, dan override baseUrl yang tersimpan.
  Future<UserProfile?> loadSavedSession() async {
    final savedUrl = await _storage.read(_baseUrlKey);
    if (savedUrl != null && savedUrl.trim().isNotEmpty) {
      _baseUrl = _normalizeBaseUrl(savedUrl);
      _dio.options.baseUrl = _baseUrl;
    }

    final token = await _storage.read(_tokenKey);
    if (token == null || token.trim().isEmpty) {
      _accessToken = null;
      _currentUser = null;
      return null;
    }

    _accessToken = token;
    final rawUser = await _storage.read(_userKey);
    if (rawUser != null && rawUser.isNotEmpty) {
      try {
        _currentUser = UserProfile.fromJson(
          jsonDecode(rawUser) as Map<String, dynamic>,
        );
      } catch (_) {
        _currentUser = null;
      }
    }

    _isRestoringSession = true;
    try {
      final profile = await getMe();
      _currentUser = profile;
      await _storage.write(_userKey, jsonEncode(profile.toJson()));
      return profile;
    } on ApiException catch (exc) {
      if (exc.statusCode == 401 || exc.statusCode == 403) {
        await logout();
        return null;
      }
      return _currentUser;
    } catch (_) {
      return _currentUser;
    } finally {
      _isRestoringSession = false;
    }
  }

  /// Menyimpan token dan profil pengguna secara manual (juga berguna untuk pengujian).
  Future<void> saveSession(String token, UserProfile user) async {
    _accessToken = token;
    _currentUser = user;
    await _storage.write(_tokenKey, token);
    await _storage.write(_userKey, jsonEncode(user.toJson()));
  }

  /// Menghapus token dan profil sesi aktif dari perangkat.
  Future<void> logout() async {
    _accessToken = null;
    _currentUser = null;
    await _storage.delete(_tokenKey);
    await _storage.delete(_userKey);
  }

  // ---------------------------------------------------------------------------
  // Autentikasi & PIN Kiosk
  // ---------------------------------------------------------------------------

  Future<LoginResult> login({
    required String identifier,
    required String password,
  }) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>(
        '/auth/login',
        data: {
          'identifier': identifier.trim(),
          'password': password,
        },
      ),
    );
    final result = LoginResult.fromJson(data);
    await saveSession(result.accessToken, result.user);
    return result;
  }

  Future<UserProfile> getMe() async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.get<dynamic>('/auth/me'),
    );
    final profile = UserProfile.fromJson(data);
    _currentUser = profile;
    await _storage.write(_userKey, jsonEncode(profile.toJson()));
    return profile;
  }

  Future<void> updateKioskPin(String pin, {String? currentPin}) async {
    final trimmedCurrent = currentPin?.trim();
    await _request<Map<String, dynamic>>(
      () => _dio.put<dynamic>(
        '/auth/kiosk-pin',
        data: {
          'pin': pin.trim(),
          if (trimmedCurrent != null && trimmedCurrent.isNotEmpty)
            'current_pin': trimmedCurrent,
        },
      ),
    );
    if (_currentUser != null) {
      _currentUser = _currentUser!.copyWith(hasKioskPin: true);
      await _storage.write(_userKey, jsonEncode(_currentUser!.toJson()));
    }
  }

  Future<VerifyPinResult> verifyKioskPinResult(String pin) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>(
        '/auth/verify-pin',
        data: {'pin': pin.trim()},
      ),
    );
    final result = VerifyPinResult.fromJson(data);
    if (_currentUser != null && _currentUser!.hasKioskPin != result.hasKioskPin) {
      _currentUser = _currentUser!.copyWith(hasKioskPin: result.hasKioskPin);
      await _storage.write(_userKey, jsonEncode(_currentUser!.toJson()));
    }
    return result;
  }

  Future<bool> verifyKioskPin(String pin) async {
    final result = await verifyKioskPinResult(pin);
    if (!result.hasKioskPin) {
      throw const ApiException(
        statusCode: 403,
        message: 'PIN Kiosk belum diatur. Silakan atur PIN Kiosk terlebih dahulu.',
      );
    }
    return result.valid;
  }

  // ---------------------------------------------------------------------------
  // Dashboard Guru, Kelas, Siswa, Jadwal & Sesi Presensi
  // ---------------------------------------------------------------------------

  Future<TeacherDashboardData> getTeacherDashboard() async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.get<dynamic>('/teacher/dashboard'),
    );
    return TeacherDashboardData.fromJson(data);
  }

  Future<List<SchoolClassItem>> getClasses() async {
    final data = await _request<List<dynamic>>(
      () => _dio.get<dynamic>('/classes'),
    );
    return data
        .map((item) => SchoolClassItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<StudentListItem>> getStudents({
    String? classId,
    bool? isActive = true,
  }) async {
    final query = <String, dynamic>{
      if (classId != null && classId.isNotEmpty) 'class_id': classId,
      'is_active': ?isActive,
    };
    final data = await _request<List<dynamic>>(
      () => _dio.get<dynamic>('/students', queryParameters: query),
    );
    return data
        .map((item) => StudentListItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<List<ScheduleItem>> getSchedules({
    String? classId,
    String? teacherId,
    int? dayOfWeek,
  }) async {
    final query = <String, dynamic>{
      if (classId != null && classId.isNotEmpty) 'class_id': classId,
      if (teacherId != null && teacherId.isNotEmpty) 'teacher_id': teacherId,
      'day_of_week': ?dayOfWeek,
    };
    final data = await _request<List<dynamic>>(
      () => _dio.get<dynamic>('/schedules', queryParameters: query),
    );
    return data
        .map((item) => ScheduleItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<SessionSummary> createSession({
    required String sessionType,
    String? classId,
    String? scheduleId,
    String? sessionDate,
    String? expectedStartTime,
    int? lateToleranceMinutes,
  }) async {
    final payload = <String, dynamic>{
      'session_type': sessionType,
      if (classId != null && classId.isNotEmpty) 'class_id': classId,
      if (scheduleId != null && scheduleId.isNotEmpty) 'schedule_id': scheduleId,
      if (sessionDate != null && sessionDate.isNotEmpty) 'session_date': sessionDate,
      if (expectedStartTime != null && expectedStartTime.isNotEmpty)
        'expected_start_time': expectedStartTime,
      'late_tolerance_minutes': ?lateToleranceMinutes,
    };
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>('/sessions', data: payload),
    );
    return SessionSummary.fromJson(data);
  }

  Future<SessionDetail> getSessionDetail(String sessionId) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.get<dynamic>('/sessions/${Uri.encodeComponent(sessionId)}'),
    );
    return SessionDetail.fromJson(data);
  }

  Future<SessionDetail> closeSession(String sessionId) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>('/sessions/${Uri.encodeComponent(sessionId)}/close'),
    );
    return SessionDetail.fromJson(data);
  }

  // ---------------------------------------------------------------------------
  // Kiosk Scan Wajah, Input Manual & Kirim Ulang WA
  // ---------------------------------------------------------------------------

  Future<ScanResult> scanKioskFace({
    required String sessionId,
    String? imagePath,
    List<int>? imageBytes,
    String filename = 'kiosk_face.jpg',
    bool livenessPassed = true,
    String? conditionNote,
  }) async {
    if (imagePath == null && imageBytes == null) {
      throw const ApiException(
        statusCode: 0,
        message: 'Berkas foto wajah tidak tersedia untuk dipindai.',
      );
    }

    final multipartFile = imageBytes != null
        ? MultipartFile.fromBytes(imageBytes, filename: filename)
        : await MultipartFile.fromFile(imagePath!, filename: filename);

    final formData = FormData.fromMap({
      'session_id': sessionId,
      'liveness_passed': livenessPassed ? 'true' : 'false',
      if (conditionNote != null && conditionNote.trim().isNotEmpty)
        'condition_note': conditionNote.trim(),
      'file': multipartFile,
    });

    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>('/attendance/scan', data: formData),
    );
    return ScanResult.fromJson(data);
  }

  Future<ManualAttendanceResult> submitManualAttendance({
    required String sessionId,
    required String studentId,
    required String status,
    required String kioskPin,
    bool notifyWa = true,
  }) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>(
        '/attendance/manual',
        data: {
          'session_id': sessionId,
          'student_id': studentId,
          'status': status,
          'kiosk_pin': kioskPin.trim(),
          'notify_wa': notifyWa,
        },
      ),
    );
    return ManualAttendanceResult.fromJson(data);
  }

  Future<ResendWaResult> resendWa(String attendanceId) async {
    final data = await _request<Map<String, dynamic>>(
      () => _dio.post<dynamic>(
        '/attendance/${Uri.encodeComponent(attendanceId)}/resend-wa',
      ),
    );
    return ResendWaResult.fromJson(data);
  }

  // ---------------------------------------------------------------------------
  // Verifikasi Pengajuan Izin / Sakit
  // ---------------------------------------------------------------------------

  Future<List<LeaveRequestItem>> getLeaveRequests({
    String? status,
    String? classId,
  }) async {
    final query = <String, dynamic>{
      if (status != null && status.isNotEmpty) 'status': status,
      if (classId != null && classId.isNotEmpty) 'class_id': classId,
    };
    final data = await _request<List<dynamic>>(
      () => _dio.get<dynamic>('/leave-requests', queryParameters: query),
    );
    return data
        .map((item) => LeaveRequestItem.fromJson(item as Map<String, dynamic>))
        .toList();
  }

  Future<LeaveVerifyResult> verifyLeaveRequest({
    required String leaveId,
    required String decision,
    String? note,
  }) async {
    final payload = <String, dynamic>{
      'decision': decision,
      if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
    };
    final data = await _request<Map<String, dynamic>>(
      () => _dio.patch<dynamic>(
        '/leave-requests/${Uri.encodeComponent(leaveId)}/verify',
        data: payload,
      ),
    );
    return LeaveVerifyResult.fromJson(data);
  }

  // ---------------------------------------------------------------------------
  // Internal HTTP Error Handling
  // ---------------------------------------------------------------------------

  Future<T> _request<T>(Future<Response<dynamic>> Function() executor) async {
    try {
      final response = await executor();
      return response.data as T;
    } on DioException catch (exc) {
      throw _mapDioException(exc);
    } on ApiException {
      rethrow;
    } catch (exc) {
      throw ApiException(
        statusCode: 0,
        message: 'Terjadi kesalahan tidak terduga: $exc',
      );
    }
  }

  ApiException _mapDioException(DioException exc) {
    final statusCode = exc.response?.statusCode ?? 0;
    final data = exc.response?.data;

    if (exc.type == DioExceptionType.connectionTimeout ||
        exc.type == DioExceptionType.receiveTimeout ||
        exc.type == DioExceptionType.sendTimeout) {
      return const ApiException(
        statusCode: 0,
        message: 'Koneksi ke server melebihi batas waktu. Periksa jaringan Anda.',
      );
    }

    if (exc.type == DioExceptionType.connectionError || statusCode == 0) {
      return const ApiException(
        statusCode: 0,
        message:
            'Tidak dapat terhubung ke server backend. Pastikan API FastAPI aktif dan URL server benar.',
      );
    }

    final detailMessage = _extractDetailMessage(data);
    if (detailMessage != null && detailMessage.isNotEmpty) {
      return ApiException(
        statusCode: statusCode,
        message: detailMessage,
        detail: data,
      );
    }

    switch (statusCode) {
      case 401:
        return ApiException(
          statusCode: 401,
          message: 'Sesi Anda telah berakhir. Silakan masuk kembali.',
          detail: data,
        );
      case 403:
        return ApiException(
          statusCode: 403,
          message: 'Akses ditolak. Fitur ini hanya tersedia untuk akun Guru.',
          detail: data,
        );
      case 404:
        return ApiException(
          statusCode: 404,
          message: 'Data yang diminta tidak ditemukan.',
          detail: data,
        );
      default:
        return ApiException(
          statusCode: statusCode,
          message: 'Permintaan gagal dengan kode status $statusCode.',
          detail: data,
        );
    }
  }

  String? _extractDetailMessage(dynamic data) {
    if (data is Map<String, dynamic> && data.containsKey('detail')) {
      final detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) {
        return detail.trim();
      }
      if (detail is List && detail.isNotEmpty) {
        final messages = detail
            .map((item) {
              if (item is Map<String, dynamic> && item['msg'] != null) {
                return item['msg'].toString();
              }
              return item?.toString() ?? '';
            })
            .where((text) => text.isNotEmpty)
            .toList();
        if (messages.isNotEmpty) {
          return messages.join('; ');
        }
      }
    }
    return null;
  }
}
