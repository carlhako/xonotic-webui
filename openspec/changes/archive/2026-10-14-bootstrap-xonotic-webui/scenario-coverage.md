# Scenario coverage (task 10.5)

Walk of every `#### Scenario:` in the five specs of `bootstrap-xonotic-webui` against the
tests that exercise it.

## Run record

| Check | Result |
| --- | --- |
| `.venv/bin/pytest -q` | 403 passed, 0 skipped, 0 failed (includes the network-dependent `test_install_needs_no_node_and_no_compiler` and the user-namespace `test_layout_is_enforced_for_real_in_a_user_namespace`, neither skipped on this host). The 403 predates the one test added in this pass. |
| `.venv/bin/pytest tests/test_installer.py -q` after adding one test | 29 passed |
| `npm --prefix web test` | 9 files, 91 tests passed |
| `openspec validate bootstrap-xonotic-webui --strict` | `Change 'bootstrap-xonotic-webui' is valid` |

Test path prefixes: `tests/` is pytest, `web/src/test/` is Vitest. Pytest ids are written
`file::test`.

Status key:

- **exercised**: an automated test drives the behaviour and asserts the scenario's outcome.
- **exercised on LXC**: the outcome needs a clean Debian 13 machine and was observed there in
  the real-host run recorded below (tasks 10.1 / 10.4).
- **exercised manually**: no automated test; observed by hand and recorded below or in a ticked
  manual task.
- **NOT exercised**: nothing covers it.

## Totals

| Status | Count |
| --- | --- |
| exercised (automated) | 71 |
| exercised on the clean LXC (10.1 / 10.4) | 7 |
| exercised manually (8.8, phone width) | 1 |
| NOT exercised | 0 |
| **Total** | **79** |

The lifecycle, console and status scenarios are exercised against the fake dedicated server
(`tests/fake_xonotic/server.py`, behaviour driven by real captures from the spike). Tasks 10.2
and 10.3 (ticked) record the same behaviours being checked once against the real server.

## server-lifecycle (21)

| Scenario | Covered by | Status |
| --- | --- | --- |
| Initial state | `test_supervisor::test_initial_state_is_stopped`, `test_state_machine::test_initial_state_is_stopped` | exercised |
| Start requested | `test_supervisor::test_start_reaches_running_and_launches_as_designed` (states `[starting, running]`), `test_requests_during_a_start_are_rejected` (still `starting` until ready) | exercised |
| Stop requested | `test_supervisor::test_stop_is_graceful_and_not_a_crash` (`[stopping, stopped]`) | exercised |
| Normal start | `test_supervisor::test_start_reaches_running_and_launches_as_designed` (port, userdir, `serverconfig`, cwd, wrapper config read from the data dir) | exercised |
| Game files missing | `test_supervisor::test_start_requires_an_installation`, `test_api::test_game_not_installed_is_503` | exercised |
| Server becomes ready | `test_supervisor::test_start_reaches_running_and_launches_as_designed`, `test_readiness_falls_back_to_a_status_reply` | exercised |
| Server never becomes ready | `test_supervisor::test_never_ready_is_a_failed_start`, `test_api::test_readiness_timeout_is_504` | exercised |
| Process exits during startup | `test_supervisor::test_exit_during_startup_is_a_failed_start`, `test_api::test_startup_failures_are_reported_with_the_reason` | exercised |
| Server exits on request | `test_supervisor::test_stop_is_graceful_and_not_a_crash` (no `last_crash`) | exercised |
| Server ignores the quit request | `test_supervisor::test_stop_escalates_when_quit_is_ignored`, `test_stop_kills_a_server_that_ignores_everything` | exercised |
| Restart a running server | `test_supervisor::test_restart_running_server_is_one_operation` (`stopping, stopped, starting, running`) | exercised |
| Restart a stopped server | `test_supervisor::test_restart_stopped_server_starts_it` | exercised |
| Start while running | `test_supervisor::test_start_while_running_is_rejected_and_undisturbed`, `test_api::test_rejections_carry_precise_codes` | exercised |
| Stop while stopped | `test_supervisor::test_stop_while_stopped_is_rejected`, `test_api::test_rejections_carry_precise_codes` | exercised |
| Request during a transition | `test_supervisor::test_requests_during_a_start_are_rejected`, `test_requests_during_a_stop_are_rejected`, `test_api::test_transition_in_progress_is_a_409` | exercised |
| Single crash | `test_supervisor::test_single_crash_restarts_and_is_recorded` (time and exit status 139); task 10.3 kill -9 | exercised |
| Crash loop | `test_supervisor::test_crash_loop_is_abandoned`, `test_status::test_restart_abandoned_and_last_crash_are_visible`; task 10.3 | exercised |
| Restart limiting disabled | `test_supervisor::test_restart_limiting_disabled_does_not_restart` | exercised |
| Panel restarts with the server meant to be running | `test_supervisor::test_restore_starts_a_server_that_was_running`, `test_process_shutdown::test_panel_restores_a_server_that_was_running` (real panel process) | exercised |
| Server was deliberately stopped | `test_supervisor::test_restore_leaves_a_deliberately_stopped_server_stopped` | exercised |
| Service stop | `test_supervisor::test_panel_shutdown_leaves_no_orphan`, `test_process_shutdown::test_sigterm_stops_the_game_server_and_leaves_no_orphan` (real SIGTERM to a real panel process, child pid gone) | exercised |

