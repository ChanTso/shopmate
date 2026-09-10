package io.shopmate.buyer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.SubcomposeAsyncImage
import kotlinx.serialization.json.*

val Paper = Color(0xFFF6F1E6)
val Ink = Color(0xFF191810)
val Vermilion = Color(0xFFBE3828)
val Muted = Color(0xFF716B5E)
val Line = Color(0xFFE5D9C1)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Vermilion, onPrimary = Color.White, background = Paper, surface = Color(0xFFFFFDF7), onSurface = Ink, secondary = Ink, secondaryContainer = Line, onSecondaryContainer = Ink, primaryContainer = Line, onPrimaryContainer = Ink, surfaceVariant = Paper, onSurfaceVariant = Muted, outline = Line, outlineVariant = Line)) {
                Surface(Modifier.fillMaxSize(), color = Paper) { BuyerApp() }
            }
        }
    }
}

@Composable fun Heading(text: String, modifier: Modifier = Modifier) { Text(text, modifier, fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold, fontSize = 25.sp, color = Ink) }
@Composable fun Note(text: String) { Text(text, fontSize = 13.sp, color = Muted) }
@Composable fun Sheet(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.background(MaterialTheme.colorScheme.surface, RoundedCornerShape(20.dp)).border(1.dp, Line, RoundedCornerShape(20.dp)).padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
}

@Composable fun BuyerApp(vm: BuyerViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    if (!state.signedIn) { LoginScreen(vm, state); return }
    var confirm by remember { mutableStateOf<Pair<String, () -> Unit>?>(null) }
    Scaffold(containerColor = Paper, bottomBar = {
        NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
            val pages = listOf("首页" to Icons.Outlined.Home, "助手" to Icons.Outlined.AutoAwesome, "购物车" to Icons.Outlined.ShoppingBag, "订单" to Icons.Outlined.ReceiptLong, "我的" to Icons.Outlined.Person)
            pages.forEach { (label, icon) -> NavigationBarItem(selected = state.screen == label, onClick = { vm.navigate(label) }, icon = { Icon(icon, label) }, label = { Text(label) }, colors = NavigationBarItemDefaults.colors(indicatorColor = Line, selectedIconColor = Vermilion)) }
        }
    }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Column { Text("ShopMate", fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold, fontSize = 29.sp); Note("精选生活 · 官方商店") }
                IconButton(onClick = { when(state.screen) { "助手" -> vm.restoreChat(); "我的" -> vm.refreshProfile(); else -> vm.refresh() } }) { Icon(Icons.Outlined.Refresh, "刷新") }
            }
            if (state.error != null || state.notice != null) {
                Surface(color = if (state.error != null) Color(0xFFF9DFD7) else Line, modifier = Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(horizontal = 18.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(state.error ?: state.notice.orEmpty(), Modifier.weight(1f), fontSize = 13.sp)
                        IconButton(onClick = vm::dismiss) { Icon(Icons.Outlined.Close, "关闭提示") }
                    }
                }
            }
            if (state.loading || state.writing) LinearProgressIndicator(Modifier.fillMaxWidth(), color = Vermilion)
            BoxWithConstraints(Modifier.weight(1f)) {
                val wide = maxWidth >= 840.dp
                Row(Modifier.fillMaxSize()) {
                    Box(Modifier.weight(1f)) {
                        when(state.screen) {
                            "首页" -> CatalogScreen(vm, state)
                            "助手" -> ChatScreen(vm, state)
                            "购物车" -> CartScreen(vm, state) { label, action -> confirm = label to action }
                            "订单" -> OrdersScreen(vm, state) { label, action -> confirm = label to action }
                            else -> ProfileScreen(vm, state)
                        }
                    }
                    if (wide && state.screen != "助手") {
                        VerticalDivider(color = Line)
                        Box(Modifier.width(390.dp)) { ChatScreen(vm, state) }
                    }
                }
            }
        }
    }
    state.selected?.let { ProductDialog(it, vm, state.writing) }
    confirm?.let { (message, action) -> AlertDialog(onDismissRequest = { confirm = null }, title = { Heading("请核对后确认") }, text = { Text(message) }, confirmButton = { Button(onClick = { confirm = null; action() }, enabled = !state.writing) { Text("确认提交") } }, dismissButton = { TextButton(onClick = { confirm = null }) { Text("再看一下") } }) }
}

