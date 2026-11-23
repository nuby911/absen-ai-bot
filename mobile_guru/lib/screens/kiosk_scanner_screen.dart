import 'dart:async';

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

class _KioskScannerScreenState extends State<KioskScannerScreen> {
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

  bool _isInitializingCamera = false;
  String? _cameraError;
  bool _isDetectingFrame = false;
  bool _isSubmittingScan = false;
  bool _isPinSheetOpen = false;

  late int _recordedCount;
  ScanResult? _overlayResult;
  String? _scanError;
  LivenessDecision _decision = const LivenessDecision(
    status: LivenessStatus.noFace,
    instruction: 'Arahkan wajah ke dalam bingkai oval',
    shouldCapture: false,
  );

  @override
  void initState() {
    super.initState();
    _livenessDetector = widget.livenessDetector ?? BlinkLivenessDetector();
    _recordedCount = widget.session.summary.recordedCount;

    if (widget.sampleStream != null) {
      _sampleSubscription = widget.sampleStream!.listen(_handleFaceSample);
    }

    final shouldUseHardwareCamera = widget.enableHardwareCamera &&
        widget.sampleStream == null &&
        widget.previewBuilder == null;
    if (shouldUseHardwareCamera) {
      _initializeHardwarePipeline();
    }
  }

  @override
  void dispose() {
    _resetTimer?.cancel();
    _sampleSubscription?.cancel();
    _stopCameraSafely();
    _faceDetector?.close();
    super.dispose();
  }

