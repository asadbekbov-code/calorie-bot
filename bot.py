import os
import json
import base64
import logging
from datetime import datetime, date, timedelta
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
    "protein_goal": 160,
    "tdee": 2400
}

DAYS_UZ = {
    0: "Dushanba", 1: "Seshanba", 2: "Chorshanba",
    3: "Payshanba", 4: "Juma", 5: "Shanba", 6: "Yakshanba"
}

MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["📊 Statistika", "🍽️ Menyu"],
    ["🏃 Faollik", "📖 Retsept"],
    ["📅 Haftalik hisobot", "💬 Savol"]
], resize_keyboard=True)

# ─── DATABASE ───────────────────────────────────────────

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
    c.execute('''CREATE TABLE IF NOT EXISTS weight_log
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER, date TEXT, weight REAL, created_at TEXT)''')
    conn.commit()
    conn.close()

def get_stats_for_date(user_id, target_date):
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    c.execute("SELECT SUM(calories), SUM(protein) FROM meals WHERE user_id=? AND date=?", (user_id, target_date))
    meal_stats = c.fetchone()
    c.execute("SELECT SUM(calories_burned) FROM activity WHERE user_id=? AND date=?", (user_id, target_date))
    activity_stats = c.fetchone()
    conn.close()
    return {
        "calories": meal_stats[0] or 0,
        "protein": meal_stats[1] or 0,
        "burned": activity_stats[0] or 0
    }

def get_today_stats(user_id):
    today = date.today().isoformat()
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
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

def get_weekly_stats(user_id):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    stats = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        if d <= today:
            s = get_stats_for_date(user_id, d.isoformat())
            s['date'] = d
            s['day_name'] = DAYS_UZ[d.weekday()]
            stats.append(s)
    return stats

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

# ─── AI FUNCTIONS ────────────────────────────────────────

def analyze_food_image(image_data):
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
            {"type": "text", "text": """Bu ovqat rasmini tahlil qil. Faqat JSON qaytар:
{"description": "ovqat nomi (o'zbek tilida, aniq)", "calories": 300, "protein": 10, "fat": 10, "carbs": 30, "assessment": "yaxshi", "comment": "qisqa izoh"}
assessment: yaxshi / qabul qilsa bo'ladi / yomon"""}
        ]}]
    )
    try:
        text = message.content[0].text
        return json.loads(text[text.find('{'):text.rfind('}')+1])
    except:
        return {"description": "Ovqat", "calories": 300, "protein": 10, "fat": 10, "carbs": 30, "assessment": "qabul qilsa bo'ladi", "comment": "Tahlil xatoligi"}

def recalculate_food(food_name):
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": f""""{food_name}" uchun kaloriya hisobla (1 porsiya).
Faqat JSON: {{"description": "{food_name}", "calories": 200, "protein": 10, "fat": 8, "carbs": 20, "assessment": "yaxshi", "comment": "izoh"}}"""}]
    )
    try:
        text = message.content[0].text
        return json.loads(text[text.find('{'):text.rfind('}')+1])
    except:
        return {"description": food_name, "calories": 200, "protein": 10, "fat": 8, "carbs": 20, "assessment": "qabul qilsa bo'ladi", "comment": ""}

def answer_food_question(question, today_stats, weekly_stats):
    """Answer any diet/food question intelligently"""
    today = date.today()
    day_name = DAYS_UZ[today.weekday()]
    
    weekly_summary = ""
    for s in weekly_stats:
        deficit = USER_PROFILE['tdee'] - s['calories'] - s['burned']
        weekly_summary += f"{s['day_name']}: {s['calories']} kkal yegan, {s['burned']} kkal sarf, defitsit: {deficit}\n"
    
    prompt = f"""Sen dieta va fitness bo'yicha mutaxassis yordamchisan. O'zbek tilida javob ber.

Foydalanuvchi ma'lumotlari:
- Ism: Asadbek, 22 yosh, 88.5 kg, 183 sm
- Kunlik maqsad: 1900 kkal, oqsil: 160g
- Kunlik metabolizm (TDEE): 2400 kkal
- Bugun ({day_name}): {today_stats['calories']} kkal yegan, {today_stats['burned']} kkal sarf, {today_stats['protein']:.0f}g oqsil

Haftalik ma'lumotlar:
{weekly_summary}

Savol: {question}

Qisqa, aniq va amaliy javob ber. Agar ovqat haqida so'ralsa kaloriyasini ham ayt."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def get_gym_plan(day_name):
    """Get gym plan for specific day"""
    prompt = f"""Bugun {day_name}. Asadbek uchun bugungi gym mashq rejasini ber.
