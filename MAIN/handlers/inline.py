import asyncio
from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, ChosenInlineResult, InlineKeyboardMarkup, InlineKeyboardButton
from config import bot, client, logger, SYSTEM_PROMPT, BUTTON_PROMPTS, ERROR_FALLBACK_TEXT

router = Router()

@router.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    query_text = inline_query.query.strip()
    results = []

    if not query_text:
        quick_presets = [
            (
                "static_joke", 
                "⚡️ Оторвать тромб", 
                "Случайный жесткий панчлайн",
                "Камон, ребята, ну вы чего? Система Комитета Люстрации зафиксировала сбой. Срочно донатим ФБК, чтобы тромб прирос обратно!"
            ),
            (
                "static_leaks", 
                "🕵️‍♂️ Секретные сливы ФБК", 
                "Диалог руководства из Slack",
                "Жданов: Кто опять съел мой сэндвич на кухне в Лондоне?\nПевчих: Это Волков, он заложил его в бюджет под новую партию худи."
            ),
            (
                "static_merch", 
                "🛍 Запустить сбор на мерч", 
                "Анонс абсурдного товара",
                "Встречайте новую коллекцию мерча! Тактический фонарик 'Люблино-2007' с автографом. Всего за 50$ в крипте. Защити свою Прекрасную Россию Будущего правильно."
            )
        ]
        
        for idx, (result_id, title, desc, static_text) in enumerate(quick_presets):
            results.append(
                InlineQueryResultArticle(
                    id=f"{result_id}_{idx}",
                    title=title,
                    description=desc,
                    input_message_content=InputTextMessageContent(message_text=static_text)
                )
            )
    else:
        placeholder_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Думает...", callback_data="thinking_process")]
        ])

        results.append(
            InlineQueryResultArticle(
                id="dynamic_request",
                title="💬 Ответ Цифрового Навального",
                description=f"Нажмите, чтобы отправить запрос: \"{query_text}\"",
                input_message_content=InputTextMessageContent(
                    message_text=f"<b>Запрос:</b> <i>{query_text}</i>\n\n😎 <b>Навальный:</b> ⏳ <i>Генерирую ответ, секунду...</i>",
                    parse_mode="HTML"
                ),
                reply_markup=placeholder_keyboard
            )
        )

    await inline_query.answer(results, cache_time=1, is_personal=True)

@router.chosen_inline_result()
async def chosen_inline_result_handler(chosen_result: ChosenInlineResult):
    if chosen_result.result_id != "dynamic_request":
        return

    inline_msg_id = chosen_result.inline_message_id
    query_text = chosen_result.query.strip()

    if not inline_msg_id:
        logger.error("Не получен inline_message_id. Проверь, включен ли inline feedback в BotFather!")
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + BUTTON_PROMPTS["chat"]},
        {"role": "user", "content": query_text}
    ]
    ai_reply = ERROR_FALLBACK_TEXT
    for attempt in range(3):
        try:
            response = await client.chat.completions.create(
                model="deepseek/deepseek-v4-flash",
                messages=messages,
                max_tokens=500,
                temperature=0.7,
                timeout=25.0,
            )
            ai_reply = response.choices[0].message.content or ERROR_FALLBACK_TEXT
            break
        except Exception as e:
            if attempt < 2:
                logger.warning(f"Inline AI attempt {attempt + 1}/3 failed: {e}. Retry in {attempt + 1}s")
                await asyncio.sleep(float(attempt + 1))
            else:
                logger.error(f"Inline AI error after 3 attempts: {e}")

    final_text = f"<b>Запрос:</b> <i>{query_text}</i>\n\n😎 <b>Навальный:</b> {ai_reply}"

    try:
        await bot.edit_message_text(
            text=final_text,
            inline_message_id=inline_msg_id,
            parse_mode="HTML",
            reply_markup=None  
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования инлайн-сообщения: {e}")