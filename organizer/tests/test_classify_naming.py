from datetime import datetime
from pathlib import Path

from app import naming
from app.classify import classify
from app.fsops import clean_name, unique_path


def test_movie_and_episode(cfg):
    g = classify(cfg.inbox / "The.Kid.1921.1080p.BluRay.x264.mkv", cfg.inbox)
    assert (g.kind, g.title, g.year) == ("movie", "The Kid", 1921)

    g = classify(cfg.inbox / "Some.Show.S02E05.720p.WEB.mkv", cfg.inbox)
    assert (g.kind, g.title, g.season, g.episode) == ("episode", "Some Show", 2, 5)


def test_folder_hints_and_personal(cfg):
    assert classify(cfg.inbox / "Documentaries" / "Planet.Story.2019.mp4", cfg.inbox).kind == "documentary"
    assert classify(cfg.inbox / "Education" / "Lecture 01 - Intro.mp4", cfg.inbox).kind == "education"
    g = classify(cfg.inbox / "VID_20240131_154501.mp4", cfg.inbox)
    assert g.kind == "personal" and g.date == datetime(2024, 1, 31)
    assert classify(cfg.inbox / "PXL_20230705_101010.jpg", cfg.inbox).kind == "personal"


def test_audio_kinds(cfg):
    assert classify(cfg.inbox / "song.flac", cfg.inbox).kind == "music"
    assert classify(cfg.inbox / "Podcasts" / "ep1.mp3", cfg.inbox).kind == "podcast"
    assert classify(cfg.inbox / "book.m4b", cfg.inbox).kind == "audiobook"
    assert classify(cfg.inbox / "notes.pdf", cfg.inbox).kind == "unknown"


def test_naming():
    root = Path("/m")
    assert naming.movie_path(root / "Movies", "Metropolis", 1927, ".MKV") == root / "Movies/Metropolis (1927)/Metropolis (1927).mkv"
    assert naming.episode_path(root / "TV", "Show", 2010, 1, 3, "Pilot: Part 2", ".mp4") == \
        root / "TV/Show (2010)/Season 01/Show - S01E03 - Pilot  Part 2.mp4".replace("  ", " ")
    p = naming.music_path(root / "Music", {"artist": "AC/DC", "album": "Live", "year": 1992, "title": "T.N.T.", "track": 4}, ".mp3")
    assert p == root / "Music/AC DC/Live (1992)/04 - T.N.T.mp3"
    assert naming.subtitle_suffix(Path("Movie.2001.fr.forced.srt"), "Movie.2001") == ".fr.forced.srt"
    assert naming.subtitle_suffix(Path("Movie.2001.srt"), "Movie.2001") == ".srt"


def test_clean_name_and_unique(tmp_path):
    assert clean_name('a<b>:c"d|e?*') == "a b c d e"
    assert clean_name("CON") == "_CON"
    f = tmp_path / "x.mkv"
    f.write_text("1")
    assert unique_path(f).name == "x (2).mkv"
