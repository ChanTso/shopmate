import SwiftUI
import UIKit

/// Adapts catalog, cart and order shapes without replacing the server's product snapshot.
enum ProductPresentation {
    static func productID(_ product: Object) -> String {
        for key in ["product_id", "productId", "id"] {
            let value = text(product, key)
            if !value.isEmpty { return value }
        }
        return ""
    }

    static func title(_ product: Object) -> String {
        for key in ["title", "name"] {
            let value = text(product, key)
            if !value.isEmpty { return value }
        }
        return "商品详情"
    }

    static func category(_ product: Object) -> String {
        let value = text(product, "category")
        return ["home-kitchen": "居家好物", "office-electronics": "桌面与数码", "outdoor-camping": "户外与露营", "fitness": "运动健身", "toys-games": "玩具与游戏", "pet-supplies": "宠物生活", "beauty-personal-care": "个护与美妆", "travel": "旅行装备", "kids-room": "儿童房", "furniture-bedroom": "卧室与家居", "grocery": "食材与食品"][value] ?? value
    }

    static func imageURL(_ product: Object, baseURL: String) -> URL? {
        let content = object(product, "content")
        let path = [text(product, "image_url"), text(product, "imageUrl"), text(content, "imageUrl")].first { !$0.isEmpty }
        guard let path, let base = URL(string: baseURL) else { return nil }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    static func bundledImage(_ product: Object) -> UIImage? {
        let id = productID(product)
        // Each bundled photo belongs to an explicit demo SKU; unrelated products never share it.
        let supplied = [text(product, "image_url"), text(product, "imageUrl"), text(object(product, "content"), "imageUrl")].first { !$0.isEmpty }
        guard supplied == nil || supplied == "/products/\(id).webp" else { return nil }
        return id.isEmpty ? nil : UIImage(named: "Product-" + id)
    }

    static func symbol(_ product: Object) -> String {
        ["home-kitchen": "cup.and.saucer", "office-electronics": "desktopcomputer", "outdoor-camping": "tent", "fitness": "dumbbell", "toys-games": "puzzlepiece", "pet-supplies": "pawprint", "beauty-personal-care": "sparkles", "travel": "suitcase.rolling", "kids-room": "teddybear", "furniture-bedroom": "bed.double", "grocery": "carrot"][text(product, "category")] ?? "bag"
    }
}

struct ProductArtwork: View {
    let product: Object
    let baseURL: String

    var body: some View {
        GeometryReader { geometry in
            Group {
                if let image = ProductPresentation.bundledImage(product) {
                    Image(uiImage: image).resizable().scaledToFill()
                } else if let url = ProductPresentation.imageURL(product, baseURL: baseURL) {
                    AsyncImage(url: url) { phase in
                        if let image = phase.image { image.resizable().scaledToFill() }
                        else { placeholder }
                    }
                } else { placeholder }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .clipped()
        }
        .accessibilityHidden(true)
    }

    private var placeholder: some View {
        ZStack {
            Color(red: 0.93, green: 0.90, blue: 0.84)
            Image(systemName: ProductPresentation.symbol(product))
                .font(.system(size: 32, weight: .light))
                .foregroundStyle(Color(red: 0.48, green: 0.44, blue: 0.36))
        }
    }
}
