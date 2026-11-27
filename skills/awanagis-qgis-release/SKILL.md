---
name: awanagis-qgis-release
description: >
  Prepare, merge, tag, publish, and upload AwanaGIS releases to GitHub and the
  official QGIS plugin repository. Use whenever the user asks to release, tag,
  publish, upload, approve, or check an AwanaGIS plugin version, or when a QGIS
  security scan blocks a version. Covers fail-closed Bandit checks, protected
  GitHub release approval, exact release-asset digest verification, authenticated
  Brave reuse, QGIS upload verification, and pending-approval status.
license: GPL-2.0-or-later
metadata:
  author: Awana Digital
  version: "1.0"
---

# AwanaGIS QGIS release and upload

Use this workflow for every AwanaGIS version intended for `plugins.qgis.org`.
The canonical repository is `digidem/awanaGIS`; plugin ID is `7139`.

**Failure pattern:** a release can pass ordinary CI yet still be blocked by QGIS,
or can be uploaded successfully but remain unavailable because staff approval is
pending. Treating those states as the same leads to duplicate uploads or false
success reports.

**Verified by:** AwanaGIS `1.1.1` passed all PR and release CI, the QGIS scan
reported zero issues/warnings/critical findings, and the exact GitHub Release ZIP
was uploaded and verified on the QGIS version page.

## Safety boundaries

- Separate **prepare**, **merge/release**, and **QGIS upload** actions. Require
  explicit user authorization before pushing a release branch, merging, tagging,
  approving a protected environment, or submitting a QGIS version.
- Never upload a version that already exists on QGIS. Check the Versions table
  first; a green scan with `Approved: no` is already uploaded and needs staff
  approval, not another upload.
- Never write cookie values, tokens, passwords, or auth-state contents into this
  skill, logs, reports, or git. Use short-lived copied browser profiles and remove
  them afterward.
- Keep `metadata.txt` and `server/mcp_server.py::SERVER_INFO["version"]` in sync.

## Procedure

### 1. Establish the release target

- [ ] Confirm the repository explicitly: `gh repo set-default digidem/awanaGIS`.
  Multiple remotes exist; do not trust implicit `gh` repository selection.
- [ ] Fetch `main`, confirm a clean worktree, and identify the exact version/tag.
- [ ] Check that the version does not already exist locally, remotely, on GitHub,
  or in the QGIS Versions table.
- [ ] Read `references/known-issues.md` before interpreting local test failures.

### 2. Validate the exact package

- [ ] Confirm `metadata.txt` version, top changelog entry, and MCP `SERVER_INFO`
  version all match.
- [ ] Run release metadata validation:

  ```sh
  python3 ci/check_plugin.py release-meta metadata.txt --tag vX.Y.Z
  ```

- [ ] Build the package and scan the extracted ZIP, not just the source tree:

  ```sh
  python3 scripts/package_plugin.py --output /tmp/opencode/awanagis-X.Y.Z.zip
  python3 ci/check_plugin.py archive /tmp/opencode/awanagis-X.Y.Z.zip \
    --extract-to /tmp/opencode/awanagis-X.Y.Z-extracted
  python3 ci/check_plugin.py scan /tmp/opencode/awanagis-X.Y.Z-extracted/awanagis \
    --check bandit
  python3 ci/check_plugin.py scan /tmp/opencode/awanagis-X.Y.Z-extracted/awanagis \
    --check secrets --include-metadata --baseline-file .secrets.baseline
  ```

- [ ] Run the CI checker tests with real scanners and the full QGIS suite. Every
  Bandit finding blocks, including `LOW`/`B110`.
- [ ] Require green PR checks before merge. The release workflow reruns the same
  package, Bandit, secrets, quality, QGIS 3/Qt 5, and QGIS 4/Qt 6 gates.

### 3. Merge and publish the GitHub Release

- [ ] Push the reviewed branch and open a PR against `main`.
- [ ] Watch checks to completion:

  ```sh
  gh pr checks <pr> --repo digidem/awanaGIS --watch --interval 30
  gh pr merge <pr> --repo digidem/awanaGIS --merge --delete-branch
  ```

- [ ] Tag the exact merge commit and push the tag:

  ```sh
  git tag -a vX.Y.Z <merge-sha> -m "AwanaGIS vX.Y.Z"
  git push origin vX.Y.Z
  ```

- [ ] Monitor `.github/workflows/release.yml`. If `Publish GitHub Release` waits on
  the protected `release` environment, inspect pending deployments:

  ```sh
  gh api repos/digidem/awanaGIS/actions/runs/<run-id>/pending_deployments
  ```

- [ ] Approve only after explicit user authorization and only when
  `current_user_can_approve` is true. Send numeric environment IDs as JSON; string
  form values are rejected:

  ```sh
  gh api --method POST \
    repos/digidem/awanaGIS/actions/runs/<run-id>/pending_deployments \
    --input - <<'JSON'
  {"environment_ids":[<numeric-environment-id>],"state":"approved","comment":"Approved for AwanaGIS vX.Y.Z release"}
  JSON
  ```

