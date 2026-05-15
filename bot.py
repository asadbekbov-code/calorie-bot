import os
import json
import base64
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import anthropic
import sqlite3

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

USER_PROFILE = {
    "name": "Asadbek",
    "weight": 88.5,
    "height": 183,
    "age": 22,
    "daily_goal": 1900,
    "protein_goal": 160
}

MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["📊 Statistika", "🍽️ Menyu"],
    ["🏃 Faollik qo'shish", "📖 Retsept"],
], resize_keyboard=True)

def init_db():
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS meals
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER, date TEXT, meal_type TEXT,
                  description TEXT, calories INTEGER, protein REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS activity
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER, date TEXT, activity_type TEXT,
                  duration INTEGER, calories_burned INTEGER, created_at TEXT)''')
    conn.commit()
    conn.close()

def get_today_stats(user_id):
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    today = date.today().isoformat()
    c.execute("SELECT SUM(calories), SUM(protein) FROM meals WHERE user_id=? AND date=?", (user_id, today))
    meal_stats = c.fetchone()
    c.execute("SELECT SUM(calories_burned) FROM activity WHERE user_id=? AND date=?", (user_id, today))
    activity_stats = c.fetchone()
    c.execute("SELECT meal_type, description, calories FROM meals WHERE user_id=? AND date=? ORDER BY created_at", (user_id, today))
    meals = c.fetchall()
    conn.close()
    return {
        "calories": meal_stats[0] or 0,
        "protein": meal_stats[1] or 0,
        "burned": activity_stats[0] or 0,
        "meals": meals
    }

def add_meal(user_id, meal_type, description, calories, protein):
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO meals (user_id, date, meal_type, description, calories, protein, created_at) VALUES (?,?,?,?,?,?,?)",
              (user_id, today, meal_type, description, calories, protein, now))
    conn.commit()
    conn.close()

def add_activity(user_id, activity_type, duration, calories_burned):
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    today = date.today().isoformat()
    now = datetime.now().isoformat()
    c.execute("INSERT INTO activity (user_id, date, activity_type, duration, calories_burned, created_at) VALUES (?,?,?,?,?,?)",
              (user_id, today, activity_type, duration, calories_burned, now))
    conn.commit()
    conn.close()

def analyze_food_image(image_data):
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                {"type": "text", "text": """Bu ovqat rasmini tahlil qil. Faqat JSON qaytар:
{"description": "ovqat nomi (o'zbek tilida)", "calories": 300, "protein": 10, "assessment": "yaxshi", "comment": "izoh"}
assessment: yaxshi / qabul qilsa bo'ladi / yomon"""}
            ]
        }]
    )
    try:
        text = message.content[0].text
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except:
        return {"description": "Ovqat", "calories": 300, "protein": 10, "assessment": "qabul qilsa bo'ladi", "comment": "Tahlil qilishda xatolik"}

def get_daily_menu(meal_type=None):
    if meal_type:
        prompt = f"{meal_type} uchun 1 ta tavsiya ber. Faqat JSON: {{\"name\": \"nom\", \"calories\": 400, \"description\": \"tarkib\", \"recipe\": \"qisqa retsept\"}}"
    else:
        prompt = """Bugungi 1900 kkal li menyu. Faqat JSON:
{"breakfast": {"name": "nom", "calories": 400, "description": "tarkib"},
 "lunch": {"name": "nom", "calories": 700, "description": "tarkib"},
 "snack": {"name": "nom", "calories": 200, "description": "tarkib"},
 "dinner": {"name": "nom", "calories": 500, "description": "tarkib"}}"""
    
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        text = message.content[0].text
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except:
        return None

def get_recipe(food_name):
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": f"{food_name} uchun diet retsept ber o'zbek tilida. Qisqa va amaliy. Kaloriyasini ham yoz."}]
    )
    return message.content[0].text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        f"👋 Salom, {USER_PROFILE['name']}!\n\n"
        f"Men sizning shaxsiy dieta botingizman 🤖\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚖️ Vazn: {USER_PROFILE['weight']} kg\n"
        f"📏 Bo'y: {USER_PROFILE['height']} sm\n"
        f"🎯 Kunlik maqsad: {USER_PROFILE['daily_goal']} kkal\n"
        f"💪 Oqsil maqsad: {USER_PROFILE['protein_goal']}g\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📸 Ovqat rasmini yuboring — kaloriyasini hisoblayman!\n"
        f"👇 Tugmalardan foydalaning:"
    )
    await update.message.reply_text(welcome, reply_markup=MAIN_KEYBOARD)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ask meal type first
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌅 Nonushta", callback_data="mealtype_Nonushta"),
         InlineKeyboardButton("☀️ Tushlik", callback_data="mealtype_Tushlik")],
        [InlineKeyboardButton("🍎 Snack", callback_data="mealtype_Snack"),
         InlineKeyboardButton("🌙 Kechki ovqat", callback_data="mealtype_Kechki ovqat")]
    ])
    
    # Store photo file_id
    context.user_data['pending_photo'] = update.message.photo[-1].file_id
    await update.message.reply_text("🍽️ Qaysi ovqat vaqti?", reply_markup=keyboard)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data.startswith("mealtype_"):
        meal_type = query.data.replace("mealtype_", "")
        photo_id = context.user_data.get('pending_photo')
        
        if not photo_id:
            await query.edit_message_text("❌ Rasm topilmadi. Qayta yuboring.")
            return
        
        await query.edit_message_text(f"📸 {meal_type} tahlil qilinmoqda... ⏳")
        
        import httpx
        file = await query.get_bot().get_file(photo_id)
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(file.file_path)
            image_data = base64.b64encode(response.content).decode('utf-8')
        
        result = analyze_food_image(image_data)
        add_meal(user_id, meal_type, result['description'], result['calories'], result.get('protein', 0))
        
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        assessment_emoji = {"yaxshi": "✅", "qabul qilsa bo'ladi": "⚠️", "yomon": "❌"}.get(result.get('assessment', ''), "ℹ️")
        
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        msg = (
            f"🍽️ *{meal_type}*\n"
            f"📝 {result['description']}\n"
            f"🔥 {result['calories']} kkal | 💪 {result.get('protein', 0)}g oqsil\n"
            f"{assessment_emoji} {result.get('comment', '')}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 *Bugun:*\n"
            f"🔥 Yegan: *{stats['calories']} kkal*\n"
            f"📉 Qoldi: *{remaining} kkal*\n"
            f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n"
            f"[{bar}] {progress}%"
        )
        await query.edit_message_text(msg, parse_mode='Markdown')

    elif query.data == "stats":
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        meals_text = ""
        if stats['meals']:
            meals_text = "\n\n🍽️ *Ovqatlar:*\n"
            for meal in stats['meals']:
                desc = meal[1][:25] + "..." if len(meal[1]) > 25 else meal[1]
                meals_text += f"• {meal[0]}: {desc} — {meal[2]} kkal\n"
        
        msg = (
            f"📊 *Bugungi statistika*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔥 Yegan: *{stats['calories']} kkal*\n"
            f"🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*\n"
            f"📉 Qoldi: *{remaining} kkal*\n"
            f"🏃 Sarf: *{stats['burned']} kkal*\n"
            f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n\n"
            f"[{bar}] {progress}%{meals_text}"
        )
        await query.edit_message_text(msg, parse_mode='Markdown')

    elif query.data == "menu_select":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌅 Nonushta", callback_data="menu_Nonushta"),
             InlineKeyboardButton("☀️ Tushlik", callback_data="menu_Tushlik")],
            [InlineKeyboardButton("🍎 Snack", callback_data="menu_Snack"),
             InlineKeyboardButton("🌙 Kechki ovqat", callback_data="menu_Kechki")],
            [InlineKeyboardButton("📋 Kunlik to'liq menyu", callback_data="menu_full")]
        ])
        await query.edit_message_text("Qaysi ovqat uchun tavsiya kerak?", reply_markup=keyboard)

    elif query.data.startswith("menu_"):
        meal = query.data.replace("menu_", "")
        await query.edit_message_text("🍽️ Menyu tayyorlanmoqda... ⏳")
        
        if meal == "full":
            menu = get_daily_menu()
            if menu:
                msg = (
                    f"🍽️ *Bugungi menyu*\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🌅 *Nonushta* — {menu['breakfast']['calories']} kkal\n"
                    f"{menu['breakfast']['name']}\n"
                    f"_{menu['breakfast']['description']}_\n\n"
                    f"☀️ *Tushlik* — {menu['lunch']['calories']} kkal\n"
                    f"{menu['lunch']['name']}\n"
                    f"_{menu['lunch']['description']}_\n\n"
                    f"🍎 *Snack* — {menu['snack']['calories']} kkal\n"
                    f"{menu['snack']['name']}\n\n"
                    f"🌙 *Kechki ovqat* — {menu['dinner']['calories']} kkal\n"
                    f"{menu['dinner']['name']}\n"
                    f"_{menu['dinner']['description']}_\n\n"
                    f"🔥 Jami: *~1900 kkal*"
                )
                await query.edit_message_text(msg, parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ Xatolik. Qayta urinib ko'ring.")
        else:
            result = get_daily_menu(meal_type=meal)
            if result:
                msg = (
                    f"🍽️ *{meal} tavsiyasi*\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🥘 {result.get('name', '')}\n"
                    f"🔥 {result.get('calories', '')} kkal\n\n"
                    f"📝 {result.get('description', '')}\n\n"
                    f"👨‍🍳 *Retsept:*\n{result.get('recipe', '')}"
                )
                await query.edit_message_text(msg, parse_mode='Markdown')

    elif query.data == "activity":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏃 Yugurish 30 daq", callback_data="act_run_30"),
             InlineKeyboardButton("🏃 Yugurish 60 daq", callback_data="act_run_60")],
            [InlineKeyboardButton("🏋️ Gym 60 daq", callback_data="act_gym_60"),
             InlineKeyboardButton("⚽ Futbol 60 daq", callback_data="act_football_60")],
            [InlineKeyboardButton("🚶 10,000 qadam", callback_data="act_walk_10k"),
             InlineKeyboardButton("🚶 5,000 qadam", callback_data="act_walk_5k")]
        ])
        await query.edit_message_text("🏃 Qanday faollik qildingiz?", reply_markup=keyboard)

    elif query.data.startswith("act_"):
        parts = query.data.split("_")
        activity_map = {
            "run": ("Yugurish", {30: 180, 60: 350}),
            "gym": ("Gym", {60: 400}),
            "football": ("Futbol", {60: 600}),
            "walk": ("Yurish", {"10k": 350, "5k": 180})
        }
        act_type = parts[1]
        duration_key = parts[2] if len(parts) > 2 else "60"
        
        if act_type in activity_map:
            name, cal_map = activity_map[act_type]
            duration = int(duration_key) if duration_key.isdigit() else 60
            calories = cal_map.get(int(duration_key) if duration_key.isdigit() else duration_key, 300)
            
            add_activity(user_id, name, duration, calories)
            stats = get_today_stats(user_id)
            
            await query.edit_message_text(
                f"✅ *{name}* qo'shildi!\n"
                f"🔥 Sarf: *{calories} kkal*\n\n"
                f"📊 Bugun jami sarf: *{stats['burned']} kkal*",
                parse_mode='Markdown'
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "📊 Statistika":
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        meals_text = ""
        if stats['meals']:
            meals_text = "\n\n🍽️ *Ovqatlar:*\n"
            for meal in stats['meals']:
                desc = meal[1][:25] + "..." if len(meal[1]) > 25 else meal[1]
                meals_text += f"• {meal[0]}: {desc} — {meal[2]} kkal\n"
        
        msg = (
            f"📊 *Bugungi statistika*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔥 Yegan: *{stats['calories']} kkal*\n"
            f"🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*\n"
            f"📉 Qoldi: *{remaining} kkal*\n"
            f"🏃 Sarf: *{stats['burned']} kkal*\n"
            f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n\n"
            f"[{bar}] {progress}%{meals_text}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

    elif text == "🍽️ Menyu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌅 Nonushta", callback_data="menu_Nonushta"),
             InlineKeyboardButton("☀️ Tushlik", callback_data="menu_Tushlik")],
            [InlineKeyboardButton("🍎 Snack", callback_data="menu_Snack"),
             InlineKeyboardButton("🌙 Kechki ovqat", callback_data="menu_Kechki")],
            [InlineKeyboardButton("📋 Kunlik to'liq menyu", callback_data="menu_full")]
        ])
        await update.message.reply_text("Qaysi ovqat uchun tavsiya kerak?", reply_markup=keyboard)

    elif text == "🏃 Faollik qo'shish":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏃 Yugurish 30 daq", callback_data="act_run_30"),
             InlineKeyboardButton("🏃 Yugurish 60 daq", callback_data="act_run_60")],
            [InlineKeyboardButton("🏋️ Gym 60 daq", callback_data="act_gym_60"),
             InlineKeyboardButton("⚽ Futbol 60 daq", callback_data="act_football_60")],
            [InlineKeyboardButton("🚶 10,000 qadam", callback_data="act_walk_10k"),
             InlineKeyboardButton("🚶 5,000 qadam", callback_data="act_walk_5k")]
        ])
        await update.message.reply_text("🏃 Qanday faollik qildingiz?", reply_markup=keyboard)

    elif text == "📖 Retsept":
        await update.message.reply_text(
            "📖 Qaysi ovqat retseptini olmoqchisiz?\n\nOvqat nomini yozing (masalan: *Tovuq sho'rva*)",
            parse_mode='Markdown',
            reply_markup=MAIN_KEYBOARD
        )
        context.user_data['waiting_recipe'] = True

    elif context.user_data.get('waiting_recipe'):
        context.user_data['waiting_recipe'] = False
        await update.message.reply_text(f"📖 {text} retsepti tayyorlanmoqda... ⏳")
        recipe = get_recipe(text)
        await update.message.reply_text(recipe, reply_markup=MAIN_KEYBOARD)

    else:
        await update.message.reply_text(
            "📸 Ovqat rasmini yuboring yoki tugmalardan foydalaning 👇",
            reply_markup=MAIN_KEYBOARD
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_today_stats(user_id)
    remaining = USER_PROFILE['daily_goal'] - stats['calories']
    progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
    filled = int(progress / 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    msg = (
        f"📊 *Bugungi statistika*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔥 Yegan: *{stats['calories']} kkal*\n"
        f"🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*\n"
        f"📉 Qoldi: *{remaining} kkal*\n"
        f"🏃 Sarf: *{stats['burned']} kkal*\n"
        f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n\n"
        f"[{bar}] {progress}%"
    )
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
