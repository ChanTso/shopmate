import SwiftUI
import UIKit

@MainActor
final class ConversationReadingPosition {
    var following: Bool?
    private struct Anchor { let messageID: Int64; let y: CGFloat; let revision: Int }
    private weak var scrollView: UIScrollView?
    private weak var container: UIView?
    private var frames: [Int64: CGRect] = [:]
    private var frameRevision = 0
    private var adjustedRevision: Int?
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
        frames.removeAll(); scrollView = nil; container = nil
    }

    // LazyVStack can retain offscreen native views with origin frames; SwiftUI reports the row's actual position.
    func updateFrames(_ value: [Int64: CGRect]) {
        frames = value
        frameRevision += 1
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
        let viewport = CGRect(origin: .zero, size: scrollView.bounds.size)
        return frames.compactMap { id, frame -> Anchor? in
            guard frame.height > 0, frame.intersects(viewport) else { return nil }
            return Anchor(messageID: id, y: frame.minY, revision: frameRevision)
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
            guard self.correcting != nil, let scroll = self.scrollView, scroll.window != nil else { return }
            guard !scroll.isDragging, !scroll.isDecelerating else { self.userDragged(); return }
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
        // The pre-insertion geometry cannot decide whether a row needs realization or correction.
        guard frameRevision > anchor.revision else { return }
        guard let frame = frames[anchor.messageID] else {
            reveal?(anchor.messageID); reveal = nil
            return
        }
        // A native offset change must receive new SwiftUI geometry before another adjustment.
        guard adjustedRevision != frameRevision else { return }
        let error = frame.minY - anchor.y
        if abs(error) <= 0.5 {
            stableFrames += 1
            if stableFrames >= 3 { cancelCorrection() }
            return
        }
        stableFrames = 0
        let minimum = -scroll.adjustedContentInset.top
        let maximum = max(minimum, scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom)
        let y = min(maximum, max(minimum, scroll.contentOffset.y + error))
        adjustedRevision = frameRevision
        scroll.setContentOffset(CGPoint(x: scroll.contentOffset.x, y: y), animated: false)
    }

    private func cancelCorrection() {
        displayLink?.invalidate(); displayLink = nil
        correcting = nil; reveal = nil; stableFrames = 0; adjustedRevision = nil
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

struct ConversationMessageFrames: PreferenceKey {
    static var defaultValue: [Int64: CGRect] = [:]
    static func reduce(value: inout [Int64: CGRect], nextValue: () -> [Int64: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}
