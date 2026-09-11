# ShopMate product showcase

A standalone static product site for the native buyer applications and merchant workspace. It does not connect to the retail API or a model provider. The single GitHub link leads to this repository; build and runtime instructions remain in the application READMEs.

Preview from the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory site
```

## Presentation

One sticky device moves from the introduction into three buyer chapters and then expands into the native iPad two-pane layout. Scroll position continuously moves the buyer text and interpolates chapter-number size, emphasis and progress; reduced motion uses discrete chapter states. Scroll position selects the chapter; its screen continues playing while the visitor stops scrolling. The merchant section uses crisp HTML/SVG scenes with animated analysis and approval steps. There is no external font service, analytics, player UI or framework dependency.

All four buyer clips use actual iOS Simulator application frames from the local demo on 2026-09-11. They show real model recommendations, checkout and mock-payment confirmations, persisted memory editing, and iPad shopping alongside chat. The clips are muted, inline H.264, with WebP posters. Inactive/offscreen clips pause. Both pause controls and the reduced-motion preference stop automatic playback.

These are edited product demonstrations, not latency or frame-rate evidence: idle waits are shortened and some completed frames are held. The phone and wide-screen input animations reverse and retimes a recording of native per-character deletion, producing a readable typing sequence without replacing the native screen. The following request, streamed response and final state come from the actual application.

The merchant walkthrough is a DOM/SVG reconstruction of the workspace's existing analysis, proposal and approval interactions, using illustrative fixture values. Its animated totals and timing are presentation data, not a live business report or performance result. It does not submit approvals.

## Media edits

Local raw recordings remain in ignored `.run/site-media/`. Buyer clips use these ranges (seconds on their respective source timelines):

- Discover: native input `0–19.5` reversed at 5× speed; conversation `20–21.5`, `37–38.5`, `40.5–47.5`; final screenshot held for 3 seconds.
- Confirm: `6.2–9.5`, `12.1–13.7`, `22.9–27.2`, `42.6–46.1`, `260.2–262.3`, `264.6–266.1`, `270.65–270.75`; final paid frame held for 3 seconds.
- Memory: `memory-chat-input-raw.mp4` ranges `25–34` then `4–13`, each reversed at 4×, show native assistant input. `memory-chat-flow-raw.mp4` ranges `12–16` retimed to 32.5% and `39–43.5` show the actual request and remembered-preference response. `memory-raw.mp4` ranges `0–8`, `19–29`, `37–42` continue the same preference scenario into My, viewing, editing and reloading the saved preference.
- Wide: `wide-typing-raw.mp4` range `65–100` reversed at 8× for input; `wide-raw.mp4` ranges `70–78` retimed to 14%, `78–93` for the actual request and response. Both are rotated into the simulator's landscape display orientation.

`assets/IMAGE-CREDITS.md` records image provenance. The demo identity and retail records are fictional. No credentials or runtime databases are included.

GitHub Pages publishes only this directory through the Pages workflow. Local preview is independent of remote publication.

The curved S mark is maintained as a local SVG in `assets/logo.svg`; the favicon uses the same geometry. Merchant scenes share a fixed viewport, while their internal animations use an independent paused/offscreen-aware clock.

Chapter numbers and names share a serif family and a fixed text baseline; each progress track fills within its own chapter column. Settled buyer chapters occupy roughly 1.85–2.5 viewport heights of scrolling, with separate position-driven transitions. On wide-screen expansion, labels move beside their numerals, and navigation and description form a compact top band above the enlarged device. Merchant chapters use the same horizontal pairing above a fixed-size workspace. Chapter buttons position the page immediately, without a playback wait or timed transition. Header and introductory anchor transitions retain the interruptible 1.25–1.7-second entrance; ordinary wheel scrolling remains native. The merchant growth animation uses a 2.4-second ease-out cubic curve on the animation frame clock.
