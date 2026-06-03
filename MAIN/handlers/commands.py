import sys
import time
import asyncio
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import bot, client, logger, SYSTEM_PROMPT, BUTTON_PROMPTS, BOT_STATE, ADMIN_PASSWORD
from database import (
    save_context,
    get_or_create_user,
    check_and_reset_daily_limits,
    expire_premium_if_needed,
    update_tariff,
)
from tariffs import TARIFFS, STARS_PRICES, get_tariff, get_tariff_limits_display
from services.ai import (
    process_ai_reply,
    factcheck_claim,
    generate_investigation_post,
    analyze_document,
)

router = Router()

# ═════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═════════════════════════════════════════════

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
    builder.button(text="⭐ Купить VIP-доступ", callback_data="tariff_info")
    builder.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1)
    return builder.as_markup()


async def _get_user_status(user_id: int, username: str = None) -> dict:
    """Получить актуальный статус пользователя (тариф + лимиты)."""
    record = await get_or_create_user(user_id, username)
    record = await check_and_reset_daily_limits(user_id)
    record = await expire_premium_if_needed(user_id)
    return record


# ═════════════════════════════════════════════
#  КОМАНДЫ
# ═════════════════════════════════════════════

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
        "Полный список всех фич доступен по команде /help !\n\n"
        "<i>⚠️ Это сатирический развлекательный бот. Все высказывания являются художественным вымыслом и пародией. "
        "Бот не аффилирован ни с какими политическими организациями и не призывает к каким-либо действиям.</i>"
    )


