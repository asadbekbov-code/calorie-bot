import os
import json
import base64
import logging
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import anthropic
import sqlite3

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Anthropic client
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# User profile (Asadbek's data)
USER_PROFILE = {
    "name": "Asadbek",
    "weight": 88.5,
    "height": 183,
    "age": 22,
    "gender": "male",
    "daily_goal": 1900,
    "protein_goal": 160
}

# Database setup
def init_db():
    conn = sqlite3.connect("calories.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS meals
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  date TEXT,
                  meal_type TEXT,
                  description TEXT,
                  calories INTEGER,
                  protein REAL,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS activity
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  date TEXT,
                  activity_type TEXT,
                  duration INTEGER,
                  calories_burned INTEGER,
                  created_at TEXT)''')
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

def analyze_food_image(image_data, meal_type="ovqat"):
    """Analyze food image using Claude"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Bu ovqat rasmini tahlil qil va quyidagi formatda JSON qaytар:
{
  "description": "ovqat nomi va tarkibi (o'zbek tilida)",
  "calories": kaloriya soni (butun son),
  "protein": oqsil grammda (raqam),
  "assessment": "dieta uchun baholash (yaxshi/qabul qilsa bo'ladi/yomon)",
  "comment": "qisqa izoh (o'zbek tilida, 1 jumla)"
}

Faqat JSON qaytар, boshqa matn yo'q."""
                    }
                ],
            }
        ],
    )
    
    try:
        result = json.loads(message.content[0].text)
        return result
    except:
        return {
            "description": "Ovqat",
            "calories": 300,
            "protein": 10,
            "assessment": "qabul qilsa bo'ladi",
            "comment": "Tahlil qilishda xatolik yuz berdi"
        }

def get_daily_menu():
    """Get daily menu recommendation"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Bugun uchun 1900 kkal li kunlik menyu ber. 
Foydalanuvchi: erkak, 88.5 kg, 183 sm, 18-25 yosh, Toshkentda yashaydi.
Oddiy o'zbek va xalqaro ovqatlar aralashmasi.

Quyidagi formatda JSON qaytар:
{{
  "breakfast": {{"name": "nom", "calories": 400, "description": "tarkib"}},
  "lunch": {{"name": "nom", "calories": 700, "description": "tarkib"}},
  "snack": {{"name": "nom", "calories": 200, "description": "tarkib"}},
  "dinner": {{"name": "nom", "calories": 500, "description": "tarkib"}}
}}

Faqat JSON qaytар."""
            }
        ],
    )
    
    try:
        return json.loads(message.content[0].text)
    except:
        return None

def get_recipe(food_name):
    """Get recipe for a food"""
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[
            {
                "role": "user", 
                "content": f"""{food_name} uchun diet retsept ber o'zbek tilida.
Qisqa va amaliy bo'lsin. Format:
🥘 {food_name}
⏱ Vaqt: ...
👤 Porsiya: ...

📦 Tarkib:
- ...

📋 Tayyorlash:
1. ...

🔥 Kaloriya: ... kkal"""
            }
        ],
    )
    return message.content[0].text

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Bugungi statistika", callback_data="stats")],
        [InlineKeyboardButton("🍽️ Kunlik menyu", callback_data="menu")],
        [InlineKeyboardButton("🏃 Faollik qo'shish", callback_data="activity")],
        [InlineKeyboardButton("📖 Retsept olish", callback_data="recipe")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Salom! Men sizning kaloriya tracker botingizman!\n\n"
        f"📸 Ovqat rasmini yuboring — kaloriyasini hisoblab beraman\n"
        f"📊 Kunlik maqsad: {USER_PROFILE['daily_goal']} kkal\n"
        f"💪 Oqsil maqsad: {USER_PROFILE['protein_goal']}g\n\n"
        f"Nima qilmoqchisiz?",
        reply_markup=reply_markup
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Rasm tahlil qilinmoqda... ⏳")
    
    # Get photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Download and encode
    import io
    import httpx
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(file.file_path)
        image_data = base64.b64encode(response.content).decode('utf-8')
    
    # Analyze
    result = analyze_food_image(image_data)
    
    # Determine meal type
    hour = datetime.now().hour
    if 6 <= hour < 11:
        meal_type = "Nonushta"
    elif 11 <= hour < 15:
        meal_type = "Tushlik"
    elif 15 <= hour < 18:
        meal_type = "Snack"
    else:
        meal_type = "Kechki ovqat"
    
    # Save to DB
    user_id = update.effective_user.id
    add_meal(user_id, meal_type, result['description'], result['calories'], result.get('protein', 0))
    
    # Get updated stats
    stats = get_today_stats(user_id)
    remaining = USER_PROFILE['daily_goal'] - stats['calories']
    
    assessment_emoji = {"yaxshi": "✅", "qabul qilsa bo'ladi": "⚠️", "yomon": "❌"}.get(result.get('assessment', ''), "ℹ️")
    
    message = f"""🍽️ *{meal_type}*

📝 {result['description']}
🔥 Kaloriya: *{result['calories']} kkal*
💪 Oqsil: *{result.get('protein', 0)}g*
{assessment_emoji} {result.get('comment', '')}

━━━━━━━━━━━━━━━
📊 *Bugun jami:*
🔥 Yegan: *{stats['calories']} kkal*
🎯 Qoldi: *{remaining} kkal*
💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*"""
    
    keyboard = [[InlineKeyboardButton("📊 To'liq statistika", callback_data="stats")]]
    
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "stats":
        stats = get_today_stats(user_id)
        remaining = USER_PROFILE['daily_goal'] - stats['calories']
        net_calories = stats['calories'] - stats['burned']
        progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
        
        # Progress bar
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        
        meals_text = ""
        if stats['meals']:
            meals_text = "\n\n🍽️ *Bugungi ovqatlar:*\n"
            for meal in stats['meals']:
                meals_text += f"• {meal[0]}: {meal[1][:30]}... — {meal[2]} kkal\n"
        
        message = f"""📊 *Bugungi statistika*
━━━━━━━━━━━━━━━
🔥 Yegan: *{stats['calories']} kkal*
🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*
📉 Qoldi: *{remaining} kkal*
🏃 Sarf: *{stats['burned']} kkal*
⚡ Sof: *{net_calories} kkal*

💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*

[{bar}] {progress}%{meals_text}"""
        
        keyboard = [
            [InlineKeyboardButton("🍽️ Menyu", callback_data="menu"),
             InlineKeyboardButton("🏃 Faollik", callback_data="activity")]
        ]
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "menu":
        await query.edit_message_text("🍽️ Menyu tayyorlanmoqda... ⏳")
        menu = get_daily_menu()
        
        if menu:
            message = f"""🍽️ *Bugungi tavsiya etilgan menyu*
━━━━━━━━━━━━━━━
🌅 *Nonushta* — {menu['breakfast']['calories']} kkal
{menu['breakfast']['name']}
_{menu['breakfast']['description']}_

☀️ *Tushlik* — {menu['lunch']['calories']} kkal
{menu['lunch']['name']}
_{menu['lunch']['description']}_

🍎 *Snack* — {menu['snack']['calories']} kkal
{menu['snack']['name']}
_{menu['snack']['description']}_

🌙 *Kechki ovqat* — {menu['dinner']['calories']} kkal
{menu['dinner']['name']}
_{menu['dinner']['description']}_

━━━━━━━━━━━━━━━
🔥 Jami: *~1900 kkal*"""
        else:
            message = "Menyu tayyorlashda xatolik. Qayta urinib ko'ring."
        
        keyboard = [
            [InlineKeyboardButton("📖 Retsept olish", callback_data="recipe")],
            [InlineKeyboardButton("◀️ Orqaga", callback_data="back")]
        ]
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "activity":
        keyboard = [
            [InlineKeyboardButton("🏃 Yugurish (30 daq)", callback_data="act_run_30")],
            [InlineKeyboardButton("🏋️ Gym (60 daq)", callback_data="act_gym_60")],
            [InlineKeyboardButton("⚽ Futbol (60 daq)", callback_data="act_football_60")],
            [InlineKeyboardButton("🚶 10,000 qadam", callback_data="act_walk_10k")],
            [InlineKeyboardButton("◀️ Orqaga", callback_data="back")]
        ]
        await query.edit_message_text("🏃 Qanday faollik qildingiz?", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data.startswith("act_"):
        parts = query.data.split("_")
        activity_map = {
            "run": ("Yugurish", 350),
            "gym": ("Gym/Kuch mashqlari", 400),
            "football": ("Futbol", 600),
            "walk": ("10,000 qadam", 350)
        }
        
        act_type = parts[1]
        duration = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 60
        
        if act_type in activity_map:
            name, calories = activity_map[act_type]
            add_activity(user_id, name, duration, calories)
            
            stats = get_today_stats(user_id)
            await query.edit_message_text(
                f"✅ *{name}* qo'shildi!\n"
                f"🔥 Sarf: *{calories} kkal*\n\n"
                f"📊 Bugun jami sarf: *{stats['burned']} kkal*",
                parse_mode='Markdown'
            )
    
    elif query.data == "recipe":
        await query.edit_message_text(
            "📖 Qaysi ovqat retseptini olmoqchisiz?\n\n"
            "Ovqat nomini yozing (masalan: *Tovuq sho'rva*, *Protein omlet*)",
            parse_mode='Markdown'
        )
        context.user_data['waiting_recipe'] = True
    
    elif query.data == "back":
        keyboard = [
            [InlineKeyboardButton("📊 Bugungi statistika", callback_data="stats")],
            [InlineKeyboardButton("🍽️ Kunlik menyu", callback_data="menu")],
            [InlineKeyboardButton("🏃 Faollik qo'shish", callback_data="activity")],
            [InlineKeyboardButton("📖 Retsept olish", callback_data="recipe")],
        ]
        await query.edit_message_text(
            "Nima qilmoqchisiz?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_recipe'):
        context.user_data['waiting_recipe'] = False
        food_name = update.message.text
        await update.message.reply_text(f"📖 {food_name} retsepti tayyorlanmoqda... ⏳")
        recipe = get_recipe(food_name)
        await update.message.reply_text(recipe)
    else:
        keyboard = [
            [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
            [InlineKeyboardButton("🍽️ Menyu", callback_data="menu")],
        ]
        await update.message.reply_text(
            "📸 Ovqat rasmini yuboring — kaloriyasini hisoblayman!\n"
            "Yoki quyidagi tugmalardan foydalaning:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_today_stats(user_id)
    remaining = USER_PROFILE['daily_goal'] - stats['calories']
    progress = min(100, int(stats['calories'] / USER_PROFILE['daily_goal'] * 100))
    filled = int(progress / 10)
    bar = "█" * filled + "░" * (10 - filled)
    
    message = f"""📊 *Bugungi statistika*
━━━━━━━━━━━━━━━
🔥 Yegan: *{stats['calories']} kkal*
🎯 Maqsad: *{USER_PROFILE['daily_goal']} kkal*
📉 Qoldi: *{remaining} kkal*
🏃 Sarf: *{stats['burned']} kkal*
💪 Oqsil: *{stats['protein']:.0f}g / {USER_PROFILE['protein_goal']}g*

[{bar}] {progress}%"""
    
    await update.message.reply_text(message, parse_mode='Markdown')

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