Ma'lumotlar: 22 yosh, 88.5 kg, 183 sm, maqsad: yog' yoqish + muskul qurish.

Format:
💪 *{day_name} — [Mashq turi]*

⏱ Umumiy vaqt: X daqiqa

🔥 *Isitish (5-7 daq):*
- ...

💪 *Asosiy mashqlar:*
1. [Mashq nomi] — X set × X takror
2. ...

🏃 *Kardio (X daq):*
- ...

❄️ *Sovitish:*
- ...

🔥 Taxminiy kaloriya sarfi: ~XXX kkal"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def get_weekly_gym_plan():
    """Get full weekly gym plan"""
    prompt = """Asadbek uchun haftalik gym rejasi ber.
Ma'lumotlar: 22 yosh, 88.5 kg, 183 sm, maqsad: yog' yoqish + muskul qurish.

Har kun uchun qisqa:
- Dushanba: [mashq turi]
- Seshanba: [mashq turi]
- Chorshanba: [dam olish yoki kardio]
- Payshanba: [mashq turi]
- Juma: [mashq turi]
- Shanba: [faol dam olish]
- Yakshanba: [to'liq dam olish]

Har kunning asosiy mashqlari ro'yxati."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def get_daily_menu(meal_type=None):
    if meal_type:
        prompt = f"""{meal_type} uchun 1 ta tavsiya ber. Faqat JSON:
{{"name": "nom", "calories": 400, "description": "tarkib", "recipe": "qisqa retsept"}}"""
    else:
        prompt = """1900 kkal li kunlik menyu. Faqat JSON:
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
        return json.loads(text[text.find('{'):text.rfind('}')+1])
    except:
        return None

def get_recipe(food_name):
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": f"{food_name} uchun diet retsept ber o'zbek tilida. Qisqa va amaliy. Kaloriyasini ham yoz."}]
    )
    return message.content[0].text

def calculate_weekly_loss(weekly_stats):
    """Calculate estimated fat loss for the week"""
    total_deficit = 0
    days_tracked = 0
    for s in weekly_stats:
        if s['calories'] > 0:
            deficit = USER_PROFILE['tdee'] - s['calories'] - s['burned']
            total_deficit += deficit
            days_tracked += 1
    
    fat_loss_kg = total_deficit / 7700
    return total_deficit, fat_loss_kg, days_tracked

# ─── HANDLERS ────────────────────────────────────────────

