#!/usr/bin/env python3

import argparse
import datetime
import glob
import json
import os
import re
import signal
import time
import subprocess
import sys
import tempfile
import textwrap
from typing import Dict, List


class Backup:
    def prepare(self, target: str, src_args: List[str]):
        raise NotImplemented

    def morph(self, morpher_args: List[str], target_dir: str, dest_args: List[str]):
        if morpher_args.destination == "borg":
            morph_backup_into_borg(morpher_args, self, target_dir, dest_args)
        elif morpher_args.destination == "restic":
            morph_backup_into_restic(morpher_args, self, target_dir, dest_args)

    def cleanup(self):
        raise NotImplemented


class BorgArchive(Backup):
    archive: str
    barchive: str
    id: str
    name: str
    start: str
    time: str

    active_archive_mount: str

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.time = datetime.datetime.strptime(self.time, "%Y-%m-%dT%H:%M:%S.%f").astimezone(datetime.timezone.utc)

    def prepare(self, target: str, src_args: List[str]):
        mount_dest = os.path.join(target, "data")
        os.makedirs(mount_dest, exist_ok=True)
        print(f"Mounting borg archive ::{self.name} to {mount_dest} ...")
        subprocess.check_call(
            [
                "borg",
                "mount",
                f"::{self.name}",
                mount_dest,
            ],
            env=get_source_environ()
        )
        self.active_archive_mount = mount_dest
        print(f"Successfully mounted borg archive ::{self.name} to {mount_dest}")

        global active_backup
        active_backup = self

        fpath = os.path.join(target, "borg_info_archive.txt")
        with open(fpath, "wt") as f:
            info = subprocess.check_output(
                ["borg", "info", f"::{self.name}"],
                env=get_source_environ(),
                text=True,
            )
            f.write(info)
        print(f"Exported borg archive info as text file into {fpath}")

        fpath = os.path.join(target, "borg_info_archive.json")
        with open(fpath, "wt") as f:
            info = subprocess.check_output(
                ["borg", "info", "--json", f"::{self.name}"],
                env=get_source_environ(),
                text=True,
            )
            f.write(info)
        print(f"Exported borg archive info as json file into {fpath}")

    def cleanup(self):
        try:
            subprocess.check_call(["borg", "umount", self.active_archive_mount], env=get_source_environ())
            print(f"Unmounted borg archive from {self.active_archive_mount}")
            self.active_archive_mount = None
        except:
            print(f"Unmounting of borg archive from {self.active_archive_mount} failed. Ignoring.")

        global active_backup
        active_backup = None


