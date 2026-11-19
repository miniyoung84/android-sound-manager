import subprocess

import pytest

from soundmanager.audio import EditSpec, build_filters, export, extract_audio, probe_duration
from soundmanager.tools import ToolNotFoundError, find_tool


def test_build_filters_places_fade_out_at_clip_end():
    spec = EditSpec(fade_in=1, fade_out=2, gain_db=-3, normalize=True)
    assert build_filters(spec, clip_duration=10) == [
        "volume=-3dB",
        "loudnorm=I=-14:TP=-1.5:LRA=11",
        "afade=t=in:st=0:d=1",
        "afade=t=out:st=8.000:d=2",
    ]


def test_build_filters_empty_for_noop_edit():
    assert build_filters(EditSpec(), clip_duration=5) == []


@pytest.fixture
def tone_video(tmp_path):
    try:
        ffmpeg = find_tool("ffmpeg")
    except ToolNotFoundError:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=5",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_extract_then_trim(tone_video, tmp_path):
    audio = extract_audio(tone_video, tmp_path / "tone.ogg")
    assert probe_duration(audio) == pytest.approx(5, abs=0.2)

    clip = export(audio, tmp_path / "clip.mp3", EditSpec(start=1, end=3, fade_out=0.5))
    assert probe_duration(clip) == pytest.approx(2, abs=0.2)
