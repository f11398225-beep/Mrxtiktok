import os
import re
import asyncio
import aiohttp
import aiofiles
import tempfile
import json

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

# ─── Утилиты TikTok ────────────────────────────────────────────────────────────

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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.youtube.com/",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status == 200:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    async with aiofiles.open(tmp.name, "wb") as f:
                        await f.write(await resp.read())
                    if os.path.getsize(tmp.name) > 10000:  # минимум 10KB
                        return tmp.name
                    os.unlink(tmp.name)
    except Exception:
        pass
    return None


# ─── Получение прямой ссылки на MP3 через несколько API ───────────────────────

async def get_youtube_video_id(query: str) -> str | None:
    """Ищет видео на YouTube и возвращает первый video ID."""
    try:
        search_url = "https://www.youtube.com/results?search_query=" + query.replace(" ", "+")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                html = await resp.text()
                ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                return ids[0] if ids else None
    except Exception:
        return None


async def get_mp3_via_loader_to(video_id: str) -> str | None:
    """loader.to API — дает прямую ссылку на MP3."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://loader.to/",
        }
        # Шаг 1 — запрос конвертации
        url = f"https://loader.to/ajax/download.php?format=mp3&url=https://www.youtube.com/watch?v={video_id}"
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
                task_id = data.get("id")
                if not task_id:
                    return None

            # Шаг 2 — ждём готовности
            for _ in range(20):
                await asyncio.sleep(3)
                progress_url = f"https://loader.to/ajax/progress.php?id={task_id}"
                async with session.get(progress_url, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                    progress = await resp2.json()
                    if progress.get("success") == 1:
                        download_url = progress.get("download_url")
                        if download_url:
                            return await download_file(download_url, ".mp3")
    except Exception:
        pass
    return None


async def get_mp3_via_y2mate(video_id: str) -> str | None:
    """y2mate API."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.y2mate.com/",
        }
        # Шаг 1 — анализ
        async with aiohttp.ClientSession(headers=headers) as session:
            data1 = f"k_query=https://www.youtube.com/watch?v={video_id}&k_page=home&hl=en&q_auto=0"
            async with session.post(
                "https://www.y2mate.com/mates/analyzeV2/ajax",
                data=data1,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                result = await resp.json()
                links = result.get("links", {}).get("mp3", {})
                # Берём лучшее качество
                best_key = None
                for key, val in links.items():
                    if "128" in str(val.get("q", "")):
                        best_key = val.get("k")
                        break
                if not best_key and links:
                    best_key = list(links.values())[0].get("k")
                if not best_key:
                    return None

            # Шаг 2 — конвертация
            data2 = f"vid={video_id}&k={best_key}"
            async with session.post(
                "https://www.y2mate.com/mates/convertV2/index",
                data=data2,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                result2 = await resp.json()
                dl_url = result2.get("dlink")
                if dl_url:
                    return await download_file(dl_url, ".mp3")
    except Exception:
        pass
    return None


async def get_mp3_via_cobalt(video_id: str) -> str | None:
    """cobalt.tools — современный конвертер."""
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "downloadMode": "audio",
            "audioFormat": "mp3",
            "audioBitrate": "128",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.cobalt.tools/",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                status = data.get("status")
                if status in ("stream", "redirect", "tunnel"):
                    url = data.get("url")
                    if url:
                        return await download_file(url, ".mp3")
    except Exception:
        pass
    return None


async def download_full_music(artist: str, title: str) -> str | None:
    """Пробует все методы по очереди."""
    query = f"{artist} {title} official audio"
    video_id = await get_youtube_video_id(query)
    if not video_id:
        return None

    # Пробуем методы один за другим
    for method in [get_mp3_via_cobalt, get_mp3_via_loader_to, get_mp3_via_y2mate]:
        path = await method(video_id)
        if path:
            return path

    return None


# ─── Поиск через Deezer ────────────────────────────────────────────────────────

async def search_deezer(query: str) -> list:
    try:
        url = f"https://api.deezer.com/search?q={query.replace(' ', '+')}&limit=5"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                results = []
                for track in data.get("data", []):
                    results.append({
                        "id": track["id"],
                        "title": track["title"],
                        "artist": track["artist"]["name"],
                        "preview": track.get("preview", ""),
                        "duration": track.get("duration", 0),
                    })
                return results
    except Exception:
        return []


# ─── Команды ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 Привет! Меня создал *MRX*, для общения с ним напишите в личку @M\\_R\\_X\\_W\\_H\\_O\\_A\\_M\\_I\n\n"
        "Этот бот создан для скачивания видео/музыки с помощью ссылки TikTok, "
        "а также для поиска и скачивания любой музыки.\n\n"
        "📌 *Что умею:*\n\n"
        "🎬 *TikTok видео* — отправь ссылку:\n"
        "`https://vm.tiktok.com/XXXXX/`\n\n"
        "🎵 *Музыка* — напиши название песни:\n"
        "`Drake God's Plan`\n\n"
        "Попробуй прямо сейчас 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ *Как пользоваться:*\n\n"
        "🎵 Напиши название песни — бот найдёт и скачает полную версию\n"
        "Пример: `Eminem Lose Yourself`\n\n"
        "🎬 Отправь ссылку TikTok — бот скачает видео без водяного знака\n\n"
        "По всем вопросам: @M\\_R\\_X\\_W\\_H\\_O\\_A\\_M\\_I"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "🎵 Напиши название:\n`/music Eminem Lose Yourself`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    await search_and_show_music(update, context, query)


# ─── Обработчик сообщений ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip() if update.message.text else ""
    match = TIKTOK_LINK_PATTERN.search(text)
    if match:
        await handle_tiktok(update, context, match.group(0))
    elif len(text) > 1:
        await search_and_show_music(update, context, text)


# ─── TikTok ────────────────────────────────────────────────────────────────────

async def handle_tiktok(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    message = update.message
    if not url.startswith("http"):
        url = "https://" + url
    await message.chat.send_action(ChatAction.TYPING)
    if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
        url = await resolve_short_url(url)

    msg = await message.reply_text("⏳ Получаю информацию о видео...")
    info = await fetch_tiktok_info(url)

    if not info:
        await msg.edit_text("❌ Не удалось получить видео. Возможно оно приватное или удалено.")
        return

    context.user_data["tiktok_info"] = info
    author = info.get("author", {})
    caption = (
        f"✅ *Видео найдено!*\n\n"
        f"👤 {author.get('nickname', '?')}\n"
        f"📝 {info.get('title', '')[:100]}\n"
        f"⏱ {info.get('duration', 0)} сек. | ❤️ {info.get('digg_count', 0):,}\n\n"
        f"Что скачать?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Видео (без водяного знака)", callback_data="dl_video")],
        [
            InlineKeyboardButton("📱 Видео HD", callback_data="dl_video_hd"),
            InlineKeyboardButton("🎵 Музыка из видео", callback_data="dl_audio"),
        ],
    ])
    await msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


