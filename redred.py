import os
import random
import asyncio
import discord
from discord.ext import commands
import yt_dlp

# -------------------------------------------------------------
# 1. 디스코드 봇 기본 설정
# -------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 서버별 노래 대기열 (Queue)
music_queues = {}

# -------------------------------------------------------------
# 2. yt-dlp & FFmpeg 옵션 (유튜브 봇 차단 방지 포함)
# -------------------------------------------------------------
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    # Render 같은 서버 IP 차단을 막기 위한 핵심 모바일 클라이언트 위장 옵션
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios'],
            'skip': ['webpage', 'authcheck']
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# -------------------------------------------------------------
# 3. 다음 곡 자동 재생 헬퍼 함수
# -------------------------------------------------------------
def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        next_song = music_queues[guild_id].pop(0)
        
        # 음원 스트림 추출
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
            info = ytdl.extract_info(next_song['url'], download=False)
            stream_url = info['url']

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🎵 **{next_song['title']}** 을(를) 재생합니다!"),
            bot.loop
        )
    else:
        if guild_id in music_queues:
            del music_queues[guild_id]

@bot.event
async def on_ready():
    print(f'✅ 봇 성공적으로 로그인 완료: {bot.user.name}')

# =============================================================
# 🎮 롤 5인큐 라인 랜덤 배치
# =============================================================
@bot.command(name="라인")
async def roll_line(ctx, *players):
    if len(players) != 5:
        await ctx.send("❌ 플레이어 5명의 이름을 띄어쓰기로 구분해서 입력해 주세요!\n예시: `!라인 유저1 유저2 유저3 유저4 유저5`")
        return

    lanes = ["🔝 탑", "🌲 정글", "⚔️ 미드", "🏹 원딜", "🛡️ 서폿"]
    player_list = list(players)
    random.shuffle(player_list)
    
    embed = discord.Embed(title="🎮 롤 5인큐 라인 배치 결과", color=0x5865F2)
    for lane, player in zip(lanes, player_list):
        embed.add_field(name=lane, value=player, inline=False)
        
    await ctx.send(embed=embed)

# =============================================================
# 🎵 유튜브 10개 검색 + 화살표 넘기기 + 재생
# =============================================================
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        await ctx.send("❌ 먼저 음성 채널에 들어간 후 명령어를 사용해 주세요!")
        return

    async with ctx.typing():
        # 검색 속도 향상 및 차단 방지를 위한 flat 검색 옵션
        search_opts = {
            **YTDL_OPTIONS,
            'default_search': 'ytsearch10',
            'extract_flat': 'in_playlist'
        }
        
        with yt_dlp.YoutubeDL(search_opts) as ytdl:
            info = ytdl.extract_info(search, download=False)
            
            if 'entries' not in info or not info['entries']:
                await ctx.send("❌ 검색 결과를 찾을 수 없습니다.")
                return
            
            results = info['entries'][:10]

    current_idx = 0

    # 1/10 카드 형태의 임베드 생성 함수
    def make_embed(idx):
        item = results[idx]
        title = item.get('title', '제목 없음')
        url = item.get('url') or item.get('webpage_url', '')
        if not url.startswith('http'):
            url = f"https://www.youtube.com/watch?v={url}"
            
        uploader = item.get('uploader', '채널 정보 없음')
        
        embed = discord.Embed(
            title=f"🔎 검색 결과 ({idx + 1}/{len(results)})",
            description=f"**[{title}]({url})**",
            color=0x00FFB3
        )
        embed.add_field(name="채널/업로더", value=uploader, inline=True)
        embed.set_footer(text="⬅️ 이전 곡 | ➡️ 다음 곡 | ▶️ 이 노래 선택해서 재생")
        return embed

    message = await ctx.send(embed=make_embed(current_idx))

    reactions = ["⬅️", "➡️", "▶️"]
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

            if emoji == "⬅️":
                current_idx = (current_idx - 1) % len(results)
                await message.edit(embed=make_embed(current_idx))
            elif emoji == "➡️":
                current_idx = (current_idx + 1) % len(results)
                await message.edit(embed=make_embed(current_idx))
            elif emoji == "▶️":
                selected_item = results[current_idx]
                await message.delete()

                # 음성 채널 연결
                channel = ctx.author.voice.channel
                if ctx.voice_client is None:
                    await channel.connect()

                # 선택된 곡의 상세 정보 및 스트리밍 URL 추출
                song_url = selected_item.get('url') or selected_item.get('webpage_url', '')
                if not song_url.startswith('http'):
                    song_url = f"https://www.youtube.com/watch?v={song_url}"

                async with ctx.typing():
                    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                        song_info = ytdl.extract_info(song_url, download=False)
                        stream_url = song_info['url']
                        title = song_info['title']

                song_item = {'title': title, 'url': song_url, 'stream_url': stream_url}
                guild_id = ctx.guild.id

                if guild_id not in music_queues:
                    music_queues[guild_id] = []

                # 이미 재생 중이면 대기열에 추가
                if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                    music_queues[guild_id].append(song_item)
                    await ctx.send(f"📑 **{title}** 이(가) 대기열 **{len(music_queues[guild_id])}번째**에 추가되었습니다.")
                else:
                    source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                    ctx.voice_client.play(source, after=lambda e: play_next(ctx))
                    await ctx.send(f"🎵 **{title}** 을(를) 재생합니다!")
                break

        except asyncio.TimeoutError:
            try:
                await message.clear_reactions()
            except:
                pass
            break

# =============================================================
# 🎼 제어 명령어 (일시정지, 재개, 스킵, 대기열, 퇴장)
# =============================================================
@bot.command(name="일시정지", aliases=["정지", "pause"])
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ 노래를 일시정지했습니다.")
    else:
        await ctx.send("❌ 재생 중인 노래가 없습니다.")

@bot.command(name="다시재생", aliases=["재개", "resume"])
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ 노래를 다시 재생합니다.")
    else:
        await ctx.send("❌ 일시정지된 노래가 없습니다.")

@bot.command(name="스킵", aliases=["넘기기", "skip", "s"])
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ 다음 곡으로 넘깁니다.")
    else:
        await ctx.send("❌ 넘길 노래가 없습니다.")

@bot.command(name="대기열", aliases=["목록", "queue", "q"])
async def queue_list(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        embed = discord.Embed(title="🎶 현재 대기열 목록", color=0x00FFB3)
        for idx, song in enumerate(music_queues[guild_id], start=1):
            embed.add_field(name=f"{idx}. {song['title']}", value=f"[링크]({song['url']})", inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send("📜 현재 대기열에 노래가 없습니다.")

@bot.command(name="퇴장", aliases=["leave", "stop"])
async def leave(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        del music_queues[guild_id]
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 음성 채널에서 나갔습니다.")
    else:
        await ctx.send("❌ 봇이 음성 채널에 연결되어 있지 않습니다.")

# -------------------------------------------------------------
# 봇 토큰 실행 (환경 변수)
# -------------------------------------------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
