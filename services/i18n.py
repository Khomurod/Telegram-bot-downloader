from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyrogram.types import InlineKeyboardMarkup

DEFAULT_LANGUAGE = "en"
LANGUAGE_ORDER = ("uz", "ru", "en")
LANGUAGE_LABELS = {
    "uz": "O'zbekcha",
    "ru": "Русский",
    "en": "English",
}

TRANSLATIONS = {
    "en": {
        "welcome": (
            "👋 Welcome to the Downloader Bot!\n\n"
            "Send me a link from YouTube, TikTok, Instagram, etc., and I'll download "
            "the video/audio for you.\n"
            "Just paste the link to get started!"
        ),
        "help_text": (
            "🤖 **How to use Downloader Bot**\n\n"
            "1. Copy a link to a video or audio from YouTube, TikTok, Instagram, etc.\n"
            "2. Paste the link here and send it to me.\n"
            "3. Choose the desired format and quality from the buttons.\n"
            "4. Wait for the download to finish!\n\n"
            "You can change the language anytime using /language."
        ),
        "start_language_prompt": (
            "Choose the bot interface language below. "
            "English stays the default until you change it."
        ),
        "language_prompt": "Choose your language:",
        "language_updated": "Language updated to {language_name}.",
        "analyzing_link": "Analyzing link...",
        "extract_failed": (
            "Sorry, I couldn't extract media info from this link. "
            "Please try another link or try again later."
        ),
        "media_found": "Media found!",
        "title_label": "Title",
        "duration_label": "Duration",
        "choose_format": "Choose one of the available formats below:",
        "audio_only": "Only audio is available for this link.",
        "unknown": "Unknown",
        "expired_selection": "This selection has expired. Send the link again.",
        "original_link_not_found": "Original link not found.",
        "no_url_found": "No URL found.",
        "rate_limit_exceeded": "Rate limit exceeded. Max 5 downloads per minute.",
        "queued": "Your download is queued.\nPosition: {position}",
        "downloading_media": "Downloading media...",
        "download_failed": "Download failed. Please try again.",
        "uploading_to_telegram": "Uploading to Telegram...",
        "upload_error": "An error occurred during upload.",
        "audio_mp3": "Audio (MP3)",
        "stats_title": "📊 **Bot Statistics**",
        "total_users": "👥 Total Users: `{count}`",
        "total_downloads": "⬇️ Total Downloads: `{count}`",
        "downloads_today": "📅 Downloads Today: `{count}`",
        "broadcast_reply_required": "Please reply to a message you want to broadcast.",
        "broadcast_started": "Broadcast started...",
        "broadcast_finished": (
            "✅ Broadcast finished!\n\n"
            "Successful: `{success}`\n"
            "Failed: `{failed}`"
        ),
        "quality_excellent": "🌟 Excellent Quality",
        "quality_good": "👍 Good Quality",
        "quality_bad": "📉 Bad Quality",
        "more_options": "⬇️ More options",
    },
    "uz": {
        "welcome": (
            "👋 Downloader Bot'ga xush kelibsiz!\n\n"
            "Menga YouTube, TikTok, Instagram va boshqa platformalardan havola yuboring, "
            "men siz uchun video yoki audioni yuklab beraman.\n"
            "Boshlash uchun havolani yuboring!"
        ),
        "help_text": (
            "🤖 **Downloader Bot'dan qanday foydalanish kerak**\n\n"
            "1. YouTube, TikTok, Instagram yoki boshqa tarmoqdan video/audio havolasini nusxalang.\n"
            "2. Havolani shu yerga tashlang va menga yuboring.\n"
            "3. Tugmalar yordamida kerakli format va sifatni tanlang.\n"
            "4. Yuklab olinishini kuting!\n\n"
            "Tilni xohlagan vaqtda /language yordamida o'zgartirishingiz mumkin."
        ),
        "start_language_prompt": (
            "Quyida bot interfeysi tilini tanlang. "
            "Tilni tanlamasangiz, standart til English bo'lib qoladi."
        ),
        "language_prompt": "Tilni tanlang:",
        "language_updated": "Til {language_name} ga o'zgartirildi.",
        "analyzing_link": "Havola tahlil qilinmoqda...",
        "extract_failed": (
            "Kechirasiz, bu havoladan media ma'lumotlarini olib bo'lmadi. "
            "Boshqa havolani yuboring yoki keyinroq qayta urinib ko'ring."
        ),
        "media_found": "Media topildi!",
        "title_label": "Nomi",
        "duration_label": "Davomiyligi",
        "choose_format": "Quyidagi mavjud formatlardan birini tanlang:",
        "audio_only": "Bu havola uchun faqat audio mavjud.",
        "unknown": "Noma'lum",
        "expired_selection": "Bu tanlov muddati tugagan. Havolani qayta yuboring.",
        "original_link_not_found": "Asl havola topilmadi.",
        "no_url_found": "Havola topilmadi.",
        "rate_limit_exceeded": (
            "Limit oshdi. Bir daqiqada eng ko'pi bilan 5 ta yuklab olish mumkin."
        ),
        "queued": "Yuklab olish navbatga qo'yildi.\nNavbat: {position}",
        "downloading_media": "Media yuklab olinmoqda...",
        "download_failed": "Yuklab olish muvaffaqiyatsiz tugadi. Qayta urinib ko'ring.",
        "uploading_to_telegram": "Telegram'ga yuklanmoqda...",
        "upload_error": "Yuklash vaqtida xatolik yuz berdi.",
        "audio_mp3": "Audio (MP3)",
        "stats_title": "📊 **Bot statistikasi**",
        "total_users": "👥 Jami foydalanuvchilar: `{count}`",
        "total_downloads": "⬇️ Jami yuklab olishlar: `{count}`",
        "downloads_today": "📅 Bugungi yuklab olishlar: `{count}`",
        "broadcast_reply_required": "Tarqatmoqchi bo'lgan xabarga javob bering.",
        "broadcast_started": "Tarqatish boshlandi...",
        "broadcast_finished": (
            "✅ Tarqatish yakunlandi!\n\n"
            "Muvaffaqiyatli: `{success}`\n"
            "Xatolik: `{failed}`"
        ),
        "quality_excellent": "🌟 Zo'r Sifat",
        "quality_good": "👍 Yaxshi Sifat",
        "quality_bad": "📉 Past Sifat",
        "more_options": "⬇️ Ko'proq variantlar",
    },
    "ru": {
        "welcome": (
            "👋 Добро пожаловать в Downloader Bot!\n\n"
            "Отправьте мне ссылку с YouTube, TikTok, Instagram и других платформ, "
            "и я скачаю для вас видео или аудио.\n"
            "Просто отправьте ссылку, чтобы начать!"
        ),
        "help_text": (
            "🤖 **Как использовать Downloader Bot**\n\n"
            "1. Скопируйте ссылку на видео или аудио из YouTube, TikTok, Instagram и др.\n"
            "2. Вставьте ссылку сюда и отправьте мне.\n"
            "3. Выберите нужный формат и качество с помощью кнопок.\n"
            "4. Дождитесь окончания загрузки!\n\n"
            "Вы можете изменить язык в любое время с помощью команды /language."
        ),
        "start_language_prompt": (
            "Выберите язык интерфейса бота ниже. "
            "Если ничего не выбирать, по умолчанию останется English."
        ),
        "language_prompt": "Выберите язык:",
        "language_updated": "Язык переключен на {language_name}.",
        "analyzing_link": "Анализирую ссылку...",
        "extract_failed": (
            "Не удалось получить информацию по этой ссылке. "
            "Попробуйте другую ссылку или повторите попытку позже."
        ),
        "media_found": "Медиа найдено!",
        "title_label": "Название",
        "duration_label": "Длительность",
        "choose_format": "Выберите один из доступных форматов:",
        "audio_only": "Для этой ссылки доступно только аудио.",
        "unknown": "Неизвестно",
        "expired_selection": "Срок действия этого выбора истек. Отправьте ссылку еще раз.",
        "original_link_not_found": "Исходная ссылка не найдена.",
        "no_url_found": "Ссылка не найдена.",
        "rate_limit_exceeded": "Превышен лимит. Максимум 5 загрузок в минуту.",
        "queued": "Загрузка добавлена в очередь.\nПозиция: {position}",
        "downloading_media": "Скачиваю медиа...",
        "download_failed": "Не удалось скачать файл. Попробуйте еще раз.",
        "uploading_to_telegram": "Загружаю в Telegram...",
        "upload_error": "Во время загрузки произошла ошибка.",
        "audio_mp3": "Audio (MP3)",
        "stats_title": "📊 **Статистика бота**",
        "total_users": "👥 Всего пользователей: `{count}`",
        "total_downloads": "⬇️ Всего загрузок: `{count}`",
        "downloads_today": "📅 Загрузок сегодня: `{count}`",
        "broadcast_reply_required": "Ответьте на сообщение, которое нужно разослать.",
        "broadcast_started": "Рассылка началась...",
        "broadcast_finished": (
            "✅ Рассылка завершена!\n\n"
            "Успешно: `{success}`\n"
            "Не удалось: `{failed}`"
        ),
        "quality_excellent": "🌟 Отличное качество",
        "quality_good": "👍 Хорошее качество",
        "quality_bad": "📉 Низкое качество",
        "more_options": "⬇️ Больше вариантов",
    },
}


