#!/usr/bin/env python3
"""Rebuild the repository's directory tree from a bundle made by pack_repo.py.

  python3 unpack_repo.py drawlogic_bundle.txt                  # into ./drawlogic
  python3 unpack_repo.py drawlogic_bundle.txt -d some/folder
  python3 unpack_repo.py bundle.part001.txt bundle.part002.txt ...
  python3 unpack_repo.py drawlogic_bundle.txt --check          # verify only

Every file is checked against the line count and SHA-256 written beside it
when it was packed. A copy-paste that dropped a line, wrapped one, or changed
tabs or trailing spaces is reported by file name, and the run exits non-zero.
Windows line endings picked up on the way are taken off before checking, since
the originals have none.

Stdlib only, Python 3.9+, and self-contained: copy this one file across with
the bundle.
"""

import argparse
import glob
import hashlib
import os
import re
import sys

BEGIN = re.compile(r"^<{10} DLBUNDLE BEGIN path=(?P<path>.+?) lines=(?P<lines>\d+) "
                   r"sha256=(?P<sha>[0-9a-f]{64})(?P<noeol> eol=no)? >{10}$")
END = "<<<<<<<<<< DLBUNDLE END path=%s >>>>>>>>>>"
HEADER = re.compile(r"^<{10} DLBUNDLE v1 part=(?P<part>\d+)/(?P<parts>\d+) "
                    r"files=(?P<files>\d+) >{10}$")


def safe_target(root, rel):
  """Where `rel` goes under root, refusing anything that would land outside it."""
  if rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
    raise ValueError("absolute path in bundle: %s" % rel)
  target = os.path.normpath(os.path.join(root, *rel.split("/")))
  if os.path.commonpath([os.path.abspath(root), os.path.abspath(target)]) \
      != os.path.abspath(root):
    raise ValueError("path escapes the target folder: %s" % rel)
  return target


def read_sections(paths, expected):
  """Yield (path, text, expected_lines, expected_sha, problems) per file.

  `expected` is filled in from the headers: {"files": n, "parts": {i, ...},
  "of": total parts}, so a lost part or a cut-off paste is noticed even where
  nothing is left of the files it held.
  """
  for bundle in paths:
    with open(bundle, "r", encoding="utf-8", newline="") as handle:
      lines = handle.read().split("\n")
    lines = [line[:-1] if line.endswith("\r") else line for line in lines]
    header = HEADER.match(lines[0]) if lines else None
    if not header:
      print("warning: %s does not start with a DLBUNDLE header" % bundle,
            file=sys.stderr)
    else:
      expected["files"] += int(header.group("files"))
      expected["parts"].add(int(header.group("part")))
      expected["of"] = int(header.group("parts"))
    index = 0
    while index < len(lines):
      match = BEGIN.match(lines[index])
      index += 1
      if not match:
        continue
      rel = match.group("path")
      closing = END % rel
      body = []
      while index < len(lines) and lines[index] != closing:
        if BEGIN.match(lines[index]):
          break
        body.append(lines[index])
        index += 1
      problems = []
      if index >= len(lines) or lines[index] != closing:
        problems.append("no END marker -- the bundle was cut off here")
      else:
        index += 1
      text = "\n".join(body) + ("\n" if body else "")
      if match.group("noeol") and text.endswith("\n"):
        text = text[:-1]
      yield rel, text, int(match.group("lines")), match.group("sha"), problems


def main():
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("bundles", nargs="+",
                      help="bundle file(s); parts are read in name order")
  parser.add_argument("-d", "--dest", default="drawlogic",
                      help="folder to rebuild into (default: ./drawlogic)")
  parser.add_argument("--check", action="store_true",
                      help="verify the bundle without writing anything")
  parser.add_argument("--force", action="store_true",
                      help="write files that fail their check anyway")
  args = parser.parse_args()

  paths = []
  for pattern in args.bundles:
    matched = sorted(glob.glob(pattern))
    paths.extend(matched or [pattern])

  dest = os.path.abspath(args.dest)
  written = bad = 0
  seen = set()
  expected = {"files": 0, "parts": set(), "of": 0}
  for rel, text, want_lines, want_sha, problems in read_sections(paths, expected):
    if rel in seen:
      problems.append("appears twice in the bundle")
    seen.add(rel)
    got_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if got_lines != want_lines:
      problems.append("%d lines, expected %d" % (got_lines, want_lines))
    elif hashlib.sha256(text.encode("utf-8")).hexdigest() != want_sha:
      problems.append("content changed (line count is right: look for altered "
                      "tabs, trailing spaces or characters)")
    if problems:
      bad += 1
      print("BAD  %s: %s" % (rel, "; ".join(problems)), file=sys.stderr)
      if not args.force:
        continue
    if args.check:
      continue
    target = safe_target(dest, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
      handle.write(text)
    written += 1

  if not seen:
    print("no files found -- is this a DLBUNDLE file?", file=sys.stderr)
    sys.exit(1)
  missing_parts = sorted(set(range(1, expected["of"] + 1)) - expected["parts"])
  if missing_parts:
    bad += 1
    print("BAD  part(s) %s of %d not given" % (
      ", ".join(map(str, missing_parts)), expected["of"]), file=sys.stderr)
  if len(seen) < expected["files"]:
    bad += 1
    print("BAD  the headers promise %d files but only %d were found -- the rest "
          "were cut off" % (expected["files"], len(seen)), file=sys.stderr)
  if args.check:
    print("%d files checked, %d bad" % (len(seen), bad))
  else:
    print("wrote %d of %d files into %s%s"
          % (written, len(seen), dest, "" if not bad else
             " -- %d failed their check%s" % (bad, ", written anyway" if args.force
                                               else " and were not written")))
  sys.exit(1 if bad else 0)


if __name__ == "__main__":
  main()
