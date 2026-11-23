/// Data frame wajah yang diekstrak per frame dari Google ML Kit Face Detection.
class FaceSample {
  const FaceSample({
    required this.leftEyeOpenProbability,
    required this.rightEyeOpenProbability,
    required this.headEulerAngleY,
    required this.headEulerAngleZ,
    required this.timestamp,
  });

  final double? leftEyeOpenProbability;
  final double? rightEyeOpenProbability;

  /// Sudut yaw kepala dalam derajat (menoleh kiri/kanan).
  final double? headEulerAngleY;

  /// Sudut roll kepala dalam derajat (miring kiri/kanan).
  final double? headEulerAngleZ;

  final DateTime timestamp;
}

/// Tahapan mesin status verifikasi keaktifan berbasis kedipan mata.
enum LivenessStatus {
  noFace,
  poseInvalid,
  waitingOpen,
  waitingBlink,
  blinkDetectedWaitingReopen,
  passed,
  cooldown,
}

/// Hasil evaluasi liveness untuk satu frame wajah.
class LivenessDecision {
  const LivenessDecision({
    required this.status,
    required this.instruction,
    required this.shouldCapture,
  });

  final LivenessStatus status;
  final String instruction;
  final bool shouldCapture;
}

enum _BlinkPhase {
  waitingOpen,
  waitingBlink,
  blinkDetectedWaitingReopen,
}

/// State machine anti-spoofing berbasis kedipan mata (open -> closed -> open)
/// dengan validasi sudut kepala lurus dan cooldown pasca-scan Kiosk.
class BlinkLivenessDetector {
  BlinkLivenessDetector({
    this.openEyeThreshold = 0.7,
    this.closedEyeThreshold = 0.25,
    this.maxYawDegrees = 18.0,
    this.maxRollDegrees = 15.0,
    this.blinkWindow = const Duration(milliseconds: 2500),
    this.cooldownDuration = const Duration(milliseconds: 2500),
  });

  final double openEyeThreshold;
  final double closedEyeThreshold;
  final double maxYawDegrees;
  final double maxRollDegrees;
  final Duration blinkWindow;
  final Duration cooldownDuration;

  _BlinkPhase _phase = _BlinkPhase.waitingOpen;
  DateTime? _blinkWindowStart;
  DateTime? _cooldownStart;

  /// Mengembalikan `true` jika detektor sedang dalam masa tunggu pasca-scan.
  bool isInCooldown(DateTime now) {
    final cooldownStart = _cooldownStart;
    if (cooldownStart == null) {
      return false;
    }
    final elapsed = now.difference(cooldownStart);
    return !elapsed.isNegative && elapsed < cooldownDuration;
  }

  /// Menandai bahwa scan wajah telah selesai diproses dan memulai cooldown 2500 ms.
  void markScanCompleted(DateTime now) {
    _cooldownStart = now;
    _resetBlinkPhase();
  }

  /// Mengatur ulang seluruh status liveness dan cooldown ke kondisi awal.
  void reset() {
    _cooldownStart = null;
    _resetBlinkPhase();
  }

  void _resetBlinkPhase() {
    _phase = _BlinkPhase.waitingOpen;
    _blinkWindowStart = null;
  }

