import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smart_school_guru/core/api_client.dart';
import 'package:smart_school_guru/core/theme.dart';
import 'package:smart_school_guru/main.dart';
import 'package:smart_school_guru/models/models.dart';
import 'package:smart_school_guru/screens/leave_verification_screen.dart';

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

List<LeaveRequestItem> _sampleLeaves() {
  return [
    LeaveRequestItem(
      id: 'leave-pending-1',
      studentId: 'stu-3',
      studentName: 'Septi Cahyaningtias',
      studentNis: '24781026',
      classId: 'cls-1',
      className: 'XI IPA 1',
      parentId: 'par-3',
      parentName: 'Bapak Cahyo',
      parentPhoneWa: '6281279001236',
      requestType: 'sick',
      startDate: '2026-11-23',
      endDate: '2026-11-23',
      reason: 'Demam tinggi dan batuk, sedang beristirahat sesuai anjuran dokter.',
      attachmentUrl: '/uploads/leaves/surat_dokter_septi.jpg',
      status: 'pending',
      verifiedBy: null,
      verifiedByName: null,
      verifiedAt: null,
      createdAt: DateTime.utc(2026, 11, 23, 0, 10),
    ),
    LeaveRequestItem(
      id: 'leave-approved-1',
      studentId: 'stu-5',
      studentName: 'Ahmad Fauzi',
      studentNis: '24781031',
      classId: 'cls-1',
      className: 'XI IPA 1',
      parentId: 'par-5',
      parentName: 'Bapak Fauzi',
      parentPhoneWa: '6281279001238',
      requestType: 'permit',
      startDate: '2026-11-22',
      endDate: '2026-11-23',
      reason: 'Mengikuti lomba karya tulis ilmiah tingkat provinsi mewakili sekolah.',
      attachmentUrl: null,
      status: 'approved',
      verifiedBy: 'tch-1',
      verifiedByName: 'Ibu Sari Wulandari, S.Pd',
      verifiedAt: DateTime.utc(2026, 11, 22, 6, 30),
      createdAt: DateTime.utc(2026, 11, 22, 5, 0),
    ),
    LeaveRequestItem(
      id: 'leave-rejected-1',
      studentId: 'stu-2',
      studentName: 'Deni Prawira',
      studentNis: '24781007',
      classId: 'cls-1',
      className: 'XI IPA 1',
      parentId: 'par-2',
      parentName: 'Ibu Prawira',
      parentPhoneWa: '6281279001235',
      requestType: 'permit',
      startDate: '2026-11-21',
      endDate: '2026-11-21',
      reason: 'Acara keluarga di luar kota tanpa keterangan resmi.',
      attachmentUrl: null,
      status: 'rejected',
      verifiedBy: 'tch-1',
      verifiedByName: 'Ibu Sari Wulandari, S.Pd',
      verifiedAt: DateTime.utc(2026, 11, 21, 8, 0),
      createdAt: DateTime.utc(2026, 11, 21, 7, 15),
    ),
  ];
}