@router.message(Command("help"))
async def help_command(message: Message):
    """Динамический /help — показывает статус тарифа и остаток лимитов."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.full_name

    # Получить актуальные данные из БД
    record = await _get_user_status(user_id, username)
    tariff_name = record["tariff_name"]
    tariff = get_tariff(tariff_name)

    # Остаток лимитов
    limits_line = get_tariff_limits_display(
        tariff_name,
        record["daily_text_used"],
        record["daily_media_used"],
    )

    # Список фич текущего тарифа
    features_list = "\n".join(f"• {f}" for f in tariff.features)

    # Информация о премиум-подписке
    premium_info = ""
    if tariff_name != "FREE" and record.get("premium_until"):
        premium_info = f"\n⭐ Премиум активен до: <b>{record['premium_until'][:10]}</b>"

    msg = (
        f"⚖️ <b>Цифровой Навальный 2.0 — Справка</b>\n\n"
        f"Твой тариф: <b>{tariff.name_ru}</b>{premium_info}\n"
        f"{limits_line}\n\n"
        f"<b>Доступные тебе фичи:</b>\n{features_list}\n\n"
        f"<b>Базовые команды:</b>\n"
        f"/start — Приветствие и перезапуск.\n"
        f"/actions — Панель интерактивных кнопок.\n"
        f"/help — Это руководство.\n\n"
        f"<b>Мультимедиа:</b>\n"
        f"• 🎧 Голос в текст — шли голосовые, расшифрую и отвечу.\n"
        f"• 🗣 Текст в голос — <code>АУДИО твой текст</code> (1 раз в 30 мин).\n"
        f"• 🖼 Компьютерное зрение — скидывай фото, опишу.\n\n"
        f"<b>AI-инструменты:</b>\n"
        f"• /factcheck — Проверка новости/утверждения на правдивость.\n"
        f"• /post — Генератор сатирического поста-расследования.\n"
        f"• /doc — Глубокий анализ документа (скриншот или текст).\n\n"
        f"<b>Суд Люстрации (в группах):</b>\n"
        f"• /sud — Ответь на сообщение, чтобы устроить суд.\n\n"
        f"<b>💰 Монетизация:</b>\n"
        f"• /buy — Купить VIP-доступ за Telegram Stars.\n"
        f"• /tariff — Информация о тарифах и ценах."
    )

    await message.answer(msg, parse_mode="HTML")


@router.message(Command("actions"))
async def actions_command(message: Message):
    await message.answer("Выбери, что ты хочешь сделать:", reply_markup=create_main_keyboard())


@router.message(Command("tariff"))
async def tariff_command(message: Message):
    """Информация о всех доступных тарифах и ценах."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить VIP Lite (30 дн) — 149 ⭐", callback_data="buy_vip_lite_30")
    builder.button(text="⭐ Купить VIP Lite (90 дн) — 299 ⭐", callback_data="buy_vip_lite_90")
    builder.button(text="👑 Купить VIP Pro (30 дн) — 399 ⭐", callback_data="buy_vip_pro_30")
    builder.button(text="👑 Купить VIP Pro (90 дн) — 1099 ⭐", callback_data="buy_vip_pro_90")
    builder.adjust(1)

    msg = (
        f"💰 <b>Тарифы Цифрового Навального 2.0</b>\n\n"
        f"🎟 <b>Бесплатный (Free)</b> — 0 ⭐\n"
        f"• 20 текстовых запросов в день\n"
        f"• 5 медиа-запросов в день\n\n"
        f"⭐ <b>VIP Lite</b> — 149 ⭐ / 30 дней  или  299 ⭐ / 90 дней\n"
        f"• 100 текстовых запросов в день\n"
        f"• 20 медиа-запросов в день\n"
        f"• Фактчекинг, генератор постов\n\n"
        f"👑 <b>VIP Pro</b> — 399 ⭐ / 30 дней  или  1099 ⭐ / 90 дней\n"
        f"• ♾ Безлимит на всё\n"
        f"• Топовые AI-модели\n"
        f"• Глубокий анализ документов\n\n"
        f"1 ⭐ ≈ 1.5–2 ₽. Оплата через Telegram Stars.\n"
        f"Выбери тариф и нажми кнопку ниже 👇"
    )
    await message.answer(msg, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(Command("buy"))
async def buy_command(message: Message):
    """Покупка VIP — переадресация на меню тарифов."""
    await tariff_command(message)


@router.message(Command("factcheck"))
async def factcheck_command(message: Message):
    """
    Проверка фактов: /factcheck <текст утверждения>
    Или реплай на сообщение (в т.ч. на картинку).
    """
    user_id = message.from_user.id
    record = await _get_user_status(user_id)
    tariff_name = record["tariff_name"]
    tariff = get_tariff(tariff_name)

    # Собираем текст
    claim_text = ""
    image_bytes = None

    # Текст после команды
    args = message.text.split(None, 1)
    if len(args) > 1:
        claim_text = args[1]

    # Если реплай на сообщение с фото — извлекаем текст из картинки
    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.photo:
            file_info = await bot.get_file(replied.photo[-1].file_id)
            downloaded = await bot.download_file(file_info.file_path)
            image_bytes = downloaded.read()
        if not claim_text and (replied.text or replied.caption):
            claim_text = replied.text or replied.caption

    if not claim_text and not image_bytes:
        await message.reply(
            "Используй: <code>/factcheck твоё утверждение</code>\n"
            "Или ответь этой командой на сообщение / картинку с новостью.",
            parse_mode="HTML"
        )
        return

    placeholder = await message.reply(
        "🔍 <i>Запускаю проверку фактов... Это займёт около минуты.</i>",
        parse_mode="HTML"
    )

    loading_phrases = [
        "🔍 <i>Роюсь в открытых источниках. Кремль, к счастью, иногда врёт публично.</i>",
        "📡 <i>Сканирую мировые новостные агентства. Их много, врут по-разному.</i>",
        "🕵️ <i>Опрашиваю источники в трёх странах. Анонимно, разумеется.</i>",
        "📊 <i>Сверяю цифры с официальной статистикой. Это всегда весело.</i>",
        "🧪 <i>Отправил запрос в профильные лаборатории. Ждём ответа.</i>",
        "📰 <i>Листаю 847 страниц расследований Bellingcat. Почти добрался до сути.</i>",
        "🌐 <i>Проверяю первоисточники. Оказывается, их никто не читает, кроме меня.</i>",
        "🔎 <i>Сравниваю версии событий. Официальная и реальная — как всегда две разные истории.</i>",
        "💾 <i>Архивирую доказательства. На всякий случай — вдруг удалят.</i>",
        "📋 <i>Составляю вердикт. Главное — не дать эмоциям победить факты.</i>",
        "⚖️ <i>Взвешиваю аргументы. Чаша весов уже склоняется в одну сторону.</i>",
        "✍️ <i>Формулирую заключение. Скоро всё будет готово.</i>",
    ]

    factcheck_task = asyncio.create_task(
        factcheck_claim(user_id, claim_text, image_bytes, tariff_name)
    )

    idx = 0
    while not factcheck_task.done():
        await asyncio.sleep(5)
        if factcheck_task.done():
            break
        try:
            await bot.edit_message_text(
                chat_id=placeholder.chat.id,
                message_id=placeholder.message_id,
                text=loading_phrases[idx % len(loading_phrases)],
                parse_mode="HTML",
            )
            idx += 1
        except Exception:
            pass

    result = await factcheck_task
    try:
        await bot.edit_message_text(
            chat_id=placeholder.chat.id,
            message_id=placeholder.message_id,
            text=result,
            parse_mode="HTML",
        )
    except Exception:
        await message.reply(result, parse_mode="HTML")


@router.message(Command("post"))
async def post_command(message: Message):
    """
    Генератор поста: /post <описание темы или тезисы>
    """
    user_id = message.from_user.id
    record = await _get_user_status(user_id)
    tariff_name = record["tariff_name"]

    args = message.text.split(None, 1)
    if len(args) < 2:
        if message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
            topic = message.reply_to_message.text or message.reply_to_message.caption
        else:
            await message.reply(
                "Используй: <code>/post описание ситуации, тезисы</code>\n"
                "Или ответь этой командой на сообщение с описанием.",
                parse_mode="HTML"
            )
            return
    else:
        topic = args[1]

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    result = await generate_investigation_post(user_id, topic, tariff_name)
    await message.reply(result, parse_mode="HTML")
    await save_context(user_id, f"Генератор постов: {topic}", is_user=True)
    await save_context(user_id, result, is_user=False)


@router.message(Command("doc"))
async def doc_command(message: Message):
    """
    Анализ документа: /doc <текст>
    Или реплай на скриншот / документ.
    """
    user_id = message.from_user.id
    record = await _get_user_status(user_id)
    tariff_name = record["tariff_name"]

    document_text = None
    image_bytes = None

    args = message.text.split(None, 1)
    if len(args) > 1:
        document_text = args[1]

    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.photo:
            file_info = await bot.get_file(replied.photo[-1].file_id)
            downloaded = await bot.download_file(file_info.file_path)
            image_bytes = downloaded.read()
        elif replied.document:
            # Пробуем скачать документ (PDF и т.д.) — версия-заглушка через байты
            file_info = await bot.get_file(replied.document.file_id)
            downloaded = await bot.download_file(file_info.file_path)
            raw = downloaded.read()
            # Пытаемся декодировать как текст (работает для .txt, .csv, .sub)
            try:
                document_text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # PDF или бинарный файл — пробуем через ImageMagick? Нет, отправляем как картинку в Vision
                # Для простоты: пробуем отправить байты документа как image_bytes в Vision-модель
                image_bytes = raw
                logger.info("Бинарный документ отправлен в Vision-модель для чтения")
        elif not document_text and (replied.text or replied.caption):
            document_text = replied.text or replied.caption

    if not document_text and not image_bytes:
        await message.reply(
            "Используй: <code>/doc текст документа</code>\n"
            "Или ответь этой командой на скриншот / PDF / сообщение с текстом документа.",
            parse_mode="HTML"
        )
        return

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    result = await analyze_document(user_id, image_bytes, document_text, tariff_name)
    await message.reply(result, parse_mode="HTML")
    await save_context(user_id, f"Анализ документа [текст предоставлен]", is_user=True)
    await save_context(user_id, result, is_user=False)


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
        {"role": "user", "content": trigger_text},
    ]
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash", messages=messages, max_tokens=250, temperature=0.7
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating sud response: {e}")
        response_text = "приговаривается к мгновенному помилованию, упал сервер люстрации."

    await message.reply(f"⚖️ Суд идет! {user_link}, {response_text}", parse_mode="HTML")
    await save_context(message.from_user.id, trigger_text, is_user=True)