- [ ] Verify the release is not draft/prerelease unless intended, and record the
  ZIP asset name and `sha256:` digest:

  ```sh
  gh release view vX.Y.Z --repo digidem/awanaGIS \
    --json tagName,isDraft,isPrerelease,url,assets
  ```

### 4. Download and verify the official release asset

Use the bundled verifier instead of manually comparing digests:

```sh
python3 skills/awanagis-qgis-release/scripts/verify_release_asset.py \
  --repo digidem/awanaGIS --tag vX.Y.Z \
  --asset awanagis-X.Y.Z.zip --output-dir /tmp/opencode/qgis-upload
```

The script fails if the GitHub digest is missing/malformed or the downloaded
file's SHA-256 differs.

### 5. Reuse the authenticated QGIS browser session

The user's normal browser is Brave. A fresh Chrome profile is not authenticated.

- [ ] Check for QGIS cookies without reading values:

  ```sh
  python3 - <<'PY'
  import sqlite3
  from pathlib import Path
  p = Path.home()/".config/BraveSoftware/Brave-Browser/Default/Cookies"
  con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
  print(con.execute(
      "SELECT host_key, name FROM cookies WHERE host_key LIKE '%qgis.org'"
  ).fetchall())
  PY
  ```

- [ ] If Brave has no CDP port, create a temporary profile containing only
  `Local State`, `Default/Cookies`, and `Default/Preferences`. Launch Brave
  headless on a free local port with a long tool timeout. Do not restart or take
  over the user's normal Brave process.
- [ ] Connect `agent-browser` with an explicit worktree session and CDP port.
  Navigate to `https://plugins.qgis.org/plugins/my`, then AwanaGIS, then
  `+ Add version`.
- [ ] Upload the verified GitHub Release ZIP. Fill the version changelog.
- [ ] Check the six pre-upload declarations only when each is true: ZIP structure,
  repository/source parity, English description, valid public links, QGIS tested,
  and email/contact agreement.
- [ ] Save, then open `Check validation status`.

### 6. Verify QGIS acceptance and report the real state

- [ ] Require `Security Scan ✓` and `Qt6 Check ✓`.
- [ ] Require `All security checks passed!` with zero issues, warnings, and
  critical findings. Inspect Bandit, Secrets, Flake8, File Permissions, and
  Suspicious Files individually.
- [ ] Open version **Details** and record `Approved`.
- [ ] Check the public feed: `https://plugins.qgis.org/plugins/awanagis/json`.
  It lists approved public versions only and can lag the management UI.
- [ ] Interpret states correctly:
  - scan failed or critical findings: blocked; fix and upload a higher version;
  - scan passed and `Approved: no`: uploaded, awaiting QGIS staff approval;
  - `Approved: yes` and present in public JSON: publicly released.

### 7. Clean up authenticated browser state

- [ ] Close the `agent-browser` session.
- [ ] Verify the exact Brave parent/child PIDs from `/proc/<pid>/cmdline`, stop
  only those processes, and confirm the CDP port is closed.
- [ ] Remove the temporary copied Brave profile and verify it is absent. It
  contains plaintext session cookies.

## Report format

Use this structure:

```text
GitHub Release: <url> (draft: no, prerelease: no)
Release ZIP: <name>
SHA-256: <digest>
QGIS version: <url>
QGIS scan: passed | failed
Issues/warnings/critical: <n>/<n>/<n>
Approved: yes | no
Public latest: <version>
State: released | awaiting QGIS staff approval | blocked
```

## Gotchas

- QGIS blocked `1.1.0` for two low-severity Bandit `B110` findings. CI must not
  classify low findings as informational.
- `gh repo view` selected an unrelated upstream repository in this multi-remote
  checkout. Pass `--repo digidem/awanaGIS` or set the default explicitly.
- The branding test scans tracked documentation too. Keep retired upstream
  product and repository names out of new runbooks.
- `gh api -f 'environment_ids[]=...'` sends strings and fails validation. Use
  `--input -` with a JSON number.
- `agent-browser`'s bundled Chrome does not inherit Brave authentication. Reuse a
  short-lived Brave profile copy or attach to Brave's CDP port.
- A 120-second background browser timeout kills Brave and can leave child
  processes. Use a long timeout, track parent and child PIDs, and verify cleanup.
- The QGIS public JSON can continue to show an older latest version while a newer
  scanned version awaits approval. Do not call that a security rejection.

## What didn't work

- Allowing low-severity Bandit findings to pass CI: this shipped the exact `B110`
  blockers that QGIS rejected.
- Reviewing only source-tree scans: the release gate must scan the extracted ZIP
  that will actually be uploaded.
- Using a fresh Chrome profile for QGIS: it had no authenticated session.
- Uploading a duplicate version to “fix” pending approval: `1.1.1` already passed
  scanning and only needed staff approval.
- Leaving a copied Brave profile behind: it contains usable session cookies and
  must be removed after the upload.
