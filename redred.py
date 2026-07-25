import os
import random
import asyncio
import discord
from discord.ext import commands
import yt-dlp

# -------------------------------------------------------------
# 봇 기본 설정 및 Intents 설정
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 서버(Guild)별 노래 대기열(Queue) 관리 저장소
# 구조: { guild_id: [ {"title": "제목", "url": "원래URL", "stream_url": "오디오스트림URL"}, ... ] }
music_queues = {}

# yt-dlp 옵션
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'default_search': 'ytsearch',
    'quiet': True,
    'no_warnings': True,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# -------------------------------------------------------------
# 음악 재생 헬퍼 함수
# -------------------------------------------------------------
def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        # 대기열의 첫 번째 곡 꺼내기
        next_song = music_queues[guild_id].pop(0)
        
        source = discord.FFmpegPCMAudio(next_song['stream_url'], **FFMPEG_OPTIONS)
        
        # 노래가 끝나면 다음 곡 자동 재생 (재귀)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        
        # 다음 곡 재생 알림 메시지 (비동기 처리)
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🎵 **{next_song['title']}** 을(를) 재생합니다!"),
            bot.loop
        )
    else:
        # 더 이상 재생할 곡이 없으면 대기열 삭제
        if guild_id in music_queues:
            del music_queues[guild_id]


@bot.event
async def on_ready():
    print(f'✅ 봇 성공적으로 로그인 완료: {bot.user.name}')

# =============================================================
# 1. 🎮 롤 5인큐 라인 랜덤 배치 기능
# 사용법: !라인 유저1 유저2 유저3 유저4 유저5
# =============================================================
@bot.command(name="라인")
async def roll_line(ctx, *players):
    if len(players) != 5:
        await ctx.send("❌ 플레이어 5명의 이름을 띄어쓰기로 구분해서 입력해 주세요!\n예시: `!라인 제트 레이나 피닉스 요루 네온     `")
        return

    lanes = ["🔝 탑", "🌲 정글", "⚔️ 미드", "🏹 원딜", "🛡️ 서폿"]
    player_list = list(players)
    
    # 무작위 셔플
    random.shuffle(player_list)
    
    embed = discord.Embed(title="🎮 롤 5인큐 라인 배치 결과", color=0x5865F2)
    for lane, player in zip(lanes, player_list):
        embed.add_field(name=lane, value=player, inline=False)
        
    await ctx.send(embed=embed)

# =============================================================
# 2. 🎵 노래 관련 기능 (재생, 일시정지, 재개, 넘기기, 대기열, 퇴장)
# =============================================================

# [ !재생 / !play ]
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str):
    # 유저가 음성 채널에 있는지 확인
    if not ctx.author.voice:
        await ctx.send("❌ 먼저 음성 채널에 들어간 후 명령어를 사용해 주세요!")
        return

    channel = ctx.author.voice.channel

    # 봇이 접속해 있지 않다면 음성 채널 들어가지
    if ctx.voice_client is None:
        await channel.connect()

    async with ctx.typing():
        # 유튜브 정보 검색/추출
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
            info = ytdl.extract_info(search, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            
            stream_url = info['url']
            title = info['title']
            webpage_url = info.get('webpage_url', search)

    song_item = {
        'title': title,
        'stream_url': stream_url,
        'url': webpage_url
    }

    guild_id = ctx.guild.id

    # 대기열 목록 초기화
    if guild_id not in music_queues:
        music_queues[guild_id] = []

    # 현재 음악이 재생 중이거나 일시정지 중이면 대기열에 추가
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        music_queues[guild_id].append(song_item)
        await ctx.send(f"📑 **{title}** 이(가) 대기열 **{len(music_queues[guild_id])}번째**에 추가되었습니다.")
    else:
        # 아무것도 재생 중이지 않다면 바로 재생
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        await ctx.send(f"🎵 **{title}** 을(를) 재생합니다!")

# [ !정지 / !일시정지 ]
@bot.command(name="일시정지", aliases=["정지", "pause"])
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ 노래를 일시정지했습니다. 다시 재생하려면 `!다시재생`을 입력하세요.")
    else:
        await ctx.send("❌ 현재 재생 중인 노래가 없습니다.")

# [ !다시재생 / !재개 ]
@bot.command(name="다시재생", aliases=["재개", "resume"])
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ 노래를 다시 재생합니다.")
    else:
        await ctx.send("❌ 일시정지된 노래가 없습니다.")

# [ !스킵 / !넘기기 ]
@bot.command(name="스킵", aliases=["넘기기", "skip", "s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()  # 현재 노래를 멈추면 after 함수에 의해 다음 대기열 곡이 바로 실행됨
        await ctx.send("⏭️ 현재 노래를 넘겼습니다.")
    else:
        await ctx.send("❌ 넘길 노래가 없습니다.")

# [ !대기열 / !목록 ]
@bot.command(name="대기열", aliases=["목록", "queue", "q"])
async def queue_list(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        embed = discord.Embed(title="🎶 현재 대기열 목록", color=0x00FFB3)
        for idx, song in enumerate(music_queues[guild_id], start=1):
            embed.add_field(
                name=f"{idx}. {song['title']}",
                value=f"[유튜브 링크]({song['url']})",
                inline=False
            )
        await ctx.send(embed=embed)
    else:
        await ctx.send("📜 현재 대기열에 들어있는 노래가 없습니다.")

# [ !퇴장 / !끄기 ]
@bot.command(name="퇴장", aliases=["leave", "stop"])
async def leave(ctx):
    guild_id = ctx.guild.id
    # 대기열 비우기
    if guild_id in music_queues:
        del music_queues[guild_id]
        
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 음성 채널에서 나갔습니다.")
    else:
        await ctx.send("❌ 봇이 음성 채널에 들어가 있지 않습니다.")

# -------------------------------------------------------------
# 봇 실행 (환경 변수 또는 직접 입력)
# -------------------------------------------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")

# 만약 환경변수를 안 쓴다면 테스트용으로 아래 줄의 주석(#)을 풀고 직접 토큰 입력 가능
# TOKEN = "여기에_진짜_디스코드_토큰_입력"

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN 이 설정되지 않았습니다! 환경 변수를 설정해주세요.")