@router.message(Command("control"))
async def control_command(message: Message):
    args = message.text.split()
    if len(args) < 3:
        await message.reply(
            "⚙️ <b>Инструкция по управлению ботом:</b>\n\n"
            "• <code>/control КОД pause</code> — поставить на вечную паузу\n"
            "• <code>/control КОД resume</code> — снять с паузы или мута\n"
            "• <code>/control КОД mute Минуты</code> — замутить бота на X минут\n"
            "• <code>/control КОД stop</code> — полностью выключить процесс (скрипт упадет)\n\n"
            "<i>Замечание: все присланные в период паузы сообщения сгорают навсегда и не будут отправлены повторно.</i>",
            parse_mode="HTML",
        )
        return

    input_password = args[1]
    action = args[2].lower()

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
        await asyncio.sleep(1)
        sys.exit(0)
    else:
        await message.reply("❌ Неизвестное действие. Доступны: pause, resume, mute, stop.")


# ═════════════════════════════════════════════
#  ОБРАБОТКА ПЛАТЕЖЕЙ TELEGRAM STARS
# ═════════════════════════════════════════════

# Маппинг callback_data → (tariff_name, days)
_PAYMENT_CALLBACK_TO_TARIFF = {
    "buy_vip_lite_30": ("VIP_LITE", 30),
    "buy_vip_lite_90": ("VIP_LITE", 90),
    "buy_vip_pro_30": ("VIP_PRO", 30),
    "buy_vip_pro_90": ("VIP_PRO", 90),
}


