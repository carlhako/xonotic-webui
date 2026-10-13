# Xonotic fixtures

Real console output captured from the unmodified Xonotic **0.8.6** dedicated server
(`xonotic-linux64-dedicated`, build 03:14:05 Jun 20 2023), not hand-written. Humans were a
real `xonotic-linux64-sdl` client run headless (`SDL_VIDEODRIVER=offscreen`,
`LIBGL_ALWAYS_SOFTWARE=1`); bots came from `bot_number N`.

The server was launched as the supervisor launches it:

    xonotic-linux64-dedicated -userdir <dir> +port <p> +sys_colortranslation 2 \
        +serverconfig xonotic-webui.cfg

where `xonotic-webui.cfg` is `exec server.cfg` followed by the event-log cvars (see design.md
D3). Each line is exactly as the server printed it (including the leading `^7`).

| file | what it is |
| --- | --- |
| `startup.txt` | process start through the first `:gamestart:` / `:gameinfo:end` |
| `status_premap.txt` | `status` reply while the server is still in `_init/_init` (not ready) |
| `status1_empty.txt` | `status 1` with no players |
| `status1_one_human.txt` | `status 1` with one human whose name has colour codes |
| `status1_humans_bots_v6.txt` | `status 1` with two humans (one over IPv6) and a bot |
| `status_two_line_humans_bots.txt` | plain `status` (two lines per player, names truncated) |
| `match_end_next_map.txt` | `:scores` / `:gameover` then the next `:gamestart` |
| `session_humans_only.txt` | whole run: join, rename, part, no bots |
| `session_humans_bots_v6.txt` | whole run: two humans (IPv4 and IPv6), a bot, rename, parts, match end |
| `session_ansi_translated.txt` | whole run with the engine's default ANSI colour translation (`sys_colortranslation` not set) |
