"""Audio sample analysis module for the Sample Library Organizer.

Extracts metadata, BPM, musical key, and spectral features from
audio files using librosa. All functions are standalone (functional style)
to match the project's convention in downtime_analyzer.py.
"""

import logging
from datetime import datetime
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Pitch class labels for key detection (C through B)
_PITCH_CLASSES: list[str] = [
    "C", "C#", "D", "D#", "E", "F",
    "F#", "G", "G#", "A", "A#", "B",
]

# Krumhansl-Kessler key profiles for major and minor keys.
# These model how humans perceive tonal hierarchy — the tonic
# gets the highest weight, the dominant fifth the second highest.
_MAJOR_PROFILE: list[float] = [
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
    2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
]
_MINOR_PROFILE: list[float] = [
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
    2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
]

# Category classification keywords, checked against the full lowercased path
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "bass": ["bass", "sub", "808bass", "reese"],
    "drum": [
        "kick", "snare", "hat", "hihat", "hi-hat", "clap", "perc",
        "tom", "cymbal", "rim", "shaker", "drum", "808", "break",
    ],
    "vocal": ["vocal", "vox", "voice", "acapella", "choir", "sing"],
    "synth": [
        "synth", "pad", "lead", "pluck", "arp", "chord", "keys",
        "piano", "organ", "string", "brass", "bell", "stab",
    ],
    "fx": [
        "fx", "riser", "impact", "sweep", "noise", "transition",
        "whoosh", "siren", "sfx", "foley", "ambient", "texture",
    ],
}

# Keywords for loop vs one-shot classification from file paths
_LOOP_KEYWORDS: list[str] = ["loop", "loops", "break", "beats"]
_ONESHOT_KEYWORDS: list[str] = ["oneshot", "one-shot", "one shot", "hit", "hits", "single"]


def analyze_file(filepath: Path) -> dict:
    """Extract all metadata from an audio file.

    Returns a dict ready for SampleDB.insert_sample().
    Returns a dict with 'error' key on failure.
    """
    filepath = Path(filepath).resolve()
    if not filepath.exists():
        return {"error": f"File not found: {filepath}"}

    try:
        # sr=None preserves native sample rate for accurate analysis
        y, sr = librosa.load(str(filepath), sr=None, mono=True)
    except Exception as exc:
        logger.warning("Cannot load audio file %s: %s", filepath, exc)
        return {"error": str(exc)}

    duration = librosa.get_duration(y=y, sr=sr)
    bpm = detect_bpm(y, sr)
    musical_key = detect_key(y, sr)
    stats = get_audio_stats(y, sr)
    sample_type, category = classify_sample(filepath, duration, y, sr)

    try:
        info = sf.info(str(filepath))
        channels = info.channels
        native_sr = info.samplerate
    except Exception:
        channels = 1
        native_sr = sr

    return {
        "file_path": str(filepath),
        "filename": filepath.name,
        "format": filepath.suffix.lstrip(".").upper(),
        "duration_seconds": round(duration, 3),
        "bpm": round(bpm, 1) if bpm is not None else None,
        "musical_key": musical_key,
        "is_loop": 1 if sample_type == "loop" else 0,
        "sample_type": sample_type,
        "category": category,
        "spectral_centroid": round(stats["spectral_centroid"], 2),
        "rms_energy": round(stats["rms_energy"], 6),
        "file_size_bytes": filepath.stat().st_size,
        "channels": channels,
        "sample_rate": native_sr,
        "date_scanned": datetime.now().isoformat(),
        "file_modified_at": datetime.fromtimestamp(
            filepath.stat().st_mtime
        ).isoformat(),
    }


def detect_bpm(y: np.ndarray, sr: int) -> float | None:
    """Estimate BPM using librosa onset-based tempo detection.

    Returns None for files where tempo detection is unreliable
    (silent audio, very short files, non-rhythmic content).
    """
    if len(y) < sr * 0.5:
        # Too short for reliable tempo detection
        return None

    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm_value = float(np.atleast_1d(tempo)[0])
        if bpm_value < 20.0 or bpm_value > 300.0:
            return None
        return bpm_value
    except Exception as exc:
        logger.debug("BPM detection failed: %s", exc)
        return None


