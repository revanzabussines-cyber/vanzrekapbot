import os
import sqlite3
import csv
from datetime import datetime, date

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    filters,
)

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("ENV TELEGRAM_TOKEN belum di-set (TELEGRAM_TOKEN)")

DB_PATH = "sales.db"

# Conversation states
ADD_PRODUCT, ADD_SALE, DELETE_PRODUCT = range(3)

# =========================
# KEYBOARD BUTTON TEXT
# =========================

BTN_ADD_PRODUCT = "🛒 Tambah Produk"
BTN_ADD_SALE = "💰 Tambah Penjualan"
BTN_MANAGE_PRODUCT = "📦 Kelola Produk"
BTN_LIST_SALES = "📊 Daftar Penjualan"
BTN_REPORT = "📈 Laporan"
BTN_SETTINGS = "⚙️ Pengaturan"
BTN_UTILITY = "🧰 Utility"
BTN_HELP = "❓ Bantuan"

BTN_LIST_PRODUCTS = "📦 Daftar Produk"
BTN_EDIT_PRODUCT = "✏️ Edit Produk"
BTN_DELETE_PRODUCT = "🗑 Hapus Produk"

BTN_BACK_MAIN = "🔙 Kembali ke Menu Utama"

BTN_BACK_UTILITY = "🔙 Kembali ke Menu Utama"  # sama text
BTN_BACK_MANAGE = "🔙 Kembali ke Menu Utama"

BTN_BACKUP_DATA = "💾 Backup Data"
BTN_EXPORT_DATA = "📤 Export Data"
BTN_EDIT_SETTINGS = "🛠 Edit Pengaturan"


# =========================
# DB SETUP
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total_price INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
        """
    )

    conn.commit()
    conn.close()


# =========================
# DB HELPERS
# =========================

def add_product_db(name: str, price: int, category: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (name, price, category, created_at) VALUES (?, ?, ?, ?)",
        (name, price, category, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def list_products_db(limit: int = 20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, price, category FROM products ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_product_by_id(product_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, price, category FROM products WHERE id = ?",
        (product_id,),
    )
    row = c.fetchone()
    conn.close()
    return row


def delete_product_db(product_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


def add_sale_db(product_id: int, quantity: int):
    product = get_product_by_id(product_id)
    if not product:
        return None

    _, name, price, _ = product
    total = price * quantity

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO sales (product_id, quantity, total_price, created_at) "
        "VALUES (?, ?, ?, ?)",
        (product_id, quantity, total, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    return name, price, total


def list_sales_db(limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT s.id, p.name, s.quantity, s.total_price, substr(s.created_at, 1, 16)
        FROM sales s
        LEFT JOIN products p ON s.product_id = p.id
        ORDER BY s.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_today_summary():
    today_str = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_price), 0)
        FROM sales
        WHERE substr(created_at, 1, 10) = ?
        """,
        (today_str,),
    )
    count, total = c.fetchone()
    conn.close()
    return count, total


