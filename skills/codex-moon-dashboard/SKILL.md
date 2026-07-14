---
name: codex-moon-dashboard
description: Install, use, and troubleshoot the local Codex Moon Dashboard companion.
---

# Codex Moon Dashboard

This plugin provides a Windows companion process rather than a native Codex panel. Use `scripts/install.ps1` to register the monitor in the user's Startup folder.

## Behavior

- `monitor.py` watches the WindowsApps Codex desktop processes (`ChatGPT.exe` / `codex.exe`) using `psutil`, while ignoring standalone app-server processes.
- `dashboard.py` is a 390×275 movable, always-on-top Tkinter window with the supplied moon image as a complete background, a Codex Radar-style dark-blue header, a `#27384d` blue-gray body, and a manual close button.
- The moon surface is fully opaque with reduced brightness and increased detail contrast; the quota work bar uses a more visible 78% alpha, and the glass uses the Codex Radar dark-blue header with a `#27384d` blue-gray body.
- The title is compact, there is no `TOKEN OBSERVER` subtitle, and the sync state sits near the right-side controls.
- The top gear opens a live slider panel for interface/background RGB and alpha plus moon alpha and contrast; values persist in `%USERPROFILE%/.codex/codex-moon-dashboard-settings.json`.
- The top collapse control hides detail cards and leaves a compact one-line capsule with time, working/synced state, quota percentage, and current-session token usage; clicking it again restores the full dashboard.
- The moon surface is fully opaque with reduced brightness, the quota work bar uses 78% alpha, and the remaining dashboard glass surfaces keep the 20% treatment.
- The dashboard closes when all Codex desktop processes exit.
- A manual close suppresses reopening for the current Codex lifecycle only.
- Local token usage is read-only from `%USERPROFILE%/.codex/state_5.sqlite` and the newest rollout metadata.
- The UI intentionally does not show a 5-hour quota or weather effect.
- The reset card shows the rolling quota's automatic reset time from `rate_limits.resets_at` above the nearest future manual-reset `expires_at`; use `available_count` for the manual reset count and never derive that count from `rate_limits.resets_at`.
- Recent 7-day usage, total consumed tokens, plus current-lifecycle token usage, are shown as one compact numeric row; do not reintroduce a token bar chart.
- Quota color represents remaining quota: it is vivid when remaining quota is high and fades toward gray as quota is consumed.
- Do not use the previous deep-blue flame effect; the working state may show an occasional shooting-star trail, while the idle state may show subtle twinkling star points.
- Shooting stars must only animate while Codex is working, traverse the full dashboard from edge to edge, and use the 40 FPS timer.
- Idle star points should fade in around the moon as a 12-point cyclic field, with approximately 3–8 points visible or pulsing at once, at the same smooth frame rate.
- Moon phases use the 33 pre-rendered frames under `assets/moon-phases/` with soft adjacent-frame blending; do not restore a hard runtime terminator mask or crop-based phase change.
- Keep text directly over the glass background; do not add opaque black label backgrounds.

## Safe maintenance

Do not edit Codex databases. If usage reads as `0`, check that `%USERPROFILE%/.codex/state_5.sqlite` exists and that the Python environment has `Pillow` and `psutil` installed. The dashboard stays alive when the database is temporarily locked. If the account summary endpoint is unavailable, show `--` for manual reset data rather than displaying an inferred value.
