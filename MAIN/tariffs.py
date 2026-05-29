"""
Централизованная конфигурация тарифов и лимитов.
Все AI-модели, квоты и цены управляются из одного файла.
"""
from dataclasses import dataclass, field


@dataclass
class Tariff:
    """Описание одного тарифного плана."""

    name_ru: str
    daily_text_limit: int          # -1 = безлимит
    daily_media_limit: int         # -1 = безлимит
    text_model: str                # модель для текстовых ответов
    vision_model: str              # модель для анализа картинок
    vision_fallback_models: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)


# ═════════════════════════════════════════════
# ТРИ УРОВНЯ ДОСТУПА
# ═════════════════════════════════════════════

TARIFFS: dict[str, Tariff] = {
    "FREE": Tariff(
        name_ru="🎟 Бесплатный (Free)",
        daily_text_limit=50,
        daily_media_limit=7,
        text_model="deepseek-v4-flash",
        vision_model="gemini-3.1-flash-lite",
        vision_fallback_models=["gemini-3-flash"],
        features=[
            "💬 Базовое общение",
            "📰 Комментарий к новостям",
            "⚡️ Панчлайны / чёрный юмор",
            "🖼 Распознавание картинок (5 в день)",
        ],
    ),
    "VIP_LITE": Tariff(
        name_ru="⭐ VIP Lite (Премиум 1)",
        daily_text_limit=200,
        daily_media_limit=20,
        text_model="deepseek-v4-flash",
        vision_model="gemini-3.1-flash-lite",
        vision_fallback_models=["gemini-3-flash", "gpt-4o-mini"],
        features=[
            "💬 Общение (до 100 запросов/день)",
            "📰 Комментарий к новостям",
            "⚡️ Панчлайны / чёрный юмор",
            "🖼 Распознавание картинок (20 в день)",
            "🔍 Фактчекинг: проверка новостей",
            "📝 Генератор сатирических постов",
        ],
    ),
    "VIP_PRO": Tariff(
        name_ru="👑 VIP Pro (Премиум 2)",
        daily_text_limit=-1,   # безлимит
        daily_media_limit=-1,  # безлимит
        text_model="deepseek-v4-flash",
        vision_model="gemini-3.1-flash-lite",
        vision_fallback_models=["gemini-3-flash", "gpt-4o-mini"],
        features=[
            "💬 Безлимитное общение",
            "📰 Комментарий к новостям",
            "⚡️ Панчлайны / чёрный юмор",
            "🖼 Безлимитное распознавание картинок",
            "🔍 Фактчекинг: проверка новостей",
            "📝 Генератор сатирических постов/расследований",
            "📑 Глубокий анализ документов (Vision/Text)",
        ],
    ),
}


# ═════════════════════════════════════════════
# ЦЕНЫ В TELEGRAM STARS
# ═════════════════════════════════════════════

STARS_PRICES: dict[str, dict[str, int]] = {
    "VIP_LITE": {
        "30_days": 149,    # ⭐ за 30 дней
        "90_days": 299,    # ⭐ за 90 дней
    },
    "VIP_PRO": {
        "30_days": 399,    # ⭐ за 30 дней
        "90_days": 1099,   # ⭐ за 90 дней
    },
}

# Стоимость в рублях (для справки, 1 ⭐ ≈ 1.5–2 ₽)
STARS_ROUGH_RUB = "~1.5–2 ₽"


def get_tariff(name: str) -> Tariff:
    """Безопасное получение тарифа с fallback на FREE."""
    return TARIFFS.get(name, TARIFFS["FREE"])


def is_premium_feature(feature_name: str, tariff_name: str) -> bool:
    """Проверить, доступна ли конкретная фича на этом тарифе."""
    tariff = get_tariff(tariff_name)
    return any(feature_name in f for f in tariff.features)


def get_tariff_limits_display(tariff_name: str, text_used: int, media_used: int) -> str:
    """Красивая строка остатка лимитов для /help."""
    tariff = get_tariff(tariff_name)

    def limit_str(used: int, limit: int) -> str:
        if limit == -1:
            return "♾ Безлимит"
        return f"{used} из {limit}"

    text_line = f"💬 Текстовых: {limit_str(text_used, tariff.daily_text_limit)}"
    media_line = f"🖼 Медиа (фото/аудио): {limit_str(media_used, tariff.daily_media_limit)}"
    return f"{text_line}\n{media_line}"
