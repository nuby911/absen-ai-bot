import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/theme.dart';

/// Aksi yang dipilih guru setelah PIN Kiosk berhasil diverifikasi.
enum KioskPinAction {
  primary,
  secondary,
}

/// Hasil terstruktur dari [KioskPinSheet.showWithAction].
class KioskPinSheetResult {
  const KioskPinSheetResult({
    required this.pin,
    required this.action,
  });

  final String pin;
  final KioskPinAction action;
}

/// Layar 06 Figma: Bottom sheet verifikasi PIN Kiosk Guru (4–6 digit).
class KioskPinSheet extends StatefulWidget {
  const KioskPinSheet({
    super.key,
    required this.onVerify,
    this.title = 'Masukkan PIN Kiosk Guru',
    this.subtitle = 'Masukkan 4–6 digit PIN untuk membuka kunci Mode Kiosk.',
    this.confirmLabel = 'Buka Kunci & Keluar Kiosk',
    this.secondaryActionLabel,
    this.cancelLabel = 'Batal — Kembali ke Pemindaian Wajah',
    this.minLength = 4,
    this.maxLength = 6,
    this.onVerifiedSuccess,
    this.onSecondaryVerifiedSuccess,
  });

  final Future<bool> Function(String pin) onVerify;
  final String title;
  final String subtitle;
  final String confirmLabel;
  final String? secondaryActionLabel;
  final String cancelLabel;
  final int minLength;
  final int maxLength;
  final ValueChanged<String>? onVerifiedSuccess;
  final ValueChanged<String>? onSecondaryVerifiedSuccess;

  /// Menampilkan [KioskPinSheet] sebagai modal bottom sheet dan mengembalikan PIN valid jika berhasil.
  static Future<String?> show(
    BuildContext context, {
    required Future<bool> Function(String pin) onVerify,
    String title = 'Masukkan PIN Kiosk Guru',
    String subtitle = 'Masukkan 4–6 digit PIN untuk membuka kunci Mode Kiosk.',
    String confirmLabel = 'Buka Kunci & Keluar Kiosk',
    String cancelLabel = 'Batal — Kembali ke Pemindaian Wajah',
  }) {
    return showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => KioskPinSheet(
        onVerify: onVerify,
        title: title,
        subtitle: subtitle,
        confirmLabel: confirmLabel,
        cancelLabel: cancelLabel,
        onVerifiedSuccess: (pin) => Navigator.of(sheetContext).pop(pin),
      ),
    );
  }

  /// Menampilkan [KioskPinSheet] dengan opsi aksi sekunder (mis. Absen Manual langsung dari Kiosk).
  static Future<KioskPinSheetResult?> showWithAction(
    BuildContext context, {
    required Future<bool> Function(String pin) onVerify,
    String title = 'Masukkan PIN Kiosk Guru',
    String subtitle = 'Masukkan 4–6 digit PIN untuk membuka kunci Mode Kiosk.',
    String confirmLabel = 'Buka Kunci & Keluar Kiosk',
    String? secondaryActionLabel,
    String cancelLabel = 'Batal — Kembali ke Pemindaian Wajah',
  }) {
    return showModalBottomSheet<KioskPinSheetResult>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => KioskPinSheet(
        onVerify: onVerify,
        title: title,
        subtitle: subtitle,
        confirmLabel: confirmLabel,
        secondaryActionLabel: secondaryActionLabel,
        cancelLabel: cancelLabel,
        onVerifiedSuccess: (pin) => Navigator.of(sheetContext).pop(
          KioskPinSheetResult(pin: pin, action: KioskPinAction.primary),
        ),
        onSecondaryVerifiedSuccess: secondaryActionLabel == null
            ? null
            : (pin) => Navigator.of(sheetContext).pop(
                  KioskPinSheetResult(pin: pin, action: KioskPinAction.secondary),
                ),
      ),
    );
  }

  @override
  State<KioskPinSheet> createState() => _KioskPinSheetState();
}

class _KioskPinSheetState extends State<KioskPinSheet> {
  String _pin = '';
  bool _isVerifying = false;
  KioskPinAction? _verifyingAction;
  String? _errorMessage;

  void _appendDigit(String digit) {
    if (_isVerifying || _pin.length >= widget.maxLength) return;
    HapticFeedback.selectionClick();
    setState(() {
      _pin += digit;
      _errorMessage = null;
    });
  }

  void _backspace() {
    if (_isVerifying || _pin.isEmpty) return;
    HapticFeedback.selectionClick();
    setState(() {
      _pin = _pin.substring(0, _pin.length - 1);
      _errorMessage = null;
    });
  }

  void _clearAll() {
    if (_isVerifying) return;
    HapticFeedback.selectionClick();
    setState(() {
      _pin = '';
      _errorMessage = null;
    });
  }