## server-status (15)

| Scenario | Covered by | Status |
| --- | --- | --- |
| Server running with a match in progress | `test_status::test_ready_reconciles_the_roster_and_confirms_the_event_log` (map), `test_matches_players_and_bots_from_a_real_session` (map, gametype, players), `test_api::test_status_stream_snapshot_then_live_changes` (state, map, gametype, player over HTTP) | exercised |
| Server stopped | `test_status::test_stopped_server_has_no_map_gametype_or_players` | exercised |
| Client connects | `test_status::test_stream_sends_the_snapshot_on_connect_then_every_change`, `test_api::test_status_stream_snapshot_then_live_changes` | exercised |
| A player joins | `test_status::test_every_connected_client_gets_updates`, `test_api::test_status_stream_snapshot_then_live_changes` | exercised |
| State changes | `test_status::test_stream_sends_the_snapshot_on_connect_then_every_change` (starting then running) | exercised |
| Humans and bots connected | `test_status::test_three_humans_and_two_bots_are_counted_separately` | exercised |
| Player leaves | `test_status::test_player_leaves_and_name_changes`, `test_rename_part_and_next_match_from_a_real_session` | exercised |
| Name changes | `test_status::test_player_leaves_and_name_changes`, `test_rename_part_and_next_match_from_a_real_session` | exercised |
| Map change | `test_status::test_rename_part_and_next_match_from_a_real_session` (atelier to boil) | exercised |
| Not yet known | `test_status::test_unknown_map_and_gametype_are_not_guessed`, `web/src/test/dashboard.test.tsx` "does not guess an unknown map or gametype". Caveat: the backend test uses a tracker that has seen no match start, not a supervisor in `running`; the fake server cannot reach "running but no gamestart" because readiness waits for the map load | exercised |
| Server crashes with players connected | `test_status::test_crash_with_players_connected_clears_them_and_records_the_crash` | exercised |
| Restart abandoned | `test_status::test_restart_abandoned_and_last_crash_are_visible`; `web/src/test/dashboard.test.tsx` "shows the last crash and an abandoned restart" | exercised |
| No crashes | `test_status::test_stopped_server_has_no_map_gametype_or_players` (`last_crash is None` after a requested stop), `test_supervisor::test_initial_state_is_stopped` | exercised |
| Server stopped (health) | `test_api::test_health_reports_version_while_the_game_server_is_stopped` | exercised |
| Panel not serving | A refused connection is the failure by construction. The consumers of the check are covered: `test_installer::test_bad_release_restores_the_previous_version_and_exits_nonzero`, `test_fresh_install_that_does_not_answer_fails` (curl shim exits 7) | exercised |

## server-console (11)

