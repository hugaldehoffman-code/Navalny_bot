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
# ДВА УРОВНЯ ДОСТУПА: FREE и VIP
# ═════════════════════════════════════════════

TARIFFS: dict[str, Tariff] = {
    "FREE": Tariff(
        name_ru="🎟 Бесплатный (Free)",
        daily_text_limit=50,
        daily_media_limit=7,
        text_model="deepseek/deepseek-v4-flash",
        vision_model="qwen/qwen3.5-flash-02-23",
        vision_fallback_models=["google/gemini-2.0-flash"],
        features=[
            "💬 Базовое общение (50 в день)",
            "📰 Комментарий к новостям",
            "⚡️ Панчлайны / чёрный юмор",
            "🖼 Распознавание картинок (7 в день)",
            "🎙 Голосовые ответы (1 раз в 30 мин)",
            "🔍 Фактчекинг (3 в день)",
        ],
    ),
    "VIP_LITE": Tariff(
        name_ru="⭐ VIP",
        daily_text_limit=-1,
        daily_media_limit=-1,
        text_model="deepseek/deepseek-v4-flash",
        vision_model="qwen/qwen3.5-flash-02-23",
        vision_fallback_models=["google/gemini-2.0-flash", "openai/o4-mini"],
        features=[
            "💬 Безлимитное общение",
            "📰 Комментарий к новостям",
            "⚡️ Панчлайны / чёрный юмор",
            "🖼 Безлимитное распознавание картинок",
            "🎙 Голосовые ответы (1 раз в 5 мин)",
            "🔍 Фактчекинг (20 в день)",
            "📝 Генератор сатирических постов",
            "📑 Глубокий анализ документов",
        ],
    ),
}


# ═════════════════════════════════════════════
# ЦЕНЫ В TELEGRAM STARS
# ═════════════════════════════════════════════

STARS_PRICES: dict[str, dict[str, int]] = {
    "VIP_LITE": {
        "30_days": 99,    # ⭐ за 30 дней
        "90_days": 249,   # ⭐ за 90 дней (~17% скидка)
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
