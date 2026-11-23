import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../models/models.dart';
import 'home_screen.dart';

/// Layar 01 Figma: Autentikasi Guru (NIP/Email, Kata Sandi, & PIN Kiosk opsional).
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.apiClient,
    this.kioskScannerBuilder,
    this.leaveVerificationBuilder,
    this.pinPromptBuilder,
    this.onLoginSuccess,
  });

  final ApiClient apiClient;
  final KioskScannerBuilder? kioskScannerBuilder;
  final LeaveVerificationTabBuilder? leaveVerificationBuilder;
  final ManualPinPromptBuilder? pinPromptBuilder;
  final void Function(UserProfile user)? onLoginSuccess;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _identifierController = TextEditingController();
  final _passwordController = TextEditingController();
  final _pinController = TextEditingController();

  bool _obscurePassword = true;
  bool _obscurePin = true;
  bool _isSubmitting = false;
  String? _errorMessage;

  @override
  void dispose() {
    _identifierController.dispose();
    _passwordController.dispose();
    _pinController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final result = await widget.apiClient.login(
        identifier: _identifierController.text.trim(),
        password: _passwordController.text,
      );

      if (result.user.role != 'teacher') {
        await widget.apiClient.logout();
        if (!mounted) return;
        setState(() {
          _errorMessage =
              'Akun ini berstatus "${result.user.role}". Aplikasi mobile hanya diperuntukkan bagi akun Guru.';
          _isSubmitting = false;
        });
        return;
      }

      var activeUser = result.user;
      final pinText = _pinController.text.trim();
      if (pinText.isNotEmpty) {
        try {
          await widget.apiClient.updateKioskPin(pinText);
        } catch (_) {
          await widget.apiClient.logout();
          rethrow;
        }
        activeUser = activeUser.copyWith(hasKioskPin: true);
      }

      if (!mounted) return;
      if (widget.onLoginSuccess != null) {
        widget.onLoginSuccess!(activeUser);
        return;
      }

      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => HomeScreen(
            apiClient: widget.apiClient,
            initialUser: activeUser,
            kioskScannerBuilder: widget.kioskScannerBuilder,
            leaveVerificationBuilder: widget.leaveVerificationBuilder,
            pinPromptBuilder: widget.pinPromptBuilder,
          ),
        ),
      );
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = exc.message;
        _isSubmitting = false;
      });
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Gagal masuk ke sistem: $exc';
        _isSubmitting = false;
      });
    }
  }

  Future<void> _showServerConfigDialog() async {
    final updated = await showDialog<String>(
      context: context,
      builder: (_) => _ServerConfigDialog(initialUrl: widget.apiClient.baseUrl),
    );

    if (updated != null && updated.isNotEmpty) {
      await widget.apiClient.setBaseUrl(updated);
      if (mounted) {
        setState(() {});
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Alamat server diatur ke ${widget.apiClient.baseUrl}'),
          ),
        );
      }
    }
  }

  void _fillDemoTeacher() {
    setState(() {
      _identifierController.text = 'sari.wulandari@sekolah.sch.id';
      _passwordController.text = 'guru123';
      _pinController.text = '1234';
      _errorMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        top: false,
        child: LayoutBuilder(
          builder: (context, constraints) {
            return SingleChildScrollView(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(
                      children: [
                        _buildBlueHeader(context),
                        Transform.translate(
                          offset: const Offset(0, -32),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 20),
                            child: _buildLoginCard(),
                          ),
                        ),
                      ],
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                      child: Column(
                        children: [
                          TextButton.icon(
                            onPressed: _isSubmitting ? null : _showServerConfigDialog,
                            icon: const Icon(Icons.dns_outlined, size: 18),
                            label: Text(
                              'Server: ${widget.apiClient.baseUrl}',
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 12),
                            ),
                          ),
                          const SizedBox(height: 4),
                          const Text(
                            'Politeknik Negeri Lampung • SmartSchool AI',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 12,
                              color: AppColors.textMuted,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildBlueHeader(BuildContext context) {
    final topInset = MediaQuery.of(context).padding.top;
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(24, topInset + 28, 24, 56),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppColors.primary, AppColors.primaryDark],
        ),
        borderRadius: BorderRadius.only(
          bottomLeft: Radius.circular(28),
          bottomRight: Radius.circular(28),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(999),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.face_retouching_natural, color: Colors.white, size: 16),
                SizedBox(width: 6),
                Text(
                  'Mode Kiosk & Verifikasi Guru',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          const Text(
            'SmartSchool AI',
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w800,
              color: Colors.white,
              letterSpacing: -0.4,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Masuk untuk mengelola sesi presensi wajah, izin siswa, dan notifikasi WhatsApp orang tua.',
            style: TextStyle(
              fontSize: 14,
              height: 1.45,
              color: Colors.white.withValues(alpha: 0.88),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLoginCard() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: AppColors.card,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: AppColors.border),
        boxShadow: [
          BoxShadow(
            color: AppColors.textPrimary.withValues(alpha: 0.08),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Form(
        key: _formKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Login Akun Guru',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              'Gunakan NIP atau email sekolah yang terdaftar.',
              style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
            ),
            const SizedBox(height: 18),
            if (_errorMessage != null) ...[
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.dangerTint,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: AppColors.danger.withValues(alpha: 0.35),
                  ),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.error_outline, color: AppColors.danger, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _errorMessage!,
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.danger,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
            ],
            TextFormField(
              controller: _identifierController,
              textInputAction: TextInputAction.next,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                labelText: 'NIP atau Email Guru',
                hintText: 'sari.wulandari@sekolah.sch.id',
                prefixIcon: Icon(Icons.badge_outlined),
              ),
              validator: (value) {
                if (value == null || value.trim().isEmpty) {
                  return 'NIP atau email guru wajib diisi.';
                }
                return null;
              },
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _passwordController,
              obscureText: _obscurePassword,
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(
                labelText: 'Kata Sandi',
                hintText: 'Masukkan kata sandi',
                prefixIcon: const Icon(Icons.lock_outline),
                suffixIcon: IconButton(
                  tooltip: _obscurePassword ? 'Tampilkan' : 'Sembunyikan',
                  onPressed: () {
                    setState(() => _obscurePassword = !_obscurePassword);
                  },
                  icon: Icon(
                    _obscurePassword
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
              validator: (value) {
                if (value == null || value.isEmpty) {
                  return 'Kata sandi wajib diisi.';
                }
                return null;
              },
            ),
            const SizedBox(height: 14),
            TextFormField(
              controller: _pinController,
              obscureText: _obscurePin,
              keyboardType: TextInputType.number,
              maxLength: 6,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              textInputAction: TextInputAction.done,
              onFieldSubmitted: (_) => _isSubmitting ? null : _submit(),
              decoration: InputDecoration(
                labelText: 'PIN Kiosk 4–6 Digit (Opsional)',
                hintText: 'Atur PIN saat login pertama',
                helperText: 'Kosongkan jika sudah pernah mengatur PIN Kiosk.',
                counterText: '',
                prefixIcon: const Icon(Icons.pin_outlined),
                suffixIcon: IconButton(
                  tooltip: _obscurePin ? 'Tampilkan PIN' : 'Sembunyikan PIN',
                  onPressed: () {
                    setState(() => _obscurePin = !_obscurePin);
                  },
                  icon: Icon(
                    _obscurePin
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
              validator: (value) {
                final trimmed = value?.trim() ?? '';
                if (trimmed.isEmpty) return null;
                if (!RegExp(r'^\d{4,6}$').hasMatch(trimmed)) {
                  return 'PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.';
                }
                return null;
              },
            ),
            const SizedBox(height: 20),
            ElevatedButton(
              onPressed: _isSubmitting ? null : _submit,
              child: _isSubmitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.2,
                        color: Colors.white,
                      ),
                    )
                  : const Text('Masuk ke Beranda Guru'),
            ),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _isSubmitting ? null : _fillDemoTeacher,
              icon: const Icon(Icons.auto_fix_high_outlined, size: 18),
              label: const Text('Isi Akun Demo Ibu Sari'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ServerConfigDialog extends StatefulWidget {
  const _ServerConfigDialog({required this.initialUrl});

  final String initialUrl;

  @override
  State<_ServerConfigDialog> createState() => _ServerConfigDialogState();
}

class _ServerConfigDialogState extends State<_ServerConfigDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _save() {
    Navigator.of(context).pop(_controller.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Alamat Server Backend'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Gunakan 10.0.2.2 untuk emulator Android atau alamat IP lokal laptop untuk perangkat fisik.',
            style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            keyboardType: TextInputType.url,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _save(),
            decoration: const InputDecoration(
              labelText: 'API Base URL',
              hintText: 'http://10.0.2.2:8000/api/v1',
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Batal'),
        ),
        ElevatedButton(
          onPressed: _save,
          child: const Text('Simpan'),
        ),
      ],
    );
  }
}
