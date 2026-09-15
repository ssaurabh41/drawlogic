# verify.ps1 self-test

A throwaway fixture for checking that `verify.ps1` itself runs correctly on
your machine -- separate from the real `manifest.txt` at the repo root, so
running it can't produce a false "your drawlogic copy is broken" result.

From the repo root on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File verify.ps1 -Root verify_selftest
```

Expected output: `1 files, all as they should be`.

To confirm it also catches a real mismatch, edit `sample.txt` (change the
text, save) and run the command again -- it should report `MISMATCH
sample.txt`. Put the original line back afterwards, or just re-clone this
folder from git.

This folder is not covered by the project's own manifest.txt check
(`tests/test_manifest.py` only tracks files under `drawlogic/`), so it's
safe to leave in place or delete once you're done.
