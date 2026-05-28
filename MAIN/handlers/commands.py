from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import bot, client, logger, SYSTEM_PROMPT, BUTTON_PROMPTS
from database import save_context
import sys
import time
import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from config import BOT_STATE, ADMIN_PASSWORD

router = Router()

def create_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Просто поболтать", callback_data="chat")
    builder.button(text="📰 Реальные новости", callback_data="news")
    builder.button(text="⚡️ Оторвать тромб", callback_data="joke")
    builder.button(text="🕵️‍♂️ Секретные сливы из чата ФБК", callback_data="leaks")
    builder.button(text="🛍 Запустить сбор на мерч", callback_data="merch")
    builder.button(text="🥖 Заказать обед в ШИЗО", callback_data="food")
    builder.button(text="🏛 Подать жалобу в ЕСПЧ", callback_data="complaint")
    builder.button(text="🔄 Сбросить память", callback_data="reset")
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()

@router.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "Привет, это Навальный! Раз уж я заперт в этом боте, давай называть вещи своими именами: "
        "здесь построена Прекрасная Россия Будущего в миниатюре. 🏛\n\n"
        "<b>Основные возможности:</b>\n"
        "💬 <b>Живое общение</b> — просто пиши мне любой текст.\n"
        "🎙 <b>Голосовые ответы</b> — начни текст со слова <code>АУДИО</code>.\n"
        "🖼 <b>Разбор картинок</b> — скидывай фото.\n"
        "🎛 <b>Меню действий</b> — введи команду /actions.\n\n"
        "Полный список всех фич доступен по команде /help !"
    )

@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "⚖️ <b>Полный список возможностей Цифрового Навального 2.0</b>\n\n"
        "<b>Базовые команды:</b>\n"
        "/start — Перезапустить бота и вывести приветствие.\n"
        "/actions — Вызвать панель управления интерактивными кнопками.\n"
        "/help — Открыть это подробное руководство.\n\n"
        "<b>Мультимедиа:</b>\n"
        "• 🎧 Голос в текст: Шли голосовые, я дословно их расшифрую через Gemini и хлёстко отвечу.\n"
        "• 🗣 Текст в голос: Формат: <code>АУДИО твой текст</code>. (Лимит: 1 раз в 30 мин).\n"
        "• 👁 Компьютерное зрение: Фотографии анализируются через Qwen3.5-Flash.\n\n"
        "<b>Суд Люстрации (В группах):</b>\n"
        "• /sud — Отправь команду <i>в ответ (reply)</i> на сообщение любого участника в чате."
    )

@router.message(Command("actions"))
async def actions_command(message: Message):
    await message.answer("Выбери, что ты хочешь сделать:", reply_markup=create_main_keyboard())

@router.message(Command("sud"))
async def sud_command(message: Message):
    if message.from_user and message.from_user.is_bot:
        return

    if message.chat.type not in ["group", "supergroup"]:
        await message.reply("Камон, в личке судить некого. Добавь меня в чат и суди своих друзей там.")
        return
    if not message.reply_to_message:
        await message.reply("Чтобы устроить суд, ответь командой /sud на чье-то сообщение!")
        return

    obvinitel = message.from_user.full_name
    osuzhdennyi_user = message.reply_to_message.from_user
    user_link = f'<a href="tg://user?id={osuzhdennyi_user.id}">{osuzhdennyi_user.full_name}</a>'
    trigger_text = f"Обвинитель {obvinitel} вызывает в суд пользователя {osuzhdennyi_user.full_name}. Вынеси ему приговор."
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + BUTTON_PROMPTS["sud"]},
        {"role": "user", "content": trigger_text}
    ]
    try:
        response = await client.chat.completions.create(model="deepseek-v4-flash", messages=messages, max_tokens=250, temperature=0.7)
        response_text = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating sud response: {e}")
        response_text = "приговаривается к мгновенному помилованию, упал сервер люстрации."

    await message.reply(f"⚖️ Суд идет! {user_link}, {response_text}", parse_mode="HTML")
    await save_context(message.from_user.id, trigger_text, is_user=True)
@router.message(Command("control"))
async def control_command(message: Message):
    # Ожидаемый формат: /control <пароль> <действие> [доп_параметр]
    args = message.text.split()
    
    if len(args) < 3:
        await message.reply(
            "⚙️ <b>Инструкция по управлению ботом:</b>\n\n"
            "• <code>/control КОД pause</code> — поставить на вечную паузу\n"
            "• <code>/control КОД resume</code> — снять с паузы или мута\n"
            "• <code>/control КОД mute Минуты</code> — замутить бота на X минут\n"
            "• <code>/control КОД stop</code> — полностью выключить процесс (скрипт упадет)\n\n"
            "<i>Замечание: все присланные в период паузы сообщения сгорают навсегда и не будут отправлены повторно.</i>",
            parse_mode="HTML"
        )
        return

    input_password = args[1]
    action = args[2].lower()

    # Проверка пароля
    if input_password != ADMIN_PASSWORD:
        await message.reply("❌ Неверный секретный код! Доступ к управлению заблокирован.")
        return

    if action == "pause":
        BOT_STATE["is_paused"] = True
        await message.reply("⏸ <b>Бот успешно приостановлен!</b> Теперь он игнорирует всех пользователей и не копит сообщения в очередь.")

    elif action == "resume":
        BOT_STATE["is_paused"] = False
        BOT_STATE["mute_until"] = 0
        await message.reply("▶️ <b>Бот снова запущен!</b> Пауза и временный мут полностью сняты.")

    elif action == "mute":
        if len(args) < 4:
            await message.reply("❌ Укажи время мута в минутах! Пример: <code>/control код mute 15</code>")
            return
        try:
            minutes = int(args[3])
            BOT_STATE["mute_until"] = time.time() + (minutes * 60)
            await message.reply(f"🔇 <b>Бот отправлен в ШИЗО на {minutes} мин.</b> Он не будет реагировать ни на кого до истечения таймера.")
        except ValueError:
            await message.reply("❌ Время должно быть целым числом минут!")

    elif action == "stop":
        await message.reply("🛑 <b>Полная остановка бота...</b> Скрипт завершает свою работу.")
        await asyncio.sleep(1)  # Даем сообщению успеть отправиться в Telegram
        sys.exit(0)  # Полностью гасим процесс Python

    else:
        await message.reply("❌ Неизвестное действие. Доступны: pause, resume, mute, stop.")