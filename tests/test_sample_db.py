"""Tests for the sample database module."""

import pytest
import pandas as pd

from stresscon.sample_db import SampleDB


@pytest.fixture
def sample_record() -> dict:
    """A minimal valid sample record for a drum one-shot."""
    return {
        "file_path": "/Users/test/Music/Samples/Drums/kick_01.wav",
        "filename": "kick_01.wav",
        "format": "WAV",
        "duration_seconds": 0.45,
        "bpm": None,
        "musical_key": None,
        "is_loop": 0,
        "sample_type": "one-shot",
        "category": "drum",
        "spectral_centroid": 1234.56,
        "rms_energy": 0.234,
        "file_size_bytes": 45678,
        "channels": 2,
        "sample_rate": 44100,
        "date_scanned": "2026-02-07T12:00:00",
        "file_modified_at": "2026-01-15T08:30:00",
    }


@pytest.fixture
def synth_record() -> dict:
    """A sample record for a synth loop."""
    return {
        "file_path": "/Users/test/Music/Samples/Synths/warm_pad_120bpm.wav",
        "filename": "warm_pad_120bpm.wav",
        "format": "WAV",
        "duration_seconds": 8.0,
        "bpm": 120.0,
        "musical_key": "C major",
        "is_loop": 1,
        "sample_type": "loop",
        "category": "synth",
        "spectral_centroid": 2500.0,
        "rms_energy": 0.15,
        "file_size_bytes": 704000,
        "channels": 2,
        "sample_rate": 44100,
        "date_scanned": "2026-02-07T12:00:00",
        "file_modified_at": "2026-01-20T10:00:00",
    }


def test_insert_and_get_all(tmp_path, sample_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        df = db.get_all()
        assert len(df) == 1
        assert df.iloc[0]["filename"] == "kick_01.wav"
        assert df.iloc[0]["category"] == "drum"


def test_dedup_by_file_path(tmp_path, sample_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(sample_record)
        df = db.get_all()
        assert len(df) == 1


def test_bulk_insert(tmp_path) -> None:
    records = [
        {
            "file_path": f"/test/sample_{i}.wav",
            "filename": f"sample_{i}.wav",
            "format": "WAV",
            "date_scanned": "2026-02-07T12:00:00",
        }
        for i in range(5)
    ]
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        inserted = db.bulk_insert(records)
        assert inserted == 5
        df = db.get_all()
        assert len(df) == 5


def test_bulk_insert_dedup(tmp_path, sample_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        inserted = db.bulk_insert([sample_record, sample_record])
        assert inserted == 0


def test_search_by_name(tmp_path, sample_record, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(synth_record)
        results = db.search_by_name("kick")
        assert len(results) == 1
        assert results.iloc[0]["filename"] == "kick_01.wav"
        results = db.search_by_name("snare")
        assert len(results) == 0


def test_filter_by_category(tmp_path, sample_record, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(synth_record)
        drums = db.filter_by_category("drum")
        assert len(drums) == 1
        synths = db.filter_by_category("synth")
        assert len(synths) == 1
        vocals = db.filter_by_category("vocal")
        assert len(vocals) == 0


def test_filter_by_bpm_range(tmp_path, sample_record, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(synth_record)
        # Only synth_record has bpm=120
        results = db.filter_by_bpm_range(110.0, 130.0)
        assert len(results) == 1
        assert results.iloc[0]["bpm"] == 120.0


def test_filter_by_key(tmp_path, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(synth_record)
        results = db.filter_by_key("C major")
        assert len(results) == 1
        results = db.filter_by_key("D minor")
        assert len(results) == 0


def test_get_stats(tmp_path, sample_record, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(synth_record)
        stats = db.get_stats()
        assert stats["total_count"] == 2
        assert stats["avg_bpm"] == 120.0  # only one sample has bpm
        assert stats["by_format"] == {"WAV": 2}
        assert stats["by_category"]["drum"] == 1
        assert stats["by_category"]["synth"] == 1


def test_get_stats_empty_db(tmp_path) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        stats = db.get_stats()
        assert stats["total_count"] == 0
        assert stats["avg_bpm"] == 0.0


def test_delete_missing(tmp_path, sample_record) -> None:
    # Create a real file so it won't be deleted
    real_file = tmp_path / "real_sample.wav"
    real_file.touch()
    real_record = sample_record.copy()
    real_record["file_path"] = str(real_file)
    real_record["filename"] = "real_sample.wav"

    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)  # fake path, will be "missing"
        db.insert_sample(real_record)  # real path, will be kept
        deleted = db.delete_missing()
        assert deleted == 1
        df = db.get_all()
        assert len(df) == 1
        assert df.iloc[0]["filename"] == "real_sample.wav"


def test_get_scanned_paths(tmp_path, sample_record, synth_record) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        db.insert_sample(sample_record)
        db.insert_sample(synth_record)
        paths = db.get_scanned_paths()
        assert len(paths) == 2
        assert sample_record["file_path"] in paths
        assert synth_record["file_path"] in paths


def test_context_manager_connect_and_close(tmp_path) -> None:
    db_path = tmp_path / "test_samples.db"
    with SampleDB(db_path) as db:
        assert db._conn is not None
        db.insert_sample({
            "file_path": "/test/a.wav",
            "filename": "a.wav",
            "format": "WAV",
            "date_scanned": "2026-02-07T12:00:00",
        })
    # After exiting context, connection should be closed
    assert db._conn is None


def test_conn_property_raises_when_not_connected(tmp_path) -> None:
    db = SampleDB(tmp_path / "test.db")
    with pytest.raises(RuntimeError, match="Not connected"):
        _ = db.conn
