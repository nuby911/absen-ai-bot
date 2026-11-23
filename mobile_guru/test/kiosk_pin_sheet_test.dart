import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smart_school_guru/core/api_client.dart';
import 'package:smart_school_guru/core/theme.dart';
import 'package:smart_school_guru/models/models.dart';
import 'package:smart_school_guru/screens/kiosk_scanner_screen.dart';
import 'package:smart_school_guru/services/liveness_detector.dart';
import 'package:smart_school_guru/widgets/kiosk_pin_sheet.dart';

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

SessionDetail _sampleSession() {
  return SessionDetail(
    id: 'sess-1',
    classId: 'cls-1',
    className: 'XI IPA 1',
    teacherId: 'tch-1',
    teacherName: 'Ibu Sari Wulandari, S.Pd',
    scheduleId: 'sch-1',
    subjectName: 'Pemrograman Mobile',
    sessionType: 'subject',
    sessionDate: '2026-11-23',
    expectedStartTime: '07:30:00',
    lateToleranceMinutes: 15,
    openedAt: DateTime.utc(2026, 11, 23, 0, 25),
    closedAt: null,
    status: 'open',
    summary: const SessionSummaryCounters(
      totalStudents: 32,
      presentCount: 28,
      lateCount: 2,
      permitCount: 0,
      sickCount: 0,
      absentCount: 0,
      unrecordedCount: 2,
      recordedCount: 30,
    ),
    students: const [],
  );
}