void main() {
  group('LeaveVerificationScreen', () {
    testWidgets(
      'merender kartu izin pending lengkap dengan nama, kelas, alasan, lampiran, dan memanggil onVerify saat Setujui / Tolak',
      (WidgetTester tester) async {
        final calls = <(String, String)>[];
        final apiClient = _createStubApiClient((_) => const <dynamic>[]);

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: LeaveVerificationScreen(
              apiClient: apiClient,
              initialLeaves: _sampleLeaves(),
              onVerify: (leaveId, decision) async {
                calls.add((leaveId, decision));
              },
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Septi Cahyaningtias'), findsOneWidget);
        expect(find.textContaining('XI IPA 1'), findsOneWidget);
        expect(
          find.text(
            'Demam tinggi dan batuk, sedang beristirahat sesuai anjuran dokter.',
          ),
          findsOneWidget,
        );
        expect(find.text('surat_dokter_septi.jpg'), findsOneWidget);
        expect(find.text('SAKIT'), findsOneWidget);

        await tester.tap(find.text('Setujui & Kabari WA'));
        await tester.pumpAndSettle();
        expect(find.text('Setujui Pengajuan SAKIT?'), findsOneWidget);
        await tester.tap(find.byKey(const Key('leave_confirm_decision_button')));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Tolak'));
        await tester.pumpAndSettle();
        expect(find.text('Tolak Pengajuan SAKIT?'), findsOneWidget);
        await tester.tap(find.byKey(const Key('leave_confirm_decision_button')));
        await tester.pumpAndSettle();

        expect(calls, [
          ('leave-pending-1', 'approved'),
          ('leave-pending-1', 'rejected'),
        ]);
      },
    );

    testWidgets(
      'perpindahan tab Menunggu, Disetujui, dan Ditolak memfilter daftar dengan benar',
      (WidgetTester tester) async {
        final apiClient = _createStubApiClient((_) => const <dynamic>[]);

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: LeaveVerificationScreen(
              apiClient: apiClient,
              initialLeaves: _sampleLeaves(),
            ),
          ),
        );
        await tester.pumpAndSettle();

        // Tab default: Menunggu
        expect(find.text('Septi Cahyaningtias'), findsOneWidget);
        expect(find.text('Ahmad Fauzi'), findsNothing);
        expect(find.text('Deni Prawira'), findsNothing);

        // Pindah ke tab Disetujui
        await tester.tap(find.text('Disetujui'));
        await tester.pumpAndSettle();

        expect(find.text('Ahmad Fauzi'), findsOneWidget);
        expect(find.text('Septi Cahyaningtias'), findsNothing);
        expect(find.text('Deni Prawira'), findsNothing);

        // Pindah ke tab Ditolak
        await tester.tap(find.text('Ditolak'));
        await tester.pumpAndSettle();

        expect(find.text('Deni Prawira'), findsOneWidget);
        expect(find.text('Ahmad Fauzi'), findsNothing);
        expect(find.text('Septi Cahyaningtias'), findsNothing);
      },
    );

    testWidgets(
      'mengambil daftar dari ApiClient, mengirim note opsional pada PATCH verify, dan menyinkronkan badge pending',
      (WidgetTester tester) async {
        String currentStatus = 'pending';
        String? sentDecision;
        String? sentNote;
        final reportedPendingCounts = <int>[];

        final apiClient = _createStubApiClient((options) {
          if (options.path == '/leave-requests' && options.method == 'GET') {
            return [
              {
                'id': 'leave-api-1',
                'student_id': 'stu-3',
                'student_name': 'Septi Cahyaningtias',
                'student_nis': '24781026',
                'class_id': 'cls-1',
                'class_name': 'XI IPA 1',
                'parent_id': 'par-3',
                'parent_name': 'Bapak Cahyo',
                'parent_phone_wa': '6281279001236',
                'request_type': 'sick',
                'start_date': '2026-11-23',
                'end_date': '2026-11-23',
                'reason': 'Sakit demam',
                'attachment_url': '/uploads/leaves/surat_dokter_septi.jpg',
                'status': currentStatus,
                'verified_by': currentStatus == 'pending' ? null : 'tch-1',
                'verified_by_name':
                    currentStatus == 'pending' ? null : 'Ibu Sari Wulandari, S.Pd',
                'verified_at':
                    currentStatus == 'pending' ? null : '2026-11-23T01:00:00Z',
                'verification_note': currentStatus == 'pending' ? null : sentNote,
                'created_at': '2026-11-23T00:10:00Z',
              },
            ];
          }
          if (options.path == '/leave-requests/leave-api-1/verify' &&
              options.method == 'PATCH') {
            final body = options.data as Map<String, dynamic>;
            sentDecision = body['decision'] as String?;
            sentNote = body['note'] as String?;
            currentStatus = 'approved';
            return {
              'leave': {
                'id': 'leave-api-1',
                'student_id': 'stu-3',
                'student_name': 'Septi Cahyaningtias',
                'student_nis': '24781026',
                'class_id': 'cls-1',
                'class_name': 'XI IPA 1',
                'parent_id': 'par-3',
                'parent_name': 'Bapak Cahyo',
                'parent_phone_wa': '6281279001236',
                'request_type': 'sick',
                'start_date': '2026-11-23',
                'end_date': '2026-11-23',
                'reason': 'Sakit demam',
                'attachment_url': '/uploads/leaves/surat_dokter_septi.jpg',
                'status': 'approved',
                'verified_by': 'tch-1',
                'verified_by_name': 'Ibu Sari Wulandari, S.Pd',
                'verified_at': '2026-11-23T01:00:00Z',
                'verification_note': sentNote,
                'created_at': '2026-11-23T00:10:00Z',
              },
              'synced_sessions_count': 1,
              'wa_sent': true,
              'message': 'Pengajuan izin Septi Cahyaningtias berhasil disetujui.',
            };
          }
          return <String, dynamic>{};
        });

        var notifyParentCount = 0;
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: LeaveVerificationScreen(
              apiClient: apiClient,
              onLeaveChanged: () => notifyParentCount += 1,
              onPendingCountLoaded: reportedPendingCounts.add,
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(reportedPendingCounts, [1]);
        expect(find.text('Septi Cahyaningtias'), findsOneWidget);
        expect(find.textContaining('Diajukan 23 Nov 2026, 07:10 WIB'), findsOneWidget);

        // Buka dialog konfirmasi lalu batalkan -> tidak memanggil PATCH
        await tester.tap(find.text('Setujui & Kabari WA'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Batal'));
        await tester.pumpAndSettle();
        expect(sentDecision, isNull);

        // Buka ulang dialog konfirmasi, isi catatan opsional, lalu konfirmasi
        await tester.tap(find.text('Setujui & Kabari WA'));
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const Key('leave_verification_note_field')),
          'Semoga lekas sembuh',
        );
        await tester.tap(find.byKey(const Key('leave_confirm_decision_button')));
        await tester.pumpAndSettle();

        expect(sentDecision, 'approved');
        expect(sentNote, 'Semoga lekas sembuh');
        expect(notifyParentCount, 1);
        expect(reportedPendingCounts, [1, 0]);

        // Setelah refresh, Septi berpindah dari tab Menunggu ke tab Disetujui dengan catatan guru
        expect(find.text('Septi Cahyaningtias'), findsNothing);
        await tester.tap(find.text('Disetujui'));
        await tester.pumpAndSettle();
        expect(find.text('Septi Cahyaningtias'), findsOneWidget);
        expect(find.textContaining('Catatan guru: Semoga lekas sembuh'), findsOneWidget);
      },
    );

    testWidgets(
      'berpindah ke tab Verifikasi Izin pada SmartSchoolGuruApp memicu refreshTrigger dan fetch ulang daftar izin',
      (WidgetTester tester) async {
        var leaveFetchCount = 0;
        var includeNewLeave = false;

        final apiClient = _createStubApiClient((options) {
          if (options.path == '/auth/me') {
            return {
              'id': 'tch-1',
              'name': 'Ibu Sari Wulandari, S.Pd',
              'email': 'sari.wulandari@sekolah.sch.id',
              'role': 'teacher',
              'nip': '198901012015032001',
              'has_kiosk_pin': true,
            };
          }
          if (options.path == '/teacher/dashboard') {
            return {
              'teacher_name': 'Ibu Sari Wulandari, S.Pd',
              'today_date': '2026-11-23',
              'stats': {
                'present_rate': 90.0,
                'present_count': 27,
                'late_count': 1,
                'pending_leaves_count': includeNewLeave ? 1 : 0,
              },
              'sessions': const <dynamic>[],
              'today_schedules': const <dynamic>[],
            };
          }
          if (options.path == '/leave-requests' && options.method == 'GET') {
            leaveFetchCount += 1;
            if (!includeNewLeave) {
              return const <dynamic>[];
            }
            return [
              {
                'id': 'leave-new-1',
                'student_id': 'stu-6',
                'student_name': 'Nadia Pratama',
                'student_nis': '24781040',
                'class_id': 'cls-2',
                'class_name': 'XI IPA 2',
                'parent_id': 'par-6',
                'parent_name': 'Ibu Pratama',
                'parent_phone_wa': '6281279001239',
                'request_type': 'permit',
                'start_date': '2026-11-23',
                'end_date': '2026-11-23',
                'reason': 'Keperluan keluarga mendadak',
                'attachment_url': null,
                'status': 'pending',
                'verified_by': null,
                'verified_by_name': null,
                'verified_at': null,
                'created_at': '2026-11-23T01:15:00Z',
              },
            ];
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
        await apiClient.saveSession('token-guru', teacher);

        await tester.pumpWidget(SmartSchoolGuruApp(apiClient: apiClient));
        await tester.pumpAndSettle();

        expect(leaveFetchCount, 1);

        // Simulasikan ada pengajuan izin baru masuk sebelum guru berpindah ke tab Verifikasi Izin
        includeNewLeave = true;
        await tester.tap(find.text('Verifikasi Izin'));
        await tester.pumpAndSettle();

        expect(leaveFetchCount, 2);
        expect(find.text('Nadia Pratama'), findsOneWidget);

        // Kembali ke Beranda lalu tekan kartu KPI Izin Pending -> juga memicu refreshTrigger
        await tester.tap(find.text('Beranda'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Izin Pending'));
        await tester.pumpAndSettle();

        expect(leaveFetchCount, 3);
      },
    );
  });
}