  /// Mengevaluasi satu frame wajah dan mengembalikan instruksi serta keputusan capture.
  LivenessDecision evaluate(FaceSample? sample, {DateTime? now}) {
    final timestamp = sample?.timestamp ?? now ?? DateTime.now();

    if (_cooldownStart != null) {
      if (isInCooldown(timestamp)) {
        _resetBlinkPhase();
        return const LivenessDecision(
          status: LivenessStatus.cooldown,
          instruction: 'Presensi berhasil, bersiap untuk siswa berikutnya...',
          shouldCapture: false,
        );
      }
      _cooldownStart = null;
    }

    if (sample == null) {
      _resetBlinkPhase();
      return const LivenessDecision(
        status: LivenessStatus.noFace,
        instruction: 'Arahkan wajah ke dalam bingkai oval',
        shouldCapture: false,
      );
    }

    final yaw = sample.headEulerAngleY;
    final roll = sample.headEulerAngleZ;
    if (yaw == null ||
        roll == null ||
        yaw.abs() >= maxYawDegrees ||
        roll.abs() >= maxRollDegrees) {
      _resetBlinkPhase();
      return const LivenessDecision(
        status: LivenessStatus.poseInvalid,
        instruction: 'Posisikan wajah lurus menghadap kamera',
        shouldCapture: false,
      );
    }

    final left = sample.leftEyeOpenProbability;
    final right = sample.rightEyeOpenProbability;
    if (left == null || right == null) {
      if (_phase == _BlinkPhase.blinkDetectedWaitingReopen &&
          _isWindowExpired(timestamp)) {
        _resetBlinkPhase();
      }
      return _currentWaitingDecision();
    }

    final bothOpen = left > openEyeThreshold && right > openEyeThreshold;
    final bothClosed = left < closedEyeThreshold && right < closedEyeThreshold;

    switch (_phase) {
      case _BlinkPhase.waitingOpen:
        if (bothOpen) {
          _phase = _BlinkPhase.waitingBlink;
          _blinkWindowStart = timestamp;
          return const LivenessDecision(
            status: LivenessStatus.waitingBlink,
            instruction: 'Silakan berkedip sekali untuk verifikasi',
            shouldCapture: false,
          );
        }
        return const LivenessDecision(
          status: LivenessStatus.waitingOpen,
          instruction: 'Arahkan wajah dan buka kedua mata',
          shouldCapture: false,
        );

      case _BlinkPhase.waitingBlink:
        if (bothOpen) {
          _blinkWindowStart = timestamp;
          return const LivenessDecision(
            status: LivenessStatus.waitingBlink,
            instruction: 'Silakan berkedip sekali untuk verifikasi',
            shouldCapture: false,
          );
        }
        if (bothClosed) {
          if (_isWindowExpired(timestamp)) {
            _resetBlinkPhase();
            return const LivenessDecision(
              status: LivenessStatus.waitingOpen,
              instruction: 'Waktu kedipan habis, buka mata lalu berkedip kembali',
              shouldCapture: false,
            );
          }
          _phase = _BlinkPhase.blinkDetectedWaitingReopen;
          return const LivenessDecision(
            status: LivenessStatus.blinkDetectedWaitingReopen,
            instruction: 'Kedipan terdeteksi, buka mata kembali...',
            shouldCapture: false,
          );
        }
        if (_isWindowExpired(timestamp)) {
          _resetBlinkPhase();
          return const LivenessDecision(
            status: LivenessStatus.waitingOpen,
            instruction: 'Arahkan wajah dan buka kedua mata',
            shouldCapture: false,
          );
        }
        return const LivenessDecision(
          status: LivenessStatus.waitingBlink,
          instruction: 'Silakan berkedip sekali untuk verifikasi',
          shouldCapture: false,
        );

      case _BlinkPhase.blinkDetectedWaitingReopen:
        if (_isWindowExpired(timestamp)) {
          _resetBlinkPhase();
          return const LivenessDecision(
            status: LivenessStatus.waitingOpen,
            instruction: 'Kedipan terlalu lama, buka mata lalu berkedip kembali',
            shouldCapture: false,
          );
        }
        if (bothOpen) {
          _resetBlinkPhase();
          return const LivenessDecision(
            status: LivenessStatus.passed,
            instruction: 'Verifikasi kedipan berhasil! Memindai wajah...',
            shouldCapture: true,
          );
        }
        return const LivenessDecision(
          status: LivenessStatus.blinkDetectedWaitingReopen,
          instruction: 'Kedipan terdeteksi, buka mata kembali...',
          shouldCapture: false,
        );
    }
  }

  bool _isWindowExpired(DateTime timestamp) {
    final windowStart = _blinkWindowStart;
    if (windowStart == null) {
      return true;
    }
    final elapsed = timestamp.difference(windowStart);
    return elapsed.isNegative || elapsed > blinkWindow;
  }

  LivenessDecision _currentWaitingDecision() {
    switch (_phase) {
      case _BlinkPhase.waitingOpen:
        return const LivenessDecision(
          status: LivenessStatus.waitingOpen,
          instruction: 'Arahkan wajah dan buka kedua mata',
          shouldCapture: false,
        );
      case _BlinkPhase.waitingBlink:
        return const LivenessDecision(
          status: LivenessStatus.waitingBlink,
          instruction: 'Silakan berkedip sekali untuk verifikasi',
          shouldCapture: false,
        );
      case _BlinkPhase.blinkDetectedWaitingReopen:
        return const LivenessDecision(
          status: LivenessStatus.blinkDetectedWaitingReopen,
          instruction: 'Kedipan terdeteksi, buka mata kembali...',
          shouldCapture: false,
        );
    }
  }
}
