import 'dart:async';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';

import '../core/api_client.dart';
import '../core/formatters.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../services/liveness_detector.dart';
import '../widgets/kiosk_pin_sheet.dart';
import '../widgets/manual_attendance_dialog.dart';

/// Mengonversi 3-plane Android `YUV_420_888` (format raw `35`) menjadi buffer
/// `NV21` (Y diikuti VU interleaved) dengan menghormati `bytesPerRow` dan `bytesPerPixel`.
@visibleForTesting
Uint8List convertYuv420ToNv21({
  required int width,
  required int height,
  required Uint8List yBytes,
  required int yRowStride,
  required int yPixelStride,
  required Uint8List uBytes,
  required int uRowStride,
  required int uPixelStride,
  required Uint8List vBytes,
  required int vRowStride,
  required int vPixelStride,
}) {
  final ySize = width * height;
  final uvWidth = width ~/ 2;
  final uvHeight = height ~/ 2;
  final nv21 = Uint8List(ySize + uvWidth * uvHeight * 2);

  for (var row = 0; row < height; row++) {
    final dstRowStart = row * width;
    final srcRowStart = row * yRowStride;
    if (yPixelStride == 1 && srcRowStart + width <= yBytes.length) {
      nv21.setRange(dstRowStart, dstRowStart + width, yBytes, srcRowStart);
    } else {
      for (var col = 0; col < width; col++) {
        final srcIdx = srcRowStart + col * yPixelStride;
        if (srcIdx < yBytes.length) {
          nv21[dstRowStart + col] = yBytes[srcIdx];
        }
      }
    }
  }

  var outIdx = ySize;
  for (var row = 0; row < uvHeight; row++) {
    final uRowStart = row * uRowStride;
    final vRowStart = row * vRowStride;
    for (var col = 0; col < uvWidth; col++) {
      final vIdx = vRowStart + col * vPixelStride;
      final uIdx = uRowStart + col * uPixelStride;
      nv21[outIdx++] = vIdx < vBytes.length ? vBytes[vIdx] : 128;
      nv21[outIdx++] = uIdx < uBytes.length ? uBytes[uIdx] : 128;
    }
  }

  return nv21;
}

/// Menghitung rata-rata kecerahan (`0–255`) dari plane Y (atau BGRA pada iOS) secara sampling.
@visibleForTesting
double? computeSampledMeanLuma({
  required Uint8List bytes,
  required int width,
  required int height,
  required int bytesPerRow,
  int bytesPerPixel = 1,
  bool isBgra = false,
  int step = 8,
}) {
  if (bytes.isEmpty || width <= 0 || height <= 0 || bytesPerRow <= 0) {
    return null;
  }
  final effectiveStep = step < 1 ? 1 : step;
  final pixelStride = bytesPerPixel < 1 ? (isBgra ? 4 : 1) : bytesPerPixel;
  double sum = 0;
  var count = 0;

  for (var row = 0; row < height; row += effectiveStep) {
    final rowOffset = row * bytesPerRow;
    for (var col = 0; col < width; col += effectiveStep) {
      final idx = rowOffset + col * pixelStride;
      if (isBgra) {
        if (idx + 2 >= bytes.length) break;
        final b = bytes[idx];
        final g = bytes[idx + 1];
        final r = bytes[idx + 2];
        sum += 0.114 * b + 0.587 * g + 0.299 * r;
      } else {
        if (idx >= bytes.length) break;
        sum += bytes[idx];
      }
      count += 1;
    }
  }

  if (count == 0) return null;
  return sum / count;
}

/// Layar 04 & 05 Figma: Mode Kiosk Hands-Free (Live Kamera, Liveness Kedip, & Overlay Konfirmasi).
class KioskScannerScreen extends StatefulWidget {
  const KioskScannerScreen({
    super.key,
    required this.apiClient,
    required this.session,
    this.onAttendanceRecorded,
    this.livenessDetector,
    this.verifyPinCallback,
    this.onCaptureFaceBytes,
    this.sampleStream,
    this.previewBuilder,
    this.onPlaySuccessSound,
    this.autoResetDuration = const Duration(milliseconds: 2500),
    this.enableHardwareCamera = true,
  });

  final ApiClient apiClient;
  final SessionDetail session;
  final VoidCallback? onAttendanceRecorded;

  /// Hook opsional untuk injeksi dependensi dan pengujian widget tanpa hardware kamera.
  final BlinkLivenessDetector? livenessDetector;
  final Future<bool> Function(String pin)? verifyPinCallback;
  final Future<Uint8List> Function()? onCaptureFaceBytes;
  final Stream<FaceSample?>? sampleStream;
  final WidgetBuilder? previewBuilder;
  final Future<void> Function()? onPlaySuccessSound;
  final Duration autoResetDuration;
  final bool enableHardwareCamera;

  @override
  State<KioskScannerScreen> createState() => _KioskScannerScreenState();
}

