"""Tests for the sample analyzer module.

Uses synthetic numpy arrays instead of real audio files to keep
tests fast and deterministic with no filesystem dependencies.
"""

import numpy as np
import pytest
from pathlib import Path

from stresscon.sample_analyzer import (
    detect_bpm,
    detect_key,
    classify_sample,
    get_audio_stats,
    _classify_type,
    _classify_category,
)


@pytest.fixture
def sine_440hz() -> tuple[np.ndarray, int]:
    """A 2-second 440Hz sine wave at 22050 Hz sample rate (A4 note)."""
    sr = 22050
    t = np.linspace(0, 2.0, sr * 2, endpoint=False)
    y = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    return y, sr


@pytest.fixture
def silent_audio() -> tuple[np.ndarray, int]:
    """1 second of silence at 22050 Hz."""
    sr = 22050
    y = np.zeros(sr, dtype=np.float32)
    return y, sr


@pytest.fixture
def click_train() -> tuple[np.ndarray, int]:
    """Regular click train at ~120 BPM (2 Hz) for 4 seconds."""
    sr = 22050
    duration = 4.0
    y = np.zeros(int(sr * duration), dtype=np.float32)
    # Place impulses every 0.5 seconds (120 BPM = 2 beats/sec)
    for i in range(int(duration * 2)):
        idx = int(i * 0.5 * sr)
        if idx + 100 < len(y):
            y[idx:idx + 100] = 0.9
    return y, sr


@pytest.fixture
def short_impulse() -> tuple[np.ndarray, int]:
    """A very short 0.1s impulse — typical drum one-shot length."""
    sr = 22050
    length = int(sr * 0.1)
    y = np.zeros(length, dtype=np.float32)
    y[0:50] = 0.8
    return y, sr


def test_detect_bpm_click_train(click_train: tuple[np.ndarray, int]) -> None:
    y, sr = click_train
    bpm = detect_bpm(y, sr)
    assert bpm is not None
    assert 80.0 < bpm < 160.0  # Should be near 120


def test_detect_bpm_silent(silent_audio: tuple[np.ndarray, int]) -> None:
    y, sr = silent_audio
    bpm = detect_bpm(y, sr)
    # Silent audio may return None or an unreliable value
    assert bpm is None or isinstance(bpm, float)


def test_detect_bpm_too_short(short_impulse: tuple[np.ndarray, int]) -> None:
    y, sr = short_impulse
    bpm = detect_bpm(y, sr)
    assert bpm is None  # < 0.5s, should bail out


def test_detect_key_a440(sine_440hz: tuple[np.ndarray, int]) -> None:
    y, sr = sine_440hz
    key = detect_key(y, sr)
    # A 440Hz pure tone should detect as having A as root
    assert key is not None
    assert "A" in key


def test_detect_key_silent(silent_audio: tuple[np.ndarray, int]) -> None:
    y, sr = silent_audio
    key = detect_key(y, sr)
    assert key is None  # No tonal content


def test_detect_key_too_short(short_impulse: tuple[np.ndarray, int]) -> None:
    y, sr = short_impulse
    key = detect_key(y, sr)
    assert key is None  # < 0.5s


def test_get_audio_stats_sine(sine_440hz: tuple[np.ndarray, int]) -> None:
    y, sr = sine_440hz
    stats = get_audio_stats(y, sr)
    assert "spectral_centroid" in stats
    assert "rms_energy" in stats
    assert stats["rms_energy"] > 0.0
    assert stats["spectral_centroid"] > 0.0


def test_get_audio_stats_silent(silent_audio: tuple[np.ndarray, int]) -> None:
    y, sr = silent_audio
    stats = get_audio_stats(y, sr)
    assert stats["rms_energy"] < 1e-10


def test_classify_type_path_loop(tmp_path, sine_440hz) -> None:
    """Path containing 'loop' should classify as loop."""
    y, sr = sine_440hz
    fake_path = tmp_path / "Loops" / "Synths" / "warm_loop.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_type(fake_path, 2.0, y, sr)
    assert result == "loop"


def test_classify_type_path_oneshot(tmp_path, sine_440hz) -> None:
    """Path containing 'oneshot' should classify as one-shot."""
    y, sr = sine_440hz
    fake_path = tmp_path / "OneShot" / "kick.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_type(fake_path, 2.0, y, sr)
    assert result == "one-shot"


def test_classify_type_short_duration(tmp_path, short_impulse) -> None:
    """Very short files (< 1s) should be one-shots regardless of path."""
    y, sr = short_impulse
    fake_path = tmp_path / "Misc" / "click.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_type(fake_path, 0.1, y, sr)
    assert result == "one-shot"


def test_classify_type_long_duration(tmp_path, sine_440hz) -> None:
    """Long files (> 4s) default to loop when path is ambiguous."""
    y, sr = sine_440hz
    fake_path = tmp_path / "Misc" / "ambient.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_type(fake_path, 8.0, y, sr)
    assert result == "loop"


def test_classify_category_path_drum(tmp_path, sine_440hz) -> None:
    """Path containing 'Drums' or 'Kicks' should classify as drum."""
    y, sr = sine_440hz
    fake_path = tmp_path / "Drums" / "Kicks" / "kick_01.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_category(fake_path, y, sr)
    assert result == "drum"


def test_classify_category_path_synth(tmp_path, sine_440hz) -> None:
    """Path containing 'Synths' or 'pad' should classify as synth."""
    y, sr = sine_440hz
    fake_path = tmp_path / "Synths" / "Pads" / "warm_pad.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_category(fake_path, y, sr)
    assert result == "synth"


def test_classify_category_path_vocal(tmp_path, sine_440hz) -> None:
    y, sr = sine_440hz
    fake_path = tmp_path / "Vocals" / "vocal_chop.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_category(fake_path, y, sr)
    assert result == "vocal"


def test_classify_category_path_fx(tmp_path, sine_440hz) -> None:
    y, sr = sine_440hz
    fake_path = tmp_path / "FX" / "riser_01.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_category(fake_path, y, sr)
    assert result == "fx"


def test_classify_category_path_bass(tmp_path, sine_440hz) -> None:
    y, sr = sine_440hz
    fake_path = tmp_path / "Bass" / "sub_808.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    result = _classify_category(fake_path, y, sr)
    assert result == "bass"


def test_classify_sample_combined(tmp_path, sine_440hz) -> None:
    """Full classify_sample returns a (type, category) tuple."""
    y, sr = sine_440hz
    fake_path = tmp_path / "Drums" / "Loops" / "break_120bpm.wav"
    fake_path.parent.mkdir(parents=True, exist_ok=True)
    fake_path.touch()
    sample_type, category = classify_sample(fake_path, 4.0, y, sr)
    assert sample_type == "loop"
    assert category == "drum"
