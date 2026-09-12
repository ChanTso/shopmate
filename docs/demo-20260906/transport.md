# SSE transport verification through the frontend proxy

CityBuddy: `69be167a3df030bf45795c49f444d6e7c24d0423`.<br>
ShopMate before: `02d1bf0d0d1e4f5d71925f7db92ed3c4d9726b28`.<br>
ShopMate after: `ac6b1404e17a007b8c5563449872c69c520787a0`.<br>
Verified on 2026-09-06 UTC, on the same local host, through the Next production frontend at 3100 → Python API at 8101, using real `gpt-5.6-terra`.

During the real browser demo, tool progress did not appear promptly before the streaming turn completed. Investigation traced the frontend proxy path to Next's default compression: it compressed `text/event-stream`, while the upstream response supplied only `Cache-Control: no-cache`. Using the existing local operator account through the actual Next entry point, each run created a separate conversation and sent the same read-only prompt, retained verbatim: “用一句话说明你能做什么，不需要查询业务数据。” The request accepted gzip; allowlisted response headers and decoded raw data chunks were saved.

| Check | Before | After |
| --- | --- | --- |
| `Content-Encoding` | `gzip` | Absent |
| `Cache-Control` | `no-cache` | `no-cache, no-transform` |
| Decoded chunks received by the client | 1, containing the whole turn and terminal event | 40, with 39 before the terminal event |

Only `no-transform` was added to SSE responses, preventing the proxy from buffering events in a compressed stream. Other page compression, model protocol, prompts, and call budget were unchanged. The existing completed-stream test gained a response-header assertion; the full Python checks passed 517 tests with 1 existing optional-SDK module skipped. The real page subsequently showed `analysis: step 2 — running a query` before the turn ended; see `streaming-progress.png`.

This establishes that the identified compression-buffering path was removed. Chunk counts vary with model text and network segmentation; they are not throughput or model-speed metrics. The two outputs and model durations need not match, and no latency improvement was calculated from them. Not all waiting in the earliest page observation can be attributed to compression. This record is separate from the 90-attempt complete business acceptance and 24-attempt targeted regression.

The two original transport files, `sse-transport-before.jsonl` and `sse-transport-after.jsonl`, are inside this directory's archive. Credentials and request authorization headers were not saved.
