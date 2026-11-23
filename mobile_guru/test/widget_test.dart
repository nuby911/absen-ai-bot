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
}
