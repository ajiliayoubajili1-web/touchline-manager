"""Game logic systems (no UI, no I/O).

Each system owns one part of the game's behaviour - squad selection,
match simulation (Phase 3), transfers (Phase 4), development (Phase 5),
AI world (Phase 6), news (Phase 7). New systems plug in without touching
the core models or the UI.
"""