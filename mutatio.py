#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    mutatio.py: Look for changes in several OpenBSD topics.
"""

# =============================================================================
# This script is originally intended to be run via cron jobs, using
# different jobs for different options. The purpose is to get
# notified when some change occurs from several OpenBSD related topics
# from "official" sources, keeping the pace with the evolution of the
# project in a more comfortable way.
# =============================================================================

# =============================================================================
#
# Copyright (c) 2018 joe di castro <joe@joedicastro.com>
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
# =============================================================================

__author__ = "joe di castro <joe@joedicastro.com>"
__license__ = "ISC"
__date__ = "2018/02/18"
__version__ = "0.1"

import os
import subprocess
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from difflib import context_diff
from filecmp import cmp
from http.client import HTTPResponse
from pathlib import Path
from platform import machine
from re import findall
from shutil import move, rmtree, which
from time import sleep
from typing import Dict, List, Optional, Tuple, Union
from urllib import request, error, parse


def arguments() -> ArgumentParser:
    """Defines the command line arguments for the script."""
    desc = """Look for changes in several OpenBSD topics."""

    parser = ArgumentParser(description=desc)
    parser.add_argument("-q", "--quiet", dest="quiet", action="store_true",
                        help="do not send any output to the command line")
    parser.add_argument("-m", "--mail", dest="mail", action="store_true",
                        help="send feedback via local mail to current user")
    parser.add_argument("-n", "--notify", dest="notify", action="store_true",
                        help="send feedback via popup notification"
                        " (notify-send)")
    parser.add_argument("-t", "--no-temp", dest="no_temp", action="store_true",
                        help="do not use the /tmp directory/partition")
    parser.add_argument("-S", "--snapshot", dest="snapshot",
                        action="store_true",
                        help="look for a new snapshot set for current arch")
    parser.add_argument("-P", "--packages", dest="packages",
                        action="store_true",
                        help="look for a new set of packages")
    parser.add_argument("-l", "--changelog", dest="changelog",
                        action="store_true",
                        help="look for changes in the ChangeLog file")
    parser.add_argument("-s", "--errata", dest="errata", action="store_true",
                        help="look for changes in the errata web page")
    parser.add_argument("-e", "--events", dest="events", action="store_true",
                        help="look for changes in the events web page")
    parser.add_argument("-c", "--current", dest="current", action="store_true",
                        help="look for changes in the FAQ's current web page.")
    parser.add_argument("-i", "--innovations", dest="innovations",
                        action="store_true",
                        help="look for changes in the innovations web page.")
    parser.add_argument("-H", "--hackathons", dest="hackathons",
                        action="store_true",
                        help="look for changes in the hackathons web page")
    parser.add_argument("-M", "--mirror", default=None, nargs="?",
                        help="The mirror where to get the snapshots from "
                        "[default: the one from /etc/installurl]")
    parser.add_argument("path", default="~/obsd", nargs="?",
                        help="The path to store the working files "
                        "[default: ~/obsd]")
    parser.add_argument("-v", "--version", action="version",
                        version=f"%(prog)s {__version__}",
                        help="show program's version number and exit")
    return parser


def get_document(url: str) -> List[str]:
    """Retrieve a document from a given URL.

    url -- the document URL

    """
    # use w3m if available to remove html tags in diff output for readability.
    # Some notification daemons like dunst support html tags output and
    # that's not a problem, but if you are going to use the mail
    # option, then it looks better with w3m's conversion to ASCII output.
    w3m_is_installed = which("w3m")
    try:
        with request.urlopen(url) as page:
            if isinstance(page, HTTPResponse):
                content_type = page.getheader("Content-Type")
            if content_type == "text/html":
                if w3m_is_installed:
                    proc = subprocess.Popen(
                        "w3m -dump -cols 80 -O ascii -T text/html".split(),
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE
                    )
                    output = proc.communicate(input=page.read())
                    content = [
                        f"{i}\n"
                        for i
                        in output[0].decode("ascii").split("\n")
                    ]
                else:
                    content = [
                        i.decode("utf-8", errors="ignore")
                        for i
                        in page.readlines()
                    ]
            else:
                content = [
                    i.decode("ascii", errors="ignore")
                    for i
                    in page.readlines()
                ]
            return content
    except (ValueError, error.URLError, error.HTTPError) as err:
        print(err, file=sys.stderr)
        sys.exit(-2)


def get_document_changes(previous: str, current: List[str], url: str) -> str:
    """Get the differences between versions of the same document.

    previous -- the file name of the previous document version
    current -- the current document version
    url -- the document's URL

    """
    changes = "".join(
        context_diff(
            open(previous, "r").readlines(),
            current,
            fromfile="previous",
            tofile="current"
        )
    )

    # I append the document URL to the output because some
    # notification daemons like dunst allows us to open it in a
    # browser directly, and sometimes it could be very handy.
    return changes + os.linesep + url if changes else changes


def get_update_info(url: str) -> Tuple[str, Optional[str]]:
    """Get the document changes and its status.

    url -- the current document url

    """
    doc_from_mirror, doc_name = get_document(url), url.split("/")[-1]
    status, changes = None, None
    if not Path(doc_name).exists():
        status = "bootstrap"
    else:
        changes = get_document_changes(doc_name, doc_from_mirror, url)
        status = "same" if not changes else "new"
    if status in ("new", "bootstrap"):
        with open(doc_name, "w") as f:
            f.writelines(doc_from_mirror)
    return status, changes


def get_binary(url: str, filename: Union[Path, str]) -> None:
    """Retrieve a binary file from a given URL.

    url -- the binary file URL.
    filename -- the file name.

    """
    try:
        with request.urlopen(url) as binary, open(filename, "wb") as output:
            output.write(binary.read())
    except (ValueError, error.URLError, error.HTTPError) as err:
        print(err, file=sys.stderr)
        sys.exit(-2)


def download_snapshot(url: str, signify_file: str, directory: str) -> Path:
    """Download a snapshot from the mirror.

    url -- the snapshot's mirror URL
    signify_file -- a signify signed SHA256 checksums file
    directory -- the directory root where to store the snapshot

    """
    subdir = Path(directory, "snapshot")
    signify_file_path = subdir / signify_file
    subdir.mkdir()
    get_binary(parse.urljoin(url, signify_file), signify_file_path)
    files = findall("\((.*)\)", open(signify_file_path).read())
    for f in files:
        get_binary(parse.urljoin(url, f), subdir / f)
    return subdir


def verify(signify: Dict[str, str], snapshot: Path,
           filename: str="") -> Tuple[bool, List[str]]:
    """Verify the integrity of a given snapshot with signify.

    signify -- a dict with signify key and signify signed SHA256 checksums file
    snapshot -- the directory where the snapshot is stored
    filename -- the name of a file for a single file verification

    """
    os.chdir(snapshot)
    snapshot_release = list(
        Path('.').glob('base*.tgz')
    )[0].as_posix().rstrip('.tgz').lstrip('base')
    signify_key = Path(
        signify['key_dir'],
        f"/etc/signify/openbsd-{snapshot_release}-base.pub"
    ).as_posix()
    command = f"signify -Cp {signify_key} -x {signify['file']} {filename}"
    status = subprocess.getstatusoutput(command)
    failed = [
        i.split(":")[0]
        for i
        in status[1].split(os.linesep)
        if i.endswith("FAIL")
    ]
    return status[0] == 0, failed


def check_integrity(signify: Dict[str, str], snapshot: Path, url: str) -> bool:
    """Check the integrity of the snapshot and retry once if failed files.

    signify -- the signify key and a signify signed file with SHA256 checksums
    snapshot -- the directory where the snapshot is stored
    url --  the snapshots' mirror URL

    """
    whole, failed = verify(signify, snapshot)
    # if there are some failed files, retry once, five minutes
    # after. Downloads can fail or just get the mirror in the middle
    # of a sync.
    if failed:
        sleep(300)
        for f in failed:
            get_binary(parse.urljoin(url, f), f)
        whole, failed = verify(signify, snapshot)
    return whole


def is_installed(snapshot: Path) -> bool:
    """Check if a given snapshot is already installed and running.

    snapshot -- the snapshot directory

    """
    ramdisk_file = "bsd.rd"
    return cmp(
        Path(snapshot, ramdisk_file).as_posix(),
        Path("/", ramdisk_file).as_posix(),
    )


def rotate(snapshots_directory: Path, subdirectories: Dict[str, Path]) -> None:
    """Rotate the available snapshots if needed.

    snapshots_directory -- the directory where the snapshots are stored

    """
    if subdirectories["previous"].exists():
        rmtree(subdirectories["previous"])
    if subdirectories["current"].exists():
        move(subdirectories["current"], subdirectories["previous"])
    move(subdirectories["upgrade"], subdirectories["current"])


def notify(header: str, body: str, urgency: str="normal") -> None:
    """Show a desktop notification via notify-send.

    header -- the notification header
    body -- the notification body
    urgency -- the urgency level (default 'normal') [low|normal|critical]

    """
    if which("notify-send"):
        subprocess.run(["notify-send", "-a", header, "-u", urgency, body])


def mail(subject: str, body: str) -> None:
    """Send a local mail to the current user.

    subject - the mail subject
    body - the mail body

    """
    proc = subprocess.Popen(
        ["mail", "-s", f"{subject}", f"{os.getenv('USER')}"],
        stdin=subprocess.PIPE
    )
    proc.communicate(input=body.encode(errors="ignore"))


def feedback(args: Namespace, title: str, body: str, urgency: str) -> None:
    """Give feedback to the user following the script arguments.

    args -- the script arguments
    title -- the notification title
    body -- the notification body
    urgency -- the urgency level (default 'normal') [low|normal|critical]

    """
    if args.notify:
        notify(title, body, urgency)
    if args.mail:
        mail(title, body)
    if not args.quiet:
        sys.stdout.writelines(body+os.linesep)


def main() -> None:
    """Main section."""

    args = arguments().parse_args()

    current_release = os.uname().release.replace(".", "")
    architecture = machine()
    signify = {
        "key_dir": f"/etc/signify/",
        "file": "SHA256.sig"
    }

    # URLs
    if args.mirror:
        mirror_url = args.mirror
    else:
        try:
            mirror_url = open("/etc/installurl").read().rstrip()
            if not mirror_url:
                print("Your /etc/installurl file is empty.", file=sys.stderr)
                sys.exit(-2)
        except FileNotFoundError:
            print("You do not have a /etc/installurl file.", file=sys.stderr)
            sys.exit(-2)
    # ensure to have a proper URL to make the joins
    mirror_url = mirror_url if mirror_url.endswith("/") else f"{mirror_url}/"

    snapshots_url = parse.urljoin(mirror_url, f"snapshots/{architecture}/")
    packages_url = parse.urljoin(
        mirror_url,
        f"snapshots/packages/{architecture}/"
    )
    website_url = "https://www.openbsd.org/"

    # files to check for updates/download
    files_urls = {
        "changelog": parse.urljoin(mirror_url, "Changelogs/ChangeLog"),
        "packages": parse.urljoin(packages_url, "index.txt"),
        "snapshots": parse.urljoin(snapshots_url, "BUILDINFO"),
        "events": parse.urljoin(website_url, "events.html"),
        "hackathons": parse.urljoin(website_url, "hackathons.html"),
        "innovations": parse.urljoin(website_url, "innovations.html"),
        "errata": parse.urljoin(website_url, f"errata{current_release}.html"),
        "current": parse.urljoin(website_url, "faq/current.html"),
    }

    # directories
    working_dir = Path(args.path).expanduser()
    snaps_dir = working_dir / "snapshots"
    snaps_subdirs = {
        i: snaps_dir / i
        for i
        in ["previous", "current", "upgrade"]
    }

    data: Dict[str, Dict] = {
        "errata": {
            "url": files_urls["errata"],
            "title": "New OpenBSD security patch.",
            "body": None,
            "level": "normal"
        },
        "changelog": {
            "url": files_urls["changelog"],
            "title": "New OpenBSD CVS commits.",
            "body": None,
            "level": "low"
        },
        "events": {
            "url": files_urls["events"],
            "title": "New OpenBSD event.",
            "body": None,
            "level": "normal"
        },
        "current": {
            "url": files_urls["current"],
            "title": "OpenBSD FAQ's following current update.",
            "body": None,
            "level": "critical"
        },
        "innovations": {
            "url": files_urls["innovations"],
            "title": "New OpenBSD innovations.",
            "body": None,
            "level": "normal"
        },
        "hackathons": {
            "url": files_urls["hackathons"],
            "title": "OpenBSD hackathons update.",
            "body": None,
            "level": "normal"
        },
        "packages": {
            "url": files_urls["packages"],
            "title": "OpenBSD package set",
            "body": f"New {architecture} package set available.",
            "level": "critical"
        },
    }

    if not working_dir.exists():
        working_dir.mkdir()
    os.chdir(working_dir)

    # look for changes in all but snapshots
    for k, v in vars(args).items():
        if v is True and k in data.keys():
            status, changes = get_update_info(data[k]["url"])

            if changes:
                feedback(
                    args,
                    data[k]["title"],
                    changes if not data[k]["body"] else data[k]["body"],
                    data[k]["level"],
                )

    # look for changes in snapshots
    if args.snapshot:
        status, changes = get_update_info(files_urls["snapshots"])
        tempfile.tempdir = Path(snaps_dir).as_posix() if args.no_temp else None

        if status == "bootstrap":
            with tempfile.TemporaryDirectory() as tmp:
                snapshot = download_snapshot(
                    snapshots_url,
                    signify["file"],
                    tmp
                )
                intact = check_integrity(signify, snapshot, snapshots_url)
                if intact:
                    if is_installed(snapshot):
                        move(snapshot, snaps_subdirs["current"])
                    else:
                        move(snapshot, snaps_subdirs["upgrade"])
                        feedback(
                            args,
                            "OpenBSD Snapshot",
                            "New Snapshot set available to upgrade.",
                            "critical"
                        )

        if status == "same":
            if snaps_subdirs["upgrade"].exists():
                if is_installed(snaps_subdirs["upgrade"]):
                    rotate(snaps_dir, snaps_subdirs)

        if status == "new":
            with tempfile.TemporaryDirectory() as tmp:
                snapshot = download_snapshot(
                    snapshots_url,
                    signify["file"],
                    tmp
                )
                intact = check_integrity(signify, snapshot, snapshots_url)
                if intact:
                    if not snaps_subdirs["upgrade"].exists():
                        move(snapshot, snaps_subdirs["upgrade"])
                    else:
                        rmtree(snaps_subdirs["upgrade"])
                        move(snapshot, snaps_subdirs["upgrade"])
                    feedback(
                        args,
                        "OpenBSD Snapshot",
                        "New Snapshot set available to upgrade.",
                        "critical"
                    )


if __name__ == "__main__":
    main()


###############################################################################
#                                  ChangeLog                                  #
###############################################################################
#
# 0.1:
#
# * First raw working attempt
#
