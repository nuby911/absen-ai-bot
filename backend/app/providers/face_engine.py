from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import importlib.util
from io import BytesIO
from typing import Any, Protocol, runtime_checkable

from fastapi import Request
import numpy as np
from PIL import Image, UnidentifiedImageError

from app.config import Settings, get_settings

EMBEDDING_DIM = 512


@dataclass(frozen=True, slots=True)
class FaceExtractionResult:
    """Extracted face embedding and validation metadata for a single image."""

    embedding: list[float]
    quality_score: float
    face_count: int


class FaceValidationError(ValueError):
    """Raised when an uploaded face image fails quality or face-count validation."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@runtime_checkable
class FaceEngine(Protocol):
    """Protocol for extracting a normalized 512-d face embedding from image bytes."""

    def extract_single_face(self, image_bytes: bytes) -> FaceExtractionResult:
        """Validate a single face image and return its normalized 512-d embedding."""
        ...


def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute safe cosine similarity in [-1.0, 1.0], returning 0.0 for zero-norm vectors."""
    arr_a = np.asarray(vec_a, dtype=np.float64)
    arr_b = np.asarray(vec_b, dtype=np.float64)
    if arr_a.size == 0 or arr_b.size == 0:
        return 0.0
    if arr_a.shape != arr_b.shape:
        raise ValueError("Dimensi vektor embedding tidak cocok.")

    norm_a = float(np.linalg.norm(arr_a))
    norm_b = float(np.linalg.norm(arr_b))
    if not np.isfinite(norm_a) or not np.isfinite(norm_b) or norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    similarity = float(np.dot(arr_a, arr_b) / (norm_a * norm_b))
    if not np.isfinite(similarity):
        return 0.0
    return max(-1.0, min(1.0, similarity))


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    """Return L2-normalized float64 vector, or zero vector when norm is zero."""
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1e-12:
        return np.zeros_like(vector, dtype=np.float64)
    return (vector / norm).astype(np.float64)


def _decode_rgb_image(image_bytes: bytes, min_resolution: int = 64) -> Image.Image:
    """Verify image integrity, decode to RGB, and enforce minimum pixel dimensions."""
    if not image_bytes:
        raise FaceValidationError("File gambar wajah kosong.")

    try:
        with Image.open(BytesIO(image_bytes)) as probe:
            probe.verify()
        with Image.open(BytesIO(image_bytes)) as loaded:
            loaded.load()
            rgb = loaded.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise FaceValidationError(
            "File yang diunggah bukan gambar yang valid atau file rusak."
        ) from exc

    width, height = rgb.size
    if width < min_resolution or height < min_resolution:
        raise FaceValidationError(
            f"Resolusi gambar wajah terlalu kecil (minimal {min_resolution}x{min_resolution} piksel)."
        )
    return rgb


class DeterministicFaceEngine:
    """Deterministic Pillow/NumPy face engine for offline tests and non-ML fallback."""

    def __init__(
        self,
        min_resolution: int = 64,
        min_std_dev: float = 5.0,
        min_quality_score: float = 0.5,
    ) -> None:
        self.min_resolution = min_resolution
        self.min_std_dev = min_std_dev
        self.min_quality_score = min_quality_score

    def extract_single_face(self, image_bytes: bytes) -> FaceExtractionResult:
        """Validate image contrast/size and derive a deterministic 512-d unit vector."""
        rgb = _decode_rgb_image(image_bytes, min_resolution=self.min_resolution)

        gray = np.asarray(rgb.convert("L"), dtype=np.float32)
        std_dev = float(np.std(gray))
        if std_dev < self.min_std_dev:
            raise FaceValidationError(
                "Kualitas foto wajah terlalu rendah atau gambar terlalu polos/buram. "
                "Pastikan pencahayaan cukup dan wajah terlihat jelas."
            )

        quality_score = round(min(1.0, 0.5 + (std_dev - self.min_std_dev) / 100.0), 4)
        if quality_score < self.min_quality_score:
            raise FaceValidationError(
                "Kualitas foto wajah tidak memenuhi standar minimum. Silakan unggah foto yang lebih jelas."
            )

        embedding = self._compute_embedding(rgb, image_bytes)
        return FaceExtractionResult(
            embedding=embedding,
            quality_score=quality_score,
            face_count=1,
        )

    def _compute_embedding(self, rgb: Image.Image, image_bytes: bytes) -> list[float]:
        # Combine coarse bilinear luminance, detail nearest-neighbor luminance, and
        # chrominance so identical/re-encoded images align (~1.0) while distinct images diverge.
        gray_img = rgb.convert("L")
        coarse_gray = np.asarray(
            gray_img.resize((16, 12), Image.Resampling.BILINEAR),
            dtype=np.float64,
        ).ravel()
        coarse_centered = _l2_normalize(coarse_gray - float(coarse_gray.mean()))

        detail_gray = np.asarray(
            gray_img.resize((16, 12), Image.Resampling.NEAREST),
            dtype=np.float64,
        ).ravel()
        detail_centered = _l2_normalize(detail_gray - float(detail_gray.mean()))

        ycbcr = np.asarray(
            rgb.convert("YCbCr").resize((8, 8), Image.Resampling.BILINEAR),
            dtype=np.float64,
        )
        cb_centered = _l2_normalize(ycbcr[:, :, 1].ravel() - 128.0) * 0.5
        cr_centered = _l2_normalize(ycbcr[:, :, 2].ravel() - 128.0) * 0.5

        combined = np.concatenate([coarse_centered, detail_centered, cb_centered, cr_centered])
        normalized = _l2_normalize(combined)
        if float(np.linalg.norm(normalized)) <= 1e-8:
            # Fallback for degenerate periodic textures whose downsampling cancels to zero.
            digest = hashlib.sha256(image_bytes).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
            normalized = _l2_normalize(rng.standard_normal(EMBEDDING_DIM))

        return normalized.tolist()