void main() {
  group('KioskPinSheet', () {
    testWidgets(
      'mengetuk 4 angka (1, 2, 3, 4) lalu konfirmasi memanggil onVerify("1234")',
      (WidgetTester tester) async {
        String? verifiedPin;

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: Scaffold(
              body: KioskPinSheet(
                onVerify: (pin) async {
                  verifiedPin = pin;
                  return true;
                },
              ),
            ),
          ),
        );

        await tester.tap(find.text('1'));
        await tester.tap(find.text('2'));
        await tester.tap(find.text('3'));
        await tester.tap(find.text('4'));
        await tester.pump();

        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();

        expect(verifiedPin, '1234');
      },
    );

    testWidgets(
      'menampilkan pesan error "PIN Kiosk salah" saat onVerify mengembalikan false',
      (WidgetTester tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: Scaffold(
              body: KioskPinSheet(
                onVerify: (_) async => false,
              ),
            ),
          ),
        );

        for (final digit in ['9', '9', '9', '9']) {
          await tester.tap(find.text(digit));
        }
        await tester.pump();

        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();

        expect(find.textContaining('PIN Kiosk salah'), findsOneWidget);
      },
    );

    testWidgets(
      'tombol ⌫ menghapus digit terakhir dan C mengosongkan semua digit',
      (WidgetTester tester) async {
        final submittedPins = <String>[];

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: Scaffold(
              body: KioskPinSheet(
                onVerify: (pin) async {
                  submittedPins.add(pin);
                  return false;
                },
              ),
            ),
          ),
        );

        // Ketuk 1, 2, 3, lalu hapus 3 dengan ⌫, ketuk 4, 5 -> 1245
        await tester.tap(find.text('1'));
        await tester.tap(find.text('2'));
        await tester.tap(find.text('3'));
        await tester.tap(find.text('⌫'));
        await tester.tap(find.text('4'));
        await tester.tap(find.text('5'));
        await tester.pump();

        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();
        expect(submittedPins, ['1245']);

        // Ketuk C untuk mengosongkan semua digit, lalu masukkan 1, 2, 3, 4
        await tester.tap(find.text('C'));
        await tester.pump();

        // Tombol konfirmasi tidak memanggil onVerify saat digit kosong
        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pump();
        expect(submittedPins, ['1245']);

        for (final digit in ['5', '6', '7', '8']) {
          await tester.tap(find.text(digit));
        }
        await tester.pump();

        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();
        expect(submittedPins, ['1245', '5678']);
      },
    );
  });

  group('KioskScannerScreen', () {
    testWidgets(
      'melindungi rute dengan PopScope(canPop: false) dan hanya keluar setelah PIN valid',
      (WidgetTester tester) async {
        final apiClient = _createStubApiClient((options) {
          if (options.path == '/auth/verify-pin') {
            final body = options.data as Map<String, dynamic>;
            return {'valid': body['pin'] == '1234'};
          }
          return <String, dynamic>{};
        });

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: Builder(
              builder: (context) => Scaffold(
                body: Center(
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => KioskScannerScreen(
                            apiClient: apiClient,
                            session: _sampleSession(),
                            enableHardwareCamera: false,
                            previewBuilder: (_) => const SizedBox.expand(),
                          ),
                        ),
                      );
                    },
                    child: const Text('Buka Kiosk'),
                  ),
                ),
              ),
            ),
          ),
        );

        await tester.tap(find.text('Buka Kiosk'));
        await tester.pumpAndSettle();

        final popScope = tester.widget<PopScope>(
          find.descendant(
            of: find.byType(KioskScannerScreen),
            matching: find.byType(PopScope),
          ),
        );
        expect(popScope.canPop, isFalse);

        // Tombol back / maybePop tidak langsung keluar, melainkan membuka KioskPinSheet
        final rootNav = tester.state<NavigatorState>(find.byType(Navigator));
        unawaited(rootNav.maybePop());
        await tester.pumpAndSettle();

        expect(find.text('Masukkan PIN Kiosk Guru'), findsOneWidget);
        expect(find.byType(KioskScannerScreen), findsOneWidget);

        // Batal dari modal PIN kembali ke Mode Kiosk, lalu buka ulang via tombol 🔒 PIN
        await tester.tap(find.text('Batal — Kembali ke Pemindaian Wajah'));
        await tester.pumpAndSettle();
        expect(find.text('Masukkan PIN Kiosk Guru'), findsNothing);
        expect(find.byType(KioskScannerScreen), findsOneWidget);

        await tester.tap(find.byKey(const Key('kiosk_pin_button')));
        await tester.pumpAndSettle();
        expect(find.text('Masukkan PIN Kiosk Guru'), findsOneWidget);

        // Masukkan PIN salah -> tetap di Mode Kiosk + error
        for (final digit in ['0', '0', '0', '0']) {
          await tester.tap(find.text(digit));
        }
        await tester.pump();
        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();

        expect(find.textContaining('PIN Kiosk salah'), findsOneWidget);
        expect(find.byType(KioskScannerScreen), findsOneWidget);

        // Bersihkan lalu masukkan PIN benar 1234 -> keluar ke halaman sebelumnya
        await tester.tap(find.text('C'));
        for (final digit in ['1', '2', '3', '4']) {
          await tester.tap(find.text(digit));
        }
        await tester.pump();
        await tester.tap(find.text('Buka Kunci & Keluar Kiosk'));
        await tester.pumpAndSettle();

        expect(find.byType(KioskScannerScreen), findsNothing);
        expect(find.text('Buka Kiosk'), findsOneWidget);
      },
    );

    testWidgets(
      'menampilkan overlay konfirmasi Screen 05 dengan status WA terkirim saat scan wajah berhasil',
      (WidgetTester tester) async {
        final sampleController = StreamController<FaceSample?>();
        addTearDown(sampleController.close);

        var scanCalled = false;
        var attendanceCallbackCount = 0;

        final apiClient = _createStubApiClient((options) {
          if (options.path == '/attendance/scan') {
            scanCalled = true;
            return {
              'matched': true,
              'already_recorded': false,
              'attendance_id': 'att-101',
              'student_id': 'stu-1',
              'student_name': 'Rubby Ibnu Anantara',
              'nis': '24781025',
              'class_name': 'XI IPA 1',
              'status': 'present',
              'scanned_at': '2026-11-23T00:26:00Z',
              'similarity_score': 0.91,
              'threshold_used': 0.55,
              'wa_status': 'sent',
              'wa_queued': true,
              'message': 'Presensi Rubby Ibnu Anantara berhasil dicatat (Hadir).',
            };
          }
          return <String, dynamic>{};
        });

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: KioskScannerScreen(
              apiClient: apiClient,
              session: _sampleSession(),
              enableHardwareCamera: false,
              sampleStream: sampleController.stream,
              previewBuilder: (_) => const SizedBox.expand(),
              onCaptureFaceBytes: () async => Uint8List.fromList([1, 2, 3, 4]),
              onPlaySuccessSound: () async {},
              onAttendanceRecorded: () => attendanceCallbackCount += 1,
            ),
          ),
        );
        await tester.pump();

        final t0 = DateTime(2026, 11, 23, 7, 30, 0);
        // Frame 1: mata terbuka -> waitingBlink
        sampleController.add(
          FaceSample(
            leftEyeOpenProbability: 0.92,
            rightEyeOpenProbability: 0.90,
            headEulerAngleY: 1.0,
            headEulerAngleZ: 0.0,
            timestamp: t0,
          ),
        );
        await tester.pump();

        // Frame 2: mata tertutup -> blinkDetectedWaitingReopen
        sampleController.add(
          FaceSample(
            leftEyeOpenProbability: 0.10,
            rightEyeOpenProbability: 0.12,
            headEulerAngleY: 0.5,
            headEulerAngleZ: 0.0,
            timestamp: t0.add(const Duration(milliseconds: 250)),
          ),
        );
        await tester.pump();

        // Frame 3: mata terbuka kembali -> passed -> capture & API scan!
        sampleController.add(
          FaceSample(
            leftEyeOpenProbability: 0.91,
            rightEyeOpenProbability: 0.89,
            headEulerAngleY: 0.0,
            headEulerAngleZ: 0.0,
            timestamp: t0.add(const Duration(milliseconds: 550)),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 50));

        expect(scanCalled, isTrue);
        expect(attendanceCallbackCount, 1);
        expect(find.text('Rubby Ibnu Anantara'), findsOneWidget);
        expect(find.textContaining('24781025'), findsOneWidget);
        expect(find.text('HADIR TEPAT WAKTU'), findsOneWidget);
        expect(
          find.textContaining('Notifikasi WhatsApp Orang Tua Terkirim'),
          findsOneWidget,
        );

        // Selesaikan timer auto-reset 2.5 detik agar kembali siap untuk siswa berikutnya
        await tester.pump(const Duration(milliseconds: 2600));
        expect(find.text('HADIR TEPAT WAKTU'), findsNothing);
      },
    );

    testWidgets(
      'menangani already_recorded dan wajah tidak dikenali dengan pesan ramah',
      (WidgetTester tester) async {
        final sampleController = StreamController<FaceSample?>();
        addTearDown(sampleController.close);

        var scanAttempt = 0;
        final apiClient = _createStubApiClient((options) {
          if (options.path == '/attendance/scan') {
            scanAttempt += 1;
            if (scanAttempt == 1) {
              return {
                'matched': true,
                'already_recorded': true,
                'attendance_id': 'att-101',
                'student_id': 'stu-1',
                'student_name': 'Deni Prawira',
                'nis': '24781007',
                'class_name': 'XI IPA 1',
                'status': 'late',
                'scanned_at': '2026-11-23T00:46:00Z',
                'similarity_score': 0.84,
                'threshold_used': 0.55,
                'wa_status': 'sent',
                'wa_queued': false,
                'message': 'Deni Prawira sudah tercatat presensi pada sesi ini.',
              };
            }
            if (scanAttempt == 2) {
              return {
                'matched': true,
                'already_recorded': true,
                'attendance_id': 'att-102',
                'student_id': 'stu-2',
                'student_name': 'Septi Rahmawati',
                'nis': '24781008',
                'class_name': 'XI IPA 1',
                'status': 'sick',
                'scanned_at': null,
                'similarity_score': 0.88,
                'threshold_used': 0.55,
                'wa_status': 'sent',
                'wa_queued': false,
                'message': 'Septi Rahmawati sudah tercatat presensi pada sesi ini.',
              };
            }
            if (scanAttempt == 3) {
              return {
                'matched': true,
                'already_recorded': true,
                'attendance_id': 'att-103',
                'student_id': 'stu-3',
                'student_name': 'Ahmad Fauzi',
                'nis': '24781009',
                'class_name': 'XI IPA 1',
                'status': 'permit',
                'scanned_at': null,
                'similarity_score': 0.87,
                'threshold_used': 0.55,
                'wa_status': 'sent',
                'wa_queued': false,
                'message': 'Ahmad Fauzi sudah tercatat presensi pada sesi ini.',
              };
            }
            return {
              'matched': false,
              'already_recorded': false,
              'similarity_score': 0.31,
              'threshold_used': 0.55,
              'wa_queued': false,
              'message': 'Wajah tidak dikenali. Silakan posisikan ulang wajah Anda.',
            };
          }
          return <String, dynamic>{};
        });

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.light(),
            home: KioskScannerScreen(
              apiClient: apiClient,
              session: _sampleSession(),
              enableHardwareCamera: false,
              sampleStream: sampleController.stream,
              previewBuilder: (_) => const SizedBox.expand(),
              onCaptureFaceBytes: () async => Uint8List.fromList([1, 2, 3]),
              onPlaySuccessSound: () async {},
            ),
          ),
        );
        await tester.pump();

        Future<void> triggerBlink(DateTime start) async {
          sampleController.add(
            FaceSample(
              leftEyeOpenProbability: 0.9,
              rightEyeOpenProbability: 0.9,
              headEulerAngleY: 0,
              headEulerAngleZ: 0,
              timestamp: start,
            ),
          );
          await tester.pump();
          sampleController.add(
            FaceSample(
              leftEyeOpenProbability: 0.1,
              rightEyeOpenProbability: 0.1,
              headEulerAngleY: 0,
              headEulerAngleZ: 0,
              timestamp: start.add(const Duration(milliseconds: 200)),
            ),
          );
          await tester.pump();
          sampleController.add(
            FaceSample(
              leftEyeOpenProbability: 0.9,
              rightEyeOpenProbability: 0.9,
              headEulerAngleY: 0,
              headEulerAngleZ: 0,
              timestamp: start.add(const Duration(milliseconds: 450)),
            ),
          );
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 50));
        }

        // Scan 1: already_recorded == true dengan status late -> Terlambat
        final t1 = DateTime(2026, 11, 23, 7, 30, 0);
        await triggerBlink(t1);
        expect(find.textContaining('Sudah tercatat (Terlambat)'), findsOneWidget);
        expect(find.textContaining('Deni Prawira'), findsOneWidget);

        await tester.pump(const Duration(milliseconds: 2600));

        // Scan 2: already_recorded == true dengan status sick -> Sakit
        final t2 = t1.add(const Duration(seconds: 4));
        await triggerBlink(t2);
        expect(find.textContaining('Sudah tercatat (Sakit)'), findsOneWidget);
        expect(find.textContaining('Septi Rahmawati'), findsOneWidget);

        await tester.pump(const Duration(milliseconds: 2600));

        // Scan 3: already_recorded == true dengan status permit -> Izin
        final t3 = t2.add(const Duration(seconds: 4));
        await triggerBlink(t3);
        expect(find.textContaining('Sudah tercatat (Izin)'), findsOneWidget);
        expect(find.textContaining('Ahmad Fauzi'), findsOneWidget);

        await tester.pump(const Duration(milliseconds: 2600));

        // Scan 4: matched == false
        final t4 = t3.add(const Duration(seconds: 4));
        await triggerBlink(t4);
        expect(find.textContaining('Wajah tidak dikenali'), findsOneWidget);

        await tester.pump(const Duration(milliseconds: 2600));
      },
    );
  });
}
