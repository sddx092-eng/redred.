import os
import asyncio
import discord
from discord.ext import commands
import yt_dlp

# =============================================================
# 0. Render 환경변수 쿠키 자동 복원 (있는 경우)
# =============================================================
cookies_env = os.getenv("YOUTUBE_COOKIES")
if cookies_env:
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(cookies_env)

# =============================================================
# 1. 디스코드 봇 설정
# =============================================================
TOKEN = os.getenv("DISCORD_TOKEN")  # Render Environment Variable에서 가져옵니다

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 음성 대기열 관리 (길드 ID별 목록)
music_queues = {}

# yt-dlp 옵션
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extract_flat': False,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
    'source_address': '0.0.0.0',
}

# FFmpeg 옵션
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# =============================================================
# 2. 대기열 다음 곡 재생 함수
# =============================================================
def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        next_song = music_queues[guild_id].pop(0)
        source = discord.FFmpegPCMAudio(next_song['stream_url'], **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"▶ 다음 곡 재생: **{next_song['title']}**"),
            bot.loop
        )
    else:
        asyncio.run_coroutine_threadsafe(
            ctx.send("■ 대기열의 모든 노래가 재생되었습니다."),
            bot.loop
        )

# =============================================================
# 3. 봇 이벤트 handlers
# =============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("--------------------------------------------")

# =============================================================
# 4. 음악 명령어 목록
# =============================================================

# [ !재생 / !p ]
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str = None):
    # 1. 검색어가 없을 때
    if search is None:
        await ctx.send("▶ 재생할 노래 제목이나 링크를 입력해 주세요. (예: `!재생 뉴진스`)")
        return

    # 2. 유저가 음성 채널에 없을 때
    if not ctx.author.voice:
        await ctx.send("▶ 먼저 음성 채널에 입장해 주세요.")
        return

    async with ctx.typing():
        search_opts = {
            **YTDL_OPTIONS,
            'default_search': 'ytsearch10',
            'extract_flat': 'in_playlist'
        }
        
        try:
            with yt_dlp.YoutubeDL(search_opts) as ytdl:
                info = ytdl.extract_info(search, download=False)
                
                if 'entries' not in info or not info['entries']:
                    await ctx.send("▶ 검색 결과가 없습니다.")
                    return
                
                results = info['entries'][:10]
        except Exception as e:
            await ctx.send("▶ 유튜브 정보를 불러오는 중 오류가 발생했습니다.")
            print(f"Search Error: {e}")
            return

    current_idx = 0

    # 임베드 카트 생성 함수 (단순화된 UI)
    def make_embed(idx):
        item = results[idx]
        title = item.get('title', '제목 없음')
        url = item.get('url') or item.get('webpage_url', '')
        if not url.startswith('http'):
            url = f"https://www.youtube.com/watch?v={url}"
            
        uploader = item.get('uploader', '채널 정보 없음')
        
        embed = discord.Embed(
            title=f"검색 결과 ({idx + 1}/{len(results)})",
            description=f"**[{title}]({url})**\n\n채널: {uploader}",
            color=0x2b2d31
        )
        embed.set_footer(text="◀ 이전 | ▶ 다음 | ✅ 선택")
        return embed

    message = await ctx.send(embed=make_embed(current_idx))

    # 단순한 기본 반응 이모지
    reactions = ["◀", "▶", "✅"]
    for r in reactions:
        await message.add_reaction(r)

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == message.id

    while True:
        try:
            reaction, user = await bot.wait_for("reaction_add", timeout=30.0, check=check)
            emoji = str(reaction.emoji)

            try:
                await message.remove_reaction(reaction, user)
            except:
                pass

            if emoji == "◀":
                current_idx = (current_idx - 1) % len(results)
                await message.edit(embed=make_embed(current_idx))
            elif emoji == "▶":
                current_idx = (current_idx + 1) % len(results)
                await message.edit(embed=make_embed(current_idx))
            elif emoji == "✅":
                selected_item = results[current_idx]
                await message.delete()

                # 음성 채널 연결
                channel = ctx.author.voice.channel
                if ctx.voice_client is None:
                    await channel.connect()

                song_url = selected_item.get('url') or selected_item.get('webpage_url', '')
                if not song_url.startswith('http'):
                    song_url = f"https://www.youtube.com/watch?v={song_url}"

                async with ctx.typing():
                    try:
                        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                            song_info = ytdl.extract_info(song_url, download=False)
                            stream_url = song_info['url']
                            title = song_info['title']
                    except Exception as e:
                        await ctx.send("▶ 음원을 스트리밍할 수 없습니다. (유튜브 차단 제약)")
                        print(f"Play Stream Error: {e}")
                        return

                song_item = {'title': title, 'url': song_url, 'stream_url': stream_url}
                guild_id = ctx.guild.id

                if guild_id not in music_queues:
                    music_queues[guild_id] = []

                if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                    music_queues[guild_id].append(song_item)
                    await ctx.send(f" 대기열 추가: **{title}** ({len(music_queues[guild_id])}번째)")
                else:
                    source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                    ctx.voice_client.play(source, after=lambda e: play_next(ctx))
                    await ctx.send(f"▶ 재생 시작: **{title}**")
                break

        except asyncio.TimeoutError:
            try:
                await message.clear_reactions()
            except:
                pass
            break

# [ !스킵 / !s ]
@bot.command(name="스킵", aliases=["skip", "s"])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("▶ 현재 곡을 스킵했습니다.")
    else:
        await ctx.send("▶ 재생 중인 음악이 없습니다.")

# [ !정지 / !stop ]
@bot.command(name="정지", aliases=["stop"])
async def stop(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        music_queues[guild_id].clear()

    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("■ 재생을 정지하고 음성 채널에서 퇴장했습니다.")
    else:
        await ctx.send("▶ 봇이 음성 채널에 연결되어 있지 않습니다.")

# [ !목록 / !q ]
@bot.command(name="목록", aliases=["queue", "q"])
async def queue_list(ctx):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await ctx.send("▶ 대기열이 비어 있습니다.")
        return

    msg = "**[ 대기열 목록 ]**\n"
    for idx, song in enumerate(music_queues[guild_id], 1):
        msg += f"{idx}. {song['title']}\n"

    await ctx.send(msg)

# =============================================================
# 5. 봇 실행
# =============================================================
if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")
