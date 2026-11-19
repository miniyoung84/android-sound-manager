"""Library import and YouTube safety tests. No network access; ffmpeg generates test media."""

import subprocess
import threading

import pytest

from soundmanager import audio, library, youtube
from soundmanager.tools import ToolNotFoundError, find_tool


def make_media(path, *args):
    try:
        ffmpeg = find_tool("ffmpeg")
    except ToolNotFoundError:
        pytest.skip("ffmpeg not installed")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args, str(path)], check=True)
    return path


@pytest.fixture
def video(tmp_path):
    return make_media(
        tmp_path / "My Clip.mp4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3",
        "-c:a", "aac", "-shortest",
    )  # fmt: skip


def test_import_video_copies_aac_without_reencoding(video, tmp_path):
    lib = tmp_path / "lib"
    out = library.import_file(video, lib)
    assert out == lib / "My Clip.m4a"
    assert audio.audio_codec(out) == "aac"
    assert audio.probe_duration(out) == pytest.approx(3, abs=0.2)
    assert video.exists()  # original untouched


def test_import_never_overwrites(video, tmp_path):
    lib = tmp_path / "lib"
    first = library.import_file(video, lib)
    second = library.import_file(video, lib)
    assert first != second and second.name == "My Clip (2).m4a"


def test_import_wav_is_converted_and_mp3_is_copied(tmp_path):
    lib = tmp_path / "lib"
    wav = make_media(tmp_path / "a.wav", "-f", "lavfi", "-i", "sine=duration=1")
    mp3 = make_media(tmp_path / "b.mp3", "-f", "lavfi", "-i", "sine=duration=1")
    assert library.import_file(wav, lib).suffix == ".m4a"
    copied = library.import_file(mp3, lib)
    assert copied.read_bytes() == mp3.read_bytes()


def test_failed_import_leaves_nothing_in_library(tmp_path):
    lib = tmp_path / "lib"
    fake = tmp_path / "not really.mp4"
    fake.write_bytes(b"this is not a video")
    with pytest.raises(audio.AudioError):
        library.import_file(fake, lib)
    assert not lib.exists() or list(lib.iterdir()) == []


def test_video_without_audio_is_rejected(tmp_path):
    silent = make_media(tmp_path / "silent.mp4", "-f", "lavfi", "-i", "color=c=red:s=32x32:d=1")
    with pytest.raises(audio.AudioError, match="no audio"):
        library.import_file(silent, tmp_path / "lib")


def test_list_library_skips_hidden_and_non_audio(video, tmp_path):
    lib = tmp_path / "lib"
    library.import_file(video, lib)
    (lib / "notes.txt").write_text("x")
    (lib / ".hidden.mp3").write_bytes(b"x")
    items = library.list_library(lib)
    assert [i.name for i in items] == ["My Clip.m4a"]
    assert items[0].duration == pytest.approx(3, abs=0.2)
    assert library.list_library(tmp_path / "missing") == []


def test_format_duration():
    assert library.format_duration(None) == ""
    assert library.format_duration(29.6) == "0:30"
    assert library.format_duration(3725) == "1:02:05"


def test_ffmpeg_inputs_are_forced_to_local_files(tmp_path):
    assert audio._file_arg(tmp_path / "x.mp3").startswith("file:")


# --------------------------------------------------------------------------- YouTube


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "ftp://example.com/a.mp3",
        "https://",
        "https://example.com/a b",
        "https://example.com/\nhttps://evil.example",
        "https://example.com/" + "a" * 3000,
    ],
)
def test_validate_url_rejects(bad):
    with pytest.raises(youtube.YoutubeError):
        youtube.validate_url(bad)


def test_validate_url_accepts_and_trims():
    url = "  https://www.youtube.com/watch?v=abc123  "
    assert youtube.validate_url(url) == url.strip()


def test_download_options_enforce_limits(tmp_path):
    opts = youtube.build_options(tmp_path / "lib", tmp_path / "tmp")
    assert opts["noplaylist"] is True and opts["playlist_items"] == "1"
    assert opts["max_filesize"] == youtube.MAX_FILESIZE
    assert opts["paths"]["temp"] == str(tmp_path / "tmp")  # partial files stay out of library
    assert opts["windowsfilenames"] is True
    assert "no-certifi" in opts["compat_opts"]  # TLS stays verified, via the Windows store
    reject = opts["match_filter"]({"duration": youtube.MAX_DURATION_S + 1}, incomplete=False)
    assert reject  # a reason string means "skip this video"
    assert opts["match_filter"]({"duration": 30}, incomplete=False) is None


def test_cancel_stops_the_download_hook(tmp_path):
    import yt_dlp

    cancel = threading.Event()
    hook = youtube.build_options(tmp_path, tmp_path, cancel=cancel)["progress_hooks"][0]
    hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})  # fine
    cancel.set()
    with pytest.raises(yt_dlp.utils.DownloadCancelled):
        hook({"status": "downloading", "downloaded_bytes": 2, "total_bytes": 10})
