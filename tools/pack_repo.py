#!/usr/bin/env python3
"""Concatenate this repository's files into one text bundle.

For moving the project somewhere that cannot clone it: copy the bundle (and
tools/unpack_repo.py) across as text, then run unpack_repo.py to rebuild the
directory tree.

  python3 tools/pack_repo.py                      # -> drawlogic_bundle.txt
  python3 tools/pack_repo.py -o out.txt
  python3 tools/pack_repo.py --split 400000       # parts of ~400 KB each
  python3 tools/pack_repo.py --exclude 'benchmarks/*' --exclude 'tests/golden/*'

Which files: everything git tracks (`git ls-files`), so the copy is the same
project the repository is -- manifest.txt lists the files `drawlogic doctor`
checks, and a bundle missing some would fail it. Without git, every file under
the root except the usual junk (.git, __pycache__, ...). Binary files are
skipped with a warning; this project has none.

Each file sits between two marker lines:

  <<<<<<<<<< DLBUNDLE BEGIN path=drawlogic/doc.py lines=812 sha256=... >>>>>>>>>>
  ...the file, unchanged...
  <<<<<<<<<< DLBUNDLE END path=drawlogic/doc.py >>>>>>>>>>

The line count and hash let the unpacker say exactly which file a copy-paste
damaged, instead of leaving a subtly broken tree. Stdlib only, Python 3.9+.
"""

import argparse
import fnmatch
import hashlib
import os
import subprocess
import sys

FORMAT = "DLBUNDLE v1"
OPEN = "<<<<<<<<<< "
CLOSE = " >>>>>>>>>>"
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}


def tracked_files(root):
  """Paths relative to root, '/'-separated, sorted."""
  try:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    return sorted(p for p in out.decode("utf-8").split("\0") if p)
  except (OSError, subprocess.CalledProcessError):
    found = []
    for folder, dirs, files in os.walk(root):
      dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
      for name in files:
        rel = os.path.relpath(os.path.join(folder, name), root)
        found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def read_text(path):
  """The file's text, or None if it is binary or not UTF-8."""
  with open(path, "rb") as handle:
    data = handle.read()
  if b"\0" in data:
    return None
  try:
    return data.decode("utf-8")
  except UnicodeDecodeError:
    return None


def section(rel, text):
  """One file as it goes into the bundle, ending in a newline."""
  digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
  lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
  # A file without a final newline gets one in the bundle, so its END marker
  # starts a line; `eol=no` tells the unpacker to take it off again.
  eol = "" if text.endswith("\n") or not text else " eol=no"
  body = text if text.endswith("\n") or not text else text + "\n"
  return ("%sDLBUNDLE BEGIN path=%s lines=%d sha256=%s%s%s\n%s%sDLBUNDLE END path=%s%s\n"
          % (OPEN, rel, lines, digest, eol, CLOSE, body, OPEN, rel, CLOSE))


def main():
  here = os.path.dirname(os.path.abspath(__file__))
  parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
  parser.add_argument("--root", default=os.path.dirname(here),
                      help="repository root (default: the folder above tools/)")
  parser.add_argument("-o", "--output", default="drawlogic_bundle.txt",
                      help="bundle file to write (default: drawlogic_bundle.txt)")
  parser.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                      help="leave out paths matching this glob; may repeat")
  parser.add_argument("--split", type=int, default=0, metavar="BYTES",
                      help="write several parts of about this size instead of one "
                           "file (a file is never cut in two)")
  args = parser.parse_args()

  root = os.path.abspath(args.root)
  output = os.path.abspath(args.output)
  sections = []
  for rel in tracked_files(root):
    path = os.path.join(root, rel)
    if os.path.abspath(path) == output or not os.path.isfile(path):
      continue
    if any(fnmatch.fnmatch(rel, pattern) for pattern in args.exclude):
      continue
    text = read_text(path)
    if text is None:
      print("skipped (binary or not UTF-8): %s" % rel, file=sys.stderr)
      continue
    sections.append((rel, section(rel, text)))

  # Group into parts: one part unless --split asks for several.
  parts = [[]]
  size = 0
  for rel, chunk in sections:
    if args.split and parts[-1] and size + len(chunk) > args.split:
      parts.append([])
      size = 0
    parts[-1].append((rel, chunk))
    size += len(chunk)

  stem, ext = os.path.splitext(output)
  written = []
  for index, part in enumerate(parts, 1):
    name = output if len(parts) == 1 else "%s.part%03d%s" % (stem, index, ext or ".txt")
    header = ("%s%s part=%d/%d files=%d%s\n"
              "# Rebuild with: python3 unpack_repo.py %s\n"
              % (OPEN, FORMAT, index, len(parts), len(part), CLOSE,
                 os.path.basename(name) if len(parts) == 1
                 else os.path.basename(stem) + ".part*" + (ext or ".txt")))
    with open(name, "w", encoding="utf-8", newline="\n") as handle:
      handle.write(header)
      for _rel, chunk in part:
        handle.write(chunk)
    written.append(name)

  total = sum(os.path.getsize(name) for name in written)
  print("packed %d files into %s (%d bytes)"
        % (len(sections), ", ".join(os.path.relpath(n) for n in written), total))


if __name__ == "__main__":
  main()
