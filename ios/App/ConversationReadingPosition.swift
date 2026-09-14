import SwiftUI
import UIKit

@MainActor
final class ConversationReadingPosition {
    var following: Bool?
    private struct Anchor { let messageID: Int64; let y: CGFloat }
    private final class WeakView {
        weak var view: UIView?
        init(_ view: UIView) { self.view = view }
    }
    private weak var scrollView: UIScrollView?
    private weak var container: UIView?
    private var messages: [Int64: WeakView] = [:]
    private var saved: Anchor?
    private var paging: Anchor?
    private var correcting: Anchor?
    private var reveal: ((Int64) -> Void)?
    private var displayLink: CADisplayLink?
    private var deadline: CFTimeInterval = 0
    private var stableFrames = 0
    private var scheduled = false

    func setFollowing(_ value: Bool) {
        following = value
        if value { saved = nil; paging = nil; cancelCorrection() }
    }

    func prepareForEarlierPage() {
        saved = visibleAnchor()
        paging = saved
    }

    func waitUntilScrollingStops() async throws {
        while let scroll = scrollView, scroll.window != nil,
              scroll.isDragging || scroll.isDecelerating {
            try await Task.sleep(nanoseconds: 16_000_000)
        }
        try Task.checkCancellation()
    }

    func willPrepend() {
        guard following == false else { paging = nil; return }
        if let scroll = scrollView, scroll.window != nil {
            guard !scroll.isDragging, !scroll.isDecelerating else { paging = nil; return }
            saved = visibleAnchor() ?? saved
        }
        paging = saved
    }

    func userDragged() {
        paging = nil
        cancelCorrection()
        saved = visibleAnchor()
    }

    func disappeared() {
        if following == false, correcting == nil { saved = visibleAnchor() ?? saved }
        cancelCorrection()
    }

    func appeared(messageIDs: [Int64], reveal: @escaping (Int64) -> Void) {
        guard following == false, let saved, messageIDs.contains(saved.messageID) else { return }
        correct(saved, reveal: reveal)
    }

    func prepended(messageIDs: [Int64], reveal: @escaping (Int64) -> Void) {
        guard let anchor = paging else { return }
        paging = nil
        guard following == false, messageIDs.contains(anchor.messageID) else { return }
        saved = anchor
        correct(anchor, reveal: reveal)
    }

    func reset() {
        cancelCorrection()
        following = nil; saved = nil; paging = nil
        messages.removeAll(); scrollView = nil; container = nil
    }

    fileprivate func register(_ view: UIView, messageID: Int64) {
        messages[messageID] = WeakView(view)
    }

    fileprivate func unregister(_ view: UIView, messageID: Int64) {
        if messages[messageID]?.view === view { messages.removeValue(forKey: messageID) }
    }

    fileprivate func attach(_ view: UIView) {
        var parent = view.superview
        while let current = parent {
            if let scroll = current as? UIScrollView {
                container = view; scrollView = scroll
                scheduleCorrection()
                return
            }
            parent = current.superview
        }
    }

    fileprivate func detach(_ view: UIView) {
        guard container === view else { return }
        disappeared()
        container = nil; scrollView = nil
    }

    private func visibleAnchor() -> Anchor? {
        guard let scrollView else { return nil }
        let viewport = scrollView.bounds
        return messages.compactMap { id, value -> Anchor? in
            guard let view = value.view, view.window != nil else { return nil }
            let frame = view.convert(view.bounds, to: scrollView)
            guard frame.height > 0, frame.intersects(viewport) else { return nil }
            return Anchor(messageID: id, y: frame.minY - viewport.minY)
        }.min { $0.y < $1.y }
    }

    private func correct(_ anchor: Anchor, reveal: @escaping (Int64) -> Void) {
        cancelCorrection()
        correcting = anchor; self.reveal = reveal
        scheduleCorrection()
    }

    private func scheduleCorrection() {
        guard correcting != nil, scrollView?.window != nil, displayLink == nil, !scheduled else { return }
        scheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.scheduled = false
            guard let anchor = self.correcting, let scroll = self.scrollView, scroll.window != nil else { return }
            guard !scroll.isDragging, !scroll.isDecelerating else { self.userDragged(); return }
            // Only ask SwiftUI to realize an absent row; a top-scroll would compete with a mounted row's offset.
            if self.messages[anchor.messageID]?.view?.window == nil {
                self.reveal?(anchor.messageID)
                self.reveal = nil
            }
            self.deadline = CACurrentMediaTime() + 1
            let link = CADisplayLink(target: self, selector: #selector(self.correctFrame))
            self.displayLink = link
            link.add(to: .main, forMode: .common)
        }
    }

    @objc private func correctFrame() {
        guard let anchor = correcting, let scroll = scrollView, scroll.window != nil,
              CACurrentMediaTime() < deadline else { cancelCorrection(); return }
        guard !scroll.isDragging, !scroll.isDecelerating else { userDragged(); return }
        scroll.layoutIfNeeded()
        guard let view = messages[anchor.messageID]?.view, view.window != nil else {
            reveal?(anchor.messageID); reveal = nil
            return
        }
        let actual = view.convert(view.bounds, to: scroll).minY - scroll.bounds.minY
        let error = actual - anchor.y
        if abs(error) <= 0.5 {
            stableFrames += 1
            if stableFrames >= 3 { cancelCorrection() }
            return
        }
        stableFrames = 0
        let minimum = -scroll.adjustedContentInset.top
        let maximum = max(minimum, scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom)
        let y = min(maximum, max(minimum, scroll.contentOffset.y + error))
        scroll.setContentOffset(CGPoint(x: scroll.contentOffset.x, y: y), animated: false)
    }

    private func cancelCorrection() {
        displayLink?.invalidate(); displayLink = nil
        correcting = nil; reveal = nil; stableFrames = 0
    }
}

struct ConversationViewportMarker: UIViewRepresentable {
    let position: ConversationReadingPosition
    func makeUIView(context: Context) -> ViewportView { ViewportView(position: position) }
    func updateUIView(_ view: ViewportView, context: Context) { position.attach(view) }

    final class ViewportView: UIView {
        weak var position: ConversationReadingPosition?
        init(position: ConversationReadingPosition) {
            self.position = position
            super.init(frame: .zero)
            isUserInteractionEnabled = false
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        override func didMoveToWindow() {
            super.didMoveToWindow()
            if window == nil { position?.detach(self) } else { position?.attach(self) }
        }
        override func layoutSubviews() {
            super.layoutSubviews()
            if window != nil { position?.attach(self) }
        }
    }
}

struct ConversationMessageMarker: UIViewRepresentable {
    let position: ConversationReadingPosition
    let messageID: Int64
    func makeUIView(context: Context) -> MessageView { MessageView(position: position, messageID: messageID) }
    func updateUIView(_ view: MessageView, context: Context) {
        if view.messageID != messageID { position.unregister(view, messageID: view.messageID) }
        view.messageID = messageID
        position.register(view, messageID: messageID)
    }

    final class MessageView: UIView {
        weak var position: ConversationReadingPosition?
        var messageID: Int64
        init(position: ConversationReadingPosition, messageID: Int64) {
            self.position = position; self.messageID = messageID
            super.init(frame: .zero)
            isUserInteractionEnabled = false
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
        override func didMoveToWindow() {
            super.didMoveToWindow()
            if window == nil { position?.unregister(self, messageID: messageID) }
            else { position?.register(self, messageID: messageID) }
        }
    }
}