  Future<void> _submit(KioskPinAction action) async {
    if (_isVerifying || _pin.length < widget.minLength) return;
    final candidatePin = _pin;

    setState(() {
      _isVerifying = true;
      _verifyingAction = action;
      _errorMessage = null;
    });

    try {
      final isValid = await widget.onVerify(candidatePin);
      if (!mounted) return;
      if (isValid) {
        if (action == KioskPinAction.secondary &&
            widget.onSecondaryVerifiedSuccess != null) {
          widget.onSecondaryVerifiedSuccess!(candidatePin);
        } else if (widget.onVerifiedSuccess != null) {
          widget.onVerifiedSuccess!(candidatePin);
        } else if (Navigator.of(context).canPop()) {
          Navigator.of(context).pop(candidatePin);
        } else {
          setState(() {
            _isVerifying = false;
            _verifyingAction = null;
          });
        }
        return;
      }

      setState(() {
        _isVerifying = false;
        _verifyingAction = null;
        _pin = '';
        _errorMessage = 'PIN Kiosk salah. Silakan periksa kembali PIN Anda.';
      });
    } on ApiException catch (exc) {
      if (!mounted) return;
      setState(() {
        _isVerifying = false;
        _verifyingAction = null;
        _pin = '';
        _errorMessage = exc.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _isVerifying = false;
        _verifyingAction = null;
        _pin = '';
        _errorMessage = 'Gagal memverifikasi PIN Kiosk. Coba lagi.';
      });
    }
  }

  void _cancel() {
    if (_isVerifying) return;
    if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = _pin.length >= widget.minLength && !_isVerifying;

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      child: SafeArea(
        top: false,
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 42,
                  height: 4,
                  decoration: BoxDecoration(
                    color: const Color(0xFFCBD5E1),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AppColors.primaryTint,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: const Icon(
                      Icons.lock_outline_rounded,
                      color: AppColors.primary,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          widget.title,
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                            color: AppColors.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          widget.subtitle,
                          style: const TextStyle(
                            fontSize: 12.5,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _buildPinDots(),
              if (_errorMessage != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  decoration: BoxDecoration(
                    color: AppColors.dangerTint,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: AppColors.danger.withValues(alpha: 0.35),
                    ),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.error_outline_rounded,
                        color: AppColors.danger,
                        size: 18,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _errorMessage!,
                          style: const TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                            color: AppColors.danger,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 14),
              _buildNumericKeypad(),
              const SizedBox(height: 14),
              ElevatedButton(
                onPressed: canSubmit ? () => _submit(KioskPinAction.primary) : null,
                child: _isVerifying && _verifyingAction == KioskPinAction.primary
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.2,
                          color: Colors.white,
                        ),
                      )
                    : Text(widget.confirmLabel),
              ),
              if (widget.secondaryActionLabel != null) ...[
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  key: const Key('kiosk_pin_secondary_action_button'),
                  onPressed:
                      canSubmit ? () => _submit(KioskPinAction.secondary) : null,
                  icon: _isVerifying && _verifyingAction == KioskPinAction.secondary
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.edit_note_rounded, size: 20),
                  label: Text(widget.secondaryActionLabel!),
                ),
              ],
              const SizedBox(height: 8),
              TextButton(
                onPressed: _isVerifying ? null : _cancel,
                child: Text(
                  widget.cancelLabel,
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPinDots() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(widget.maxLength, (index) {
        final isFilled = index < _pin.length;
        final isMandatorySlot = index < widget.minLength;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          margin: const EdgeInsets.symmetric(horizontal: 7),
          width: 18,
          height: 18,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isFilled ? AppColors.primary : Colors.transparent,
            border: Border.all(
              color: isFilled
                  ? AppColors.primary
                  : (isMandatorySlot
                      ? const Color(0xFF94A3B8)
                      : const Color(0xFFCBD5E1)),
              width: isFilled ? 2 : 1.6,
            ),
          ),
        );
      }),
    );
  }

  Widget _buildNumericKeypad() {
    const rows = [
      ['1', '2', '3'],
      ['4', '5', '6'],
      ['7', '8', '9'],
      ['C', '0', '⌫'],
    ];

    return Column(
      children: rows.map((row) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: row.map((label) {
              final isClear = label == 'C';
              final isBackspace = label == '⌫';
              return Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 5),
                  child: _KeypadButton(
                    label: label,
                    isDestructive: isClear,
                    isAction: isBackspace,
                    onTap: () {
                      if (isClear) {
                        _clearAll();
                      } else if (isBackspace) {
                        _backspace();
                      } else {
                        _appendDigit(label);
                      }
                    },
                  ),
                ),
              );
            }).toList(),
          ),
        );
      }).toList(),
    );
  }
}

class _KeypadButton extends StatelessWidget {
  const _KeypadButton({
    required this.label,
    required this.onTap,
    this.isDestructive = false,
    this.isAction = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool isDestructive;
  final bool isAction;

  @override
  Widget build(BuildContext context) {
    final bgColor = isDestructive
        ? AppColors.dangerTint
        : (isAction ? const Color(0xFFF1F5F9) : AppColors.background);
    final fgColor = isDestructive
        ? AppColors.danger
        : (isAction ? AppColors.textSecondary : AppColors.textPrimary);

    return Material(
      color: bgColor,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          height: 48,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(
              color: isDestructive
                  ? AppColors.danger.withValues(alpha: 0.25)
                  : AppColors.border,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 19,
              fontWeight: FontWeight.w700,
              color: fgColor,
            ),
          ),
        ),
      ),
    );
  }
}
