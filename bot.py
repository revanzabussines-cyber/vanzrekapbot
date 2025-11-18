import os
import sqlite3
import csv
from datetime import datetime, date, time

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
(
    ADD_PRODUCT,
    ADD_SALE,
    DELETE_PRODUCT,
    EDIT_PRODUCT_SELECT,
    EDIT_PRODUCT_FIELD,
    EDIT_PRODUCT_VALUE,
) = range(6)

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

BTN_BACKUP_DATA = "💾 Backup Data"
BTN_EXPORT_DATA = "📤 Export Data"
BTN_EDIT_SETTINGS = "🛠 Edit Pengaturan"

BTN_CURRENCY = "💰 Mata Uang"
BTN_DATE_FORMAT = "📅 Format Tanggal"
BTN_AUTO_BACKUP = "🔐 Auto Backup"
BTN_NOTIFICATION = "🔔 Notifikasi"

# Field edit produk
BTN_EDIT_NAME = "✏️ Ubah Nama"
BTN_EDIT_PRICE = "💰 Ubah Harga"
BTN_EDIT_CATEGORY = "🏷 Ubah Model/Kategori"
BTN_CANCEL_EDIT = "❌ Batal Edit"


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

    # Subs notifikasi harian per chat
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1
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


def list_products_db(limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, price, category FROM products ORDER BY id ASC LIMIT ?",
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


def update_product_field(product_id: int, field: str, value):
    allowed = {"name", "price", "category"}
    if field not in allowed:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE products SET {field} = ? WHERE id = ?", (value, product_id))
    conn.commit()
    conn.close()


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


# ===== Subscriptions (notif harian) =====

def is_subscribed(chat_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT enabled FROM subscriptions WHERE chat_id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    return bool(row[0])


def set_subscription(chat_id: int, enabled: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO subscriptions (chat_id, enabled)
        VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET enabled = excluded.enabled
        """,
        (chat_id, int(enabled)),
    )
    conn.commit()
    conn.close()


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


def settings_edit_keyboard():
    keyboard = [
        [BTN_CURRENCY, BTN_DATE_FORMAT],
        [BTN_AUTO_BACKUP, BTN_NOTIFICATION],
        [BTN_BACK_MAIN],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def edit_product_field_keyboard():
    keyboard = [
        [BTN_EDIT_NAME, BTN_EDIT_PRICE],
        [BTN_EDIT_CATEGORY],
        [BTN_CANCEL_EDIT],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# =========================
# HANDLERS UTAMA
# =========================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🏠 *Menu Utama*\n\n"
        "Selamat datang di *Bot Rekap Penjualan VanzShop* 🚀\n\n"
        "Pakai tombol di bawah buat navigasi:\n\n"
        "🛒 *Tambah Produk*  → input produk baru\n"
        "💰 *Tambah Penjualan* → catat transaksi jualan\n"
        "📦 *Kelola Produk* → edit / hapus / lihat daftar produk\n"
        "📊 *Daftar Penjualan* → lihat riwayat transaksi\n"
        "📈 *Laporan* → rekap harian, bulanan & top produk\n"
        "⚙️ *Pengaturan* → cek status notifikasi harian\n"
        "🧰 *Utility* → backup & export data\n"
        "❓ *Bantuan* → panduan penggunaan singkat\n\n"
        "Silakan pilih menu lewat keyboard di bawah 👇"
    )
    await update.message.reply_text(
        text, reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def handle_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 Kembali ke Menu Utama.\nSilakan pilih opsi:",
        reply_markup=main_menu_keyboard(),
    )


# =========================
# PARSER INPUT PRODUK
# =========================

def _parse_product_input(text: str):
    """
    Support 2 format:
    1) Nama | Harga | Model
    2) Nama Harga Model  (tanpa |, harga = kata kedua dari belakang)
    """
    text = text.strip()

    # Format pakai "|"
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
        if len(parts) != 3:
            return None
        name, price_raw, category = parts
    else:
        # Format tanpa "|": Nama .... Harga Model
        tokens = text.split()
        if len(tokens) < 3:
            return None
        price_raw = tokens[-2]
        category = tokens[-1]
        name = " ".join(tokens[:-2])

    def to_int(s: str):
        s = s.replace("Rp", "").replace("rp", "")
        s = s.replace(".", "").replace(",", "")
        return s

    price_clean = to_int(price_raw)
    if not price_clean.isdigit():
        return None

    price_int = int(price_clean)
    if not name or not category:
        return None

    return name, price_int, category


# =========================
# TAMBAH PRODUK (Conversation)
# =========================

async def add_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add_product_attempts"] = 3  # 3 kesempatan salah
    msg = (
        "➕ *Tambah Produk*\n\n"
        "Kamu bisa pakai *dua gaya input*:\n"
        "1️⃣ `Nama Produk | Harga | Model`\n"
        "2️⃣ `Nama Produk Harga Model`\n\n"
        "Contoh valid:\n"
        "`Kaos Polo | 150000 | Pakaian`\n"
        "`Kaos Polo 150000 Pakaian`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ADD_PRODUCT


async def add_product_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Kalau user pencet tombol menu lain, batalin mode tambah produk
    if text in {
        BTN_BACK_MAIN,
        BTN_ADD_PRODUCT,
        BTN_ADD_SALE,
        BTN_MANAGE_PRODUCT,
        BTN_LIST_PRODUCTS,
        BTN_EDIT_PRODUCT,
        BTN_DELETE_PRODUCT,
        BTN_LIST_SALES,
        BTN_REPORT,
        BTN_SETTINGS,
        BTN_UTILITY,
        BTN_HELP,
    }:
        await update.message.reply_text(
            "❌ Input produk dibatalkan. Kamu bisa lanjut pakai menu lain.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    parsed = _parse_product_input(text)

    if not parsed:
        attempts = context.user_data.get("add_product_attempts", 0)
        if attempts > 0:
            attempts -= 1
            context.user_data["add_product_attempts"] = attempts
            msg = (
                "❌ *Format salah!* Gunakan salah satu format berikut:\n"
                "1️⃣ `Nama Produk | Harga | Model`\n"
                "2️⃣ `Nama Produk Harga Model`\n\n"
                "Contoh:\n"
                "`Kaos Polo | 150000 | Pakaian`\n"
                "`Kaos Polo 150000 Pakaian`\n\n"
                f"⚠️ Sisa kesempatan: {attempts}"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")
            return ADD_PRODUCT
        else:
            await update.message.reply_text(
                "❌ Terlalu banyak percobaan. Tambah produk dibatalkan.",
                reply_markup=main_menu_keyboard(),
            )
            return ConversationHandler.END

    name, price_int, category = parsed
    add_product_db(name, price_int, category)

    msg = (
        "✅ *Produk berhasil ditambahkan!*\n\n"
        f"📛 Nama   : {name}\n"
        f"💰 Harga  : Rp {price_int:,}\n"
        f"🏷 Model  : {category}"
    )
    await update.message.reply_text(
        msg, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END


# =========================
# TAMBAH PENJUALAN (Conversation)
# =========================

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
        lines.append(f"🆔 {pid} — {name} (Rp {price:,}, {category})")

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
        f"📦 Produk : {name}\n"
        f"💰 Harga  : Rp {price:,}\n"
        f"🔢 Qty    : {qty}\n"
        f"📊 Total  : Rp {total:,}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END


# =========================
# HAPUS PRODUK (Conversation)
# =========================

async def delete_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=30)
    if not products:
        await update.message.reply_text("⚠️ Tidak ada produk untuk dihapus.")
        return ConversationHandler.END

    lines = [f"🆔 {pid} — {name} (Rp {price:,})" for pid, name, price, _ in products]
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
        f"🆔 ID   : {pid}\n"
        f"📛 Nama : {name}\n"
        f"💰 Harga: Rp {price:,}"
    )
    await update.message.reply_text(msg)
    return ConversationHandler.END


# =========================
# EDIT PRODUK (Conversation)
# =========================

async def edit_product_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=30)
    if not products:
        await update.message.reply_text("⚠️ Belum ada produk untuk diedit.")
        return ConversationHandler.END

    lines = [f"🆔 {pid} — {name} (Rp {price:,}, {category})"
             for pid, name, price, category in products]
    msg = (
        "✏️ *Edit Produk*\n\n"
        "Kirim *ID produk* yang mau diedit.\n\n"
        "*Daftar Produk:*\n" + "\n".join(lines)
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
    return EDIT_PRODUCT_SELECT


async def edit_product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("ID harus angka. Coba lagi.")
        return EDIT_PRODUCT_SELECT

    pid = int(text)
    product = get_product_by_id(pid)
    if not product:
        await update.message.reply_text("⚠️ Produk tidak ditemukan. Coba ID lain.")
        return EDIT_PRODUCT_SELECT

    context.user_data["edit_pid"] = pid
    _, name, price, category = product

    msg = (
        "Produk yang akan diedit:\n\n"
        f"🆔 ID   : {pid}\n"
        f"📛 Nama : {name}\n"
        f"💰 Harga: Rp {price:,}\n"
        f"🏷 Model: {category}\n\n"
        "Pilih bagian yang mau diubah:"
    )
    await update.message.reply_text(
        msg, parse_mode="Markdown", reply_markup=edit_product_field_keyboard()
    )
    return EDIT_PRODUCT_FIELD


async def edit_product_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == BTN_EDIT_NAME:
        context.user_data["edit_field"] = "name"
        await update.message.reply_text(
            "✏️ Kirim *nama produk baru*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return EDIT_PRODUCT_VALUE

    if choice == BTN_EDIT_PRICE:
        context.user_data["edit_field"] = "price"
        await update.message.reply_text(
            "💰 Kirim *harga baru* (angka saja, boleh pakai titik/koma):",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return EDIT_PRODUCT_VALUE

    if choice == BTN_EDIT_CATEGORY:
        context.user_data["edit_field"] = "category"
        await update.message.reply_text(
            "🏷 Kirim *model/kategori baru*:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return EDIT_PRODUCT_VALUE

    if choice == BTN_CANCEL_EDIT:
        await update.message.reply_text(
            "❌ Edit produk dibatalkan.",
            reply_markup=manage_product_keyboard(),
        )
        context.user_data.pop("edit_pid", None)
        context.user_data.pop("edit_field", None)
        return ConversationHandler.END

    await update.message.reply_text(
        "Pilih salah satu opsi yang tersedia di keyboard.", parse_mode="Markdown"
    )
    return EDIT_PRODUCT_FIELD


async def edit_product_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("edit_pid")
    field = context.user_data.get("edit_field")
    if not pid or not field:
        await update.message.reply_text("Sesi edit tidak valid, silakan mulai lagi.")
        return ConversationHandler.END

    value_text = update.message.text.strip()

    if field == "price":
        cleaned = value_text.replace("Rp", "").replace("rp", "")
        cleaned = cleaned.replace(".", "").replace(",", "")
        if not cleaned.isdigit():
            await update.message.reply_text(
                "Harga harus angka. Kirim ulang harga baru:"
            )
            return EDIT_PRODUCT_VALUE
        value = int(cleaned)
    else:
        value = value_text

    update_product_field(pid, field, value)

    product = get_product_by_id(pid)
    _, name, price, category = product

    msg = (
        "✅ Produk berhasil diupdate!\n\n"
        f"🆔 ID   : {pid}\n"
        f"📛 Nama : {name}\n"
        f"💰 Harga: Rp {price:,}\n"
        f"🏷 Model: {category}"
    )
    await update.message.reply_text(
        msg, parse_mode="Markdown", reply_markup=manage_product_keyboard()
    )

    context.user_data.pop("edit_pid", None)
    context.user_data.pop("edit_field", None)
    return ConversationHandler.END


# =========================
# MENU KELOLA PRODUK & LIST
# =========================

async def manage_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 *Kelola Produk*\nPilih aksi yang ingin dilakukan:",
        reply_markup=manage_product_keyboard(),
        parse_mode="Markdown",
    )


async def list_products_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = list_products_db(limit=50)
    if not products:
        await update.message.reply_text("📦 Belum ada produk.")
        return

    lines = []
    for pid, name, price, category in products:
        lines.append(
            f"🆔 *ID {pid}* - {name}\n"
            f"💰 Rp {price:,}\n"
            f"🏷 {category}\n"
        )

    msg = (
        "📦 *Daftar Produk Anda* (Halaman 1/1)\n\n"
        + "\n".join(lines)
        + f"\nTotal: {len(products)} produk\n\n"
          "Gunakan *Edit Produk* atau *Hapus Produk* dari menu untuk mengelola produk."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================
# DAFTAR PENJUALAN & LAPORAN
# =========================

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


# =========================
# PENGATURAN & UTILITY
# =========================

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    notif = "✅" if is_subscribed(chat_id) else "❌"

    msg = (
        "⚙️ *Pengaturan Bot*\n\n"
        "💰 Mata Uang: Rp\n"
        "📅 Format Tanggal: DD/MM/YYYY\n"
        "🔐 Auto Backup: ❌ (manual via menu Utility)\n"
        f"🔔 Notifikasi Harian: {notif}\n\n"
        "Gunakan *Edit Pengaturan* dari menu Utility untuk mengubah pengaturan."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def utility_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧰 *Menu Utility*\nPilih utilitas yang ingin digunakan:",
        reply_markup=utility_keyboard(),
        parse_mode="Markdown",
    )


async def edit_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ *Edit Pengaturan*\nPilih pengaturan yang ingin diubah:",
        reply_markup=settings_edit_keyboard(),
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


async def currency_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Mata uang saat ini: *Rp*\n\nCustom mata uang bakal disiapin di versi next.",
        parse_mode="Markdown",
    )


async def date_format_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Format tanggal saat ini: *DD/MM/YYYY*.\n"
        "Belum bisa diubah via bot, nanti bisa diupgrade.",
        parse_mode="Markdown",
    )


async def autobackup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 Auto backup belum aktif.\n\n"
        "Untuk sekarang, pakai *Backup Data* di menu Utility kalau mau backup manual.",
        parse_mode="Markdown",
    )


async def notification_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current = is_subscribed(chat_id)
    new_state = not current
    set_subscription(chat_id, new_state)

    status = "diaktifkan ✅" if new_state else "dinonaktifkan ❌"
    msg = (
        f"🔔 Notifikasi harian {status}.\n\n"
        "Bot akan mengirim pengingat setiap hari supaya kamu nggak lupa input penjualan."
    )
    await update.message.reply_text(msg)


# =========================
# BANTUAN
# =========================

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "❓ *Panduan Penggunaan Bot Penjualan*\n\n"
        "🧱 *Manajemen Produk:*\n"
        "- Tambah Produk: Tambah produk baru\n"
        "- Daftar Produk: Lihat daftar produk\n"
        "- Edit Produk: Ubah nama/harga/model\n"
        "- Hapus Produk: Hapus produk\n\n"
        "💰 *Manajemen Penjualan:*\n"
        "- Tambah Penjualan: Tambah transaksi baru\n"
        "- Daftar Penjualan: Lihat riwayat penjualan\n\n"
        "📈 *Laporan:*\n"
        "- Rekap harian & bulanan\n"
        "- Top produk terlaris\n\n"
        "🧰 *Utility:*\n"
        "- Backup Data: Backup database\n"
        "- Export Data: Export ke CSV\n"
        "- Edit Pengaturan: Ubah notifikasi harian, dll.\n\n"
        "Tips: pakai tombol keyboard biar input lebih cepat."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================
# NOTIFIKASI HARIAN (JOB)
# =========================

async def daily_notification(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM subscriptions WHERE enabled = 1")
    chats = [row[0] for row in c.fetchall()]
    conn.close()

    for chat_id in chats:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="📣 Reminder: Jangan lupa input penjualan hari ini di bot VanzShop.id!"
            )
        except Exception:
            continue


# =========================
# MAIN
# =========================

def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Job reminder harian jam 20:00 (ikut TZ container / TZ=Asia/Jakarta)
    if app.job_queue:
        app.job_queue.run_daily(
            daily_notification,
            time=time(hour=20, minute=0)
        )

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

    # Conversation: Edit Produk
    conv_edit_product = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_EDIT_PRODUCT}$"), edit_product_start)],
        states={
            EDIT_PRODUCT_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_select)
            ],
            EDIT_PRODUCT_FIELD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_field)
            ],
            EDIT_PRODUCT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_product_value)
            ],
        },
        fallbacks=[CommandHandler("cancel", handle_back_main)],
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))

    app.add_handler(conv_add_product)
    app.add_handler(conv_add_sale)
    app.add_handler(conv_delete_product)
    app.add_handler(conv_edit_product)

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MANAGE_PRODUCT}$"), manage_product_menu))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_LIST_PRODUCTS}$"), list_products_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_LIST_SALES}$"), list_sales_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_REPORT}$"), report_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_SETTINGS}$"), settings_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_UTILITY}$"), utility_menu))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BACKUP_DATA}$"), backup_data_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_EXPORT_DATA}$"), export_data_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_EDIT_SETTINGS}$"), edit_settings_menu))

    # Submenu pengaturan
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_CURRENCY}$"), currency_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_DATE_FORMAT}$"), date_format_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_AUTO_BACKUP}$"), autobackup_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_NOTIFICATION}$"), notification_toggle_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_HELP}$"), help_handler))

    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_BACK_MAIN}$"), handle_back_main))

    print("Bot rekap penjualan jalan (versi interaktif)...")
    app.run_polling()


if __name__ == "__main__":
    main()
