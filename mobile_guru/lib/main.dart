import 'package:flutter/material.dart';

import 'core/api_client.dart';
import 'core/theme.dart';
import 'models/models.dart';
import 'screens/home_screen.dart';
import 'screens/kiosk_scanner_screen.dart';
import 'screens/leave_verification_screen.dart';
import 'screens/login_screen.dart';
import 'widgets/kiosk_pin_sheet.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SmartSchoolGuruApp());
}

/// Root aplikasi Mobile Guru SmartSchool AI.
class SmartSchoolGuruApp extends StatefulWidget {
  const SmartSchoolGuruApp({super.key, this.apiClient});

  final ApiClient? apiClient;

  @override
  State<SmartSchoolGuruApp> createState() => _SmartSchoolGuruAppState();
}

class _SmartSchoolGuruAppState extends State<SmartSchoolGuruApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  late final ApiClient _apiClient;
  UserProfile? _initialUser;
  bool _initializing = true;

  @override
  void initState() {
    super.initState();
    _apiClient = widget.apiClient ?? ApiClient();
    _apiClient.onUnauthorized = _handleUnauthorized;
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final user = await _apiClient.loadSavedSession();
    if (!mounted) return;
    setState(() {
      _initialUser = (user != null && user.role == 'teacher') ? user : null;
      _initializing = false;
    });
  }

  Widget _buildKioskScanner(
    BuildContext context,
    SessionDetail session,
    VoidCallback onAttendanceChanged,
  ) {
    return KioskScannerScreen(
      apiClient: _apiClient,
      session: session,
      onAttendanceRecorded: onAttendanceChanged,
    );
  }

  Widget _buildLeaveVerificationTab(
    BuildContext context,
    VoidCallback onLeaveChanged,
    int refreshTrigger,
  ) {
    return LeaveVerificationScreen(
      apiClient: _apiClient,
      onLeaveChanged: onLeaveChanged,
      refreshTrigger: refreshTrigger,
    );
  }

  Future<String?> _showKioskPinPrompt(
    BuildContext context, {
    required String title,
    required String subtitle,
    required String confirmLabel,
  }) {
    return KioskPinSheet.show(
      context,
      title: title,
      subtitle: subtitle,
      confirmLabel: confirmLabel,
      cancelLabel: 'Batal',
      onVerify: _apiClient.verifyKioskPin,
    );
  }

  void _handleUnauthorized() {
    _apiClient.logout();
    _navigatorKey.currentState?.pushAndRemoveUntil(
      MaterialPageRoute<void>(
        builder: (_) => LoginScreen(
          apiClient: _apiClient,
          kioskScannerBuilder: _buildKioskScanner,
          leaveVerificationBuilder: _buildLeaveVerificationTab,
          pinPromptBuilder: _showKioskPinPrompt,
        ),
      ),
      (route) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'SmartSchool AI — Guru',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: _initializing
          ? const _SplashLoadingScreen()
          : (_initialUser != null
              ? HomeScreen(
                  apiClient: _apiClient,
                  initialUser: _initialUser!,
                  kioskScannerBuilder: _buildKioskScanner,
                  leaveVerificationBuilder: _buildLeaveVerificationTab,
                  pinPromptBuilder: _showKioskPinPrompt,
                )
              : LoginScreen(
                  apiClient: _apiClient,
                  kioskScannerBuilder: _buildKioskScanner,
                  leaveVerificationBuilder: _buildLeaveVerificationTab,
                  pinPromptBuilder: _showKioskPinPrompt,
                )),
    );
  }
}

class _SplashLoadingScreen extends StatelessWidget {
  const _SplashLoadingScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.primary,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.face_retouching_natural,
              color: Colors.white,
              size: 56,
            ),
            SizedBox(height: 16),
            Text(
              'SmartSchool AI',
              style: TextStyle(
                color: Colors.white,
                fontSize: 24,
                fontWeight: FontWeight.w800,
              ),
            ),
            SizedBox(height: 16),
            CircularProgressIndicator(color: Colors.white),
          ],
        ),
      ),
    );
  }
}
