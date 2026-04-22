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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8791890747:AAHr3-wJt1z9965wYk8FoTbzasQdCXeXfn8")
TIKTOK_API_URL = "https://tikwm.com/api/"
TIKTOK_LINK_PATTERN = re.compile(
    r"(https?://)?(www\.)?(vm\.|vt\.)?tiktok\.com/[\w\-/@]+"
)

# ─── Утилиты ───────────────────────────────────────────────────────────────────

async def resolve_short_url(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15), headers={"User-Agent": "Mozilla/5.0"}) as resp:
                return str(resp.url)
    except Exception:
        return url


async def fetch_tiktok_info(url: str) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TIKTOK_API_URL, data={"url": url, "hd": "1"}, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    return data.get("data")
    except Exception:
        pass
    return None


async def download_file(url: str, suffix: str) -> str | None:
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    async with aiofiles.open(tmp.name, "wb") as f:
                        await f.write(await resp.read())
                    return tmp.name
    except Exception:
        pass
    return None

# ─── Поиск через YouTube (yt-dlp) ─────────────────────────────────────────────

async def search_youtube(query: str) -> list:
    """Ищет треки через yt-dlp поиск YouTube."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            f"ytsearch5:{query}",
            "--dump-json",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "--default-search", "ytsearch",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        results = []
        for line in stdout.decode().strip().split("\n"):
            if not line:
                continue
            try:
                import json
                info = json.loads(line)
                results.append({
                    "title": info.get("title", "Unknown"),
                    "artist": info.get("uploader", "Unknown"),
                    "duration": info.get("duration", 0),
                    "video_id": info.get("id", ""),
                })
            except Exception:
                continue
        return results
    except Exception:
        return []


async def download_ytdlp(video_id: str) -> str | None:
    """Скачивает полный MP3 через yt-dlp + ffmpeg."""
    try:
        tmp = tempfile.mktemp()
        out_template = tmp + ".%(ext)s"
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "128K",
            "--output", out_template,
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        result = tmp + ".mp3"
        if os.path.exists(result) and os.path.getsize(result) > 100000:
            return result
    except Exception:
        pass
    return None

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
        "🎬 Отправь ссылку TikTok — скачает видео без водяного знака\n\n"
        "По всем вопросам: @M\\_R\\_X\\_W\\_H\\_O\\_A\\_M\\_I"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

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
    if any(x in url for x in ["vm.tiktok.com", "vt.tiktok.com"]):
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
        [InlineKeyboardButton("📱 Видео HD", callback_data="dl_video_hd"),
         InlineKeyboardButton("🎵 Музыка из видео", callback_data="dl_audio")],
    ])
    await msg.edit_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

# ─── Поиск музыки ──────────────────────────────────────────────────────────────

async def search_and_show_music(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    msg = await update.message.reply_text(f"🔍 Ищу: *{query}*...", parse_mode=ParseMode.MARKDOWN)

    results = await search_youtube(query + " official audio")

    if not results:
        await msg.edit_text("❌ Ничего не нашёл. Попробуй иначе.\nПример: `Drake God's Plan`", parse_mode=ParseMode.MARKDOWN)
        return

    context.user_data["music_results"] = results
    text = "🎵 *Результаты поиска:*\n\n"
    buttons = []
    for i, track in enumerate(results[:5]):
        mins = track['duration'] // 60
        secs = track['duration'] % 60
        text += f"{i+1}. *{track['title']}*\n   👤 {track['artist']} | ⏱ {mins}:{secs:02d}\n\n"
        buttons.append([InlineKeyboardButton(
            f"⬇️ {i+1}. {track['title'][:40]}",
            callback_data=f"dl_music_{i}"
        )])

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

# ─── Callback ──────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action = query.data

    if action.startswith("dl_music_"):
        index = int(action.split("_")[-1])
        results = context.user_data.get("music_results", [])
        if index >= len(results):
            await query.edit_message_text("❌ Ошибка. Попробуй снова.")
            return

        track = results[index]
        await query.edit_message_text(
            f"⬇️ Скачиваю: *{track['title']}*\nПодожди 20-40 сек...",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.chat.send_action(ChatAction.UPLOAD_VOICE)

        path = await download_ytdlp(track["video_id"])
        if not path:
            await query.edit_message_text("❌ Не удалось скачать. Попробуй другой вариант.")
            return

        async with aiofiles.open(path, "rb") as f:
            await query.message.reply_audio(
                audio=await f.read(),
                title=track["title"][:64],
                performer=track["artist"][:64],
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
                await query.edit_message_text("❌ Ссылка не найдена.")
                return
            path = await download_file(video_url, ".mp4")
            if not path:
                await query.edit_message_text("❌ Не удалось скачать.")
                return
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(video=await f.read(), caption=f"🎬 {info.get('title', '')[:200]}", supports_streaming=True)
            os.unlink(path)
            await query.delete_message()

        elif action == "dl_video_hd":
            video_url = info.get("hdplay") or info.get("play")
            if not video_url:
                await query.edit_message_text("❌ HD недоступно.")
                return
            path = await download_file(video_url, ".mp4")
            if not path:
                await query.edit_message_text("❌ Не удалось скачать.")
                return
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_video(video=await f.read(), caption=f"📱 HD: {info.get('title', '')[:200]}", supports_streaming=True)
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
                await query.edit_message_text("❌ Не удалось скачать.")
                return
            music_title = music.get("title", info.get("title", "TikTok Audio"))
            music_author = music.get("author", "Unknown")
            async with aiofiles.open(path, "rb") as f:
                await query.message.reply_audio(audio=await f.read(), title=music_title[:64], performer=music_author[:64], caption=f"🎵 {music_title}")
            os.unlink(path)
            await query.delete_message()

    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)[:200]}")

# ─── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("🤖 Бот запущен!")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

if __name__ == "__main__":
    main()