def get_month_summary():
    today = date.today()
    ym = f"{today.year:04d}-{today.month:02d}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(total_price), 0)
        FROM sales
        WHERE substr(created_at, 1, 7) = ?
        """,
        (ym,),
    )
    count, total = c.fetchone()
    conn.close()
    return count, total


def get_top_products(limit: int = 5):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT p.name,
               SUM(s.quantity) AS total_qty,
               SUM(s.total_price) AS total_revenue
        FROM sales s
        JOIN products p ON s.product_id = p.id
        GROUP BY p.id
        ORDER BY total_revenue DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


# =========================
# KEYBOARD BUILDERS
# =========================

def main_menu_keyboard():
    keyboard = [
        [BTN_ADD_PRODUCT, BTN_ADD_SALE],
        [BTN_MANAGE_PRODUCT, BTN_LIST_SALES],
        [BTN_REPORT, BTN_SETTINGS],
        [BTN_UTILITY, BTN_HELP],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def manage_product_keyboard():
    keyboard = [
        [BTN_ADD_PRODUCT, BTN_EDIT_PRODUCT],
        [BTN_DELETE_PRODUCT, BTN_LIST_PRODUCTS],
        [BTN_BACK_MAIN],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def utility_keyboard():
    keyboard = [
        [BTN_BACKUP_DATA, BTN_EXPORT_DATA],
        [BTN_EDIT_SETTINGS],
        [BTN_BACK_MAIN],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# =========================
# HANDLERS
# =========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏠 *Menu Utama*\n\n"
        "Bot ini buat rekap produk & penjualan.\n\n"
        "Silakan pilih menu di bawah:"
    )
    await update.message.reply_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def handle_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 Kembali ke Menu Utama.\nSilakan pilih opsi:",
        reply_markup=main_menu_keyboard(),
    )


# ---------- Tambah Produk (Conversation) ----------

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add_product_attempts"] = 2  # 2 kesempatan salah
    msg = (
        "➕ *Tambah Produk*\n\n"
        "Kirim data dengan format:\n"
        "`Nama Produk | Harga | Kategori`\n\n"
        "Contoh:\n"
        "`Kaos Polo | 150000 | Pakaian`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ADD_PRODUCT


async def add_product_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = [p.strip() for p in text.split("|")]

    def price_to_int(s):
        return s.replace(".", "").replace(",", "")

    if len(parts) != 3 or not price_to_int(parts[1]).isdigit():
        attempts = context.user_data.get("add_product_attempts", 0)
        if attempts > 0:
            context.user_data["add_product_attempts"] = attempts - 1
            msg = (
                "❌ *Format salah!* Gunakan format:\n"
                "`Nama Produk | Harga | Kategori`\n\n"
                "Contoh:\n"
                "`Kaos Polo | 150000 | Pakaian`\n\n"
                f"⚠️ Sisa kesempatan: {attempts}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return ADD_PRODUCT
        else:
            await update.message.reply_text(
                "❌ Terlalu banyak percobaan. Tambah produk dibatalkan."
            )
            return ConversationHandler.END

    name, price_str, category = parts
    price_int = int(price_to_int(price_str))

    add_product_db(name, price_int, category)

    msg = (
        "✅ *Produk berhasil ditambahkan!*\n\n"
        f"Nama     : {name}\n"
        f"Harga    : Rp {price_int:,}\n"
        f"Kategori : {category}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END


# ---------- Tambah Penjualan (Conversation) ----------

async def add_sale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=15)
    if not products:
        await update.message.reply_text(
            "⚠️ Belum ada produk. Tambah produk dulu lewat menu *Tambah Produk*.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    lines = []
    for pid, name, price, category in products:
        lines.append(f"{pid}. {name} — Rp {price:,} ({category})")

    msg = (
        "💰 *Tambah Penjualan*\n\n"
        "Kirim dengan format:\n"
        "`ID Produk | Qty`\n\n"
        "Contoh:\n"
        "`3 | 2`\n\n"
        "*Daftar Produk (terbaru):*\n" + "\n".join(lines)
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ADD_SALE


async def add_sale_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = [p.strip() for p in text.split("|")]

    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        msg = (
            "❌ Format salah!\n\n"
            "Gunakan format: `ID Produk | Qty`\n"
            "Contoh: `3 | 2`"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return ADD_SALE

    product_id = int(parts[0])
    qty = int(parts[1])

    result = add_sale_db(product_id, qty)
    if result is None:
        await update.message.reply_text(
            "⚠️ ID produk tidak ditemukan. Coba lagi."
        )
        return ADD_SALE

    name, price, total = result

    msg = (
        "✅ *Penjualan tercatat!*\n\n"
        f"Produk : {name}\n"
        f"Harga  : Rp {price:,}\n"
        f"Qty    : {qty}\n"
        f"Total  : Rp {total:,}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END


# ---------- Hapus Produk (Conversation) ----------

async def delete_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=15)
    if not products:
        await update.message.reply_text("⚠️ Tidak ada produk untuk dihapus.")
        return ConversationHandler.END

    lines = [f"{pid}. {name} — Rp {price:,}" for pid, name, price, _ in products]
    msg = (
        "🗑 *Hapus Produk*\n\n"
        "Kirim *ID produk* yang ingin dihapus.\n\n"
        "*Daftar Produk:*\n" + "\n".join(lines)
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return DELETE_PRODUCT


async def delete_product_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("ID harus angka. Coba lagi.")
        return DELETE_PRODUCT

    pid = int(text)
    product = get_product_by_id(pid)
    if not product:
        await update.message.reply_text("⚠️ Produk tidak ditemukan. Coba ID lain.")
        return DELETE_PRODUCT

    _, name, price, _ = product
    delete_product_db(pid)

    msg = (
        "✅ Produk berhasil dihapus.\n\n"
        f"ID   : {pid}\n"
        f"Nama : {name}\n"
        f"Harga: Rp {price:,}"
    )
    await update.message.reply_text(msg)
    return ConversationHandler.END


# ---------- Menu Kelola Produk & Utility ----------

async def manage_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 *Kelola Produk*\nPilih aksi yang ingin dilakukan:",
        reply_markup=manage_product_keyboard(),
        parse_mode="Markdown",
    )


async def list_products_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=30)
    if not products:
        await update.message.reply_text("📦 Belum ada produk.")
        return

    lines = []
    for pid, name, price, category in products:
        lines.append(f"{pid}. {name} — Rp {price:,} ({category})")

    msg = "*Daftar Produk:*\n\n" + "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def list_sales_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sales = list_sales_db(limit=10)
    if not sales:
        await update.message.reply_text("📊 Belum ada penjualan.")
        return

    lines = []
    for sid, name, qty, total, created_at in sales:
        lines.append(
            f"{sid}. {name} x{qty} — Rp {total:,}  ({created_at})"
        )

    msg = "*10 Penjualan Terbaru:*\n\n" + "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_count, today_total = get_today_summary()
    month_count, month_total = get_month_summary()
    tops = get_top_products(limit=5)

    lines = []
    lines.append("📅 *Rekap Hari Ini*")
    lines.append(f"Transaksi : {today_count}")
    lines.append(f"Omzet     : Rp {today_total:,}\n")

    lines.append("📆 *Rekap Bulan Ini*")
    lines.append(f"Transaksi : {month_count}")
    lines.append(f"Omzet     : Rp {month_total:,}\n")

    if tops:
        lines.append("🏆 *Top 5 Produk (all time)*")
        for name, qty, total in tops:
            lines.append(f"- {name}: {qty} pcs — Rp {total:,}")
    else:
        lines.append("Belum ada data produk terjual.")

    msg = "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "⚙️ *Pengaturan Sederhana*\n\n"
        "- Mata uang : Rupiah (Rp)\n"
        "- Zona waktu laporan : WIB\n\n"
        "Untuk sementara belum bisa diubah dari bot. "
        "Nanti bisa kita upgrade jadi lebih advanced."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def utility_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧰 *Menu Utility*\nPilih utilitas yang kamu mau:",
        reply_markup=utility_keyboard(),
        parse_mode="Markdown",
    )


async def backup_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(DB_PATH):
        await update.message.reply_text("⚠️ Belum ada file database untuk dibackup.")
        return

    await update.message.reply_document(
        InputFile(open(DB_PATH, "rb"), filename=DB_PATH),
        caption="💾 Backup database sales (SQLite).",
    )


def export_csv():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Products
    c.execute("SELECT id, name, price, category, created_at FROM products")
    products = c.fetchall()
    products_file = "products_export.csv"
    with open(products_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "price", "category", "created_at"])
        writer.writerows(products)

    # Sales
    c.execute(
        "SELECT id, product_id, quantity, total_price, created_at FROM sales"
    )
    sales = c.fetchall()
    sales_file = "sales_export.csv"
    with open(sales_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "product_id", "quantity", "total_price", "created_at"])
        writer.writerows(sales)

    conn.close()
    return products_file, sales_file


async def export_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(DB_PATH):
        await update.message.reply_text(
            "⚠️ Belum ada data. Tambah produk/penjualan dulu."
        )
        return

    products_file, sales_file = export_csv()

    await update.message.reply_document(
        InputFile(open(products_file, "rb"), filename="products.csv"),
        caption="📤 Export data produk (CSV).",
    )
    await update.message.reply_document(
        InputFile(open(sales_file, "rb"), filename="sales.csv"),
        caption="📤 Export data penjualan (CSV).",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "❓ *Bantuan Bot Rekap Penjualan*\n\n"
        "• Tambah Produk:\n"
        "  Pilih menu *Tambah Produk* lalu kirim:\n"
        "  `Nama Produk | Harga | Kategori`\n\n"
        "• Tambah Penjualan:\n"
        "  Pilih menu *Tambah Penjualan*, cek daftar produk,\n"
        "  lalu kirim: `ID Produk | Qty`\n\n"
        "• Laporan:\n"
        "  Menu *Laporan* akan menampilkan rekap hari ini,\n"
        "  bulan ini, dan top produk.\n\n"
        "• Backup / Export:\n"
        "  Masuk menu *Utility* untuk backup DB & export CSV.\n\n"
        "Kapan pun bisa kirim /start buat balik ke menu utama."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================
# MAIN
# =========================

def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Conversation: Tambah Produk
    conv_add_product = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD_PRODUCT}$"), add_product_start)],
        states={
            ADD_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_process)],
        },
        fallbacks=[CommandHandler("cancel", handle_back_main)],
    )

    # Conversation: Tambah Penjualan
    conv_add_sale = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD_SALE}$"), add_sale_start)],
        states={
            ADD_SALE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_sale_process)],
        },
        fallbacks=[CommandHandler("cancel", handle_back_main)],
    )

    # Conversation: Hapus Produk
    conv_delete_product = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_DELETE_PRODUCT}$"), delete_product_start)],
        states={
            DELETE_PRODUCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_product_process)],
        },
        fallbacks=[CommandHandler("cancel", handle_back_main)],
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))

    app.add_handler(conv_add_product)
    app.add_handler(conv_add_sale)
    app.add_handler(conv_delete_product)

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MANAGE_PRODUCT}$"), manage_product_menu))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_LIST_PRODUCTS}$"), list_products_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_LIST_SALES}$"), list_sales_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_REPORT}$"), report_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SETTINGS}$"), settings_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_UTILITY}$"), utility_menu))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BACKUP_DATA}$"), backup_data_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_EXPORT_DATA}$"), export_data_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BACK_MAIN}$"), handle_back_main))

    print("Bot rekap penjualan jalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