class _KioskScannerScreenState extends State<KioskScannerScreen>
    with WidgetsBindingObserver {
  static const int _androidYuv420888Raw = 35;
  static const int _androidNv21Raw = 17;
  static const int _maxConsecutiveFrameErrors = 5;

  static const Map<DeviceOrientation, int> _deviceOrientations = {
    DeviceOrientation.portraitUp: 0,
    DeviceOrientation.landscapeLeft: 90,
    DeviceOrientation.portraitDown: 180,
    DeviceOrientation.landscapeRight: 270,
  };

  late final BlinkLivenessDetector _livenessDetector;
  CameraController? _cameraController;
  FaceDetector? _faceDetector;
  StreamSubscription<FaceSample?>? _sampleSubscription;
  Timer? _resetTimer;

  List<CameraDescription> _availableCameras = const [];
  CameraLensDirection _currentLensDirection = CameraLensDirection.front;

  bool _isInitializingCamera = false;
  bool _isSwitchingCamera = false;
  bool _wasPausedForLifecycle = false;
  String? _cameraError;
  String? _frameErrorBanner;
  int _consecutiveFrameErrors = 0;

  bool _isDetectingFrame = false;
  bool _isSubmittingScan = false;
  bool _isPinSheetOpen = false;
  bool _sessionClosed = false;

  late int _recordedCount;
  ScanResult? _overlayResult;
  String? _scanError;
  LivenessDecision _decision = const LivenessDecision(
    status: LivenessStatus.noFace,
    instruction: 'Arahkan wajah ke dalam bingkai oval',
    shouldCapture: false,
  );

  bool get _shouldUseHardwareCamera =>
      widget.enableHardwareCamera &&
      widget.sampleStream == null &&
      widget.previewBuilder == null;

  String get _activeCameraLabel =>
      _currentLensDirection == CameraLensDirection.front
          ? 'kamera depan'
          : 'kamera belakang';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _livenessDetector = widget.livenessDetector ?? BlinkLivenessDetector();
    _recordedCount = widget.session.summary.recordedCount;

    unawaited(
      SystemChrome.setPreferredOrientations(const [
        DeviceOrientation.portraitUp,
      ]).catchError((_) {}),
    );

    if (widget.sampleStream != null) {
      _sampleSubscription = widget.sampleStream!.listen(_handleFaceSample);
    }

    if (_shouldUseHardwareCamera) {
      _initializeHardwarePipeline();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_shouldUseHardwareCamera) return;

    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      _resetTimer?.cancel();
      _wasPausedForLifecycle = true;
      unawaited(_stopCameraSafely(closeDetector: true));
    } else if (state == AppLifecycleState.resumed) {
      if (_wasPausedForLifecycle && !_sessionClosed && !_isPinSheetOpen) {
        _wasPausedForLifecycle = false;
        unawaited(
          _initializeHardwarePipeline(preferredDirection: _currentLensDirection),
        );
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _resetTimer?.cancel();
    _sampleSubscription?.cancel();
    unawaited(_stopCameraSafely(closeDetector: true));
    unawaited(
      SystemChrome.setPreferredOrientations(const []).catchError((_) {}),
    );
    super.dispose();
  }

  Future<void> _stopCameraSafely({bool closeDetector = false}) async {
    final controller = _cameraController;
    _cameraController = null;
    if (controller != null) {
      try {
        if (controller.value.isStreamingImages) {
          await controller.stopImageStream();
        }
      } catch (_) {
        // Abaikan error saat penghentian stream pada teardown.
      }
      try {
        await controller.dispose();
      } catch (_) {
        // Abaikan error saat dispose controller.
      }
    }
    if (closeDetector) {
      final detector = _faceDetector;
      _faceDetector = null;
      if (detector != null) {
        try {
          await detector.close();
        } catch (_) {
          // Abaikan error saat menutup detector.
        }
      }
    }
  }

  Future<void> _initializeHardwarePipeline({
    CameraLensDirection? preferredDirection,
  }) async {
    if (!mounted || _sessionClosed) return;

    await _stopCameraSafely(closeDetector: true);
    if (!mounted || _sessionClosed) return;

    final targetDirection = preferredDirection ?? _currentLensDirection;
    setState(() {
      _currentLensDirection = targetDirection;
      _isInitializingCamera = true;
      _cameraError = null;
      _frameErrorBanner = null;
      _consecutiveFrameErrors = 0;
    });

    CameraController? localController;
    FaceDetector? localDetector;

    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        if (!mounted) return;
        setState(() {
          _availableCameras = const [];
          _isInitializingCamera = false;
          _cameraError = 'Tidak ada kamera yang terdeteksi pada perangkat ini.';
        });
        return;
      }

      _availableCameras = cameras;
      final selectedCamera = cameras.firstWhere(
        (cam) => cam.lensDirection == targetDirection,
        orElse: () => cameras.firstWhere(
          (cam) => cam.lensDirection == CameraLensDirection.front,
          orElse: () => cameras.first,
        ),
      );
      _currentLensDirection = selectedCamera.lensDirection;

      final imageFormat = defaultTargetPlatform == TargetPlatform.android
          ? ImageFormatGroup.nv21
          : ImageFormatGroup.bgra8888;

      localController = CameraController(
        selectedCamera,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: imageFormat,
      );
      await localController.initialize();
      try {
        await localController.lockCaptureOrientation(DeviceOrientation.portraitUp);
      } catch (_) {
        // Beberapa perangkat tidak mendukung lockCaptureOrientation.
      }

      localDetector = FaceDetector(
        options: FaceDetectorOptions(
          enableClassification: true,
          enableTracking: true,
          performanceMode: FaceDetectorMode.accurate,
          minFaceSize: 0.15,
        ),
      );

      if (!mounted || _sessionClosed) {
        await localController.dispose();
        await localDetector.close();
        return;
      }

      _cameraController = localController;
      _faceDetector = localDetector;

      await localController.startImageStream(_processCameraImage);

      if (!mounted) return;
      setState(() {
        _isInitializingCamera = false;
        _isSwitchingCamera = false;
      });
    } catch (exc) {
      if (localController != null && _cameraController != localController) {
        try {
          if (localController.value.isStreamingImages) {
            await localController.stopImageStream();
          }
        } catch (_) {}
        try {
          await localController.dispose();
        } catch (_) {}
      }
      if (localDetector != null && _faceDetector != localDetector) {
        try {
          await localDetector.close();
        } catch (_) {}
      }
      if (!mounted) return;
      setState(() {
        _isInitializingCamera = false;
        _isSwitchingCamera = false;
        _cameraError =
            'Gagal mengaktifkan $_activeCameraLabel atau izin kamera ditolak ($exc).';
      });
    }
  }

  Future<void> _toggleCameraDirection() async {
    if (_availableCameras.length < 2 ||
        _isInitializingCamera ||
        _isSwitchingCamera ||
        _isSubmittingScan ||
        _sessionClosed) {
      return;
    }

    final nextDirection = _currentLensDirection == CameraLensDirection.front
        ? CameraLensDirection.back
        : CameraLensDirection.front;

    setState(() {
      _isSwitchingCamera = true;
    });
    _livenessDetector.reset();
    await _initializeHardwarePipeline(preferredDirection: nextDirection);
  }

  Future<void> _processCameraImage(CameraImage image) async {
    if (_isDetectingFrame ||
        _isSubmittingScan ||
        _isPinSheetOpen ||
        _sessionClosed ||
        _overlayResult != null ||
        _scanError != null) {
      return;
    }

    final controller = _cameraController;
    final detector = _faceDetector;
    if (controller == null || detector == null || !controller.value.isInitialized) {
      return;
    }

    _isDetectingFrame = true;
    FaceSample? extractedSample;
    var hasProcessedFrame = false;

    try {
      final prepared = _buildInputImage(image, controller);
      if (prepared == null) {
        _recordFrameError('Format frame kamera tidak dikenali.');
        return;
      }

      final faces = await detector.processImage(prepared.inputImage);
      if (!mounted) return;

      hasProcessedFrame = true;
      if (_consecutiveFrameErrors > 0 || _frameErrorBanner != null) {
        setState(() {
          _consecutiveFrameErrors = 0;
          _frameErrorBanner = null;
        });
      }

      if (faces.isEmpty) {
        extractedSample = null;
      } else {
        final primaryFace = faces.reduce((a, b) {
          final areaA = a.boundingBox.width * a.boundingBox.height;
          final areaB = b.boundingBox.width * b.boundingBox.height;
          return areaA >= areaB ? a : b;
        });

        final isRotated =
            prepared.rotation == InputImageRotation.rotation90deg ||
            prepared.rotation == InputImageRotation.rotation270deg;
        final uprightWidth = (isRotated ? image.height : image.width).toDouble();
        final uprightHeight = (isRotated ? image.width : image.height).toDouble();

        final box = primaryFace.boundingBox;
        final faceWidthRatio =
            uprightWidth > 0 ? box.width / uprightWidth : null;
        final centerX =
            uprightWidth > 0 ? box.center.dx / uprightWidth : 0.5;
        final centerY =
            uprightHeight > 0 ? box.center.dy / uprightHeight : 0.5;
        final isCentered =
            centerX >= 0.20 &&
            centerX <= 0.80 &&
            centerY >= 0.18 &&
            centerY <= 0.82;

        final meanLuma = _computeFrameMeanLuma(image);

        extractedSample = FaceSample(
          leftEyeOpenProbability: primaryFace.leftEyeOpenProbability,
          rightEyeOpenProbability: primaryFace.rightEyeOpenProbability,
          headEulerAngleY: primaryFace.headEulerAngleY,
          headEulerAngleZ: primaryFace.headEulerAngleZ,
          timestamp: DateTime.now(),
          faceCount: faces.length,
          faceWidthRatio: faceWidthRatio,
          isCentered: isCentered,
          meanLuma: meanLuma,
        );
      }
    } catch (exc, stack) {
      debugPrint(
        'Kiosk frame processing error (#${_consecutiveFrameErrors + 1}): $exc\n$stack',
      );
      _recordFrameError('Gangguan membaca frame kamera/ML Kit ($exc).');
    } finally {
      _isDetectingFrame = false;
    }

    if (hasProcessedFrame && mounted) {
      _handleFaceSample(extractedSample);
    }
  }

  void _recordFrameError(String reason) {
    _consecutiveFrameErrors += 1;
    if (_consecutiveFrameErrors >= _maxConsecutiveFrameErrors && mounted) {
      setState(() {
        _frameErrorBanner =
            'Pemrosesan kamera mengalami gangguan berulang. Ketuk Coba Ulang untuk memuat ulang kamera.';
      });
      debugPrint('Kiosk frame error banner activated: $reason');
    }
  }

  double? _computeFrameMeanLuma(CameraImage image) {
    if (image.planes.isEmpty) return null;
    final plane0 = image.planes.first;
    final isBgra = defaultTargetPlatform == TargetPlatform.iOS;
    return computeSampledMeanLuma(
      bytes: plane0.bytes,
      width: image.width,
      height: image.height,
      bytesPerRow: plane0.bytesPerRow,
      bytesPerPixel: plane0.bytesPerPixel ?? (isBgra ? 4 : 1),
      isBgra: isBgra,
    );
  }

  ({InputImage inputImage, InputImageRotation rotation})? _buildInputImage(
    CameraImage image,
    CameraController controller,
  ) {
    final camera = controller.description;
    InputImageRotation? rotation;

    if (defaultTargetPlatform == TargetPlatform.iOS) {
      rotation = InputImageRotationValue.fromRawValue(camera.sensorOrientation);
    } else if (defaultTargetPlatform == TargetPlatform.android) {
      var rotationCompensation =
          _deviceOrientations[controller.value.deviceOrientation] ?? 0;
      if (camera.lensDirection == CameraLensDirection.front) {
        rotationCompensation =
            (camera.sensorOrientation + rotationCompensation) % 360;
      } else {
        rotationCompensation =
            (camera.sensorOrientation - rotationCompensation + 360) % 360;
      }
      rotation = InputImageRotationValue.fromRawValue(rotationCompensation);
    }

    if (rotation == null || image.planes.isEmpty) return null;

    if (image.format.raw == _androidYuv420888Raw && image.planes.length == 3) {
      final yPlane = image.planes[0];
      final uPlane = image.planes[1];
      final vPlane = image.planes[2];
      final nv21Bytes = convertYuv420ToNv21(
        width: image.width,
        height: image.height,
        yBytes: yPlane.bytes,
        yRowStride: yPlane.bytesPerRow,
        yPixelStride: yPlane.bytesPerPixel ?? 1,
        uBytes: uPlane.bytes,
        uRowStride: uPlane.bytesPerRow,
        uPixelStride: uPlane.bytesPerPixel ?? 1,
        vBytes: vPlane.bytes,
        vRowStride: vPlane.bytesPerRow,
        vPixelStride: vPlane.bytesPerPixel ?? 1,
      );
      return (
        inputImage: InputImage.fromBytes(
          bytes: nv21Bytes,
          metadata: InputImageMetadata(
            size: Size(image.width.toDouble(), image.height.toDouble()),
            rotation: rotation,
            format: InputImageFormat.nv21,
            bytesPerRow: image.width,
          ),
        ),
        rotation: rotation,
      );
    }

    if (image.format.raw == _androidNv21Raw && image.planes.length == 1) {
      return (
        inputImage: InputImage.fromBytes(
          bytes: image.planes.first.bytes,
          metadata: InputImageMetadata(
            size: Size(image.width.toDouble(), image.height.toDouble()),
            rotation: rotation,
            format: InputImageFormat.nv21,
            bytesPerRow: image.planes.first.bytesPerRow,
          ),
        ),
        rotation: rotation,
      );
    }

    final format = InputImageFormatValue.fromRawValue(image.format.raw);
    if (format == null) return null;

    final Uint8List bytes;
    if (image.planes.length == 1) {
      bytes = image.planes.first.bytes;
    } else {
      final buffer = WriteBuffer();
      for (final plane in image.planes) {
        buffer.putUint8List(plane.bytes);
      }
      bytes = buffer.done().buffer.asUint8List();
    }

    return (
      inputImage: InputImage.fromBytes(
        bytes: bytes,
        metadata: InputImageMetadata(
          size: Size(image.width.toDouble(), image.height.toDouble()),
          rotation: rotation,
          format: format,
          bytesPerRow: image.planes.first.bytesPerRow,
        ),
      ),
      rotation: rotation,
    );
  }

  void _handleFaceSample(FaceSample? sample) {
    if (!mounted ||
        _isSubmittingScan ||
        _isPinSheetOpen ||
        _sessionClosed ||
        _overlayResult != null ||
        _scanError != null) {
      return;
    }

    final decision = _livenessDetector.evaluate(
      sample,
      now: sample?.timestamp ?? DateTime.now(),
    );

    setState(() {
      _decision = decision;
    });

    if (decision.shouldCapture) {
      _captureAndSubmitScan();
    }
  }

  Future<void> _captureAndSubmitScan() async {
    if (_isSubmittingScan || _sessionClosed || !mounted) return;

    setState(() {
      _isSubmittingScan = true;
      _scanError = null;
    });

    try {
      final Uint8List imageBytes;
      if (widget.onCaptureFaceBytes != null) {
        imageBytes = await widget.onCaptureFaceBytes!();
      } else {
        final controller = _cameraController;
        if (controller == null || !controller.value.isInitialized) {
          throw const ApiException(
            statusCode: 0,
            message: 'Kamera belum siap untuk mengambil gambar wajah.',
          );
        }
        XFile? captured;
        try {
          if (controller.value.isStreamingImages) {
            await controller.stopImageStream();
          }
          captured = await controller.takePicture().timeout(
                const Duration(seconds: 8),
              );
          imageBytes = await captured.readAsBytes();
        } finally {
          if (captured != null) {
            try {
              final tempFile = File(captured.path);
              if (await tempFile.exists()) {
                await tempFile.delete();
              }
            } catch (_) {
              // Abaikan error pembersihan berkas temporer.
            }
          }
        }
      }

      final result = await widget.apiClient.scanKioskFace(
        sessionId: widget.session.id,
        imageBytes: imageBytes,
        livenessPassed: true,
      );

      if (!mounted) return;

      if (result.matched && !result.alreadyRecorded) {
        await (widget.onPlaySuccessSound ?? _playDefaultSuccessSound)();
        widget.onAttendanceRecorded?.call();
        _recordedCount += 1;
      }

      _livenessDetector.markScanCompleted(DateTime.now());
      setState(() {
        _overlayResult = result;
        _isSubmittingScan = false;
      });
      _scheduleAutoReset();
    } on ApiException catch (exc) {
      if (!mounted) return;
      final isSessionClosedError = exc.statusCode == 400 &&
          !exc.message.toLowerCase().contains('liveness');
      if (isSessionClosedError) {
        _resetTimer?.cancel();
        unawaited(_stopCameraSafely());
        setState(() {
          _sessionClosed = true;
          _isSubmittingScan = false;
          _overlayResult = null;
          _scanError = null;
        });
        return;
      }
      _livenessDetector.markScanCompleted(DateTime.now());
      setState(() {
        _scanError = exc.message;
        _isSubmittingScan = false;
      });
      _scheduleAutoReset();
    } on TimeoutException {
      if (!mounted) return;
      _livenessDetector.markScanCompleted(DateTime.now());
      setState(() {
        _scanError = 'Pengambilan foto kamera terlalu lama. Mencoba ulang...';
        _isSubmittingScan = false;
      });
      _scheduleAutoReset();
    } catch (_) {
      if (!mounted) return;
      _livenessDetector.markScanCompleted(DateTime.now());
      setState(() {
        _scanError = 'Terjadi gangguan saat memindai wajah. Mencoba ulang...';
        _isSubmittingScan = false;
      });
      _scheduleAutoReset();
    }
  }

  Future<void> _playDefaultSuccessSound() async {
    try {
      await SystemSound.play(SystemSoundType.click);
      await HapticFeedback.mediumImpact();
    } catch (_) {
      // Abaikan pada platform yang tidak mendukung SystemSound.
    }
  }

  void _scheduleAutoReset() {
    if (_sessionClosed) return;
    _resetTimer?.cancel();
    _resetTimer = Timer(widget.autoResetDuration, _resetForNextStudent);
  }

  Future<void> _resetForNextStudent() async {
    if (!mounted || _sessionClosed) return;
    _livenessDetector.reset();
    setState(() {
      _overlayResult = null;
      _scanError = null;
      _decision = const LivenessDecision(
        status: LivenessStatus.noFace,
        instruction: 'Arahkan wajah ke dalam bingkai oval',
        shouldCapture: false,
      );
    });
    await _resumeCameraStreamIfNeeded();
  }

  Future<void> _resumeCameraStreamIfNeeded() async {
    if (!mounted ||
        _isSubmittingScan ||
        _overlayResult != null ||
        _scanError != null ||
        _isPinSheetOpen ||
        _sessionClosed) {
      return;
    }
    final controller = _cameraController;
    if (controller == null || !controller.value.isInitialized) {
      return;
    }
    if (!controller.value.isStreamingImages) {
      try {
        await controller.startImageStream(_processCameraImage);
      } catch (_) {
        // Abaikan jika stream sudah aktif atau kamera sedang berhenti.
      }
    }
  }

  Future<void> _promptPinToExit() async {
    if (_isPinSheetOpen || !mounted) return;

    _isPinSheetOpen = true;
    final controller = _cameraController;
    if (controller != null &&
        controller.value.isInitialized &&
        controller.value.isStreamingImages) {
      try {
        await controller.stopImageStream();
      } catch (_) {}
    }

    if (!mounted) {
      _isPinSheetOpen = false;
      return;
    }

    final result = await KioskPinSheet.showWithAction(
      context,
      title: 'Masukkan PIN Kiosk Guru',
      subtitle: _sessionClosed
          ? 'Sesi telah ditutup. Masukkan PIN Guru untuk keluar dari Mode Kiosk.'
          : 'Mode Kiosk terkunci. Masukkan PIN Guru untuk keluar atau mencatat absen manual.',
      confirmLabel: 'Buka Kunci & Keluar Kiosk',
      secondaryActionLabel: _sessionClosed ? null : 'Absen Manual',
      cancelLabel: 'Batal — Kembali ke Pemindaian Wajah',
      onVerify: widget.verifyPinCallback ?? widget.apiClient.verifyKioskPin,
    );

    if (!mounted) {
      _isPinSheetOpen = false;
      return;
    }

    if (result != null && result.pin.isNotEmpty) {
      if (result.action == KioskPinAction.secondary && !_sessionClosed) {
        await _openManualAttendanceWithPin(result.pin);
        _isPinSheetOpen = false;
        await _resumeCameraStreamIfNeeded();
        return;
      }

      _isPinSheetOpen = false;
      _resetTimer?.cancel();
      Navigator.of(context).pop();
      return;
    }

    _isPinSheetOpen = false;
    await _resumeCameraStreamIfNeeded();
  }

  Future<void> _openManualAttendanceWithPin(String verifiedPin) async {
    List<StudentAttendanceItem> candidates;
    SessionDetail activeDetail = widget.session;
    try {
      activeDetail = await widget.apiClient.getSessionDetail(widget.session.id);
    } catch (_) {
      activeDetail = widget.session;
    }

    try {
      candidates = await loadManualAttendanceCandidates(
        widget.apiClient,
        activeDetail,
      );
    } on ApiException catch (exc) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(exc.message), backgroundColor: AppColors.danger),
      );
      return;
    } catch (exc) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Gagal memuat daftar siswa: $exc'),
          backgroundColor: AppColors.danger,
        ),
      );
      return;
    }

    if (!mounted) return;
    if (candidates.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Belum ada data siswa aktif untuk input manual.'),
          backgroundColor: AppColors.danger,
        ),
      );
      return;
    }

    final selection = await showDialog<ManualAttendanceSelection>(
      context: context,
      builder: (_) => ManualAttendanceDialog(
        students: candidates,
        isGeneralGate: activeDetail.classId == null,
      ),
    );

    if (selection == null || !mounted) return;

    final previousItem = candidates.firstWhere(
      (s) => s.studentId == selection.studentId,
      orElse: () => candidates.first,
    );

    try {
      final manualResult = await widget.apiClient.submitManualAttendance(
        sessionId: widget.session.id,
        studentId: selection.studentId,
        status: selection.status,
        kioskPin: verifiedPin,
        notifyWa: selection.notifyWa,
      );
      if (!mounted) return;
      if (previousItem.status == 'unrecorded') {
        setState(() => _recordedCount += 1);
      }
      widget.onAttendanceRecorded?.call();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(manualResult.message),
          backgroundColor: AppColors.success,
        ),
      );
    } on ApiException catch (exc) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(exc.message), backgroundColor: AppColors.danger),
      );
    } catch (exc) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Gagal menyimpan presensi manual: $exc'),
          backgroundColor: AppColors.danger,
        ),
      );
    }
  }

  Color _ovalBorderColor() {
    if (_sessionClosed) return AppColors.danger;
    final result = _overlayResult;
    if (result != null) {
      if (result.matched) return AppColors.success;
      return AppColors.warning;
    }
    if (_scanError != null || _frameErrorBanner != null) {
      return AppColors.warning;
    }
    switch (_decision.status) {
      case LivenessStatus.multipleFaces:
      case LivenessStatus.tooFar:
      case LivenessStatus.tooClose:
      case LivenessStatus.poorLighting:
      case LivenessStatus.poseInvalid:
        return AppColors.warning;
      case LivenessStatus.noFace:
      case LivenessStatus.waitingOpen:
      case LivenessStatus.waitingBlink:
      case LivenessStatus.blinkDetectedWaitingReopen:
      case LivenessStatus.passed:
      case LivenessStatus.cooldown:
        return AppColors.kioskCyan;
    }
  }

  String _positionPillText() {
    if (_sessionClosed) {
      return 'Sesi Telah Ditutup';
    }
    if (_overlayResult != null && _overlayResult!.matched) {
      return 'Wajah Teridentifikasi';
    }
    if (_overlayResult != null && !_overlayResult!.matched) {
      return 'Posisikan Ulang Wajah';
    }
    switch (_decision.status) {
      case LivenessStatus.noFace:
        return 'Mencari Wajah di Kamera';
      case LivenessStatus.multipleFaces:
        return 'Terdeteksi Banyak Wajah';
      case LivenessStatus.tooFar:
        return 'Wajah Terlalu Jauh';
      case LivenessStatus.tooClose:
        return 'Wajah Terlalu Dekat';
      case LivenessStatus.poorLighting:
        return 'Cahaya Terlalu Gelap';
      case LivenessStatus.poseInvalid:
        return 'Jarak & Sudut Kurang Lurus';
      case LivenessStatus.waitingOpen:
      case LivenessStatus.waitingBlink:
      case LivenessStatus.blinkDetectedWaitingReopen:
      case LivenessStatus.passed:
        return 'Posisi Wajah Optimal';
      case LivenessStatus.cooldown:
        return 'Siap Untuk Siswa Berikutnya';
    }
  }

  @override
  Widget build(BuildContext context) {
    final ovalColor = _ovalBorderColor();

    return PopScope<dynamic>(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) {
        if (didPop) return;
        _promptPinToExit();
      },
      child: AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.light,
        child: Scaffold(
          backgroundColor: AppColors.kioskBackground,
          body: SafeArea(
            child: Column(
              children: [
                _buildTopHud(),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(28),
                      child: Container(
                        width: double.infinity,
                        color: AppColors.kioskViewport,
                        child: Stack(
                          fit: StackFit.expand,
                          children: [
                            _buildViewportContent(),
                            if (!_sessionClosed) _buildOvalGuide(ovalColor),
                            Positioned(
                              top: 16,
                              left: 16,
                              right: 16,
                              child: Center(
                                child: _StatusPill(
                                  label: _positionPillText(),
                                  color: ovalColor,
                                ),
                              ),
                            ),
                            Positioned(
                              left: 16,
                              right: 16,
                              bottom: 16,
                              child: _buildBottomFeedback(ovalColor),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTopHud() {
    final total = widget.session.summary.totalStudents;
    final isGeneralGate = widget.session.classId == null;
    final progressLabel = (!isGeneralGate && total > 0)
        ? '$_recordedCount/$total tercatat'
        : '$_recordedCount tercatat';

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: (_sessionClosed ? AppColors.danger : AppColors.success)
                  .withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: (_sessionClosed ? AppColors.danger : AppColors.success)
                    .withValues(alpha: 0.45),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.circle,
                  size: 8,
                  color: _sessionClosed ? AppColors.danger : AppColors.success,
                ),
                const SizedBox(width: 6),
                Text(
                  _sessionClosed ? 'SESI TUTUP' : 'LIVE KIOSK',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                    color: _sessionClosed ? AppColors.danger : AppColors.success,
                    letterSpacing: 0.4,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.session.displayTitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
                Text(
                  '${widget.session.displayClassName} • $progressLabel',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFFCBD5E1),
                  ),
                ),
              ],
            ),
          ),
          if (_availableCameras.length > 1 && !_sessionClosed) ...[
            const SizedBox(width: 6),
            Material(
              color: AppColors.kioskViewport,
              borderRadius: BorderRadius.circular(14),
              child: InkWell(
                key: const Key('kiosk_switch_camera_button'),
                onTap: (_isInitializingCamera || _isSwitchingCamera)
                    ? null
                    : _toggleCameraDirection,
                borderRadius: BorderRadius.circular(14),
                child: Container(
                  padding: const EdgeInsets.all(9),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: Colors.white.withValues(alpha: 0.18),
                    ),
                  ),
                  child: const Icon(
                    Icons.cameraswitch_rounded,
                    size: 18,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
          ],
          const SizedBox(width: 8),
          Material(
            color: AppColors.kioskViewport,
            borderRadius: BorderRadius.circular(14),
            child: InkWell(
              key: const Key('kiosk_pin_button'),
              onTap: _promptPinToExit,
              borderRadius: BorderRadius.circular(14),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.18),
                  ),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.lock_outline_rounded, size: 16, color: Colors.white),
                    SizedBox(width: 5),
                    Text(
                      'PIN',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildViewportContent() {
    if (_sessionClosed) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppColors.danger.withValues(alpha: 0.16),
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.lock_clock_rounded,
                  size: 48,
                  color: AppColors.danger,
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Sesi Telah Ditutup',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Sesi presensi ini sudah ditutup oleh guru/admin. Pemindaian wajah dihentikan.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Color(0xFFCBD5E1), fontSize: 13.5),
              ),
              const SizedBox(height: 18),
              ElevatedButton.icon(
                key: const Key('kiosk_session_closed_exit_button'),
                onPressed: _promptPinToExit,
                icon: const Icon(Icons.lock_open_rounded),
                label: const Text('Keluar Kiosk (PIN Guru)'),
              ),
            ],
          ),
        ),
      );
    }

    if (widget.previewBuilder != null) {
      return widget.previewBuilder!(context);
    }

    if (_isInitializingCamera) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: AppColors.kioskCyan),
            const SizedBox(height: 12),
            Text(
              'Menyiapkan $_activeCameraLabel Kiosk...',
              style: const TextStyle(color: Color(0xFFCBD5E1), fontSize: 13.5),
            ),
          ],
        ),
      );
    }

    if (_cameraError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.videocam_off_outlined,
                size: 48,
                color: AppColors.warning,
              ),
              const SizedBox(height: 12),
              Text(
                _cameraError!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white, fontSize: 13.5),
              ),
              const SizedBox(height: 14),
              ElevatedButton.icon(
                onPressed: () => _initializeHardwarePipeline(
                  preferredDirection: _currentLensDirection,
                ),
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Coba Aktifkan Kamera'),
              ),
            ],
          ),
        ),
      );
    }

    final controller = _cameraController;
    if (controller != null && controller.value.isInitialized) {
      return FittedBox(
        fit: BoxFit.cover,
        child: SizedBox(
          width: controller.value.previewSize?.height ?? 720,
          height: controller.value.previewSize?.width ?? 1280,
          child: CameraPreview(controller),
        ),
      );
    }

    return const Center(
      child: Icon(
        Icons.face_retouching_natural_rounded,
        size: 72,
        color: Color(0xFF475569),
      ),
    );
  }

  Widget _buildOvalGuide(Color borderColor) {
    return IgnorePointer(
      child: Center(
        child: FractionallySizedBox(
          widthFactor: 0.64,
          heightFactor: 0.56,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            decoration: BoxDecoration(
              shape: BoxShape.rectangle,
              borderRadius: const BorderRadius.all(Radius.elliptical(220, 290)),
              border: Border.all(color: borderColor, width: 3.5),
              boxShadow: [
                BoxShadow(
                  color: borderColor.withValues(alpha: 0.25),
                  blurRadius: 24,
                  spreadRadius: 2,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBottomFeedback(Color accentColor) {
    if (_sessionClosed) {
      return const _BannerMessageCard(
        icon: Icons.lock_outline_rounded,
        accentColor: AppColors.danger,
        title: 'Sesi Telah Ditutup',
        message: 'Masukkan PIN Guru untuk keluar dan melihat rekap sesi.',
      );
    }

    if (_frameErrorBanner != null) {
      return Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppColors.kioskBackground.withValues(alpha: 0.94),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: AppColors.warning, width: 1.5),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline_rounded, color: AppColors.warning),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                _frameErrorBanner!,
                style: const TextStyle(color: Colors.white, fontSize: 12.5),
              ),
            ),
            const SizedBox(width: 8),
            TextButton(
              onPressed: () {
                setState(() {
                  _consecutiveFrameErrors = 0;
                  _frameErrorBanner = null;
                });
                _initializeHardwarePipeline(
                  preferredDirection: _currentLensDirection,
                );
              },
              child: const Text('Coba Ulang'),
            ),
          ],
        ),
      );
    }

    if (_overlayResult != null) {
      return _buildOverlayResultCard(_overlayResult!);
    }

    if (_scanError != null) {
      return _BannerMessageCard(
        icon: Icons.warning_amber_rounded,
        accentColor: AppColors.warning,
        title: 'Pemindaian Belum Berhasil',
        message: _scanError!,
      );
    }

    final instructionText = _isSubmittingScan
        ? 'Memverifikasi wajah & mencatat kehadiran...'
        : _decision.instruction;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppColors.kioskBackground.withValues(alpha: 0.88),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: accentColor.withValues(alpha: 0.45)),
      ),
      child: Row(
        children: [
          if (_isSubmittingScan)
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(
                strokeWidth: 2.2,
                color: AppColors.kioskCyan,
              ),
            )
          else
            Icon(Icons.visibility_outlined, color: accentColor, size: 22),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              instructionText,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOverlayResultCard(ScanResult result) {
    if (!result.matched) {
      return const _BannerMessageCard(
        icon: Icons.person_search_rounded,
        accentColor: AppColors.warning,
        title: 'Wajah Belum Teridentifikasi',
        message: 'Wajah tidak dikenali, posisikan ulang wajah Anda',
      );
    }

    if (result.alreadyRecorded) {
      final statusLabel = result.status != null && result.status!.isNotEmpty
          ? AppFormatters.attendanceStatusLabel(result.status!)
          : 'Tercatat';
      return _BannerMessageCard(
        icon: Icons.info_outline_rounded,
        accentColor: AppColors.kioskCyan,
        title: '${result.studentName ?? 'Siswa'} • Sudah tercatat ($statusLabel)',
        message:
            'Status $statusLabel pada sesi ${widget.session.displayTitle} sudah tersimpan sebelumnya.',
      );
    }

    final isLate = result.status == 'late';
    final statusColor = isLate ? AppColors.warning : AppColors.success;
    final statusBadgeLabel = isLate ? 'TERLAMBAT' : 'HADIR TEPAT WAKTU';
    final waSentOk =
        result.waStatus == 'sent' || (result.waQueued && result.waStatus != 'failed');
    final studentName = result.studentName ?? 'Siswa Teridentifikasi';
    final nis = result.nis ?? '-';
    final className = result.className ?? widget.session.displayClassName;
    final timeWib = AppFormatters.formatWibTime(result.scannedAt ?? DateTime.now());
    final resetSeconds = (widget.autoResetDuration.inMilliseconds / 1000)
        .toStringAsFixed(1)
        .replaceAll('.', ',');

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppColors.success, width: 2),
        boxShadow: [
          BoxShadow(
            color: AppColors.success.withValues(alpha: 0.25),
            blurRadius: 24,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 24,
                backgroundColor: AppColors.successTint,
                child: Text(
                  AppFormatters.initials(studentName),
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: AppColors.success,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      studentName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 16.5,
                        fontWeight: FontWeight.w800,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'NIS $nis • $className',
                      style: const TextStyle(
                        fontSize: 12.5,
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: isLate ? AppColors.warningTint : AppColors.successTint,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  statusBadgeLabel,
                  style: TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w800,
                    color: statusColor,
                  ),
                ),
              ),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.access_time_rounded,
                    size: 14,
                    color: AppColors.textSecondary,
                  ),
                  const SizedBox(width: 4),
                  Text(
                    timeWib,
                    style: const TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textPrimary,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: waSentOk ? AppColors.successTint : AppColors.warningTint,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Text(
                  waSentOk ? '✓' : '!',
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800,
                    color: waSentOk ? AppColors.success : AppColors.warning,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    waSentOk
                        ? 'Notifikasi WhatsApp Orang Tua Terkirim'
                        : 'Notifikasi WhatsApp tertunda (kirim ulang dari Detail Sesi)',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: waSentOk ? AppColors.success : AppColors.warning,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Siap memindai siswa berikutnya dalam $resetSeconds detik...',
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 11.5,
              color: AppColors.textMuted,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      decoration: BoxDecoration(
        color: AppColors.kioskBackground.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.55)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.center_focus_strong_rounded, size: 15, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w700,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _BannerMessageCard extends StatelessWidget {
  const _BannerMessageCard({
    required this.icon,
    required this.accentColor,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final Color accentColor;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.kioskBackground.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: accentColor, width: 1.5),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: accentColor.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: accentColor, size: 22),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w800,
                    color: accentColor,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  message,
                  style: const TextStyle(
                    fontSize: 12.5,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