def detect_key(y: np.ndarray, sr: int) -> str | None:
    """Detect musical key using chroma CQT and Krumhansl-Kessler profiles.

    Computes the chromagram, averages energy per pitch class, then
    correlates with major/minor key profiles for all 12 root notes.
    Returns e.g. 'C major' or 'A minor', or None if confidence is low.
    """
    if len(y) < sr * 0.5:
        return None

    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)  # shape: (12,)

        # Avoid division by zero on silent audio
        if chroma_mean.sum() < 1e-10:
            return None

        major_prof = np.array(_MAJOR_PROFILE)
        minor_prof = np.array(_MINOR_PROFILE)

        best_corr = -2.0
        best_key = ""

        for shift in range(12):
            shifted = np.roll(chroma_mean, -shift)

            major_corr = float(np.corrcoef(shifted, major_prof)[0, 1])
            if major_corr > best_corr:
                best_corr = major_corr
                best_key = f"{_PITCH_CLASSES[shift]} major"

            minor_corr = float(np.corrcoef(shifted, minor_prof)[0, 1])
            if minor_corr > best_corr:
                best_corr = minor_corr
                best_key = f"{_PITCH_CLASSES[shift]} minor"

        if best_corr < 0.4:
            return None

        return best_key

    except Exception as exc:
        logger.debug("Key detection failed: %s", exc)
        return None


def classify_sample(
    filepath: Path,
    duration: float,
    y: np.ndarray,
    sr: int,
) -> tuple[str, str]:
    """Classify a sample as (sample_type, category).

    sample_type: 'loop' or 'one-shot'
    category: 'drum', 'synth', 'vocal', 'bass', 'fx', or 'other'

    Uses a two-phase approach:
    1. Path keyword matching (most reliable for organized sample libraries)
    2. Spectral heuristics as fallback
    """
    sample_type = _classify_type(filepath, duration, y, sr)
    category = _classify_category(filepath, y, sr)
    return sample_type, category


def _classify_type(filepath: Path, duration: float, y: np.ndarray, sr: int) -> str:
    """Determine if a sample is a loop or one-shot."""
    path_lower = str(filepath).lower()

    # Phase 1: path keywords
    for kw in _LOOP_KEYWORDS:
        if kw in path_lower:
            return "loop"
    for kw in _ONESHOT_KEYWORDS:
        if kw in path_lower:
            return "one-shot"

    # Phase 2: duration heuristic
    if duration < 1.0:
        return "one-shot"
    if duration > 4.0:
        return "loop"

    # Phase 3: onset regularity for ambiguous durations (1-4s)
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        if len(onsets) >= 4:
            intervals = np.diff(onsets)
            if len(intervals) >= 3:
                cv = float(np.std(intervals) / (np.mean(intervals) + 1e-10))
                if cv < 0.25:
                    return "loop"
    except Exception:
        pass

    return "one-shot" if duration < 2.0 else "loop"


def _classify_category(filepath: Path, y: np.ndarray, sr: int) -> str:
    """Determine the sample category (drum, synth, vocal, bass, fx, other)."""
    path_lower = str(filepath).lower()

    # Phase 1: path keyword matching (highest priority)
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in path_lower:
                return category

    # Phase 2: spectral heuristics (fallback)
    try:
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
        flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))
        duration = librosa.get_duration(y=y, sr=sr)

        if centroid < 500 and duration > 0.3:
            return "bass"
        if 300 < centroid < 3400 and flatness > 0.1:
            return "vocal"
        if duration < 1.5 and centroid > 6000:
            return "drum"
        if duration < 1.0 and centroid < 2000:
            return "drum"
        if flatness > 0.3 or centroid > 8000:
            return "fx"
        if 500 < centroid < 5000 and duration > 1.0:
            return "synth"
    except Exception:
        pass

    return "other"


def get_audio_stats(y: np.ndarray, sr: int) -> dict[str, float]:
    """Compute spectral centroid (mean) and RMS energy (mean)."""
    try:
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    except Exception:
        centroid = 0.0

    try:
        rms = float(np.mean(librosa.feature.rms(y=y)))
    except Exception:
        rms = 0.0

    return {
        "spectral_centroid": centroid,
        "rms_energy": rms,
    }
