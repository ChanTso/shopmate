# ShopMate product showcase

A standalone static product site. It presents actual Android, iOS and merchant-workspace screens. It never connects to the retail API or a model provider. The single GitHub link leads to this repository; client build and runtime instructions remain in their existing READMEs.

Preview from the repository root:

```sh
python3 -m http.server 4173 --bind 127.0.0.1 --directory site
```

The buyer device changes screenshots as the page scrolls and cycles when idle. The pause control and reduced-motion preference stop automatic animation. Images are compressed WebP; there is no external font service, player, analytics, cookie banner or client framework dependency.

`assets/IMAGE-CREDITS.md` preserves the source notices for category photography. Other screenshots were captured from the local demo application, using fictional retail data. Android/merchant captures are from the preceding verified client delivery; iOS recommendation/refund captures are from the native completion work on 2026-09-11. Screenshots are not frame-rate or production-capacity evidence.

GitHub Pages should publish only this directory. The Pages workflow is prepared separately from application CI. Enabling Pages or publishing the pending branch is a remote release action; local preview is available independently.
