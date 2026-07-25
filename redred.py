import os
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button
import yt_dlp
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

COLOR_PLAY = 0x5865F2
COLOR_INFO = 0x2B2D31
COLOR_WARN = 0xED4245

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

music_queues = {}

# 쿠키 없이 유튜브 차단을 우회하기 위한 최신 옵션 설정
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extract_flat': False,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['mweb', 'ios']
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        next_song = music_queues[guild_id].pop(0)
        source = discord.FFmpegPCMAudio(next_song['stream_url'], **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        
        embed = discord.Embed(
            title="🎵 다음 곡 재생",
            description=f"**[{next_song['title']}]({next_song['url']})**",
            color=COLOR_PLAY
        )
        asyncio.run_coroutine_threadsafe(ctx.send(embed=embed), bot.loop)
    else:
        if ctx.voice_client and ctx.voice_client.is_connected():
            is_forced = getattr(ctx.voice_client, 'is_forced_stop', False)
            asyncio.run_coroutine_threadsafe(ctx.voice_client.disconnect(), bot.loop)
            
            if not is_forced:
                embed = discord.Embed(
                    description="✅ 대기열의 모든 곡 재생이 완료되어 퇴장했습니다.",
                    color=COLOR_INFO
                )
                asyncio.run_coroutine_threadsafe(ctx.send(embed=embed), bot.loop)

class MusicControlView(View):
    def __init__(self, ctx, song_info):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.song_info = song_info

    @discord.ui.button(label="재생 확정", style=discord.ButtonStyle.primary)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("명령어를 입력한 사람만 누를 수 있어.", ephemeral=True)
            return

        channel = self.ctx.author.voice.channel if self.ctx.author.voice else None
        if not channel:
            await interaction.response.send_message("음성 채널에 먼저 들어가 줘.", ephemeral=True)
            return

        try:
            if self.ctx.voice_client is None:
                await channel.connect(reconnect=True, self_deaf=True)
            elif self.ctx.voice_client.channel.id != channel.id:
                await self.ctx.voice_client.move_to(channel)
        except Exception as e:
            embed = discord.Embed(description="음성 채널 연결에 실패했어.", color=COLOR_WARN)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.ctx.voice_client.is_forced_stop = False

        guild_id = self.ctx.guild.id
        if guild_id not in music_queues:
            music_queues[guild_id] = []

        title = self.song_info['title']
        stream_url = self.song_info['stream_url']
        song_url = self.song_info['url']
        song_item = {'title': title, 'url': song_url, 'stream_url': stream_url}

        self.stop()

        if self.ctx.voice_client.is_playing() or self.ctx.voice_client.is_paused():
            music_queues[guild_id].append(song_item)
            embed = discord.Embed(
                title="📝 대기열 추가",
                description=f"**[{title}]({song_url})**\n\n대기 순서: **{len(music_queues[guild_id])}번째**",
                color=COLOR_INFO
            )
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            self.ctx.voice_client.play(source, after=lambda e: play_next(self.ctx))
            embed = discord.Embed(
                title="▶️ 현재 재생 중",
                description=f"**[{title}]({song_url})**",
                color=COLOR_PLAY
            )
            await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("명령어를 입력한 사람만 누를 수 있어.", ephemeral=True)
            return

        self.stop()
        embed = discord.Embed(description="❌ 재생이 취소되었어.", color=COLOR_WARN)
        await interaction.response.edit_message(embed=embed, view=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    print("--------------------------------------------")

@bot.command(name="재생", aliases=["play", "p"])
async def play(ctx, *, search: str = None):
    if search is None:
        embed = discord.Embed(description="노래 제목이나 링크를 입력해 줘. (예: `!재생 뉴진스`)", color=COLOR_WARN)
        await ctx.send(embed=embed)
        return

    if not ctx.author.voice:
        embed = discord.Embed(description="먼저 음성 채널에 입장해 줘.", color=COLOR_WARN)
        await ctx.send(embed=embed)
        return

    async with ctx.typing():
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                query = search if search.startswith('http') else f"ytsearch1:{search}"
                info = ytdl.extract_info(query, download=False)
                
                if 'entries' in info:
                    if not info['entries']:
                        embed = discord.Embed(description="검색 결과가 없어.", color=COLOR_WARN)
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
            embed = discord.Embed(description="음원 정보를 가져올 수 없어. (유튜브 차단 우회 실패)", color=COLOR_WARN)
            await ctx.send(embed=embed)
            print(f"YTDL Error: {e}")
            return

    embed = discord.Embed(
        title="🔍 검색 결과 확인",
        description=f"**[{title}]({song_url})**\n\n채널: {uploader}",
        color=COLOR_INFO
    )
    
    view = MusicControlView(ctx, {
        'title': title,
        'url': song_url,
        'stream_url': stream_url
    })

    await ctx.send(embed=embed, view=view)

@bot.command(name="스킵", aliases=["skip", "s"])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        embed = discord.Embed(description="⏭️ 곡을 스킵했어.", color=COLOR_WARN)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(description="재생 중인 음악이 없어.", color=COLOR_WARN)
        await ctx.send(embed=embed)

@bot.command(name="정지", aliases=["stop"])
async def stop(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        music_queues[guild_id].clear()

    if ctx.voice_client:
        ctx.voice_client.is_forced_stop = True
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect(force=True)
        
        embed = discord.Embed(description="⏹️ 재생을 정지하고 대기열을 비웠어.", color=COLOR_WARN)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(description="연결된 음성 채널이 없어.", color=COLOR_WARN)
        await ctx.send(embed=embed)

@bot.command(name="목록", aliases=["queue", "q"])
async def queue_list(ctx):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        embed = discord.Embed(description="대기열이 비어 있어.", color=COLOR_INFO)
        await ctx.send(embed=embed)
        return

    description = ""
    for idx, song in enumerate(music_queues[guild_id], 1):
        description += f"**{idx}.** [{song['title']}]({song['url']})\n"

    embed = discord.Embed(
        title="📜 현재 대기열",
        description=description,
        color=COLOR_INFO
    )
    await ctx.send(embed=embed)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"YouTube Music Bot is running!")

def run_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    server.serve_forever()

if __name__ == "__main__":
    if TOKEN:
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN 환경변수가 없어.")
