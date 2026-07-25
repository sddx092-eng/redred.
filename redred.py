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
TOKEN = os.getenv("DISCORD_TOKEN")

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
        # 재생이 끝나면 자동으로 채널 나가기
        if ctx.voice_client:
            asyncio.run_coroutine_threadsafe(ctx.voice_client.disconnect(), bot.loop)
        asyncio.run_coroutine_threadsafe(
            ctx.send("■ 대기열의 모든 노래가 재생되어 음성 채널에서 퇴장했습니다."),
            bot.loop
        )

# =============================================================
# 3. 봇 이벤트
# =============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("--------------------------------------------")

# =============================================================
# 4. 음악 명령어 목록
# =============================================================

# [ !재생 / !p ] -> 검색 시 첫 번째 검색 결과 바로 재생
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str = None):
    if search is None:
        await ctx.send("▶ 재생할 노래 제목이나 링크를 입력해 주세요. (예: `!재생 뉴진스 Hype Boy`)")
        return

    if not ctx.author.voice:
        await ctx.send("▶ 먼저 음성 채널에 입장해 주세요.")
        return

    # 1. 음성 채널 연결 상태 점검 및 안전 접속
    channel = ctx.author.voice.channel
    try:
        if ctx.voice_client is None:
            await channel.connect(reconnect=True, self_deaf=True)
        elif ctx.voice_client.channel.id != channel.id:
            await ctx.voice_client.move_to(channel)
    except Exception as e:
        await ctx.send("▶ 음성 채널에 연결할 수 없습니다. 봇을 다시 시도하거나 `!정지` 후 실행해 주세요.")
        print(f"Voice Connect Error: {e}")
        return

    # 2. 유튜브 정보 추출 (1등 결과 바로 가져오기)
    async with ctx.typing():
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                # search가 url이 아닌 일반 키워드면 ytsearch로 검색
                query = search if search.startswith('http') else f"ytsearch1:{search}"
                info = ytdl.extract_info(query, download=False)
                
                if 'entries' in info:
                    if not info['entries']:
                        await ctx.send("▶ 검색 결과가 없습니다.")
                        return
                    song_info = info['entries'][0]
                else:
                    song_info = info

                stream_url = song_info['url']
                title = song_info.get('title', '제목 없음')
                song_url = song_info.get('webpage_url', search)

        except Exception as e:
            await ctx.send("▶ 음원 정보를 가져오지 못했습니다. (유튜브 차단 제약)")
            print(f"YTDL Error: {e}")
            return

    song_item = {'title': title, 'url': song_url, 'stream_url': stream_url}
    guild_id = ctx.guild.id

    if guild_id not in music_queues:
        music_queues[guild_id] = []

    # 3. 재생 중이면 대기열에 넣고, 없으면 즉시 재생
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        music_queues[guild_id].append(song_item)
        await ctx.send(f" 대기열 추가: **{title}** ({len(music_queues[guild_id])}번째)")
    else:
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        await ctx.send(f"▶ 재생 시작: **{title}**")

# [ !스킵 / !s ]
@bot.command(name="스킵", aliases=["skip", "s"])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("▶ 현재 곡을 스킵했습니다.")
    else:
        await ctx.send("▶ 재생 중인 음악이 없습니다.")

# [ !정지 / !stop ] -> 꼬인 연결 강제 종료 기능 포함
@bot.command(name="정지", aliases=["stop"])
async def stop(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        music_queues[guild_id].clear()

    if ctx.voice_client:
        try:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect(force=True)
        except Exception as e:
            print(f"Disconnect Error: {e}")
        await ctx.send("■ 재생을 정지하고 음성 채널에서 퇴장했습니다.")
    else:
        await ctx.send("▶ 봇이 연결되어 있지 않습니다.")

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