# ─── Поиск музыки ──────────────────────────────────────────────────────────────

async def search_and_show_music(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    msg = await update.message.reply_text(f"🔍 Ищу: *{query}*...", parse_mode=ParseMode.MARKDOWN)

    results = await search_deezer(query)

    if not results:
        await msg.edit_text(
            "❌ Ничего не нашёл. Попробуй иначе.\nПример: `Drake God's Plan`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data["music_results"] = results
    text = "🎵 *Результаты поиска:*\n\n"
    buttons = []

    for i, track in enumerate(results):
        mins = track['duration'] // 60
        secs = track['duration'] % 60
        text += f"{i+1}. *{track['title']}*\n   👤 {track['artist']} | ⏱ {mins}:{secs:02d}\n\n"
        buttons.append([InlineKeyboardButton(
            f"⬇️ {i+1}. {track['artist']} — {track['title'][:30]}",
            callback_data=f"dl_music_{i}"
        )])

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


# ─── Callback ──────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data

    # ── Скачать музыку ──
    if action.startswith("dl_music_"):
        index = int(action.split("_")[-1])
        results = context.user_data.get("music_results", [])
        if index >= len(results):
            await query.edit_message_text("❌ Ошибка. Попробуй снова.")
            return

        track = results[index]
        await query.edit_message_text(
            f"⬇️ Скачиваю: *{track['artist']} — {track['title']}*\n\nПодожди, это займёт 30-60 сек...",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.chat.send_action(ChatAction.UPLOAD_VOICE)

        path = await download_full_music(track["artist"], track["title"])

        if path:
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_audio(
                    audio=await f.read(),
                    title=track["title"][:64],
                    performer=track["artist"][:64],
                    caption=f"🎵 {track['artist']} — {track['title']}",
                )
            os.unlink(path)
            await query.delete_message()
        else:
            await query.edit_message_text(
                f"❌ Не удалось скачать полную версию.\n"
                f"Попробуй другой трек из списка или поищи снова."
            )
        return

    # ── TikTok callbacks ──
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
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
