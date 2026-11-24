import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:smart_school_guru/screens/kiosk_scanner_screen.dart';
import 'package:smart_school_guru/services/liveness_detector.dart';

void main() {
  group('BlinkLivenessDetector', () {
    final baseTime = DateTime(2026, 11, 23, 7, 30, 0);

    FaceSample makeSample({
      required int offsetMs,
      double? leftEye = 0.9,
      double? rightEye = 0.9,
      double? yaw = 0.0,
      double? roll = 0.0,
      int faceCount = 1,
      double? faceWidthRatio,
      bool? isCentered,
      double? meanLuma,
    }) {
      return FaceSample(
        leftEyeOpenProbability: leftEye,
        rightEyeOpenProbability: rightEye,
        headEulerAngleY: yaw,
        headEulerAngleZ: roll,
        timestamp: baseTime.add(Duration(milliseconds: offsetMs)),
        faceCount: faceCount,
        faceWidthRatio: faceWidthRatio,
        isCentered: isCentered,
        meanLuma: meanLuma,
      );
    }

    test('1. static open eyes (photo spoof) never triggers LivenessStatus.passed', () {
      final detector = BlinkLivenessDetector();

      for (var ms = 0; ms <= 5000; ms += 100) {
        final decision = detector.evaluate(
          makeSample(offsetMs: ms, leftEye: 0.95, rightEye: 0.92),
        );
        expect(decision.status, isNot(LivenessStatus.passed));
        expect(decision.shouldCapture, isFalse);
      }

      // Static closed eyes only also never triggers passed
      final closedDetector = BlinkLivenessDetector();
      for (var ms = 0; ms <= 3000; ms += 100) {
        final decision = closedDetector.evaluate(
          makeSample(offsetMs: ms, leftEye: 0.1, rightEye: 0.1),
        );
        expect(decision.status, LivenessStatus.waitingOpen);
        expect(decision.shouldCapture, isFalse);
      }
    });

    test('2. tilted head (|yaw| >= 18.0 or |roll| >= 15.0) returns poseInvalid', () {
      final detector = BlinkLivenessDetector();

      final yawEdge = detector.evaluate(
        makeSample(offsetMs: 0, yaw: 18.0, roll: 0.0),
      );
      expect(yawEdge.status, LivenessStatus.poseInvalid);
      expect(yawEdge.shouldCapture, isFalse);
      expect(yawEdge.instruction, 'Posisikan wajah lurus menghadap kamera');

      final negativeYaw = detector.evaluate(
        makeSample(offsetMs: 100, yaw: -22.5, roll: 5.0),
      );
      expect(negativeYaw.status, LivenessStatus.poseInvalid);
      expect(negativeYaw.shouldCapture, isFalse);

      final rollEdge = detector.evaluate(
        makeSample(offsetMs: 200, yaw: 2.0, roll: -15.0),
      );
      expect(rollEdge.status, LivenessStatus.poseInvalid);
      expect(rollEdge.shouldCapture, isFalse);
    });

    test('3. valid open (>0.7) -> closed (<0.25) -> open (>0.7) within 2500ms triggers passed', () {
      final detector = BlinkLivenessDetector();

      final step1 = detector.evaluate(
        makeSample(offsetMs: 0, leftEye: 0.85, rightEye: 0.88, yaw: 4.0, roll: -3.0),
      );
      expect(step1.status, LivenessStatus.waitingBlink);
      expect(step1.shouldCapture, isFalse);

      final step2 = detector.evaluate(
        makeSample(offsetMs: 300, leftEye: 0.12, rightEye: 0.18, yaw: 2.0, roll: -1.0),
      );
      expect(step2.status, LivenessStatus.blinkDetectedWaitingReopen);
      expect(step2.shouldCapture, isFalse);

      final step3 = detector.evaluate(
        makeSample(offsetMs: 700, leftEye: 0.82, rightEye: 0.79, yaw: 1.0, roll: 0.0),
      );
      expect(step3.status, LivenessStatus.passed);
      expect(step3.shouldCapture, isTrue);
    });

    test('4. blink taking > 2500ms resets and does not trigger passed', () {
      final detector = BlinkLivenessDetector();

      expect(
        detector.evaluate(makeSample(offsetMs: 0, leftEye: 0.9, rightEye: 0.9)).status,
        LivenessStatus.waitingBlink,
      );
      expect(
        detector.evaluate(makeSample(offsetMs: 200, leftEye: 0.1, rightEye: 0.1)).status,
        LivenessStatus.blinkDetectedWaitingReopen,
      );

      // Reopen happens at 2600ms (> 2500ms window)
      final expired = detector.evaluate(
        makeSample(offsetMs: 2600, leftEye: 0.9, rightEye: 0.9),
      );
      expect(expired.status, isNot(LivenessStatus.passed));
      expect(expired.status, LivenessStatus.waitingOpen);
      expect(expired.shouldCapture, isFalse);

      // Next open frame starts fresh waitingBlink rather than passing
      final restart = detector.evaluate(
        makeSample(offsetMs: 2700, leftEye: 0.9, rightEye: 0.9),
      );
      expect(restart.status, LivenessStatus.waitingBlink);
      expect(restart.shouldCapture, isFalse);
    });

    test('5. after markScanCompleted(t), cooldown blocks for 2500ms then accepts next student', () {
      final detector = BlinkLivenessDetector();

      // Complete first valid blink
      detector.evaluate(makeSample(offsetMs: 0, leftEye: 0.9, rightEye: 0.9));
      detector.evaluate(makeSample(offsetMs: 200, leftEye: 0.1, rightEye: 0.1));
      final passed = detector.evaluate(
        makeSample(offsetMs: 450, leftEye: 0.9, rightEye: 0.9),
      );
      expect(passed.status, LivenessStatus.passed);
      expect(passed.shouldCapture, isTrue);

      final completedAt = baseTime.add(const Duration(milliseconds: 450));
      detector.markScanCompleted(completedAt);

      // Within 2500ms (at +1000ms and +2400ms from completedAt): always cooldown
      final during1 = detector.evaluate(
        makeSample(offsetMs: 1450, leftEye: 0.9, rightEye: 0.9),
      );
      expect(during1.status, LivenessStatus.cooldown);
      expect(during1.shouldCapture, isFalse);

      final during2 = detector.evaluate(
        makeSample(offsetMs: 2850, leftEye: 0.1, rightEye: 0.1),
      );
      expect(during2.status, LivenessStatus.cooldown);
      expect(during2.shouldCapture, isFalse);

      // Even null face during cooldown stays cooldown
      final duringNull = detector.evaluate(
        null,
        now: baseTime.add(const Duration(milliseconds: 2900)),
      );
      expect(duringNull.status, LivenessStatus.cooldown);
      expect(duringNull.shouldCapture, isFalse);

      // After 2500ms (>= 2950ms): accepts next student blink cleanly
      final nextOpen = detector.evaluate(
        makeSample(offsetMs: 3000, leftEye: 0.9, rightEye: 0.9),
      );
      expect(nextOpen.status, LivenessStatus.waitingBlink);
      expect(nextOpen.shouldCapture, isFalse);

      detector.evaluate(makeSample(offsetMs: 3200, leftEye: 0.1, rightEye: 0.1));
      final nextPassed = detector.evaluate(
        makeSample(offsetMs: 3450, leftEye: 0.88, rightEye: 0.91),
      );
      expect(nextPassed.status, LivenessStatus.passed);
      expect(nextPassed.shouldCapture, isTrue);
    });

    test('handles noFace and one-eye wink safely without false pass', () {
      final detector = BlinkLivenessDetector();

      final noFace = detector.evaluate(null, now: baseTime);
      expect(noFace.status, LivenessStatus.noFace);
      expect(noFace.shouldCapture, isFalse);

      // Open -> wink (only left closed) -> open must NOT pass
      detector.evaluate(makeSample(offsetMs: 100, leftEye: 0.9, rightEye: 0.9));
      final wink = detector.evaluate(
        makeSample(offsetMs: 250, leftEye: 0.1, rightEye: 0.9),
      );
      expect(wink.status, LivenessStatus.waitingBlink);
      final afterWink = detector.evaluate(
        makeSample(offsetMs: 400, leftEye: 0.9, rightEye: 0.9),
      );
      expect(afterWink.status, isNot(LivenessStatus.passed));
      expect(afterWink.shouldCapture, isFalse);
    });

    test('6. multipleFaces guard blocks capture when faceCount > 1', () {
      final detector = BlinkLivenessDetector();
      final decision = detector.evaluate(
        makeSample(offsetMs: 0, faceCount: 2),
      );
      expect(decision.status, LivenessStatus.multipleFaces);
      expect(
        decision.instruction,
        'Terdeteksi lebih dari 1 wajah — maju satu per satu',
      );
      expect(decision.shouldCapture, isFalse);
    });

    test('7. distance guards (tooFar < 0.20, tooClose > 0.80) and poorLighting (< 40)', () {
      final detector = BlinkLivenessDetector();

      final far = detector.evaluate(
        makeSample(offsetMs: 0, faceWidthRatio: 0.16, meanLuma: 120),
      );
      expect(far.status, LivenessStatus.tooFar);
      expect(far.instruction, 'Dekatkan wajah ke kamera (30–80 cm)');
      expect(far.shouldCapture, isFalse);

      final close = detector.evaluate(
        makeSample(offsetMs: 100, faceWidthRatio: 0.85, meanLuma: 120),
      );
      expect(close.status, LivenessStatus.tooClose);
      expect(close.instruction, 'Sedikit menjauh dari kamera');
      expect(close.shouldCapture, isFalse);

      final dark = detector.evaluate(
        makeSample(offsetMs: 200, faceWidthRatio: 0.45, meanLuma: 28.0),
      );
      expect(dark.status, LivenessStatus.poorLighting);
      expect(dark.instruction, 'Pencahayaan terlalu gelap — cari area terang');
      expect(dark.shouldCapture, isFalse);

      final offCenter = detector.evaluate(
        makeSample(
          offsetMs: 300,
          faceWidthRatio: 0.45,
          meanLuma: 120,
          isCentered: false,
        ),
      );
      expect(offCenter.status, LivenessStatus.poseInvalid);
      expect(offCenter.shouldCapture, isFalse);
    });

    test('8. tolerates 1 transient null-eye frame during reopen, resets on 2nd null frame', () {
      final detector = BlinkLivenessDetector();

      // Valid blink with 1 transient null-eye frame during reopen
      expect(
        detector.evaluate(makeSample(offsetMs: 0, leftEye: 0.9, rightEye: 0.9)).status,
        LivenessStatus.waitingBlink,
      );
      expect(
        detector.evaluate(makeSample(offsetMs: 200, leftEye: 0.1, rightEye: 0.1)).status,
        LivenessStatus.blinkDetectedWaitingReopen,
      );
      final graceFrame = detector.evaluate(
        makeSample(offsetMs: 350, leftEye: null, rightEye: null),
      );
      expect(graceFrame.status, LivenessStatus.blinkDetectedWaitingReopen);
      expect(graceFrame.shouldCapture, isFalse);

      final reopened = detector.evaluate(
        makeSample(offsetMs: 500, leftEye: 0.88, rightEye: 0.92),
      );
      expect(reopened.status, LivenessStatus.passed);
      expect(reopened.shouldCapture, isTrue);

      // Two consecutive null-eye frames during reopen must reset blink phase
      final detector2 = BlinkLivenessDetector();
      detector2.evaluate(makeSample(offsetMs: 0, leftEye: 0.9, rightEye: 0.9));
      detector2.evaluate(makeSample(offsetMs: 200, leftEye: 0.1, rightEye: 0.1));
      expect(
        detector2.evaluate(makeSample(offsetMs: 300, leftEye: null, rightEye: null)).status,
        LivenessStatus.blinkDetectedWaitingReopen,
      );
      final secondNull = detector2.evaluate(
        makeSample(offsetMs: 400, leftEye: null, rightEye: null),
      );
      expect(secondNull.status, LivenessStatus.waitingOpen);
      expect(secondNull.shouldCapture, isFalse);
    });

    test('9. shows helpful glare warning when eye probabilities stay null > 1.5s', () {
      final detector = BlinkLivenessDetector();

      final firstNull = detector.evaluate(
        makeSample(offsetMs: 0, leftEye: null, rightEye: null),
      );
      expect(firstNull.status, LivenessStatus.waitingOpen);
      expect(firstNull.instruction, isNot(contains('pantulan kacamata')));

      final stillNullBeforeThreshold = detector.evaluate(
        makeSample(offsetMs: 1200, leftEye: null, rightEye: null),
      );
      expect(stillNullBeforeThreshold.instruction, isNot(contains('pantulan kacamata')));

      final afterThreshold = detector.evaluate(
        makeSample(offsetMs: 1600, leftEye: null, rightEye: null),
      );
      expect(
        afterThreshold.instruction,
        'Mata tidak terbaca jelas — kurangi pantulan kacamata/cahaya',
      );
      expect(afterThreshold.shouldCapture, isFalse);
    });
  });

  group('Camera YUV_420_888 & Luma helpers', () {
    test('convertYuv420ToNv21 packs Y and interleaved VU respecting row/pixel strides', () {
      // 4x2 frame: yRowStride = 6 (2 padding bytes per row), pixelStride = 1
      final yBytes = Uint8List.fromList([
        10, 20, 30, 40, 255, 255,
        50, 60, 70, 80, 255, 255,
      ]);
      // UV dimensions = 2x1, uPixelStride = 2, vPixelStride = 2 (semi-planar)
      final uBytes = Uint8List.fromList([111, 0, 122, 0]);
      final vBytes = Uint8List.fromList([211, 0, 222, 0]);

      final nv21 = convertYuv420ToNv21(
        width: 4,
        height: 2,
        yBytes: yBytes,
        yRowStride: 6,
        yPixelStride: 1,
        uBytes: uBytes,
        uRowStride: 4,
        uPixelStride: 2,
        vBytes: vBytes,
        vRowStride: 4,
        vPixelStride: 2,
      );

      // Expected: 8 Y bytes + 4 VU interleaved bytes (V0, U0, V1, U1)
      expect(
        nv21,
        Uint8List.fromList([10, 20, 30, 40, 50, 60, 70, 80, 211, 111, 222, 122]),
      );
    });

    test('computeSampledMeanLuma computes expected average brightness', () {
      final bright = Uint8List.fromList(List<int>.filled(64 * 64, 180));
      final dark = Uint8List.fromList(List<int>.filled(64 * 64, 20));

      expect(
        computeSampledMeanLuma(
          bytes: bright,
          width: 64,
          height: 64,
          bytesPerRow: 64,
        ),
        closeTo(180.0, 0.01),
      );
      expect(
        computeSampledMeanLuma(
          bytes: dark,
          width: 64,
          height: 64,
          bytesPerRow: 64,
        ),
        closeTo(20.0, 0.01),
      );
    });
  });
}