  Future<void> _stopCameraSafely() async {
    final controller = _cameraController;
    _cameraController = null;
    if (controller == null) return;
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

  Future<void> _initializeHardwarePipeline() async {
    setState(() {
      _isInitializingCamera = true;
      _cameraError = null;
    });

    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        if (!mounted) return;
        setState(() {
          _isInitializingCamera = false;
          _cameraError = 'Tidak ada kamera yang terdeteksi pada perangkat ini.';
        });
        return;
      }

      final frontCamera = cameras.firstWhere(
        (cam) => cam.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      final imageFormat = defaultTargetPlatform == TargetPlatform.android
          ? ImageFormatGroup.nv21
          : ImageFormatGroup.bgra8888;

      final controller = CameraController(
        frontCamera,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: imageFormat,
      );
      await controller.initialize();

      final detector = FaceDetector(
        options: FaceDetectorOptions(
          enableClassification: true,
          enableTracking: true,
          performanceMode: FaceDetectorMode.fast,
          minFaceSize: 0.2,
        ),
      );

      if (!mounted) {
        await controller.dispose();
        await detector.close();
        return;
      }

      _cameraController = controller;
      _faceDetector = detector;

      await controller.startImageStream(_processCameraImage);

      if (!mounted) return;
      setState(() {
        _isInitializingCamera = false;
      });
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        _isInitializingCamera = false;
        _cameraError =
            'Gagal mengaktifkan kamera depan atau izin kamera ditolak ($exc).';
      });
    }
  }

  Future<void> _processCameraImage(CameraImage image) async {
    if (_isDetectingFrame ||
        _isSubmittingScan ||
        _isPinSheetOpen ||
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
    try {
      final inputImage = _buildInputImage(image, controller);
      if (inputImage == null) return;

      final faces = await detector.processImage(inputImage);
      if (!mounted) return;

      if (faces.isEmpty) {
        _handleFaceSample(null);
        return;
      }

      final primaryFace = faces.reduce((a, b) {
        final areaA = a.boundingBox.width * a.boundingBox.height;
        final areaB = b.boundingBox.width * b.boundingBox.height;
        return areaA >= areaB ? a : b;
      });

      _handleFaceSample(
        FaceSample(
          leftEyeOpenProbability: primaryFace.leftEyeOpenProbability,
          rightEyeOpenProbability: primaryFace.rightEyeOpenProbability,
          headEulerAngleY: primaryFace.headEulerAngleY,
          headEulerAngleZ: primaryFace.headEulerAngleZ,
          timestamp: DateTime.now(),
        ),
      );
    } catch (_) {
      // Abaikan frame yang gagal diproses agar stream kamera tetap berjalan stabil.
    } finally {
      _isDetectingFrame = false;
    }
  }

  InputImage? _buildInputImage(CameraImage image, CameraController controller) {
    final camera = controller.description;
    InputImageRotation? rotation;

    if (defaultTargetPlatform == TargetPlatform.iOS) {
      rotation = InputImageRotationValue.fromRawValue(camera.sensorOrientation);
    } else if (defaultTargetPlatform == TargetPlatform.android) {
      var rotationCompensation =
          _deviceOrientations[controller.value.deviceOrientation];
      if (rotationCompensation == null) return null;
      if (camera.lensDirection == CameraLensDirection.front) {
        rotationCompensation =
            (camera.sensorOrientation + rotationCompensation) % 360;
      } else {
        rotationCompensation =
            (camera.sensorOrientation - rotationCompensation + 360) % 360;
      }
      rotation = InputImageRotationValue.fromRawValue(rotationCompensation);
    }

    if (rotation == null) return null;

    final format = InputImageFormatValue.fromRawValue(image.format.raw);
    if (format == null) return null;

    if (image.planes.isEmpty) return null;

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

    return InputImage.fromBytes(
      bytes: bytes,
      metadata: InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: rotation,
        format: format,
        bytesPerRow: image.planes.first.bytesPerRow,
      ),
    );
  }

  void _handleFaceSample(FaceSample? sample) {
    if (!mounted ||
        _isSubmittingScan ||
        _isPinSheetOpen ||
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
    if (_isSubmittingScan || !mounted) return;

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
        if (controller.value.isStreamingImages) {
          await controller.stopImageStream();
        }
        final captured = await controller.takePicture();
        imageBytes = await captured.readAsBytes();
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
      _livenessDetector.markScanCompleted(DateTime.now());
      setState(() {
        _scanError = exc.message;
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
    _resetTimer?.cancel();
    _resetTimer = Timer(widget.autoResetDuration, _resetForNextStudent);
  }

  Future<void> _resetForNextStudent() async {
    if (!mounted) return;
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
    final controller = _cameraController;
    if (!mounted ||
        controller == null ||
        !controller.value.isInitialized ||
        _isPinSheetOpen) {
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

    if (!mounted) return;
    final verifiedPin = await KioskPinSheet.show(
      context,
      title: 'Masukkan PIN Kiosk Guru',
      subtitle:
          'Mode Kiosk terkunci. Masukkan PIN Guru untuk kembali ke Detail Sesi.',
      confirmLabel: 'Buka Kunci & Keluar Kiosk',
      cancelLabel: 'Batal — Kembali ke Pemindaian Wajah',
      onVerify: widget.verifyPinCallback ?? widget.apiClient.verifyKioskPin,
    );

    _isPinSheetOpen = false;
    if (!mounted) return;

    if (verifiedPin != null && verifiedPin.isNotEmpty) {
      _resetTimer?.cancel();
      Navigator.of(context).pop();
      return;
    }

    await _resumeCameraStreamIfNeeded();
  }

  Color _ovalBorderColor() {
    final result = _overlayResult;
    if (result != null) {
      if (result.matched) return AppColors.success;
      return AppColors.warning;
    }
    if (_scanError != null || _decision.status == LivenessStatus.poseInvalid) {
      return AppColors.warning;
    }
    return AppColors.kioskCyan;
  }

  String _positionPillText() {
    if (_overlayResult != null && _overlayResult!.matched) {
      return 'Wajah Teridentifikasi';
    }
    if (_overlayResult != null && !_overlayResult!.matched) {
      return 'Posisikan Ulang Wajah';
    }
    switch (_decision.status) {
      case LivenessStatus.noFace:
        return 'Mencari Wajah di Kamera';
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
                            _buildOvalGuide(ovalColor),
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
    final progressLabel =
        total > 0 ? '$_recordedCount/$total tercatat' : '$_recordedCount tercatat';

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 10),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.success.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: AppColors.success.withValues(alpha: 0.45),
              ),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.circle, size: 8, color: AppColors.success),
                SizedBox(width: 6),
                Text(
                  'LIVE KIOSK',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                    color: AppColors.success,
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
    if (widget.previewBuilder != null) {
      return widget.previewBuilder!(context);
    }

    if (_isInitializingCamera) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircularProgressIndicator(color: AppColors.kioskCyan),
            SizedBox(height: 12),
            Text(
              'Menyiapkan kamera depan Kiosk...',
              style: TextStyle(color: Color(0xFFCBD5E1), fontSize: 13.5),
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
                onPressed: _initializeHardwarePipeline,
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
      return _BannerMessageCard(
        icon: Icons.info_outline_rounded,
        accentColor: AppColors.kioskCyan,
        title: '${result.studentName ?? 'Siswa'} • Sudah tercatat hadir',
        message:
            'Kehadiran pada sesi ${widget.session.displayTitle} sudah tersimpan sebelumnya.',
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