class InsightFaceEngine:
    """Production face engine backed by lazily loaded InsightFace ONNX FaceAnalysis."""

    def __init__(
        self,
        model_name: str = "buffalo_l",
        providers: Sequence[str] | None = None,
        min_det_score: float = 0.5,
    ) -> None:
        self.model_name = model_name
        self.providers = list(providers) if providers is not None else ["CPUExecutionProvider"]
        self.min_det_score = min_det_score
        self._face_app: Any = None

    def _get_app(self) -> Any:
        if self._face_app is None:
            from insightface.app import FaceAnalysis  # type: ignore[import-not-found]

            face_app = FaceAnalysis(name=self.model_name, providers=self.providers)
            face_app.prepare(ctx_id=0, det_size=(640, 640))
            self._face_app = face_app
        return self._face_app

    def extract_single_face(self, image_bytes: bytes) -> FaceExtractionResult:
        """Detect exactly one clear face via InsightFace and return its 512-d embedding."""
        rgb = _decode_rgb_image(image_bytes, min_resolution=64)
        bgr = np.asarray(rgb, dtype=np.uint8)[:, :, ::-1].copy()

        faces = self._get_app().get(bgr)
        face_count = len(faces)
        if face_count == 0:
            raise FaceValidationError(
                "Wajah tidak terdeteksi pada foto. Pastikan wajah menghadap kamera dengan pencahayaan cukup."
            )
        if face_count > 1:
            raise FaceValidationError(
                "Terdeteksi lebih dari satu wajah pada foto. Gunakan foto yang hanya menampilkan satu siswa."
            )

        face = faces[0]
        det_score = float(getattr(face, "det_score", 0.0))
        if det_score < self.min_det_score:
            raise FaceValidationError(
                "Kualitas deteksi wajah terlalu rendah. Gunakan foto wajah yang lebih jelas dan tidak buram."
            )

        raw_embedding = getattr(face, "normed_embedding", None)
        if raw_embedding is None:
            raw_embedding = getattr(face, "embedding", None)
        if raw_embedding is None:
            raise FaceValidationError("Gagal mengekstrak fitur vektor wajah dari foto.")

        normalized = _l2_normalize(np.asarray(raw_embedding, dtype=np.float64))
        if normalized.shape != (EMBEDDING_DIM,) or float(np.linalg.norm(normalized)) == 0.0:
            raise FaceValidationError("Vektor wajah yang dihasilkan tidak valid.")

        return FaceExtractionResult(
            embedding=normalized.tolist(),
            quality_score=round(max(0.0, min(1.0, det_score)), 4),
            face_count=1,
        )


def _insightface_available() -> bool:
    return (
        importlib.util.find_spec("insightface") is not None
        and importlib.util.find_spec("onnxruntime") is not None
    )


def create_face_engine(settings: Settings) -> FaceEngine:
    """Instantiate the configured FaceEngine implementation based on settings."""
    mode = settings.face_engine_mode.strip().lower()
    if mode == "deterministic":
        return DeterministicFaceEngine()
    if mode == "insightface":
        return InsightFaceEngine()
    if mode == "auto":
        return InsightFaceEngine() if _insightface_available() else DeterministicFaceEngine()
    raise ValueError(f"Mode face_engine_mode tidak dikenali: {settings.face_engine_mode}")


def get_face_engine(request: Request) -> FaceEngine:
    """FastAPI dependency returning the app-level FaceEngine instance."""
    engine = getattr(request.app.state, "face_engine", None)
    if engine is None:
        engine = create_face_engine(get_settings())
        request.app.state.face_engine = engine
    return engine
