import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smart_school_guru/core/api_client.dart';
import 'package:smart_school_guru/core/theme.dart';
import 'package:smart_school_guru/main.dart';
import 'package:smart_school_guru/models/models.dart';
import 'package:smart_school_guru/screens/home_screen.dart';
import 'package:smart_school_guru/screens/session_detail_screen.dart';

class _StubHttpAdapter implements HttpClientAdapter {
  _StubHttpAdapter(this.handler);

  final dynamic Function(RequestOptions options) handler;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final payload = handler(options);
    final bytes = utf8.encode(jsonEncode(payload));
    return ResponseBody.fromBytes(
      bytes,
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }
}

ApiClient _createStubApiClient(
  dynamic Function(RequestOptions options) handler,
) {
  final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000/api/v1'));
  dio.httpClientAdapter = _StubHttpAdapter(handler);
  return ApiClient(
    baseUrl: 'http://localhost:8000/api/v1',
    dio: dio,
    storage: MemoryKeyValueStorage(),
  );
}

void main() {
  testWidgets('SmartSchoolGuruApp boots to LoginScreen when unauthenticated', (
    WidgetTester tester,
  ) async {
    final apiClient = ApiClient(storage: MemoryKeyValueStorage());

    await tester.pumpWidget(SmartSchoolGuruApp(apiClient: apiClient));
    await tester.pumpAndSettle();

    expect(find.text('SmartSchool AI'), findsOneWidget);
    expect(find.text('Masuk ke Beranda Guru'), findsOneWidget);
    expect(find.text('Politeknik Negeri Lampung • SmartSchool AI'), findsOneWidget);
  });

  testWidgets('HomeScreen parses dashboard JSON and displays KPIs and session badges', (
    WidgetTester tester,
  ) async {
    final apiClient = _createStubApiClient((options) {
      if (options.path == '/teacher/dashboard') {
        return {
          'teacher_name': 'Ibu Sari Wulandari, S.Pd',
          'today_date': '2026-11-23',
          'stats': {
            'present_rate': 87.5,
            'present_count': 28,
            'late_count': 2,
            'pending_leaves_count': 3,
          },
          'sessions': [
            {
              'id': 'sess-1',
              'class_id': 'cls-1',
              'class_name': 'XI IPA 1',
              'teacher_id': 'tch-1',
              'teacher_name': 'Ibu Sari Wulandari, S.Pd',
              'schedule_id': 'sch-1',
              'subject_name': 'Pemrograman Mobile',
              'session_type': 'subject',
              'session_date': '2026-11-23',
              'expected_start_time': '07:30:00',
              'late_tolerance_minutes': 15,
              'opened_at': '2026-11-23T00:25:00Z',
              'closed_at': null,
              'status': 'open',
              'total_students': 32,
              'present_count': 28,
              'late_count': 2,
              'permit_count': 0,
              'sick_count': 0,
              'absent_count': 0,
              'unrecorded_count': 2,
              'recorded_count': 30,
            },
          ],
          'today_schedules': [
            {
              'id': 'sch-2',
              'class_id': 'cls-2',
              'class_name': 'XI IPA 2',
              'teacher_id': 'tch-1',
              'teacher_name': 'Ibu Sari Wulandari, S.Pd',
              'subject_name': 'Basis Data Lanjut',
              'day_of_week': 1,
              'start_time': '09:45:00',
              'end_time': '11:15:00',
              'late_tolerance_minutes': 15,
            },
          ],
        };
      }
      if (options.path == '/leave-requests') {
        return const <dynamic>[];
      }
      return <String, dynamic>{};
    });

    const teacher = UserProfile(
      id: 'tch-1',
      name: 'Ibu Sari Wulandari, S.Pd',
      email: 'sari.wulandari@sekolah.sch.id',
      role: 'teacher',
      nip: '198901012015032001',
      hasKioskPin: true,
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeScreen(apiClient: apiClient, initialUser: teacher),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Ibu Sari Wulandari, S.Pd'), findsOneWidget);
    expect(find.text('88%'), findsOneWidget);
    expect(find.text('Pemrograman Mobile'), findsOneWidget);
    expect(find.text('AKTIF'), findsOneWidget);
    expect(find.text('+ Buka Sesi Presensi Baru'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('Basis Data Lanjut'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Basis Data Lanjut'), findsOneWidget);
    expect(find.text('BELUM'), findsOneWidget);
  });

  testWidgets('SessionDetailScreen renders CTA, student WA indicators, and actions', (
    WidgetTester tester,
  ) async {
    final apiClient = _createStubApiClient((options) {
      if (options.path == '/sessions/sess-1') {
        return {
          'id': 'sess-1',
          'class_id': 'cls-1',
          'class_name': 'XI IPA 1',
          'teacher_id': 'tch-1',
          'teacher_name': 'Ibu Sari Wulandari, S.Pd',
          'schedule_id': 'sch-1',
          'subject_name': 'Pemrograman Mobile',
          'session_type': 'subject',
          'session_date': '2026-11-23',
          'expected_start_time': '07:30:00',
          'late_tolerance_minutes': 15,
          'opened_at': '2026-11-23T00:25:00Z',
          'closed_at': null,
          'status': 'open',
          'total_students': 2,
          'present_count': 1,
          'late_count': 0,
          'permit_count': 0,
          'sick_count': 0,
          'absent_count': 0,
          'unrecorded_count': 1,
          'recorded_count': 1,
          'summary': {
            'total_students': 2,
            'present_count': 1,
            'late_count': 0,
            'permit_count': 0,
            'sick_count': 0,
            'absent_count': 0,
            'unrecorded_count': 1,
            'recorded_count': 1,
          },
          'students': [
            {
              'student_id': 'stu-1',
              'nis': '24781025',
              'student_name': 'Rubby Ibnu Anantara',
              'class_id': 'cls-1',
              'class_name': 'XI IPA 1',
              'parent_phone_wa': '6281279001234',
              'attendance_id': 'att-1',
              'status': 'present',
              'verification_method': 'face_kiosk',
              'scanned_at': '2026-11-23T00:26:00Z',
              'similarity_score': 0.89,
              'wa_status': 'sent',
              'wa_notified_at': '2026-11-23T00:26:02Z',
            },
            {
              'student_id': 'stu-2',
              'nis': '24781007',
              'student_name': 'Deni Prawira',
              'class_id': 'cls-1',
              'class_name': 'XI IPA 1',
              'parent_phone_wa': '6281279001235',
              'attendance_id': null,
              'status': 'unrecorded',
              'verification_method': null,
              'scanned_at': null,
              'similarity_score': null,
              'wa_status': null,
              'wa_notified_at': null,
            },
          ],
        };
      }
      return <String, dynamic>{};
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: SessionDetailScreen(apiClient: apiClient, sessionId: 'sess-1'),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Mulai Mode Kiosk Scan Wajah →'), findsOneWidget);
    expect(find.text('Rubby Ibnu Anantara'), findsOneWidget);
    expect(find.text('WA Ortu ✓'), findsOneWidget);
    expect(find.text('Input Manual (PIN)'), findsOneWidget);
    expect(find.text('Tutup Sesi Kelas'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('Deni Prawira'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Deni Prawira'), findsOneWidget);
  });

  testWidgets('LoginScreen server config dialog opens, updates URL, and disposes cleanly', (
    WidgetTester tester,
  ) async {
    final apiClient = ApiClient(storage: MemoryKeyValueStorage());

    await tester.pumpWidget(SmartSchoolGuruApp(apiClient: apiClient));
    await tester.pumpAndSettle();

    final serverBtn = find.textContaining('Server: ');
    await tester.ensureVisible(serverBtn);
    await tester.tap(serverBtn);
    await tester.pumpAndSettle();

    expect(find.text('Alamat Server Backend'), findsOneWidget);

    await tester.enterText(
      find.byType(TextField).last,
      'http://192.168.1.50:8000/api/v1',
    );
    await tester.tap(find.text('Simpan'));
    await tester.pumpAndSettle();

    expect(apiClient.baseUrl, 'http://192.168.1.50:8000/api/v1');
    expect(tester.takeException(), isNull);

    // Wait for SnackBar to disappear before tapping the bottom server button again
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();

    // Re-open and cancel dialog to verify cancel disposal path is also clean
    final serverBtnAgain = find.textContaining('Server: ');
    await tester.ensureVisible(serverBtnAgain);
    await tester.tap(serverBtnAgain);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Batal'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('CreateSessionDialog handles empty classes safely', (
    WidgetTester tester,
  ) async {
    const teacher = UserProfile(
      id: 'tch-1',
      name: 'Ibu Sari Wulandari, S.Pd',
      email: 'sari.wulandari@sekolah.sch.id',
      role: 'teacher',
      nip: '198901012015032001',
      hasKioskPin: true,
    );

    final emptyClassesApi = _createStubApiClient((options) {
      if (options.path == '/teacher/dashboard') {
        return {
          'teacher_name': teacher.name,
          'today_date': '2026-11-23',
          'stats': {
            'present_rate': 0.0,
            'present_count': 0,
            'late_count': 0,
            'pending_leaves_count': 0,
          },
          'sessions': const <dynamic>[],
          'today_schedules': const <dynamic>[],
        };
      }
      if (options.path == '/classes' || options.path == '/leave-requests') {
        return const <dynamic>[];
      }
      return <String, dynamic>{};
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeScreen(apiClient: emptyClassesApi, initialUser: teacher),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('+ Buka Sesi Presensi Baru'));
    await tester.pumpAndSettle();

    expect(find.text('Buka Sesi Presensi Baru'), findsOneWidget);
    expect(
      find.textContaining('Belum ada data kelas tersedia'),
      findsOneWidget,
    );
    final openButton = tester.widget<ElevatedButton>(
      find.widgetWithText(ElevatedButton, 'Buka Sesi'),
    );
    expect(openButton.onPressed, isNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('CreateSessionDialog handles unmatched preset schedule safely', (
    WidgetTester tester,
  ) async {
    const teacher = UserProfile(
      id: 'tch-1',
      name: 'Ibu Sari Wulandari, S.Pd',
      email: 'sari.wulandari@sekolah.sch.id',
      role: 'teacher',
      nip: '198901012015032001',
      hasKioskPin: true,
    );

    final unmatchedPresetApi = _createStubApiClient((options) {
      if (options.path == '/teacher/dashboard') {
        return {
          'teacher_name': teacher.name,
          'today_date': '2026-11-23',
          'stats': {
            'present_rate': 0.0,
            'present_count': 0,
            'late_count': 0,
            'pending_leaves_count': 0,
          },
          'sessions': const <dynamic>[],
          'today_schedules': [
            {
              'id': 'sch-missing-cls',
              'class_id': 'cls-deleted',
              'class_name': 'Kelas Terhapus',
              'teacher_id': 'tch-1',
              'teacher_name': teacher.name,
              'subject_name': 'Fisika',
              'day_of_week': 1,
              'start_time': '08:00:00',
              'end_time': '09:30:00',
              'late_tolerance_minutes': 10,
            },
          ],
        };
      }
      if (options.path == '/classes') {
        return [
          {
            'id': 'cls-real',
            'name': 'XI IPA 1',
            'homeroom_teacher_id': 'tch-1',
            'homeroom_teacher_name': teacher.name,
            'student_count': 30,
            'created_at': '2026-11-23T00:00:00Z',
          },
        ];
      }
      if (options.path == '/leave-requests') {
        return const <dynamic>[];
      }
      return <String, dynamic>{};
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: HomeScreen(apiClient: unmatchedPresetApi, initialUser: teacher),
      ),
    );
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('Buka Sesi'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('Buka Sesi'));
    await tester.pumpAndSettle();

    expect(find.text('Buka Sesi Presensi Baru'), findsOneWidget);
    expect(find.text('XI IPA 1 (30 siswa)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'LoginScreen logs out and clears token when updateKioskPin fails right after login',
    (WidgetTester tester) async {
      final storage = MemoryKeyValueStorage();
      final dio = Dio(BaseOptions(baseUrl: 'http://localhost:8000/api/v1'));
      dio.httpClientAdapter = _StatusStubHttpAdapter((options) {
        if (options.path == '/auth/login') {
          return (
            statusCode: 200,
            body: {
              'access_token': 'temp-jwt-token',
              'token_type': 'bearer',
              'user': {
                'id': 'tch-1',
                'name': 'Ibu Sari Wulandari, S.Pd',
                'email': 'sari.wulandari@sekolah.sch.id',
                'role': 'teacher',
                'nip': '198901012015032001',
                'has_kiosk_pin': false,
              },
            },
          );
        }
        if (options.path == '/auth/kiosk-pin') {
          return (
            statusCode: 500,
            body: {'detail': 'Gagal menyimpan PIN Kiosk pada server.'},
          );
        }
        return (statusCode: 200, body: <String, dynamic>{});
      });

      final apiClient = ApiClient(
        baseUrl: 'http://localhost:8000/api/v1',
        dio: dio,
        storage: storage,
      );

      await tester.pumpWidget(SmartSchoolGuruApp(apiClient: apiClient));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Isi Akun Demo Ibu Sari'));
      await tester.pump();
      await tester.tap(find.text('Masuk ke Beranda Guru'));
      await tester.pumpAndSettle();

      expect(find.text('Gagal menyimpan PIN Kiosk pada server.'), findsOneWidget);
      expect(find.text('Login Akun Guru'), findsOneWidget);
      expect(apiClient.accessToken, isNull);
      expect(apiClient.currentUser, isNull);
      expect(await storage.read('smartschool_guru_token'), isNull);
    },
  );
}

class _StatusStubHttpAdapter implements HttpClientAdapter {
  _StatusStubHttpAdapter(this.handler);

  final ({int statusCode, dynamic body}) Function(RequestOptions options) handler;

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final result = handler(options);
    final bytes = utf8.encode(jsonEncode(result.body));
    return ResponseBody.fromBytes(
      bytes,
      result.statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }
}
