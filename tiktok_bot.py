import os
import re
import asyncio
import aiohttp
import aiofiles
import tempfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode, ChatAction

# ─── Конфигурация ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8791890747:AAHr3-wJt1z9965wYk8FoTbzasQdCXeXfn8")

TIKTOK_API_URL = "https://tikwm.com/api/"  # Бесплатный API без ключа

TIKTOK_LINK_PATTERN = re.compile(
    r"(https?://)?(www\.)?(vm\.|vt\.)?tiktok\.com/[\w\-/@]+"
)


# ─── Утилиты ───────────────────────────────────────────────────────────────────

async def resolve_short_url(url: str) -> str:
    """Разворачивает короткие ссылки TikTok (vm.tiktok.com)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return str(resp.url)
    except Exception:
        return url


async def fetch_tiktok_info(url: str) -> dict | None:
    """Получает информацию о видео через tikwm.com API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TIKTOK_API_URL,
                data={"url": url, "hd": "1"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    return data.get("data")
    except Exception:
        pass
    return None


async def download_file(url: str, suffix: str) -> str | None:
    """Скачивает файл во временную папку и возвращает путь."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    async with aiofiles.open(tmp.name, "wb") as f:
                        await f.write(await resp.read())
                    return tmp.name
    except Exception:
        pass
    return None


# ─── Обработчики ───────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Привет! Меня создал MRX, для общение с ним напишите ему в личку @M_R_X_W_H_O_A_M_I Этот бот создан для скачивание видео/музыки С помощью ссылки тик тока.*\n\n"
        "Просто отправь мне *ссылку на TikTok видео* — и я скачаю его для тебя.\n\n"
        "📌 Поддерживаемые форматы ссылок:\n"
        "• `https://www.tiktok.com/@user/video/...`\n"
        "• `https://vm.tiktok.com/XXXXX/`\n"
        "• `https://vt.tiktok.com/XXXXX/`\n\n"
        "Я могу дать тебе:\n"
        "🎬 *Видео без водяного знака*\n"
        "🎵 *Только музыку (MP3)*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ *Как пользоваться ботом:*\n\n"
        "1️⃣ Скопируй ссылку на видео TikTok\n"
        "2️⃣ Отправь её мне в чат\n"
        "3️⃣ Выбери что скачать: видео или музыку\n\n"
        "⚡ Всё просто!"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text.strip() if message.text else ""

    # Ищем TikTok ссылку в сообщении
    match = TIKTOK_LINK_PATTERN.search(text)
    if not match:
        await message.reply_text(
            "❌ Не нашёл ссылку TikTok в твоём сообщении.\n"
            "Попробуй скопировать ссылку ещё раз."
        )
        return

    url = match.group(0)
    if not url.startswith("http"):
        url = "https://" + url

    # Покажем индикатор загрузки
    await message.chat.send_action(ChatAction.TYPING)

    # Разворачиваем короткую ссылку
    if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
        url = await resolve_short_url(url)

    processing_msg = await message.reply_text("⏳ MRX Получает информацию о видео...")

    info = await fetch_tiktok_info(url)

    if not info:
        await processing_msg.edit_text(
            "❌ Не удалось получить информацию о видео.\n\n"
            "Возможные причины:\n"
            "• Видео приватное или удалено\n"
            "• Неверная ссылка\n"
            "• Попробуй позже"
        )
        return

    # Сохраняем данные в context.user_data
    context.user_data["tiktok_info"] = info

    # Формируем превью
    author = info.get("author", {})
    nickname = author.get("nickname", "Неизвестно")
    desc = info.get("title", "Без описания")[:100]
    duration = info.get("duration", 0)
    play_count = info.get("play_count", 0)
    like_count = info.get("digg_count", 0)

    caption = (
        f"✅ *Видео найдено!*\n\n"
        f"👤 Автор: {nickname}\n"
        f"📝 {desc}\n"
        f"⏱ Длительность: {duration} сек.\n"
        f"▶️ Просмотры: {play_count:,}\n"
        f"❤️ Лайки: {like_count:,}\n\n"
        f"Что скачать?"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Видео (без водяного знака)", callback_data="dl_video"),
        ],
        [
            InlineKeyboardButton("📱 Видео HD", callback_data="dl_video_hd"),
            InlineKeyboardButton("🎵 Музыка MP3", callback_data="dl_audio"),
        ],
    ])

    await processing_msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    info = context.user_data.get("tiktok_info")
    if not info:
        await query.edit_message_text("❌ Сессия устарела. Отправь ссылку снова.")
        return

    action = query.data
    await query.edit_message_text("⬇️ Скачиваю файл, подожди...")
    await query.message.chat.send_action(ChatAction.UPLOAD_VIDEO)

    try:
        if action == "dl_video":
            video_url = info.get("play") or info.get("wmplay")
            if not video_url:
                await query.edit_message_text("❌ Ссылка на видео не найдена.")
                return

            path = await download_file(video_url, ".mp4")
            if not path:
                await query.edit_message_text("❌ Не удалось скачать видео.")
                return

            caption = f"🎬 {info.get('title', '')[:200]}"
            await query.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(
                    video=await f.read(),
                    caption=caption,
                    supports_streaming=True,
                )
            os.unlink(path)
            await query.delete_message()

        elif action == "dl_video_hd":
            video_url = info.get("hdplay") or info.get("play")
            if not video_url:
                await query.edit_message_text("❌ HD версия недоступна.")
                return

            path = await download_file(video_url, ".mp4")
            if not path:
                await query.edit_message_text("❌ Не удалось скачать HD видео.")
                return

            caption = f"📱 HD: {info.get('title', '')[:200]}"
            await query.message.chat.send_action(ChatAction.UPLOAD_VIDEO)
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(
                    video=await f.read(),
                    caption=caption,
                    supports_streaming=True,
                )
            os.unlink(path)
            await query.delete_message()

        elif action == "dl_audio":
            music = info.get("music_info", {})
            audio_url = music.get("play") or info.get("music")
            if not audio_url:
                await query.edit_message_text("❌ Музыка не найдена.")
                return

            path = await download_file(audio_url, ".mp3")
            if not path:
                await query.edit_message_text("❌ Не удалось скачать музыку.")
                return

            music_title = music.get("title", info.get("title", "TikTok Audio"))
            music_author = music.get("author", "Unknown")

            await query.message.chat.send_action(ChatAction.UPLOAD_VOICE)
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_audio(
                    audio=await f.read(),
                    title=music_title[:64],
                    performer=music_author[:64],
                    caption=f"🎵 {music_title}",
                )
            os.unlink(path)
            await query.delete_message()

    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка при скачивании: {str(e)[:200]}")


# ─── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
