from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    keyboard = [
        [KeyboardButton("👪 Обновить жителей")],
        [KeyboardButton("🎁 Проверить бонусы")],
        [KeyboardButton("ℹ️ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def inline_menu():
    keyboard = [
        [InlineKeyboardButton("Ввести данные", callback_data="enter_data")],
        [InlineKeyboardButton("Отмена", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)
