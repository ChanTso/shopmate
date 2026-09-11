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

- KMP owns SSE frame decoding, message/card reduction, exact checkout payloads and original-write recovery policy. Swift's byte-to-line adapter preserves empty lines (Foundation's convenience line sequence removes them); it does not implement a second SSE parser.
- SwiftUI owns presentation. Conversation updates are separate from shopping state. URLSession owns native cancellation; Keychain stores the bearer and a scoped atomic file preserves pending intents before sending.
- The model is remote. The phone contains no model, service or payment-signing credentials. The shopping and checkout endpoints use the same backend as Android.
- Unknown writes retain the original key/body. Explicit retry replays that intent; payment retries use the original checkout. Stopping generation does not undo committed business actions. Restart restores saved history, not an event-offset stream or a background model job.
- Existing Java performance measurements remain server-only evidence. Simulator recordings demonstrate interaction; they are not physical-device frame-rate measurements. Explicitly rejected reservations remain in history but permit a newly confirmed attempt with the current activity version.

## Native streaming replay

The separate `StreamingReplay` scheme hosts the real SwiftUI conversation with 60 history messages and 240 four-character deltas at 50 ms intervals. Run it on a simulator when comparing render changes:

```sh
xcodebuild -project ios/ShopMate.xcodeproj -scheme StreamingReplay -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test
```

XCTest records three iterations of elapsed time, process CPU time, memory and a rendered frame attachment. Keep the source revision, device/runtime and workload with any saved result. This is a render-layer baseline, not model latency, frame pacing or physical-device capacity. It runs separately from correctness tests because simulator load affects performance measurements.
