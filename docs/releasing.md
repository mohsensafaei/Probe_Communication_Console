# Maintainer release process

`main` is the canonical cross-platform source. Stable Windows/Linux history remains
in the old branches; releases are made from tested `main` commits. Do not merge
old-layout branches back without adapting paths and running the complete checks.

## Prepare

1. Update `src/probe/__init__.py` with the release version and move user-visible
   changes into its section in `CHANGELOG.md`.
2. Check user/developer guides, examples, dependency pins and third-party notices.
   Keep the bundled USBPcap source/license/checksum aligned with its installer.
3. Merge through a reviewed pull request. Wait for all CI tests, Python distributions
   and both native portable build jobs to pass on that exact commit.
4. Download and check the native artifacts on target Windows/Linux lab machines.
   Test real serial and HID paths when those areas changed; document coverage gaps.

## Publish

Create a GitHub release with tag `v<version>` targeting that tested commit on
`main`. Use the changelog section as release notes and describe platform/hardware
limitations. The version must match `probe.__version__`. Publishing a release runs
CI again; its final job attaches the tested Windows/Linux ZIPs, their checksums,
wheel and source distribution to that release. Assets appear after the jobs finish.

The upload job has write permission only for the release event. Pull requests and
ordinary pushes use read-only repository permissions. No PyPI token, custom release
credential or signing secret is required. A failed job must be fixed before calling
the release complete; never relabel a different binary as a tested artifact.

If automatic upload is unavailable, download the artifacts from the passing run
and attach those exact files manually. Do not publish local captures/settings or
source environments. Keep the generated GitHub source archives available alongside
the portable binaries for reproducible source access.

## Repository settings

Make `main` the default branch. Enable Issues and private vulnerability reporting
where available. Protect `main` with pull-request review and the CI checks once the
first successful run has registered them; do not require unavailable checks. Allow
fork pull requests to run with the normal read-only token, without secrets.

Review release artifacts and platform support when changing runner images or
Python versions. Code signing and PyPI publication are separate future maintainer
choices; the current workflow does not claim either.
