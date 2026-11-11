import json

from app.engine import Organizer
from app.undo import undo_run


def files_under(root):
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file())


def test_dry_run_moves_nothing(cfg, make_file):
    make_file("The.Kid.1921.mkv")
    before = files_under(cfg.media_root)
    report = Organizer(cfg).run(dry_run=True)
    assert files_under(cfg.media_root) == before
    assert report["items"][0]["dst"] == "Movies/The Kid (1921)/The Kid (1921).mkv"


def test_live_run_organizes_everything(cfg, make_file):
    make_file("The.Kid.1921.mkv", b"movie")
    make_file("The.Kid.1921.en.srt", b"sub")
    make_file("Some.Show.S01E02.mkv", b"episode")
    make_file("VID_20240131_154501.mp4", b"personal")
    make_file("Music/Daft Punk - One More Time.mp3", b"song")
    make_file("weird.xyz", b"???")
    make_file("still_copying.mkv", b"new", age=0)

    report = Organizer(cfg).run(dry_run=False)
    files = files_under(cfg.media_root)
    assert "Movies/The Kid (1921)/The Kid (1921).mkv" in files
    assert "Movies/The Kid (1921)/The Kid (1921).en.srt" in files
    assert "TV/Some Show/Season 01/Some Show - S01E02.mkv" in files
    assert "Personal/2024/2024-01/VID_20240131_154501.mp4" in files
    assert "Music/Daft Punk/Singles/One More Time.mp3" in files
    assert "_Review/weird.xyz" in files
    assert "_Inbox/still_copying.mkv" in files            # untouched: modified too recently
    assert report["counts"]["waiting"] == 1
    notes = json.loads((cfg.state_dir / "queue_notes.json").read_text())
    assert "unsupported" in notes["_Review/weird.xyz"]


def test_duplicates_are_moved_never_deleted(cfg, make_file):
    make_file("Metropolis.1927.mkv", b"same-bytes" * 500)
    Organizer(cfg).run(dry_run=False)
    make_file("copy of film.mkv", b"same-bytes" * 500)          # identical content, different name
    make_file("Metropolis.1927.1080p.mkv", b"other-version")     # same title, other file
    report = Organizer(cfg).run(dry_run=False)
    files = files_under(cfg.media_root)
    assert "_Duplicates/copy of film.mkv" in files
    assert "_Duplicates/Metropolis.1927.1080p.mkv" in files
    assert "Movies/Metropolis (1927)/Metropolis (1927).mkv" in files
    assert report["counts"]["duplicate"] == 2


def test_duplicates_within_one_batch_in_dry_run(cfg, make_file):
    make_file("a/Nosferatu.1922.mkv", b"z" * 4096)
    make_file("b/Nosferatu.1922.mkv", b"z" * 4096)
    report = Organizer(cfg).run(dry_run=True)
    assert sorted(i["action"] for i in report["items"]) == ["duplicate", "organized"]


def test_well_named_copy_wins_and_junk_names_need_review(cfg, make_file):
    make_file("copy.mp4", b"same" * 600)
    make_file("Night.of.the.Living.Dead.1968.mp4", b"same" * 600)
    make_file("holiday clip.mp4", b"other")
    Organizer(cfg).run(dry_run=False)
    files = files_under(cfg.media_root)
    assert "Movies/Night of the Living Dead (1968)/Night of the Living Dead (1968).mp4" in files
    assert "_Duplicates/copy.mp4" in files
    assert "_Review/holiday clip.mp4" in files


def test_name_conflicts_get_suffix(cfg, make_file):
    (cfg.review / "weird.xyz").write_bytes(b"old")
    make_file("weird.xyz", b"new one")
    Organizer(cfg).run(dry_run=False)
    assert (cfg.review / "weird.xyz").read_bytes() == b"old"
    assert (cfg.review / "weird (2).xyz").read_bytes() == b"new one"


def test_undo_restores_files(cfg, make_file):
    make_file("The.Kid.1921.mkv", b"movie")
    Organizer(cfg).run(dry_run=False)
    journal = cfg.state_dir / "moves.jsonl"
    preview = undo_run(journal)
    assert preview and preview[0].startswith("WOULD MOVE")
    undo_run(journal, apply=True)
    assert (cfg.inbox / "The.Kid.1921.mkv").read_bytes() == b"movie"
