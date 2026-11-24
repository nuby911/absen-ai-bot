import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../models/models.dart';

/// Dialog pengaturan PIN Kiosk inline agar guru tidak terjebak di Mode Kiosk
/// saat `hasKioskPin == false`.
class KioskPinSetupDialog extends StatefulWidget {
  const KioskPinSetupDialog({
    super.key,
    required this.apiClient,
    this.onUserUpdated,
  });

  final ApiClient apiClient;
  final ValueChanged<UserProfile>? onUserUpdated;

  /// Memastikan akun guru saat ini telah memiliki PIN Kiosk sebelum masuk Kiosk
  /// atau mencatat presensi manual. Jika belum, menampilkan dialog pengaturan PIN.
  static Future<bool> ensureKioskPin(
    BuildContext context,
    ApiClient apiClient, {
    ValueChanged<UserProfile>? onUserUpdated,
  }) async {
    var user = apiClient.currentUser;
    if (user == null) {
      try {
        user = await apiClient.getMe();
      } on ApiException catch (exc) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(exc.message),
              backgroundColor: AppColors.danger,
            ),
          );
        }
        return false;
      } catch (exc) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Gagal memeriksa status PIN Kiosk: $exc'),
              backgroundColor: AppColors.danger,
            ),
          );
        }
        return false;
      }
    }

    if (user.hasKioskPin) {
      return true;
    }

    if (!context.mounted) return false;
    final configured = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => KioskPinSetupDialog(
        apiClient: apiClient,
        onUserUpdated: onUserUpdated,
      ),
    );
    return configured == true;
  }

  /// Menampilkan dialog pengaturan PIN Kiosk secara langsung (mis. dari banner peringatan).
  static Future<bool> show(
    BuildContext context,
    ApiClient apiClient, {
    ValueChanged<UserProfile>? onUserUpdated,
  }) async {
    final configured = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => KioskPinSetupDialog(
        apiClient: apiClient,
        onUserUpdated: onUserUpdated,
      ),
    );
    return configured == true;
  }

  @override
  State<KioskPinSetupDialog> createState() => _KioskPinSetupDialogState();
}

class _KioskPinSetupDialogState extends State<KioskPinSetupDialog> {
  final _pinController = TextEditingController();
  final _confirmPinController = TextEditingController();
  bool _obscurePin = true;
  bool _obscureConfirm = true;
  bool _isSaving = false;
  String? _errorMessage;

  @override
  void dispose() {
    _pinController.dispose();
    _confirmPinController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final pin = _pinController.text.trim();
    final confirm = _confirmPinController.text.trim();

    if (!RegExp(r'^\d{4,6}$').hasMatch(pin)) {
      setState(() {
        _errorMessage = 'PIN Kiosk harus terdiri dari 4 hingga 6 digit angka.';
      });
      return;
    }
    if (pin != confirm) {
      setState(() {
        _errorMessage = 'Konfirmasi PIN Kiosk tidak sesuai dengan PIN baru.';
      });
      return;
    }

    setState(() {
      _isSaving = true;
      _errorMessage = null;
    });

    try {
      await widget.apiClient.updateKioskPin(pin);
      final updatedUser = widget.apiClient.currentUser;
      if (updatedUser != null) {
        widget.onUserUpdated?.call(updatedUser);
      }
      if (!mounted) return;
      Navigator.of(context).pop(true);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('PIN Kiosk berhasil diatur.'),
          backgroundColor: AppColors.success,
        ),
      );
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = exc.message;
        _isSaving = false;
      });
    } catch (exc) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Gagal menyimpan PIN Kiosk: $exc';
        _isSaving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Row(
        children: [
          Icon(Icons.lock_outline_rounded, color: AppColors.primary),
          SizedBox(width: 8),
          Expanded(child: Text('Atur PIN Kiosk Terlebih Dahulu')),
        ],
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Anda belum memiliki PIN Kiosk. Buat PIN 4–6 digit terlebih dahulu agar dapat membuka kunci Mode Kiosk dan menyetujui presensi manual.',
              style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
            ),
            const SizedBox(height: 14),
            if (_errorMessage != null) ...[
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.dangerTint,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  _errorMessage!,
                  style: const TextStyle(
                    color: AppColors.danger,
                    fontSize: 12.5,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
              const SizedBox(height: 12),
            ],
            TextField(
              key: const Key('setup_kiosk_pin_field'),
              controller: _pinController,
              obscureText: _obscurePin,
              maxLength: 6,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              textInputAction: TextInputAction.next,
              decoration: InputDecoration(
                labelText: 'PIN Kiosk Baru (4–6 Digit)',
                hintText: 'Contoh: 1234',
                counterText: '',
                prefixIcon: const Icon(Icons.pin_outlined),
                suffixIcon: IconButton(
                  tooltip: _obscurePin ? 'Tampilkan PIN' : 'Sembunyikan PIN',
                  onPressed: () => setState(() => _obscurePin = !_obscurePin),
                  icon: Icon(
                    _obscurePin
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('setup_kiosk_pin_confirm_field'),
              controller: _confirmPinController,
              obscureText: _obscureConfirm,
              maxLength: 6,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => _isSaving ? null : _submit(),
              decoration: InputDecoration(
                labelText: 'Konfirmasi PIN Kiosk',
                hintText: 'Ulangi PIN 4–6 digit',
                counterText: '',
                prefixIcon: const Icon(Icons.lock_reset_outlined),
                suffixIcon: IconButton(
                  tooltip: _obscureConfirm ? 'Tampilkan PIN' : 'Sembunyikan PIN',
                  onPressed: () =>
                      setState(() => _obscureConfirm = !_obscureConfirm),
                  icon: Icon(
                    _obscureConfirm
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _isSaving ? null : () => Navigator.of(context).pop(false),
          child: const Text('Batal'),
        ),
        ElevatedButton(
          key: const Key('setup_kiosk_pin_save_button'),
          onPressed: _isSaving ? null : _submit,
          child: _isSaving
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : const Text('Simpan PIN Kiosk'),
        ),
      ],
    );
  }
}
