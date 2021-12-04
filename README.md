# Backup Morpher

This project can morph Borg and restic backups by converting between them, or
transparently re-creating snapshots and archives into new repositories. File
metadata and timestamps, as well as snapshot and archive metadata is preserved
as much as possible.

Backup Morpher can take either Borg or restic repositories as source, and morph
them into Borg or restic destination repositories, see different modes below.

An interesting use case is to use the Backup Morpher similar to a
`git-filter-branch` to manipulate the backups while copying them into a new
repository:

* Accidentally backed-up your photo library or a big Linux ISO file from your
  Downloads folder? Simply exclude files larger than X bytes during the
  repository conversion.
* Included files with plain-text passwords or other sensitive data? Exclude
  files based on filename patterns.
* Created a backup with the wrong hostname or want to back-date a snapshot?
  Adjust the metadata on-the-fly.

For large repositories, it might run for multiple days. Make sure to execute it
within a [tmux] or [GNU screen] session to avoid accidentally killing the
process.

Backup software is known to be memory hungry, so keep an eye on your free memory
and possible OOM (out-of-memory) kills.

Developed and tested for [Borg 1.1.17] and [restic 0.12.1]. There is no special
integration with either backup tool apart from the standard command line
interface, which should be stable and backward as well as forward-compatible.

[tmux]: https://github.com/tmux/tmux
[GNU screen]: https://www.gnu.org/software/screen/
[Borg 1.1.17]: https://github.com/borgbackup/borg/releases/tag/1.1.17
[restic 0.12.1]: https://github.com/restic/restic/releases/tag/v0.12.1

## Requirements

* Linux system
* Borg
* restic
* Python 3.9+
* FUSE (for `borg mount` to work)

## Modes of Operation

The morpher is designed for reading a source repository and transfering all backups into a destination repository. The modes are defined as `X` to `Y`, with Borg and restic being either source or destination:

* `borg2restic`
* `restic2borg`
* `borg2borg`
* `restic2restic`

The approach for all modes follows this general pattern:

* open or initialize destination repository
* list existing archive/snapshots
* loop over all source archives/snapshots
  * mount source archive/snapshot via FUSE
    * pass in source command line arguments
  * export source archive/snapshot metadata and statistics to a file
  * create new archive/snapshot in destination repository
    * pass in destination command line arguments
  * unmount and cleanup

## Usage

You can print the help and usage information with: `morpher --help`

You can pass tool arguments for either source or destination tools. Please
notice the `--` argument as separators:

* `morpher borg2restic`
  * This command does not contain any source or destination arguments and
    therefore assumes you configured appropriate environment variables, which
    are passed through.
* `morpher restic2restic -- --exclude "*.iso"`
  * This calls morpher with the `restic2restic` mode, and passes `--exclude
    "*.iso"` to the destination restic tool to remove all `.iso` files from any
    snapshot.
* `morpher borg2restic --dry-run -- --verbose -- --exclude-larger-than 256M`
  * This calls morpher with the `borg2restic` mode in dry-run, passes the
    `--verbose` argument to Borg as source, and passes `--exclude-larger-than
    256M` to restic as destination.

For each morphed backup (a restic snapshot or a Borg archive), the corresponding
metadata is exported into a text file and a json file. These files are in the
root of the new backup, and all actual data is underneath a new parent directory
`data/`. If you want to pass destination arguments with file exclusion patterns,
make sure to account for this new prefix during morphing.

You can define and use all Borg and restic-specific environment variables before
starting the converter, see [Borg docs on Environment Variables] and [restic
docs on Environment Variables]. Take care of these environment variables when
using a mode with the same tool as source and destination (`borg2borg` or
`restic2restic`) - you can fall-back to command line arguments for both
repositories.

In cases where source and destination are the same, restic2restic or borg2borg,
or simply to keep the environment variables clean, you can prefix them for the
source with `MORPHER_SRC_` and for the destination with `MORPHER_DEST_`, e.g.,
`MORPHER_SRC_RESTIC_REPOSITORY=/some/path/to/restic_repo`. Each variable is only
passed to the respective process during source or destination operations.

[Borg docs on Environment Variables]: https://borgbackup.readthedocs.io/en/stable/usage/general.html#environment-variables
[restic docs on Environment Variables]: https://restic.readthedocs.io/en/latest/040_backup.html#environment-variables

### Example: restic2restic

```shell
export GODEBUG=asyncpreemptoff=1
export MORPHER_SRC_RESTIC_REPOSITORY=/external-disk/source_repo
export MORPHER_SRC_RESTIC_PASSWORD_FILE=/external-disk/source_repo.pw
export MORPHER_DEST_RESTIC_REPOSITORY=/external-disk/destination_repo
export MORPHER_DEST_RESTIC_PASSWORD_FILE=/external-disk/destination_repo.pw
./morpher restic2restic \
  -- \
  -- \
  --exclude-file /external-disk/filter-excludes.txt \
  --exclude-caches \
  --no-cache \
  --host some_new_hostname
```

### Example: borg2restic

```shell
restic init --repo /external-disk/destination_repo --password-file /external-disk/destination_repo.pw

export MORPHER_SRC_BORG_REPOSITORY=/external-disk/source_repo
export MORPHER_SRC_BORG_PASSPHRASE=super_s3cret!
export MORPHER_DEST_RESTIC_REPOSITORY=/external-disk/destination_repo
export MORPHER_DEST_RESTIC_PASSWORD_FILE=/external-disk/destination_repo.pw
./morpher borg2restic --dry-run -- --exclude data/home/me/Downloads/bigfile.mp4
```

## Related Reading

### Borg

* https://www.borgbackup.org/
* https://github.com/borgbackup/borg
* https://borgbackup.readthedocs.io/en/stable/

### restic

* https://restic.net/
* https://github.com/restic/restic
* https://restic.readthedocs.io/en/stable/

## License

This project is made available under the MIT License. For more details, see the
``LICENSE`` file in the repository.

## Author

This project was created by Thomas Kriechbaumer.
