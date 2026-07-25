import os
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button
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

# yt-dlp 옵션 (모바일 앱 위장으로 유튜브 차단 회피)
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extract_flat': False,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'ios'],
            'skip': ['hls', 'dash']
        }
    }
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
        
        embed = discord.Embed(
            title="다음 곡 재생",
            description=f"**[{next_song['title']}]({next_song['url']})**",
            color=0x2b2d31
        )
        asyncio.run_coroutine_threadsafe(ctx.send(embed=embed), bot.loop)
    else:
        if ctx.voice_client:
            asyncio.run_coroutine_threadsafe(ctx.voice_client.disconnect(), bot.loop)
        
        embed = discord.Embed(
            description="대기열의 모든 노래 재생이 완료되어 음성 채널에서 퇴장했습니다.",
            color=0x2b2d31
        )
        asyncio.run_coroutine_threadsafe(ctx.send(embed=embed), bot.loop)

# =============================================================
# 3. 버튼 메뉴 뷰 (View) 클래스
# =============================================================
class MusicControlView(View):
    def __init__(self, ctx, song_info):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.song_info = song_info

    @discord.ui.button(label="재생 확정", style=discord.ButtonStyle.primary)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("명령어를 입력한 사용자만 조작할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()
        self.stop()

        # 음성 채널 접속 처리
        channel = self.ctx.author.voice.channel
        try:
            if self.ctx.voice_client is None:
                await channel.connect(reconnect=True, self_deaf=True)
            elif self.ctx.voice_client.channel.id != channel.id:
                await self.ctx.voice_client.move_to(channel)
        except Exception as e:
            embed = discord.Embed(description="음성 채널 연결 실패. 다시 시도해 주세요.", color=0x2b2d31)
            await self.ctx.send(embed=embed)
            return

        # 대기열 등록 및 재생
        guild_id = self.ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []

        title = self.song_info['title']
        stream_url = self.song_info['stream_url']
        song_url = self.song_info['url']

        song_item = {'title': title, 'url': song_url, 'stream_url': stream_url}

        if self.ctx.voice_client.is_playing() or self.ctx.voice_client.is_paused():
            music_queues[guild_id].append(song_item)
            embed = discord.Embed(
                title="대기열 추가",
                description=f"**[{title}]({song_url})**\n대기 순서: {len(music_queues[guild_id])}번째",
                color=0x2b2d31
            )
            await self.ctx.send(embed=embed)
        else:
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            self.ctx.voice_client.play(source, after=lambda e: play_next(self.ctx))
            embed = discord.Embed(
                title="현재 재생 중",
                description=f"**[{title}]({song_url})**",
                color=0x2b2d31
            )
            await self.ctx.send(embed=embed)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("명령어를 입력한 사용자만 조작할 수 있습니다.", ephemeral=True)
            return

        self.stop()
        embed = discord.Embed(description="재생이 취소되었습니다.", color=0x2b2d31)
        await interaction.response.edit_message(embed=embed, view=None)

# =============================================================
# 4. 봇 이벤트 handlers
# =============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("--------------------------------------------")

# =============================================================
# 5. 음악 명령어 목록
# =============================================================

# [ !재생 / !p ]
@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str = None):
    if search is None:
        embed = discord.Embed(description="재생할 노래 제목이나 링크를 입력해 주세요. (예: `!재생 뉴진스`)", color=0x2b2d31)
        await ctx.send(embed=embed)
        return

    if not ctx.author.voice:
        embed = discord.Embed(description="먼저 음성 채널에 입장해 주세요.", color=0x2b2d31)
        await ctx.send(embed=embed)
        return

    async with ctx.typing():
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                query = search if search.startswith('http') else f"ytsearch1:{search}"
                info = ytdl.extract_info(query, download=False)
                
                if 'entries' in info:
                    if not info['entries']:
                        embed = discord.Embed(description="검색 결과가 없습니다.", color=0x2b2d31)
                        await ctx.send(embed=embed)
                        return
                    song_info = info['entries'][0]
                else:
                    song_info = info

                stream_url = song_info['url']
                title = song_info.get('title', '제목 없음')
                song_url = song_info.get('webpage_url', search)
                uploader = song_info.get('uploader', '채널 정보 없음')

        except Exception as e:
            embed = discord.Embed(description="음원 정보를 가져올 수 없습니다. (유튜브 접속 제한)", color=0x2b2d31)
            await ctx.send(embed=embed)
            print(f"YTDL Error: {e}")
            return

    # 검색 결과 임베드 카드 생성
    embed = discord.Embed(
        title="검색 결과 확인",
        description=f"**[{title}]({song_url})**\n\n채널: {uploader}",
        color=0x2b2d31
    )
    
    view = MusicControlView(ctx, {
        'title': title,
        'url': song_url,
        'stream_url': stream_url
    })

    await ctx.send(embed=embed, view=view)

# [ !스킵 / !s ]
@bot.command(name="스킵", aliases=["skip", "s"])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        embed = discord.Embed(description="현재 곡을 스킵했습니다.", color=0x2b2d31)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(description="재생 중인 음악이 없습니다.", color=0x2b2d31)
        await ctx.send(embed=embed)

# [ !정지 / !stop ]
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
        embed = discord.Embed(description="재생을 정지하고 음성 채널에서 퇴장했습니다.", color=0x2b2d31)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(description="봇이 음성 채널에 연결되어 있지 않습니다.", color=0x2b2d31)
        await ctx.send(embed=embed)

# [ !목록 / !q ]
@bot.command(name="목록", aliases=["queue", "q"])
async def queue_list(ctx):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        embed = discord.Embed(description="대기열이 비어 있습니다.", color=0x2b2d31)
        await ctx.send(embed=embed)
        return

    description = ""
    for idx, song in enumerate(music_queues[guild_id], 1):
        description += f"**{idx}.** [{song['title']}]({song['url']})\n"

    embed = discord.Embed(
        title="현재 대기열 목록",
        description=description,
        color=0x2b2d31
    )
    await ctx.send(embed=embed)

# =============================================================
# 6. 봇 실행
# =============================================================
if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")
