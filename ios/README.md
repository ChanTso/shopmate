# ShopMate buyer iOS

SwiftUI buyer client sharing the Kotlin Multiplatform `BuyerCore` with Android. The native buyer experience includes product search and variants, contextual consultation and structured cards, cart editing, reviewed checkout and simulated payment, orders and refunds, original-command recovery, seckill reservations, profile, policies and editable memory. Business interfaces and shared recovery rules match Android; presentation stays native.

## Build on Apple Silicon

Install Xcode, JDK 21 and XcodeGen. Set `JAVA_HOME` to JDK 21, start the existing ShopMate API, then:

```sh
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/ShopMate.xcodeproj -scheme ShopMate -configuration Debug -destination 'generic/platform=iOS Simulator' build
```

The pre-build phase compiles the matching Kotlin/Native framework. This project targets ARM64 simulator and device architectures. Open the generated `ios/ShopMate.xcodeproj` to choose an iPhone simulator and run. The local API defaults to `http://localhost:8101`; remote origins require HTTPS. Use the existing private demo credentials. Normal simulator ad-hoc signing is needed for Keychain; `CODE_SIGNING_ALLOWED=NO` is only for compile-only checks. For a physical iPhone, choose your personal signing team. Debug builds also accept a Mac Bonjour hostname such as `http://your-mac.local:8101`, with Commerce on port 9082; configure both origins and expose the local development services only to your trusted LAN. Release builds require HTTPS outside loopback. Free personal signing needs periodic reinstall; a simulator build is not a physical-device acceptance result.

Run `BuyerTests` on an iPhone simulator with the ShopMate scheme. Tests exercise actual Swift/Kotlin stream interoperability, truncated-stream handling, endpoint policy, and Keychain/pending-intent isolation.

## Shared and native responsibilities

- KMP owns SSE frame decoding, message/card reduction, validation of server-assigned message IDs and history-page merging, exact checkout payloads and original-write recovery policy. Swift's byte-to-line adapter preserves empty lines (Foundation's convenience line sequence removes them); it does not implement a second SSE parser.
- SwiftUI owns presentation; a small UIKit bridge preserves a visible message ID and its pixel offset when older rows are inserted or the conversation reappears. Prefix insertion waits for an active drag or deceleration to finish, while live events continue. Native history requests retain their account, conversation and cursor ownership while older pages merge alongside a live reply. Conversation updates are separate from shopping state. URLSession owns native cancellation; Keychain stores the bearer and a scoped atomic file preserves pending intents before sending.
- Immutable shared message segments form SwiftUI equality boundaries. Text deltas retain existing card instances; partial/final or same-slot content replacements invalidate the segment. Native card controls still observe shopping state.
- Catalog requests do not wait for cart/order refresh. Pagination belongs to the submitted query, not the current search draft; a replaced or dismissed detail request is cancelled.
- The model is remote. The phone contains no model, service or payment-signing credentials. The shopping and checkout endpoints use the same backend as Android.
- Unknown writes retain the original key/body. Explicit retry replays that intent; payment retries use the original checkout. Stopping generation does not undo committed business actions. Restart restores saved history, not an event-offset stream or a background model job.
- Existing Java performance measurements remain server-only evidence. Simulator recordings demonstrate interaction; they are not physical-device frame-rate measurements. Explicitly rejected reservations remain in history but permit a newly confirmed attempt with the current activity version.

The [history protocol](../docs/BUYER.md#paged-conversation-history) documents the initial recent page, exclusive `before` cursor and `turn_started` IDs. Older pages use the pure-read messages endpoint; the full-session recovery API remains available.

## Native streaming replay

The separate `StreamingReplay` scheme uses Release Swift and Kotlin/Native frameworks, without debugger or coverage. Its text-only render workload has 60 history messages and 240 four-character deltas at 50 ms intervals. The mixed-card workload passes 60 history messages, 240 deltas, partial/final product and comparison events through URLSession's byte consumer and the shared reducer in four modes:

| Delivery | Following the reply | Reading history |
|---|---|---|
| Paced: one frame every 20 ms | `testMixedCardsThroughNativeTransport` | `testMixedCardsWhileReadingHistory` |
| Burst: up to eight frames per delivery, retaining the 20 ms budget per frame | `testMixedCardsBurstThroughNativeTransport` | `testMixedCardsBurstWhileReadingHistory` |

History mode starts with following disabled; it does not simulate a touch gesture. The burst case changes delivery grouping, not the payload or nominal stream duration.

```sh
xcodebuild -project ios/ShopMate.xcodeproj -scheme StreamingReplay \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  ENABLE_TESTABILITY=YES \
  -only-testing:StreamingReplayTests/MixedStreamingReplayTests \
  -resultBundlePath mixed-stream.xcresult test
```

`ENABLE_TESTABILITY` permits the test target to access app internals; optimization stays enabled. XCTest discards a warm-up iteration and records three measured iterations, with clock, process CPU, memory and card-decoding signposts. Separate signposts identify history restoration, stream consumption and final-frame capture; attachments record mode, frame/byte counts, thermal state and Low Power Mode. The mixed fixture uses URLProtocol, so it exercises native byte handling and rendering without TCP/TLS, a model or a business service. The measured block includes history restoration, stream consumption, UI work, completion polling and final-frame capture. Fixed frame delays dominate elapsed time; it is not a throughput or frame-rate test.

Save the full source revision, clean-tree status, device or simulator/runtime, build configuration and exact command with the unmodified result bundle. Compare the same workload and configuration. A physical-device Time Profiler trace can locate sampled CPU work; neither it nor these XCTest metrics measures display FPS. Simulator CPU and memory do not establish physical-device frame pacing or model latency. Correctness tests remain in the ShopMate scheme.

## History touch tests

The `BuyerInteraction` scheme runs Debug UI tests through native scrolling, typing and buttons:

```sh
xcodebuild -project ios/ShopMate.xcodeproj -scheme BuyerInteraction \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -resultBundlePath history-interaction.xcresult test
```

For a signed physical build, use `-destination 'platform=iOS,id=YOUR_DEVICE_UDID'` and the signing team configured above. These tests exercise older-page failure/retry, paging while a reply streams, returning to the latest reply, retaining a draft when stopping, a page arriving while another tab is visible, and moving to a new reading position while a page is pending. They compare the same partially visible message's frame before and after pagination, with a 2-point tolerance, and retain screenshots and coordinates in the result bundle. This is interaction acceptance, not a performance benchmark or a statement that a particular device has passed.

The test launch argument `--history-interaction-test` selects a Debug-only, in-process URLProtocol fixture: 70 variable-height saved messages, recent pages of 30, delayed older responses and one interruptible mixed text/card reply, paced to leave time for touch gestures. The failure test adds `--history-page-failure-once`; the pending-page gesture test adds `--history-page-wait-for-drag` to lengthen that response delay. Each app launch resets the fixture, saves no credentials and contacts no real model or business service. Ordinary launches and Release builds keep the normal application path.