| Scenario | Covered by | Status |
| --- | --- | --- |
| Output appears as produced | `test_console::test_output_is_streamed_in_order_to_every_client`, `test_api::test_end_to_end_start_see_output_send_command_stop` (SSE, no polling) | exercised |
| Multiple clients | `test_console::test_output_is_streamed_in_order_to_every_client` | exercised |
| Client connects mid-session | `test_console::test_connect_mid_session_replays_history_then_live_without_duplicates`; `web/src/test/console.test.tsx` "does not duplicate lines when a reconnect replays history" | exercised |
| Buffer is bounded | `test_console::test_buffer_is_bounded_and_discards_oldest_first` | exercised |
| Server restarted | `test_supervisor::test_run_boundary_marker_and_history_survive_restart`; `web/src/test/console.test.tsx` "marks where each server run begins" | exercised |
| Command submitted while running | `test_console::test_command_is_delivered_and_its_output_streamed`, `test_api::test_end_to_end_start_see_output_send_command_stop` | exercised |
| Command submitted while stopped | `test_console::test_command_while_stopped_is_rejected_and_not_queued`, `test_api::test_command_validation_and_state` | exercised |
| Multi-line input | `test_console::test_empty_or_multiline_command_is_rejected_and_nothing_is_sent` (parametrised; buffer sequence unchanged), `test_api::test_command_validation_and_state` | exercised |
| Empty input | same tests as above (`""`, `"   "`, `"\t"`) | exercised |
| Coloured player name | `web/src/test/console.test.tsx` "renders colour codes as colour and never shows the code characters", `web/src/test/colors.test.ts`; task 10.2 | exercised |
| Escaped caret | `web/src/test/colors.test.ts` "shows a literal caret for an escaped caret", `web/src/test/console.test.tsx` (`Pl:ay^^er` renders `Pl:ay^er`) | exercised |

## web-ui-shell (15)

| Scenario | Covered by | Status |
| --- | --- | --- |
| Open the root | `test_api::test_root_and_deep_links_serve_the_application`; `test_release::test_wheel_carries_the_prebuilt_interface_and_no_source` (the real bundle ships in the wheel) | exercised |
| Reload a deep link | `test_api::test_root_and_deep_links_serve_the_application`; `web/src/test/shell.test.tsx` "opens a deep link straight to its section" | exercised |
| API paths are not shadowed | `test_api::test_api_paths_are_not_shadowed_by_the_application` | exercised |
| Switch section | `web/src/test/shell.test.tsx` "highlights the current section and switches without a reload" | exercised |
| Initial sections | `web/src/test/shell.test.tsx` "names the application and lists every section" (Dashboard, Maps, Settings, Console; includes the two required) | exercised |
| Server stopped | `web/src/test/dashboard.test.tsx` "stopped: start is enabled, stop and restart are not" | exercised |
| Server running | `web/src/test/dashboard.test.tsx` "running: stop and restart are enabled, start is not" | exercised |
| Transition in progress | `web/src/test/dashboard.test.tsx` "%s: every control is disabled and the transition is shown" (starting, stopping) | exercised |
| Operation fails | `web/src/test/dashboard.test.tsx` "reports a rejected operation with the error returned" | exercised |
| Stop with players | `web/src/test/dashboard.test.tsx` "asks first when humans are connected, stating how many, and acts only on confirm", "cancelling leaves the server alone" | exercised |
| Stop with nobody connected | `web/src/test/dashboard.test.tsx` "proceeds without a confirmation when no humans are connected" | exercised |
| Panel restarts | `web/src/test/connection.test.tsx` "shows a banner while unreachable and clears it, with fresh state, on reconnect" (fake EventSource) | exercised |
| Stale data is not presented as current | `web/src/test/connection.test.tsx` "disables controls that change the server until reconnection"; `console.test.tsx` "disables input while disconnected" | exercised |
| Timestamp display | `web/src/test/time.test.ts` "formats in the browser's local timezone, not a server one" | exercised |
| Phone width | No automated test: jsdom has no layout, so 375px behaviour cannot be asserted in Vitest. Task 8.8 is ticked and records a manual screenshot check; CSS carries a `max-width: 520px` rule and `overflow-x: hidden` guards. No screenshot is stored in the repo to point at | exercised manually (8.8, 10.x) |

## installation (17)

All installer tests run the real `deploy/install.sh` (whole script or its sourced functions)
with PATH shims for system commands; none runs as real root against a real apt system.