def normalize_language_code(language_code: str | None) -> str:
    if not language_code:
        return DEFAULT_LANGUAGE

    normalized = language_code.strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized if normalized in TRANSLATIONS else DEFAULT_LANGUAGE


def get_language_label(language_code: str) -> str:
    return LANGUAGE_LABELS[normalize_language_code(language_code)]


def t(language_code: str | None, key: str, **kwargs) -> str:
    normalized = normalize_language_code(language_code)
    template = TRANSLATIONS.get(normalized, {}).get(key) or TRANSLATIONS[DEFAULT_LANGUAGE][key]
    return template.format(**kwargs)


def build_language_keyboard(selected_language: str | None) -> "InlineKeyboardMarkup":
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    selected = normalize_language_code(selected_language)
    buttons = []

    for code in LANGUAGE_ORDER:
        prefix = "✓ " if code == selected else ""
        buttons.append(
            InlineKeyboardButton(
                f"{prefix}{LANGUAGE_LABELS[code]}",
                callback_data=f"lang|{code}",
            )
        )

    return InlineKeyboardMarkup([buttons])


def build_welcome_message(language_code: str | None) -> str:
    normalized = normalize_language_code(language_code)
    return f"{t(normalized, 'welcome')}\n\n{t(normalized, 'start_language_prompt')}"
