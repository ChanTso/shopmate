import XCTest

final class HistoryInteractionTests: XCTestCase {
    private var app: XCUIApplication!
    private var history: XCUIElement { app.scrollViews["chat-history"].firstMatch }

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--history-interaction-test"]
    }

    override func tearDownWithError() throws { app.terminate() }

    func testEarlierPageFailureAndRetryKeepPartialMessagePosition() throws {
        app.launchArguments.append("--history-page-failure-once")
        app.launch()
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        try revealEarlierControl()
        let anchor = try partialMessage()
        let original = anchor.frame.minY
        capture("01 Before failed older-page request", anchor: anchor, reference: original)

        try tapHistoryControl("chat-history-earlier")
        waitForPageLoading()
        capture("01a Older-page request started", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "The coordinate tap itself must not scroll the history.")
        XCTAssertTrue(app.buttons["chat-history-retry"].waitForExistence(timeout: 8))
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "The retry header must not move the message.")
        capture("02 Older-page failure", anchor: anchor, reference: original)

        try tapHistoryControl("chat-history-retry")
        waitForPageLoading()
        capture("02a Retry request started", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "The coordinate tap itself must not scroll the history.")
        waitForPageCompletion()
        XCTAssertTrue(anchor.exists)
        capture("03 Older-page retry completed", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "Prepending older rows must preserve the partial message position.")

        try revealEarlierControl()
        XCTAssertTrue(message(11).exists, "The successful retry should expose the preceding page when scrolled to its beginning.")
    }

    func testStreamingOlderPageAndReturnToLatestKeepDraftAndStop() throws {
        app.launch()
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        let input = app.descendants(matching: .any)["chat-input"].firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText("Help me choose a coffee maker.")
        app.buttons["chat-send"].tap()
        XCTAssertTrue(app.buttons["停止生成"].waitForExistence(timeout: 5))
        let replyText = message(72).staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "先从日常")).firstMatch
        XCTAssertTrue(replyText.waitForExistence(timeout: 8))
        let firstText = replyText.label
        // Sample the fixed reply before touch scrolling moves it offscreen.
        if app.keyboards.firstMatch.exists {
            let start = history.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.92))
            let bottom = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.94))
            start.press(forDuration: 0.1, thenDragTo: bottom)
        }
        let keyboardState = XCTAttachment(screenshot: app.screenshot())
        keyboardState.name = "Keyboard after interactive downward drag"
        keyboardState.lifetime = .keepAlways
        add(keyboardState)
        wait(until: { !self.app.keyboards.firstMatch.exists }, timeout: 5)

        try revealEarlierControl()
        XCTAssertTrue(app.buttons["停止生成"].exists, "Paging must occur while the reply is still being delivered.")
        let anchor = try partialMessage()
        let original = anchor.frame.minY
        capture("04 Reading history during generation", anchor: anchor, reference: original)
        try tapHistoryControl("chat-history-earlier")
        capture("04a After tapping earlier during generation", anchor: anchor, reference: original)
        waitForPageLoading()
        waitForPageCompletion()
        XCTAssertTrue(app.buttons["停止生成"].exists)
        capture("05 Prepended page during generation", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "Concurrent reply growth must not pull the reader toward the tail.")
        try revealEarlierControl()
        XCTAssertTrue(message(11).exists, "The older page must be applied alongside the live reply.")

        app.buttons["回到最新"].tap()
        XCTAssertTrue(replyText.waitForExistence(timeout: 5))
        XCTAssertGreaterThan(replyText.label.count, firstText.count, "The reply must continue while reading older messages.")
        XCTAssertTrue(message(72).isHittable)
        XCTAssertTrue(app.buttons["停止生成"].exists)
        input.tap()
        input.typeText("Keep this draft.")
        app.buttons["停止生成"].tap()
        wait(until: { !self.app.buttons["停止生成"].exists }, timeout: 5)
        XCTAssertEqual(input.value as? String, "Keep this draft.")
        XCTAssertTrue(app.buttons["chat-send"].isEnabled)
        add(XCTAttachment(screenshot: app.screenshot()))
    }

    func testEarlierPageArrivingInAnotherTabKeepsReadingPosition() throws {
        app.launch()
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        try revealEarlierControl()
        let anchor = try partialMessage()
        let original = anchor.frame.minY
        capture("06 Before paging and leaving the assistant", anchor: anchor, reference: original)
        let leave = app.tabBars.buttons["探索"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        try tapHistoryControl("chat-history-earlier")
        waitForPageLoading()
        capture("06a Request started before leaving", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "The coordinate tap itself must not scroll the history.")
        XCTAssertTrue(pageLoading, "Leave while the history request is still pending.")
        leave.tap()
        XCTAssertTrue(app.tabBars.buttons["探索"].isSelected)
        // The fixed response arrives after five seconds while the assistant is hidden.
        let delivery = expectation(description: "Allow the in-flight fixture response to arrive")
        DispatchQueue.main.asyncAfter(deadline: .now() + 5.5) { delivery.fulfill() }
        wait(for: [delivery], timeout: 7)
        app.tabBars.buttons["助手"].tap()
        waitForPageCompletion()
        XCTAssertTrue(anchor.exists)
        capture("07 Return after hidden prepend", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2, "A page delivered while hidden must retain the same message and visible offset.")
        try revealEarlierControl()
        XCTAssertTrue(message(11).exists, "The page delivered while hidden must remain available.")
    }

    func testMovingWhileEarlierPageIsPendingKeepsTheNewReadingPosition() throws {
        app.launchArguments.append("--history-page-wait-for-drag")
        app.launch()
        XCTAssertTrue(history.waitForExistence(timeout: 10))
        try revealEarlierControl()
        try tapHistoryControl("chat-history-earlier")
        waitForPageLoading()
        let start = history.coordinate(withNormalizedOffset: CGVector(dx: 0.55, dy: 0.7))
        start.press(forDuration: 0.1, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -180)))
        let anchor = try partialMessage()
        XCTAssertTrue(pageLoading, "The new reading position must be sampled before the older-page response arrives.")
        let original = anchor.frame.minY
        capture("08 User moved while an older page was pending", anchor: anchor, reference: original)
        XCTAssertTrue(pageLoading, "The reference screenshot must precede the older-page response.")
        // Check the preserved position after completion, then scroll to the earlier page to prove it was applied.
        wait(until: {
            !self.pageLoading && !self.app.buttons["chat-history-retry"].exists
        }, timeout: 15)
        capture("09 Earlier page preserves the user's newer position", anchor: anchor, reference: original)
        XCTAssertEqual(anchor.frame.minY, original, accuracy: 2)
        try revealEarlierControl()
        XCTAssertTrue(message(11).exists)
    }

    private func message(_ id: Int) -> XCUIElement {
        app.otherElements["chat-message-\(id)"].firstMatch
    }

    private func revealEarlierControl() throws {
        for _ in 0..<24 {
            let (nodes, viewport) = try visibleHistorySnapshot()
            if let control = nodes.first(where: { $0.elementType == .button && $0.identifier == "chat-history-earlier" }),
               viewport.insetBy(dx: 1, dy: 1).contains(control.frame), !control.frame.isEmpty { return }
            history.swipeDown(velocity: .fast)
        }
        add(XCTAttachment(string: app.debugDescription))
        throw failure("The earlier-page button never became fully visible below the navigation bar.")
    }

    private func snapshots(_ root: XCUIElementSnapshot) -> [XCUIElementSnapshot] {
        [root] + root.children.flatMap { snapshots($0) }
    }

    private func visibleHistorySnapshot() throws -> ([XCUIElementSnapshot], CGRect) {
        let root = try app.snapshot()
        let nodes = snapshots(root)
        guard let scroll = nodes.first(where: { $0.elementType == .scrollView && $0.identifier == "chat-history" }) else {
            throw failure("The visible assistant scroll view is missing from the accessibility snapshot.")
        }
        var viewport = scroll.frame.intersection(root.frame)
        for bar in nodes where bar.elementType == .navigationBar && bar.frame.intersects(viewport) {
            let top = min(viewport.maxY, max(viewport.minY, bar.frame.maxY))
            viewport = CGRect(x: viewport.minX, y: top, width: viewport.width, height: viewport.maxY - top)
        }
        for element in nodes where element.identifier == "chat-input" || element.elementType == .tabBar || element.elementType == .keyboard {
            if element.frame.intersects(viewport), element.frame.minY > viewport.minY {
                viewport.size.height = element.frame.minY - viewport.minY
            }
        }
        guard viewport.height > 100 else { throw failure("The unobscured history viewport is too small for this interaction.") }
        return (nodes, viewport)
    }

    private func partial(_ frame: CGRect, in viewport: CGRect) -> Bool {
        frame.width > 100 && frame.height > 60 && frame.intersects(viewport)
            && ((frame.minY < viewport.minY - 2 && frame.maxY > viewport.minY + 20)
                || (frame.maxY > viewport.maxY + 2 && frame.minY < viewport.maxY - 20))
    }

    private func partialMessage() throws -> XCUIElement {
        for attempt in 0..<3 {
            let (nodes, viewport) = try visibleHistorySnapshot()
            let candidates = nodes.filter { $0.elementType == .other && $0.identifier.hasPrefix("chat-message-") && partial($0.frame, in: viewport) }
            for candidate in candidates {
                // Identifier and frame originate from one immutable snapshot, never a changing query index.
                let identifier = candidate.identifier
                guard nodes.filter({ $0.elementType == .other && $0.identifier == identifier }).count == 1 else {
                    throw failure("Duplicate message containers for \(identifier).")
                }
                let element = app.otherElements[identifier].firstMatch
                let first = try element.snapshot()
                let second = try element.snapshot()
                if first.identifier == identifier, second.identifier == identifier,
                   partial(first.frame, in: viewport), partial(second.frame, in: viewport),
                   abs(first.frame.minY - candidate.frame.minY) <= 0.5,
                   abs(second.frame.minY - first.frame.minY) <= 0.5,
                   abs(second.frame.minX - first.frame.minX) <= 0.5,
                   abs(second.frame.height - first.frame.height) <= 0.5 { return element }
            }
            if attempt < 2 {
                let start = history.coordinate(withNormalizedOffset: CGVector(dx: 0.55, dy: 0.75))
                start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -12)))
            }
        }
        add(XCTAttachment(string: app.debugDescription))
        throw failure("No stable, partially visible message container has an unambiguous identifier and frame.")
    }

    private func tapHistoryControl(_ identifier: String) throws {
        let (nodes, viewport) = try visibleHistorySnapshot()
        guard let button = nodes.first(where: { $0.elementType == .button && $0.identifier == identifier }),
              !button.frame.isEmpty, viewport.insetBy(dx: 1, dy: 1).contains(button.frame) else {
            throw failure("\(identifier) is covered or offscreen; do not let XCTest auto-scroll before tapping.")
        }
        app.buttons[identifier].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
    }

    private var pageLoading: Bool {
        app.progressIndicators["正在加载聊天记录"].exists || app.staticTexts["正在加载聊天记录"].exists
    }

    private func waitForPageLoading() {
        wait(until: { self.pageLoading }, timeout: 5)
    }

    private func waitForPageCompletion() {
        wait(until: { !self.pageLoading && !self.app.buttons["chat-history-retry"].exists }, timeout: 10)
    }

    private func failure(_ message: String) -> NSError {
        NSError(domain: "HistoryInteraction", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private func wait(until condition: @escaping () -> Bool, timeout: TimeInterval) {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in condition() }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: timeout), .completed)
    }

    private func capture(_ name: String, anchor: XCUIElement, reference: CGFloat) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let sample = try? anchor.snapshot()
        let viewport = try? visibleHistorySnapshot().1
        let coordinates = XCTAttachment(string: "message=\(sample?.identifier ?? anchor.identifier)\nreferenceY=\(reference)\nframe=\(String(describing: sample?.frame))\nvisibleViewport=\(String(describing: viewport))")
        coordinates.name = name + " - visible frame"
        coordinates.lifetime = .keepAlways
        add(coordinates)
    }
}