| Scenario | Covered by | Status |
| --- | --- | --- |
| Run as a non-root user | `test_installer::test_non_root_is_refused_and_nothing_changes` (exit non-zero, "must be run as root", empty tree, no apt call) | exercised |
| Unsupported architecture | `test_installer::test_unsupported_architecture_names_both_and_changes_nothing`, `test_non_debian_family_is_refused` | exercised |
| Insufficient disk space | `test_installer::test_insufficient_disk_space_states_required_and_available`, `test_space_check_is_skipped_once_the_game_is_installed` | exercised |
| Fresh install creates the user | `test_installer::test_layout_is_enforced_for_real_in_a_user_namespace` runs `ensure_user` with a stand-in `useradd`, so the real `--system --shell /usr/sbin/nologin` call and "panel and game server processes owned by that user" are not observed | exercised on LXC (10.1) |
| Application files are not writable by the service user | `test_installer::test_layout_is_enforced_for_real_in_a_user_namespace` (real chown and kernel permission checks as a distinct uid; sabotage is caught and repaired), `test_layout_has_root_owned_application_and_game_trees` | exercised |
| Archive matches the pinned digest | `test_installer::test_matching_local_archive_is_extracted_minimally`, `test_a_complete_cached_archive_is_not_fetched_again`. The real 0.8.6 archive is not downloaded by the suite | exercised |
| Archive does not match | `test_installer::test_digest_mismatch_fails_and_leaves_no_unverified_files`, `test_corrupt_download_is_removed_so_it_is_not_resumed_forever` | exercised |
| Offline install from a local archive | `test_installer::test_local_archive_is_used_instead_of_downloading` (added in this pass: curl shim fails any call, install still succeeds), `test_digest_mismatch_fails_and_leaves_no_unverified_files` (same digest check applies) | exercised |
| Install with no build tools present | `test_release::test_install_needs_no_node_and_no_compiler` (wheel-only venv build with node and compilers booby-trapped; ran, not skipped). "Panel starts without any build step" and "only the base system" are not shown on a clean machine | exercised on LXC (10.1) |
| Pinning a panel release | `test_installer::test_release_tag_pins_the_download` (latest vs `v0.3.0`), `test_offline_tarball_is_used_without_any_download` | exercised |
| Service enabled and started | `test_installer::test_swap_installs_the_new_version_when_it_answers` asserts `systemctl enable` is invoked and the unit is placed, with a stubbed systemctl; a real service answering on the port is not shown | exercised on LXC (10.1) |
| Panel crash | `test_installer::test_unit_is_valid_and_stop_timeout_exceeds_the_worst_case_shutdown` asserts `Restart=on-failure` statically and `systemd-analyze verify` passes; systemd actually restarting the panel is not shown | exercised on LXC (10.1) |
| Re-run on a healthy install | Pieces are covered separately: `test_existing_server_cfg_is_never_overwritten` (two re-runs, byte-identical), `test_env_file_is_seeded_once`, `test_installed_game_is_not_downloaded_again`, `test_swap_installs_the_new_version_when_it_answers`. The end-to-end re-run on a live install is task 10.4; panel state (`state.json`) being untouched is not asserted by any installer test | exercised on LXC (10.4) |
| New release does not start | `test_installer::test_bad_release_restores_the_previous_version_and_exits_nonzero` (old venv and unit restored, service started again, exit non-zero, message) | exercised |
| Fresh install has a joinable server | `test_installer::test_server_cfg_is_seeded_with_the_event_log_enabled` (valid cfg, `sv_eventlog 1`, `sv_eventlog_console 1`); the installed server actually starting from that cfg on a real install is not shown | exercised on LXC (10.1) |
| Existing configuration is kept | `test_installer::test_existing_server_cfg_is_never_overwritten` | exercised |
| Successful install | `test_installer::test_report_prints_the_web_url_and_game_port`, `test_report_honours_configured_ports`, `test_swap_installs_the_new_version_when_it_answers`. A complete script run that ends zero with a printed URL is task 10.1 | exercised on LXC (10.1) |

## Real-host run (clean Debian 13 LXC, amd64, no compiler or Node)

Host `10.0.1.147`, Debian 13 trixie, 29 GB free, no `gcc`/`cc`/`make`/`node`/`npm` and no
`build-essential`/`nodejs` packages. Release `v0.1.0` from `carlhako/xonotic-webui`.

