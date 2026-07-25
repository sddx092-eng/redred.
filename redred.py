import os
import random
import asyncio
import discord
from discord.ext import commands
import yt_dlp

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 서버별 노래 대기열
music_queues = {}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        next_song = music_queues[guild_id].pop(0)
        source = discord.FFmpegPCMAudio(next_song['stream_url'], **FFMPEG_OPTIONS)
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
    print(f'✅ 봇 접속 완료: {bot.user.name}')

# =============================================================
# 1. 🎮 롤 5인큐 라인 랜덤
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
# 2. 🎵 유튜브 10개 검색 + 화살표 선택 + 재생
# =============================================================
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str):
    if not ctx.author.voice:
        await ctx.send("❌ 먼저 음성 채널에 입장해 주세요!")
        return

    async with ctx.typing():
        # 유튜브에서 검색 결과 10개 가져오기 (ytsearch10:)
        search_opts = {**YTDL_OPTIONS, 'default_search': 'ytsearch10'}
        with yt_dlp.YoutubeDL(search_opts) as ytdl:
            info = ytdl.extract_info(search, download=False)
            
            if 'entries' not in info or not info['entries']:
                await ctx.send("❌ 검색 결과를 찾을 수 없습니다.")
                return
            
            results = info['entries'][:10]

    current_idx = 0

    def make_embed(idx):
        item = results[idx]
        title = item.get('title', '제목 없음')
        url = item.get('webpage_url', '')
        uploader = item.get('uploader', '알 수 없음')
        duration = item.get('duration', 0)
        thumbnail = item.get('thumbnail', '')

        # 재생 시간 초 -> 분:초 변환
        m, s = divmod(duration, 60)
        dur_str = f"{m}:{s:02d}" if duration else "라이브/알 수 없음"

        embed = discord.Embed(
            title=f"🔎 검색 결과 ({idx + 1}/{len(results)})",
            description=f"**[{title}]({url})**",
            color=0x00FFB3
        )
        embed.add_field(name="채널", value=uploader, inline=True)
        embed.add_field(name="길이", value=dur_str, inline=True)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.set_footer(text="⬅️ 이전 | ➡️ 다음 | ▶️ 이 노래 재생")
        return embed

    message = await ctx.send(embed=make_embed(current_idx))

    # 반응 이모지 추가
    reactions = ["⬅️", "➡️", "▶️"]
    for r in reactions:
        await message.add_reaction(r)

    def check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in reactions and reaction.message.id == message.id

    while True:
        try:
            # 30초 동안 유저 이모지 클릭 대기
            reaction, user = await bot.wait_for("reaction_remove" if False else "reaction_add", timeout=30.0, check=check)
            emoji = str(reaction.emoji)

            # 이모지 누른 거 지워주기 (권한 있을 때)
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
                # 선택한 곡 재생 시작
                selected_song = results[current_idx]
                await message.delete() # 검색 임베드 삭제

                # 음성 채널 접속
                channel = ctx.author.voice.channel
                if ctx.voice_client is None:
                    await channel.connect()

                stream_url = selected_song['url']
                title = selected_song['title']
                webpage_url = selected_song.get('webpage_url', '')

                song_item = {'title': title, 'stream_url': stream_url, 'url': webpage_url}
                guild_id = ctx.guild.id

                if guild_id not in music_queues:
                    music_queues[guild_id] = []

                if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                    music_queues[guild_id].append(song_item)
                    await ctx.send(f"📑 **{title}** 이(가) 대기열 **{len(music_queues[guild_id])}번째**에 추가되었습니다.")
                else:
                    source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                    ctx.voice_client.play(source, after=lambda e: play_next(ctx))
                    await ctx.send(f"🎵 **{title}** 을(를) 재생합니다!")
                break

        except asyncio.TimeoutError:
            # 30초 동안 클릭 없으면 반응 삭제
            try:
                await message.clear_reactions()
            except:
                pass
            break

# =============================================================
# 3. 기타 음악 제어 명령어
# =============================================================
@bot.command(name="일시정지", aliases=["정지", "pause"])
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ 일시정지했습니다.")
    else:
        await ctx.send("❌ 재생 중인 노래가 없습니다.")

@bot.command(name="다시재생", aliases=["재개", "resume"])
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ 다시 재생합니다.")
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
            embed.add_field(name=f"{idx}. {song['title']}", value=f"[유튜브 링크]({song['url']})", inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send("📜 대기열이 비어있습니다.")

@bot.command(name="퇴장", aliases=["leave", "stop"])
async def leave(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        del music_queues[guild_id]
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 음성 채널에서 나갔습니다.")

TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
