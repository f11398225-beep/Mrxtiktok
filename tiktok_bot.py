import os
import re
import asyncio
import aiohttp
import aiofiles
import tempfile

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

TIKTOK_API_URL = "https://tikwm.com/api/"

TIKTOK_LINK_PATTERN = re.compile(
    r"(https?://)?(www\.)?(vm\.|vt\.)?tiktok\.com/[\w\-/@]+"
)

# ─── Утилиты ───────────────────────────────────────────────────────────────────

async def resolve_short_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return str(resp.url)
    except Exception:
        return url


async def fetch_tiktok_info(url: str) -> dict | None:
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
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    async with aiofiles.open(tmp.name, "wb") as f:
                        await f.write(await resp.read())
                    return tmp.name
    except Exception:
        pass
    return None


async def search_youtube_music(query: str) -> list:
    """Ищет музыку через YouTube без API ключа используя ytdl API."""
    try:
        search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                html = await resp.text()
                # Извлекаем video ID из HTML
                video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}\]', html)
                channels = re.findall(r'"ownerText":{"runs":\[{"text":"([^"]+)"', html)

                results = []
                seen = set()
                for i, vid_id in enumerate(video_ids[:10]):
                    if vid_id not in seen:
                        seen.add(vid_id)
                        title = titles[i] if i < len(titles) else "Неизвестно"
                        channel = channels[i] if i < len(channels) else "Неизвестно"
                        results.append({
                            "id": vid_id,
                            "title": title,
                            "channel": channel,
                            "url": f"https://www.youtube.com/watch?v={vid_id}"
                        })
                    if len(results) >= 5:
                        break
                return results
    except Exception:
        return []


async def download_youtube_audio(video_id: str) -> str | None:
    """Скачивает аудио с YouTube через cobalt.tools API."""
    try:
        api_url = "https://api.cobalt.tools/api/json"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "vCodec": "h264",
            "vQuality": "720",
            "aFormat": "mp3",
            "isAudioOnly": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json()
                if data.get("status") in ("stream", "redirect", "tunnel"):
                    audio_url = data.get("url")
                    if audio_url:
                        return await download_file(audio_url, ".mp3")
    except Exception:
        pass

    # Резервный метод — через y2mate-like API
    try:
        api_url = f"https://yt-download.org/api/button/mp3/{video_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
                download_url = data.get("url") or data.get("dlink")
                if download_url:
                    return await download_file(download_url, ".mp3")
    except Exception:
        pass

    return None


# ─── Обработчики команд ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Привет! Я медиа-бот*\n\n"
        "Что я умею:\n\n"
        "🎵 *Поиск и скачивание музыки*\n"
        "Просто напиши название песни, например:\n"
        "`Eminem Lose Yourself`\n\n"
        "🎬 *Скачивание TikTok видео*\n"
        "Отправь ссылку на TikTok:\n"
        "`https://vm.tiktok.com/XXXXX/`\n\n"
        "Попробуй прямо сейчас! 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ *Как пользоваться:*\n\n"
        "🎵 *Музыка* — напиши название песни и исполнителя\n"
        "Пример: `Drake God's Plan`\n\n"
        "🎬 *TikTok* — отправь ссылку на видео\n"
        "Пример: `https://vm.tiktok.com/ABC123`\n\n"
        "🔍 Команда /music — поиск музыки"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "🎵 Напиши название песни после команды:\n`/music Eminem Lose Yourself`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    await search_and_show_music(update, context, query)


# ─── Основной обработчик сообщений ────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text.strip() if message.text else ""

    # Проверяем — это ссылка TikTok?
    match = TIKTOK_LINK_PATTERN.search(text)
    if match:
        await handle_tiktok(update, context, match.group(0))
        return

    # Иначе считаем что это поиск музыки
    if len(text) > 1:
        await search_and_show_music(update, context, text)


# ─── TikTok логика ─────────────────────────────────────────────────────────────

async def handle_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    message = update.message
    if not url.startswith("http"):
        url = "https://" + url

    await message.chat.send_action(ChatAction.TYPING)

    if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
        url = await resolve_short_url(url)

    processing_msg = await message.reply_text("⏳ Получаю информацию о видео...")
    info = await fetch_tiktok_info(url)

    if not info:
        await processing_msg.edit_text(
            "❌ Не удалось получить видео.\n"
            "Возможно видео приватное или удалено."
        )
        return

    context.user_data["tiktok_info"] = info

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
        [InlineKeyboardButton("🎬 Видео (без водяного знака)", callback_data="dl_video")],
        [
            InlineKeyboardButton("📱 Видео HD", callback_data="dl_video_hd"),
            InlineKeyboardButton("🎵 Музыка из видео", callback_data="dl_audio"),
        ],
    ])

    await processing_msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


# ─── Музыкальный поиск ─────────────────────────────────────────────────────────

async def search_and_show_music(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    message = update.message
    await message.chat.send_action(ChatAction.TYPING)

    searching_msg = await message.reply_text(f"🔍 Ищу: *{query}*...", parse_mode=ParseMode.MARKDOWN)

    results = await search_youtube_music(query)

    if not results:
        await searching_msg.edit_text(
            "❌ Ничего не нашёл. Попробуй написать по-другому.\n"
            "Пример: `Drake God's Plan`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data["music_results"] = results

    text = "🎵 *Результаты поиска:*\n\n"
    keyboard_buttons = []

    for i, track in enumerate(results):
        text += f"{i+1}. *{track['title']}*\n   👤 {track['channel']}\n\n"
        keyboard_buttons.append([
            InlineKeyboardButton(
                f"⬇️ {i+1}. {track['title'][:35]}",
                callback_data=f"dl_music_{i}"
            )
        ])

    await searching_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard_buttons))


# ─── Callback обработчик ───────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data

    # ── Музыка ──
    if action.startswith("dl_music_"):
        index = int(action.split("_")[-1])
        results = context.user_data.get("music_results", [])

        if index >= len(results):
            await query.edit_message_text("❌ Ошибка. Попробуй снова.")
            return

        track = results[index]
        await query.edit_message_text(f"⬇️ Скачиваю: *{track['title']}*\nПодожди...", parse_mode=ParseMode.MARKDOWN)
        await query.message.chat.send_action(ChatAction.UPLOAD_VOICE)

        path = await download_youtube_audio(track["id"])

        if not path:
            await query.edit_message_text(
                f"❌ Не удалось скачать эту песню.\n"
                f"Попробуй другой вариант из списка."
            )
            return

        async with aiofiles.open(path, "rb") as f:
            await query.message.reply_audio(
                audio=await f.read(),
                title=track["title"][:64],
                performer=track["channel"][:64],
                caption=f"🎵 {track['title']}",
            )
        os.unlink(path)
        await query.delete_message()
        return

    # ── TikTok ──
    info = context.user_data.get("tiktok_info")
    if not info:
        await query.edit_message_text("❌ Сессия устарела. Отправь ссылку снова.")
        return

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
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(
                    video=await f.read(),
                    caption=f"🎬 {info.get('title', '')[:200]}",
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
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(
                    video=await f.read(),
                    caption=f"📱 HD: {info.get('title', '')[:200]}",
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
        await query.edit_message_text(f"❌ Ошибка: {str(e)[:200]}")


# ─── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("music", cmd_music))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