@router.callback_query(F.data.startswith("buy_vip_"))
async def buy_vip_callback(callback):
    """Обработчик кнопки покупки VIP — выставляет счёт через Telegram Stars."""
    tariff_key = callback.data
    if tariff_key not in _PAYMENT_CALLBACK_TO_TARIFF:
        await callback.answer("Неизвестный тариф.", show_alert=True)
        return

    tariff_name, days = _PAYMENT_CALLBACK_TO_TARIFF[tariff_key]
    price_config = STARS_PRICES.get(tariff_name, {})
    days_key = f"{days}_days"
    amount = price_config.get(days_key, 0)

    if amount <= 0:
        await callback.answer("Ошибка конфигурации цены.", show_alert=True)
        return

    tariff_ru = TARIFFS[tariff_name].name_ru

    try:
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"{tariff_ru} — {days} дней",
            description=(
                f"Доступ к расширенным возможностям Цифрового Навального 2.0.\n"
                f"Тариф: {tariff_ru}\n"
                f"Срок: {days} дней"
            ),
            payload=f"tariff_{tariff_name}_{days}",
            provider_token="",       # пусто для Telegram Stars
            currency="XTR",
            prices=[LabeledPrice(label=f"{tariff_ru} ({days} дн.)", amount=amount)],
            start_parameter=f"vip_{tariff_name.lower()}_{days}",
        )
        await callback.answer("Счёт выставлен!", show_alert=False)
    except Exception as e:
        logger.error(f"Ошибка при создании инвойса: {e}")
        await callback.answer("Не удалось выставить счёт. Попробуй позже.", show_alert=True)


@router.callback_query(F.data == "tariff_info")
async def tariff_info_callback(callback):
    """Показать информацию о тарифах через callback."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить VIP Lite (30 дн) — 149 ⭐", callback_data="buy_vip_lite_30")
    builder.button(text="⭐ Купить VIP Lite (90 дн) — 299 ⭐", callback_data="buy_vip_lite_90")
    builder.button(text="👑 Купить VIP Pro (30 дн) — 399 ⭐", callback_data="buy_vip_pro_30")
    builder.button(text="👑 Купить VIP Pro (90 дн) — 1099 ⭐", callback_data="buy_vip_pro_90")
    builder.adjust(1)

    msg = (
        f"💰 <b>Тарифы Цифрового Навального 2.0</b>\n\n"
        f"🎟 <b>Бесплатный (Free)</b> — 0 ⭐\n"
        f"• 20 текстовых запросов в день\n"
        f"• 5 медиа-запросов в день\n\n"
        f"⭐ <b>VIP Lite</b> — 149 ⭐ / 30 дней  или  299 ⭐ / 90 дней\n"
        f"• 100 текстовых запросов в день\n"
        f"• 20 медиа-запросов в день\n"
        f"• Фактчекинг, генератор постов\n\n"
        f"👑 <b>VIP Pro</b> — 399 ⭐ / 30 дней  или  1099 ⭐ / 90 дней\n"
        f"• ♾ Безлимит на всё\n"
        f"• Топовые AI-модели\n"
        f"• Глубокий анализ документов\n\n"
        f"1 ⭐ ≈ 1.5–2 ₽. Оплата через Telegram Stars.\n"
        f"Выбери тариф и нажми кнопку ниже 👇"
    )
    await callback.message.edit_text(msg, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout: PreCheckoutQuery):
    """
    Подтверждение платежа Telegram Stars.
    Всегда подтверждаем (можно добавить валидацию payload позже).
    """
    logger.info(
        f"PreCheckoutQuery: user={pre_checkout.from_user.id}, "
        f"payload={pre_checkout.invoice_payload}, amount={pre_checkout.total_amount}"
    )
    await pre_checkout.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """
    Обработка успешной оплаты Telegram Stars.
    Парсит payload инвойса и начисляет премиум.
    """
    payment = message.successful_payment
    payload: str = payment.invoice_payload  # "tariff_VIP_LITE_30"

    if payload.startswith("tariff_"):
        parts = payload.split("_")
        if len(parts) >= 3:
            tariff_name = parts[1] + "_" + parts[2] if len(parts) > 3 else parts[1]
            # Формат: tariff_VIP_LITE_30 → parts = ["tariff", "VIP", "LITE", "30"]
            if len(parts) == 4:
                tariff_name = parts[1] + "_" + parts[2]  # "VIP_LITE"
                days = int(parts[3])
            else:
                tariff_name = parts[1]  # "VIP_LITE"
                days = int(parts[2]) if len(parts) > 2 else 30

            await update_tariff(message.from_user.id, tariff_name, days)
            tariff_ru = TARIFFS.get(tariff_name, TARIFFS["VIP_LITE"]).name_ru

            await message.answer(
                f"✅ <b>Платёж успешно обработан!</b>\n\n"
                f"Тариф <b>{tariff_ru}</b> активирован на <b>{days} дней</b>.\n"
                f"Спасибо за поддержку Прекрасной России Будущего!\n\n"
                f"Используй /help чтобы посмотреть свои новые возможности.",
                parse_mode="HTML",
            )
    else:
        logger.warning(f"Неизвестный payload инвойса: {payload}")
        await message.answer(
            "✅ Платёж получен, спасибо! Используй /help для проверки статуса.",
            parse_mode="HTML",
        )
