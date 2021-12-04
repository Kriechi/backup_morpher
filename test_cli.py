import os
import mock
import argparse
import pytest


from morpher import get_source_environ, get_destination_environ, parse_args, select_backup_range


def test_argparse():
    with pytest.raises(SystemExit):
        _ = parse_args(["morpher", "invalid"])

    with pytest.raises(SystemExit):
        _ = parse_args(["morpher", "restic2restic", "--foobar"])

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic"])
    assert morpher_args.mode == "restic2restic"
    assert src_args == []
    assert dest_args == []

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic", "--", "--foo"])
    assert src_args == []
    assert dest_args == ["--foo"]

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic", "--", "--foo", "--"])
    assert src_args == ["--foo"]
    assert dest_args == []

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic", "--", "--"])
    assert src_args == []
    assert dest_args == []

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic", "--", "--", "--bar"])
    assert src_args == []
    assert dest_args == ["--bar"]

    morpher_args, src_args, dest_args = parse_args(["morpher", "restic2restic", "--", "--foo", "--", "--bar"])
    assert src_args == ["--foo"]
    assert dest_args == ["--bar"]


def test_backup_range():
    with mock.patch("builtins.input", lambda _: '2-4'):
        n = argparse.Namespace(backup_range="")
        t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
        assert t == [2, 3, 4]

    n = argparse.Namespace(backup_range="1")
    t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
    assert t == [1]

    n = argparse.Namespace(backup_range="-3")
    t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
    assert t == [1, 2, 3]

    n = argparse.Namespace(backup_range="3-")
    t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
    assert t == [3, 4, 5]

    n = argparse.Namespace(backup_range="2-4")
    t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})
    assert t == [2, 3, 4]

    n = argparse.Namespace(backup_range="9")
    with pytest.raises(SystemExit):
        t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})

    n = argparse.Namespace(backup_range="9-")
    with pytest.raises(SystemExit):
        t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})

    n = argparse.Namespace(backup_range="-9")
    with pytest.raises(SystemExit):
        t = select_backup_range(n, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5})


def test_environs():
    with mock.patch.dict(os.environ, {"MORPHER_SRC_FOO": "BAR", "MORPHER_DEST_BAR": "FOO"}):
        e = get_source_environ()
        assert e["FOO"] == "BAR"
        assert "BAR" not in e

    with mock.patch.dict(os.environ, {"MORPHER_SRC_FOO": "BAR", "MORPHER_DEST_BAR": "FOO"}):
        e = get_destination_environ()
        assert "FOO" not in e
        assert e["BAR"] == "FOO"