def format_analysis_message(result, meal_type):
    emoji = {"yaxshi": "✅", "qabul qilsa bo'ladi": "⚠️", "yomon": "❌"}.get(result.get('assessment', ''), "ℹ️")
    return (
        f"🔍 *Tahlil natijasi:*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🍽️ *{result['description']}*\n"
        f"🔥 Kaloriya: *{result['calories']} kkal*\n"
        f"💪 Oqsil: *{result.get('protein', 0)}g*\n"
        f"🧈 Yog': *{result.get('fat', 0)}g*\n"
        f"🍞 Uglevodlar: *{result.get('carbs', 0)}g*\n"
        f"{emoji} {result.get('comment', '')}\n\n"
        f"📌 Vaqt: *{meal_type}*\n\n"
        f"✅ To'g'rimi yoki tuzatish kerakmi?"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    day_name = DAYS_UZ[today.weekday()]
    welcome = (
        f"👋 Salom, {USER_PROFILE['name']}!\n\n"
        f"📅 Bugun: *{day_name}, {today.strftime('%d.%m.%Y')}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚖️ Vazn: {USER_PROFILE['weight']} kg\n"
        f"📏 Bo'y: {USER_PROFILE['height']} sm\n"
        f"🎯 Kunlik maqsad: {USER_PROFILE['daily_goal']} kkal\n"
        f"💪 Oqsil maqsad: {USER_PROFILE['protein_goal']}g\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📸 Ovqat rasmini yuboring!\n"
        f"💬 Savol tugmasi orqali har qanday savol bering\n"
        f"👇 Tugmalardan foydalaning:"
    )
    await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=MAIN_KEYBOARD)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌅 Nonushta", callback_data="mealtype_Nonushta"),
         InlineKeyboardButton("☀️ Tushlik", callback_data="mealtype_Tushlik")],
        [InlineKeyboardButton("🍎 Snack", callback_data="mealtype_Snack"),
         InlineKeyboardButton("🌙 Kechki ovqat", callback_data="mealtype_Kechki ovqat")]
    ])
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
        
        context.user_data['current_meal_type'] = meal_type
        await query.edit_message_text("📸 Tahlil qilinmoqda... ⏳")
        
        import httpx
        file = await query.get_bot().get_file(photo_id)
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(file.file_path)
            image_data = base64.b64encode(response.content).decode('utf-8')
        
        context.user_data['image_data'] = image_data
        result = analyze_food_image(image_data)
        context.user_data['pending_result'] = result
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ To'g'ri, saqlash", callback_data="confirm_save")],
            [InlineKeyboardButton("✏️ Tuzatish kiritish", callback_data="confirm_edit")]
        ])
        await query.edit_message_text(format_analysis_message(result, meal_type), parse_mode='Markdown', reply_markup=keyboard)

    elif query.data == "confirm_save":
        result = context.user_data.get('pending_result')
        meal_type = context.user_data.get('current_meal_type', 'Ovqat')
        if not result:
            await query.edit_message_text("❌ Ma'lumot topilmadi.")
            return
        
        add_meal(user_id, meal_type, result['description'], result['calories'], result.get('protein', 0))
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        bar = "█" * int(progress/10) + "░" * (10 - int(progress/10))
        
        await query.edit_message_text(
            f"✅ *Saqlandi!*\n\n"
            f"🍽️ {result['description']} — {result['calories']} kkal\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔥 Bugun: *{stats['calories']} kkal* | Qoldi: *{remaining} kkal*\n"
            f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n"
            f"[{bar}] {progress}%",
            parse_mode='Markdown'
        )

    elif query.data == "confirm_edit":
        await query.edit_message_text(
            "✏️ *Tuzatish kiriting*\n\nOvqat nomini to'g'ri yozing:\n_Masalan: ayron 250ml_",
            parse_mode='Markdown'
        )
        context.user_data['waiting_correction'] = True

    elif query.data.startswith("menu_"):
        meal = query.data.replace("menu_", "")
        await query.edit_message_text("🍽️ Tayyorlanmoqda... ⏳")
        
        if meal == "full":
            menu = get_daily_menu()
            if menu:
                await query.edit_message_text(
                    f"🍽️ *Bugungi menyu*\n━━━━━━━━━━━━━━━\n"
                    f"🌅 *Nonushta* — {menu['breakfast']['calories']} kkal\n{menu['breakfast']['name']}\n_{menu['breakfast']['description']}_\n\n"
                    f"☀️ *Tushlik* — {menu['lunch']['calories']} kkal\n{menu['lunch']['name']}\n_{menu['lunch']['description']}_\n\n"
                    f"🍎 *Snack* — {menu['snack']['calories']} kkal\n{menu['snack']['name']}\n\n"
                    f"🌙 *Kechki* — {menu['dinner']['calories']} kkal\n{menu['dinner']['name']}\n_{menu['dinner']['description']}_\n\n"
                    f"🔥 Jami: *~1900 kkal*",
                    parse_mode='Markdown'
                )
        else:
            result = get_daily_menu(meal_type=meal)
            if result:
                await query.edit_message_text(
                    f"🍽️ *{meal} tavsiyasi*\n━━━━━━━━━━━━━━━\n"
                    f"🥘 {result.get('name', '')}\n🔥 {result.get('calories', '')} kkal\n\n"
                    f"📝 {result.get('description', '')}\n\n👨‍🍳 *Retsept:*\n{result.get('recipe', '')}",
                    parse_mode='Markdown'
                )

    elif query.data == "gym_today":
        today = date.today()
        day_name = DAYS_UZ[today.weekday()]
        await query.edit_message_text("💪 Gym rejasi tayyorlanmoqda... ⏳")
        plan = get_gym_plan(day_name)
        await query.edit_message_text(plan, parse_mode='Markdown')

    elif query.data == "gym_week":
        await query.edit_message_text("📅 Haftalik reja tayyorlanmoqda... ⏳")
        plan = get_weekly_gym_plan()
        await query.edit_message_text(plan, parse_mode='Markdown')

    elif query.data.startswith("act_"):
        parts = query.data.split("_")
        activity_map = {
            "run": ("Yugurish", {"30": 180, "60": 350}),
            "gym": ("Gym", {"60": 400}),
            "football": ("Futbol", {"60": 600}),
            "walk": ("Yurish", {"10k": 350, "5k": 180})
        }
        act_type = parts[1]
        duration_key = parts[2] if len(parts) > 2 else "60"
        
        if act_type in activity_map:
            name, cal_map = activity_map[act_type]
            calories = cal_map.get(duration_key, 300)
            duration = int(duration_key) if duration_key.isdigit() else 60
            add_activity(user_id, name, duration, calories)
            stats = get_today_stats(user_id)
            await query.edit_message_text(
                f"✅ *{name}* qo'shildi!\n🔥 Sarf: *{calories} kkal*\n📊 Bugun jami sarf: *{stats['burned']} kkal*",
                parse_mode='Markdown'
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    today = date.today()
    day_name = DAYS_UZ[today.weekday()]

    # Correction handler
    if context.user_data.get('waiting_correction'):
        context.user_data['waiting_correction'] = False
        meal_type = context.user_data.get('current_meal_type', 'Ovqat')
        await update.message.reply_text(f"🔄 *{text}* qayta hisoblanmoqda... ⏳", parse_mode='Markdown')
        result = recalculate_food(text)
        context.user_data['pending_result'] = result
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ To'g'ri, saqlash", callback_data="confirm_save")],
            [InlineKeyboardButton("✏️ Yana tuzatish", callback_data="confirm_edit")]
        ])
        await update.message.reply_text(format_analysis_message(result, meal_type), parse_mode='Markdown', reply_markup=keyboard)
        return

    # Recipe handler
    if context.user_data.get('waiting_recipe'):
        context.user_data['waiting_recipe'] = False
        await update.message.reply_text(f"📖 {text} retsepti tayyorlanmoqda... ⏳")
        recipe = get_recipe(text)
        await update.message.reply_text(recipe, reply_markup=MAIN_KEYBOARD)
        return

    if text == "📊 Statistika":
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        bar = "█" * int(progress/10) + "░" * (10 - int(progress/10))
        
        meals_text = ""
        if stats['meals']:
            meals_text = "\n\n🍽️ *Ovqatlar:*\n"
            for meal in stats['meals']:
                desc = meal[1][:25] + "..." if len(meal[1]) > 25 else meal[1]
                meals_text += f"• {meal[0]}: {desc} — {meal[2]} kkal\n"
        
        await update.message.reply_text(
            f"📊 *Bugun — {day_name}*\n━━━━━━━━━━━━━━━\n"
            f"🔥 Yegan: *{stats['calories']} kkal*\n"
            f"🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*\n"
            f"📉 Qoldi: *{remaining} kkal*\n"
            f"🏃 Sarf: *{stats['burned']} kkal*\n"
            f"💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*\n\n"
            f"[{bar}] {progress}%{meals_text}",
            parse_mode='Markdown', reply_markup=MAIN_KEYBOARD
        )

    elif text == "📅 Haftalik hisobot":
        weekly = get_weekly_stats(user_id)
        total_deficit, fat_loss, days = calculate_weekly_loss(weekly)
        
        days_text = ""
        for s in weekly:
            deficit = USER_PROFILE['tdee'] - s['calories'] - s['burned']
            emoji = "✅" if deficit > 0 else "⚠️"
            days_text += f"{emoji} *{s['day_name']}*: {s['calories']} kkal"
            if s['burned'] > 0:
                days_text += f" | 🏃 -{s['burned']}"
            days_text += f" | defitsit: {deficit}\n"
        
        await update.message.reply_text(
            f"📅 *Haftalik hisobot*\n━━━━━━━━━━━━━━━\n"
            f"{days_text}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 *Jami:*\n"
            f"🔥 Umumiy defitsit: *{total_deficit:.0f} kkal*\n"
            f"⚖️ Taxminiy yog' yo'qotish: *{fat_loss:.2f} kg*\n"
            f"📆 Kuzatilgan kunlar: *{days}/7*\n\n"
            f"💡 1 kg yog' = 7700 kkal defitsit",
            parse_mode='Markdown', reply_markup=MAIN_KEYBOARD
        )

    elif text == "🍽️ Menyu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌅 Nonushta", callback_data="menu_Nonushta"),
             InlineKeyboardButton("☀️ Tushlik", callback_data="menu_Tushlik")],
            [InlineKeyboardButton("🍎 Snack", callback_data="menu_Snack"),
             InlineKeyboardButton("🌙 Kechki ovqat", callback_data="menu_Kechki")],
            [InlineKeyboardButton("📋 Kunlik to'liq menyu", callback_data="menu_full")]
        ])
        await update.message.reply_text("Qaysi ovqat uchun tavsiya kerak?", reply_markup=keyboard)

    elif text == "🏃 Faollik":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏃 Yugurish 30 daq", callback_data="act_run_30"),
             InlineKeyboardButton("🏃 Yugurish 60 daq", callback_data="act_run_60")],
            [InlineKeyboardButton("🏋️ Gym 60 daq", callback_data="act_gym_60"),
             InlineKeyboardButton("⚽ Futbol 60 daq", callback_data="act_football_60")],
            [InlineKeyboardButton("🚶 10,000 qadam", callback_data="act_walk_10k"),
             InlineKeyboardButton("🚶 5,000 qadam", callback_data="act_walk_5k")],
            [InlineKeyboardButton("💪 Bugungi gym reja", callback_data="gym_today"),
             InlineKeyboardButton("📅 Haftalik gym reja", callback_data="gym_week")]
        ])
        await update.message.reply_text(
            f"🏃 *{day_name}* — bugungi faollik:",
            parse_mode='Markdown', reply_markup=keyboard
        )

    elif text == "📖 Retsept":
        await update.message.reply_text("📖 Qaysi ovqat retseptini olmoqchisiz?\n\nOvqat nomini yozing:")
        context.user_data['waiting_recipe'] = True

    elif text == "💬 Savol":
        await update.message.reply_text(
            "💬 *Savol yozing!*\n\n"
            "Masalan:\n"
            "• _Hot dog yesam bo'ladimi?_\n"
            "• _Bugun pizza yedim, qanday qoplayman?_\n"
            "• _Bugun gym ga borsammi?_\n"
            "• _Qancha kg yo'qotdim?_",
            parse_mode='Markdown'
        )
        context.user_data['waiting_question'] = True

    elif context.user_data.get('waiting_question'):
        context.user_data['waiting_question'] = False
        await update.message.reply_text("🤔 Javob tayyorlanmoqda... ⏳")
        
        today_stats = get_today_stats(user_id)
        weekly_stats = get_weekly_stats(user_id)
        answer = answer_food_question(text, today_stats, weekly_stats)
        
        await update.message.reply_text(answer, reply_markup=MAIN_KEYBOARD)

    else:
        # Auto-detect question keywords
        question_keywords = ['bo\'ladimi', 'mumkinmi', 'yesam', 'ichsam', 'qancha', 'qachon', 'nima', 'gym', 'mashq', '?']
        if any(kw in text.lower() for kw in question_keywords):
            await update.message.reply_text("🤔 Javob tayyorlanmoqda... ⏳")
            today_stats = get_today_stats(user_id)
            weekly_stats = get_weekly_stats(user_id)
            answer = answer_food_question(text, today_stats, weekly_stats)
            await update.message.reply_text(answer, reply_markup=MAIN_KEYBOARD)
        else:
            await update.message.reply_text(
                "📸 Ovqat rasmini yuboring yoki tugmalardan foydalaning 👇",
                reply_markup=MAIN_KEYBOARD
            )

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