class ResticSnapshot(Backup):
    time: str
    tree: str
    paths: List[str]
    hostname: str
    username: str
    excludes: str
    tags: List[str]
    id: str
    short_id: str

    active_repo_mount_process: subprocess.Popen
    active_snapshot_mount: str

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.name = self.short_id

        m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(.+)", self.time)
        microseconds = m.groups()[6]
        if microseconds:
            microseconds = microseconds[1:]
            while len(microseconds) > 6:
                microseconds = str(int(microseconds) // 10)
        else:
            microseconds = "0"

        zone = m.groups()[7]
        if zone == "Z":
            zone = "+0000"
        elif ":" in zone:
            zone = zone.replace(":", "")

        fixed_time = self.time[:18] + "." + microseconds + zone
        self.time = datetime.datetime.strptime(fixed_time, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(datetime.timezone.utc)

    def prepare(self, target: str, src_args: List[str]):
        self.repo_mount_dest = tempfile.mkdtemp(prefix="restic-mount-")
        print(f"Mounting restic repository to {self.repo_mount_dest} ...")
        self.active_repo_mount_process = subprocess.Popen(
            ["restic", "mount", self.repo_mount_dest],
            stdout=subprocess.PIPE,
            env=get_source_environ(),
            text=True
        )
        i = 5
        while i:
            l = self.active_repo_mount_process.stdout.readline()
            if l.startswith("Now serving the repository at "):
                break
            print(l.rstrip())
            i -= 1
        if i <= 0:
            raise RuntimeError(f"Failed to mount restic repository to {self.repo_mount_dest}")
        print(f"Successfully mounted restic repository to {self.repo_mount_dest}")
        self.active_repo_mount = self.repo_mount_dest

        global active_backup
        active_backup = self

        snapshot_mount_dest = os.path.join(target, "data")
        os.makedirs(snapshot_mount_dest, exist_ok=True)
        subprocess.check_call(
            [
                "mount",
                "-o", "bind,ro",
                os.path.join(self.repo_mount_dest, "ids", self.short_id),
                snapshot_mount_dest,
            ]
        )
        print(f"Successfully mounted restic snapshot {self.short_id} to {snapshot_mount_dest}")
        self.active_snapshot_mount = snapshot_mount_dest

        fpath = os.path.join(target, "restic_snapshot.txt")
        with open(fpath, "wt") as f:
            info = subprocess.check_output(
                ["restic", "snapshots", f"{self.id}"],
                env=get_source_environ(),
                text=True,
            )
            f.write(info)
        print(f"Exported restic snapshot info of {self.short_id} as text file into {fpath}")

        fpath = os.path.join(target, "restic_snapshot.json")
        with open(fpath, "wt") as f:
            info = subprocess.check_output(
                ["restic", "snapshots", "--json", f"{self.id}"],
                env=get_source_environ(),
                text=True,
            )
            f.write(info)
        print(f"Exported restic snapshot info of {self.short_id} as json file into {fpath}")

    def cleanup(self):
        try:
            subprocess.check_call(["umount", self.active_snapshot_mount])
            print(f"Unmounted restic snapshot from {self.active_snapshot_mount}")
            self.active_snapshot_mount = None
        except:
            print(f"Unmounting of restic snapshot from {self.active_repo_mount} failed. Ignoring.")

        self.active_repo_mount_process.send_signal(signal.SIGINT)
        self.active_repo_mount_process.wait(15) # give it some time to unmount and free fuse resources
        time.sleep(2)
        self.active_repo_mount_process = None

        os.removedirs(self.active_repo_mount)
        self.active_repo_mount = None

        global active_backup
        active_backup = None


def get_borg_archives(args, environ):
    raw = json.loads(subprocess.check_output(
        ["borg", "list", "--json"],
        env=environ
    ))
    archives = {}
    for a in raw["archives"]:
        ba = BorgArchive(**a)
        archives[ba.name] = ba
    return archives


def get_restic_snapshots(args, environ):
    raw = json.loads(subprocess.check_output(
        ["restic", "snapshots", "--json"],
        env=environ
    ))
    snapshots = {}
    for a in raw:
        s = ResticSnapshot(**a)
        snapshots[s.id] = s
    return snapshots


def get_source_environ():
    return get_morpher_environ("SRC")


def get_destination_environ():
    return get_morpher_environ("DEST")


def get_morpher_environ(side: str):
    assert side in ["SRC", "DEST"]
    PREFIX = "MORPHER_"
    new_environ = os.environ.copy()
    for k in list(new_environ.keys()):
        if k.startswith(PREFIX):
            del new_environ[k]
    for k, v in os.environ.items():
        if k.startswith(f"{PREFIX}{side}_"):
            e = k.replace(f"{PREFIX}{side}_", "")
            new_environ[e] = v
    return new_environ


def parse_args(argv):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=textwrap.dedent("""
            You can separate tool arguments with '--'.
            morpher borg2restic --dry-run
            morpher borg2restic --dry-run -- --some-dest-args
            morpher borg2restic --dry-run -- --some-src-args -- --some-dest-args
        """)
    )
    parser.add_argument(
        "mode",
        choices=['borg2restic', 'restic2borg', 'restic2restic', 'borg2borg'],
        help="selects mode of operation with a source and destination tool"
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="read-only, do not create or change destination repository"
    )
    parser.add_argument(
        "-y", "--assume-yes",
        action="store_true",
        help="assume yes to morph all found backups"
    )
    parser.add_argument(
        "-b", "--backup_range",
        action="store_true",
        help="select the range of source backups to morph, numberical, e.g., 3, -7, 21-23, 42-, or 'all'"
    )

    c = argv.count("--")
    if c == 0:
        morpher_args = argv[1:].copy()
        src_args = []
        dest_args = []
    elif c >= 1:
        i = argv.index("--")
        morpher_args = argv[1:i].copy()
        src_args = []
        dest_args = argv[i+1:].copy()
        if c == 2:
            i = dest_args.index("--")
            src_args = dest_args[:i]
            dest_args = dest_args[i+1:]

    if not morpher_args:
        parser.print_help()
        sys.exit(1)

    parsed_morpher_args = parser.parse_args(morpher_args)

    return parsed_morpher_args, src_args, dest_args


def select_backup_range(morpher_args: argparse.Namespace, src_backups: Dict[str, Backup]):
    backup_range = morpher_args.backup_range
    if not backup_range:
        print(textwrap.dedent("""
            Select source backups from valid options:
                * numerical selection (1, 2, 3, ...) for a single backup
                * numerical range selection (1-7, -7, 21-23, 42-) for multiple neighbouring backups
                * all available backups in the source repository (default or "all")
        """))
        backup_range = input("Which backups should be morphed? ").strip().lower()

    backups_to_morph = list(src_backups.values())
    if not backup_range or backup_range == "all":
        pass
    elif backup_range.isnumeric():
        try:
            n = int(backup_range) - 1
            if n >= 0 and n < len(backups_to_morph):
                backups_to_morph = [backups_to_morph[n]]
            else:
                raise ValueError()
        except:
            print("Invalid option.")
            sys.exit(1)
    elif "-" in backup_range:
        try:
            l, u = backup_range.split("-", 1)
            print(f"{l=}, {u=}")

            lower = 0
            if l:
                lower = int(l) - 1

            upper = len(backups_to_morph)
            if u:
                upper = int(u)

            if lower >= 0 and lower < upper and upper <= len(backups_to_morph):
                backups_to_morph = backups_to_morph[lower:upper]
            else:
                raise ValueError(f"value not within range: 0 <= {lower} <= {upper} <= {len(backups_to_morph)}")
        except Exception as e:
            print("Invalid option:", e)
            sys.exit(1)

    return backups_to_morph


def morph_repository(morpher_args: argparse.Namespace, src_backups: Dict[str, Backup], src_args: List[str], dest_args: List[str]):
    backups_to_morph = select_backup_range(morpher_args, src_backups)

    for b in backups_to_morph:
        print(f"Backup {b.name} @ {b.time} selected.")

    if not morpher_args.assume_yes:
        a = input(f"Proceed with morphing of {len(backups_to_morph)} backups? y/N ").strip().lower()
        if a != "y" and a != "yes":
            sys.exit(1)

    morpher_args.identifier = datetime.datetime.now().strftime('morphed_archive_%Y%m%dT%H%M%S')

    count = len(backups_to_morph)
    for i, src_backup in enumerate(backups_to_morph):
        with tempfile.TemporaryDirectory(prefix="backup-convert-") as target_dir:
            print(f"Morphing {i+1} out of {count} backups: {src_backup.name} @ {b.time} ...")
            src_backup.prepare(target_dir, src_args)
            src_backup.morph(morpher_args, target_dir, dest_args)
            src_backup.cleanup()


def morph_backup_into_borg(morpher_args: argparse.Namespace, src_backup: Backup, target: str, dest_args: List[str]):
    timestamp = src_backup.time.strftime('%Y-%m-%dT%H:%M:%S')
    print(f"Morphing {src_backup.name} from {timestamp} into new Borg archive...")
    args = [
        "borg",
        "create",
        "--dry-run" if morpher_args.dry_run else None,
        "--stats",
        "--verbose",
        f"--comment={morpher_args.identifier}",
        f"--timestamp={timestamp}",
        *dest_args,
        f"::{src_backup.name}",
        *[os.path.relpath(p, target) for p in glob.iglob(os.path.join(target, "data", "*"))],
    ]
    args = [a for a in args if a is not None]
    print("  calling:", ' '.join(args))
    r = subprocess.run(args, cwd=target, env=get_destination_environ())
    print("Borg finished with exit code:", r.returncode)


def morph_backup_into_restic(morpher_args:argparse.Namespace, src_backup: Backup, target: str, dest_args: List[str]):
    timestamp = src_backup.time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"Morphing {src_backup.name} from {timestamp} into new restic snapshot...")
    args = [
        "restic",
        "backup",
        "--dry-run" if morpher_args.dry_run else None,
        "--verbose",
        "--with-atime",
        f"--tag={morpher_args.identifier}",
        f"--time={timestamp}",
        *dest_args,
        *[os.path.relpath(p, target) for p in glob.iglob(os.path.join(target, "data", "*"))],
    ]
    args = [a for a in args if a is not None]
    print("  calling:", ' '.join(args))
    r = subprocess.run(args, cwd=target, env=get_destination_environ())
    print("restic finished with exit code:", r.returncode)


def main():
    morpher_args, src_args, dest_args = parse_args(sys.argv)
    morpher_args.source, morpher_args.destination = morpher_args.mode.split("2")
    print("Backup Morpher arguments:", morpher_args)
    print("Source arguments:", src_args)
    print("Destination arguments:", dest_args)

    if morpher_args.source == "borg":
        src_backups = get_borg_archives(src_args, get_source_environ())
    elif morpher_args.source == "restic":
        src_backups = get_restic_snapshots(src_args, get_source_environ())
    print(f"Found {len(src_backups)} backups to morph from the source repository.")

    if morpher_args.destination == "borg":
        dest_backups = get_borg_archives(dest_args, get_destination_environ())
    elif morpher_args.destination == "restic":
        dest_backups = get_restic_snapshots(dest_args, get_destination_environ())
    print(f"Found {len(dest_backups)} existing backups in the destination repository.")

    morph_repository(morpher_args, src_backups, src_args, dest_args)


active_backup = None


def exit_cleanup(signal, frame):
    global active_backup
    try:
        if active_backup:
            active_backup.cleanup()
    except:
        pass
    print("Aborted.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, exit_cleanup)
    main()