| Step | Observed |
| --- | --- |
| `apt-get install -y curl`, then the README one-liner (`curl ... install.sh \| bash`) | exit 0; printed `http://10.0.1.147/` and `UDP 26000`; `/health` and `/` answered 200 from another host |
| user and layout | `xonotic-webui` uid 999, shell `/usr/sbin/nologin`; `/opt/xonotic-webui` and `/opt/xonotic/0.8.6` root:root 755; `/var/lib/xonotic-webui` and `userdir/data` owned by the service user; service user's `touch` denied in both `/opt` trees, allowed in state dir; no non-root-owned or group/other-writable entry under `/opt` |
| service | enabled and active, `Restart=on-failure`, panel and game server both run as `xonotic-webui` |
| `server.cfg` | seeded at `userdir/data/server.cfg` with `sv_eventlog 1` and `sv_eventlog_console 1`; `POST /api/lifecycle/start` gave `running`, `event_log: enabled`, dedicated server bound on UDP 26000 |
| panel crash | `kill -9` of the panel main PID: systemd restarted it in 4 s (`NRestarts=1`), the panel logged "restoring the previously running server" and a new dedicated server came up |
| re-run (10.4), working-tree `install.sh` over the live install after a hand edit of `server.cfg` | exit 0, log said "already installed; not downloading it again" and "keeping the existing server.cfg"; `server.cfg`, `.env` and `state.json` byte-identical; game tree identical (`find -L` size/mtime); no `dl.xonotic.org` traffic in the journal; panel pid changed and `/api/status` back to `running`. Only two files appeared: `darkplaces_history.txt` and `data/server.db`, both written by the game |
| ownership repair (9.3) | after `chmod 777 /opt/xonotic-webui`, `chown xonotic-webui` on a game `.pk3` and a root-owned file in the state dir, a re-run printed "restoring root ownership of /opt/xonotic" and "restoring ownership of /var/lib/xonotic-webui", and the three entries were back to 755 root / 644 root / service-owned |
| README `RELEASE_TAG=v0.1.0` form | exit 0, downloaded from `.../releases/download/v0.1.0` |
| README offline form (game tree moved aside; `github.com`, `dl.xonotic.org`, `pypi.org`, `files.pythonhosted.org` blackholed in `/etc/hosts`) | exit 0 with `XONOTIC_WEBUI_TARBALL`, `XONOTIC_ARCHIVE` and `XONOTIC_WEBUI_WHEELHOUSE`; log: "using local game archive", "using local release tarball"; panel answered. `pip install --upgrade pip` retried against the blocked PyPI five times and carried on, because the bundled pip was kept |
| `systemctl restart xonotic-webui`, `journalctl -u xonotic-webui` | both ran; unit active and `/health` ok afterwards |
| phone width (8.8) | `http://10.0.1.147/` at 375x812 in the browser pane: `scrollWidth` 375 = `innerWidth` 375, no horizontal overflow; dashboard and console reachable |

Caveat: the one-liner installs the **released** `v0.1.0`, which predates the uncommitted work
(Settings and Maps sections, 9.3 ownership repair, README). The deployed UI shows only the
Dashboard and Console. The working-tree `install.sh` was run from a local copy over that
install; it was exercised on a real root filesystem, but the one-liner has not yet fetched an
installer containing it.

## Gaps

- No scenario is without coverage and none is unexercised.
- The seven installation scenarios were exercised on the LXC with the released `v0.1.0`
  installer (fresh install) and the working-tree installer (re-run, ownership repair, offline).
- Known weak spots inside "exercised" rows:
  - "Not yet known" is asserted on an idle tracker, not on a running server with no match start.
  - "Panel not serving" is satisfied by construction; only the installer's reaction to an
    unanswered health check is tested.
  - The lifecycle, console and status rows rely on the fake dedicated server; the real server
    was checked in tasks 10.2 and 10.3 and, for start, restart and the crash restore, on the LXC.
  - "Panel restarts" uses a fake EventSource, not a real browser against a restarted panel.

## Conclusion

All 79 scenarios are exercised and `openspec validate --strict` passes; task 10.5 is ticked.