@Composable fun LoginScreen(vm: BuyerViewModel, state: BuyerState) {
    var username by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var endpoint by rememberSaveable { mutableStateOf(vm.api.root) }
    var settings by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(28.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Spacer(Modifier.height(35.dp)); Text("ShopMate", fontFamily = FontFamily.Serif, fontSize = 44.sp, fontWeight = FontWeight.Bold)
        Note("为日常精选 · 官方商店")
        Surface(color = Ink, shape = RoundedCornerShape(24.dp)) { Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("给生活一点灵感，\n把喜欢带回日常。", color = Paper, fontFamily = FontFamily.Serif, fontSize = 28.sp, lineHeight = 38.sp)
            Text("发现合适的好物，让购物助手帮你做选择。", color = Line, fontSize = 14.sp)
        } }
        Heading("欢迎回来")
        OutlinedTextField(username, { username = it }, label = { Text("账号") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(password, { password = it }, label = { Text("密码") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
        state.error?.let { Text(it, color = Vermilion) }
        Button(onClick = { vm.login(endpoint, username, password); password = "" }, enabled = !state.loading && username.isNotBlank() && password.isNotBlank(), modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(if (state.loading) "登录中…" else "登录，开始探索") }
        TextButton(onClick = { settings = !settings }) { Text("连接设置") }
        if (settings) { OutlinedTextField(endpoint, { endpoint = it }, label = { Text("ShopMate 服务地址") }, modifier = Modifier.fillMaxWidth()); Note("模拟器可连接 10.0.2.2，远程服务使用 HTTPS。") }
    }
}

@Composable fun CatalogScreen(vm: BuyerViewModel, state: BuyerState) {
    var query by rememberSaveable { mutableStateOf(state.query) }
    LazyColumn(contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(query, { query = it }, placeholder = { Text("搜索商品或装备") }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(18.dp), singleLine = true, leadingIcon = { Icon(Icons.Outlined.Search, null) })
            FilledTonalIconButton(onClick = { vm.search(query) }) { Icon(Icons.Outlined.ArrowForward, "搜索") }
        } }
        item { Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("配一套咖啡角装备", "比较两款咖啡机", "按预算做购物计划").forEach { text -> SuggestionChip(onClick = { vm.navigate("助手"); vm.draft(text) }, label = { Text(text) }) }
        } }
        if (state.query.isEmpty()) item {
            Surface(color = Ink, shape = RoundedCornerShape(24.dp)) { Column(Modifier.fillMaxWidth().padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("购物规划  ·  PLANNER", color = Color(0xFFD6B97B), letterSpacing = 2.sp, fontSize = 12.sp)
                Text("说出预算和场景，\n助手陪你选好整套", color = Paper, fontFamily = FontFamily.Serif, fontWeight = FontWeight.Bold, fontSize = 27.sp, lineHeight = 36.sp)
                Text("比较规格与取舍，让每件装备都值得带上。", color = Line, fontSize = 14.sp)
                Button(onClick = { vm.navigate("助手"); vm.draft("预算2000元，帮我规划一套家庭咖啡角装备") }) { Text("开始规划  →") }
            } }
        }
        item { Heading(if (state.query.isBlank()) "探索生活好物" else "搜索结果") }
        if (state.products.isEmpty() && !state.loading) item { Sheet(Modifier.fillMaxWidth()) { Text("暂时没有符合条件的商品"); TextButton(onClick = { query = ""; vm.search("") }) { Text("查看全部商品") } } }
        items(state.products.chunked(2)) { pair -> Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            pair.forEach { product -> Box(Modifier.weight(1f)) { ProductTile(product, vm) } }
            if (pair.size == 1) Spacer(Modifier.weight(1f))
        } }
        if (state.nextOffset != null) item { OutlinedButton(onClick = { vm.search(state.query, true) }, enabled = !state.loading, modifier = Modifier.fillMaxWidth()) { Text("加载更多") } }
    }
}

@Composable fun ProductTile(product: Product, vm: BuyerViewModel) {
    Column(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface, RoundedCornerShape(18.dp)).border(1.dp, Line, RoundedCornerShape(18.dp)).clickable { vm.openProduct(product.product_id) }) {
        ProductImage(vm.api.asset(product.image_url), product.title, Modifier.fillMaxWidth().aspectRatio(1.1f).background(Line, RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp)))
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text(product.title, fontSize = 15.sp, minLines = 2, maxLines = 3)
            Text(decimalMoney(product.price, product.currency), color = Vermilion, fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Note(if (product.in_stock) product.category ?: "查看商品详情" else "暂时缺货")
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ProductDialog(product: Product, vm: BuyerViewModel, writing: Boolean) {
    var chosen by remember(product.product_id) { mutableStateOf<Product?>(if (product.variants.isEmpty() && product.options.isEmpty()) product else null) }
    ModalBottomSheet(onDismissRequest = vm::closeProduct, containerColor = Paper, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            ProductImage(vm.api.asset((chosen ?: product).image_url), product.title, Modifier.fillMaxWidth().height(240.dp))
            Heading(product.title); Text(decimalMoney((chosen ?: product).price, product.currency), color = Vermilion, fontSize = 28.sp, fontWeight = FontWeight.Bold)
            product.long_description?.let { Text(it) }
            product.short_description?.let { Note(it) }
            if (product.variants.isNotEmpty()) {
                Text("选择规格", fontWeight = FontWeight.Bold)
                product.variants.forEach { variant -> FilterChip(selected = chosen?.product_id == variant.product_id, onClick = { chosen = variant }, label = { Text(variant.option_values.values.joinToString(" / ").ifBlank { variant.title } + " · " + decimalMoney(variant.price, variant.currency)) }) }
            }
            product.specs.forEach { (name, value) -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Note(name); Text(value, Modifier.widthIn(max = 230.dp)) } }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { vm.askProduct(chosen ?: product); vm.closeProduct() }, modifier = Modifier.weight(1f)) { Text("就这件问助手") }
                Button(onClick = { chosen?.let(vm::add) }, enabled = chosen?.in_stock == true && !writing, modifier = Modifier.weight(1f)) { Text(if (chosen == null) "请先选规格" else "加入购物车") }
            }
        }
    }
}

@Composable fun ProductImage(url: String?, title: String, modifier: Modifier = Modifier) {
    SubcomposeAsyncImage(model = url, contentDescription = title, modifier = modifier, contentScale = ContentScale.Crop,
        loading = { Box(Modifier.fillMaxSize().background(Line), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) } },
        error = { Column(Modifier.fillMaxSize().background(Line), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) { Icon(Icons.Outlined.Inventory2, null, Modifier.size(42.dp), tint = Muted); Spacer(Modifier.height(8.dp)); Note("商品图片待补充") } })
}
