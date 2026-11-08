import discord
from discord.ext import commands
import aiohttp
import json
import os
import re
import asyncio
import hashlib
from urllib.parse import quote

# --- CONFIGURATION ---
CONFIG_FILE = 'config.json'
TOKENS_RAW = os.getenv('DISCORD_TOKEN')

if not TOKENS_RAW:
    raise ValueError("Please set the DISCORD_TOKEN environment variable.")

TOKENS = [t.strip() for t in TOKENS_RAW.split(',') if t.strip()]
if not TOKENS:
    raise ValueError("No valid tokens found in DISCORD_TOKEN environment variable.")

print(f"Found {len(TOKENS)} token(s). Starting clients...")

RPC_TYPES = ['playing', 'streaming', 'listening', 'watching']


def external_asset(url: str) -> str:
    """
    Wrap an external URL in Discord's mp:external proxy format so user
    accounts render it. Format: mp:external/<hash>/https/<url-encoded>
    The hash is arbitrary but stable; Discord's client just proxies the URL.
    """
    # Discord expects: mp:external/<md5-ish hash>/https/<url path>
    # The hash segment isn't validated strictly; using a stable md5 keeps it consistent.
    h = hashlib.md5(url.encode()).hexdigest()
    # Strip the scheme so we can prefix https/
    if url.startswith("https://"):
        rest = url[len("https://"):]
    elif url.startswith("http://"):
        rest = url[len("http://"):]
    else:
        rest = url
    return f"mp:external/{h}/https/{rest}"


class SafeSelfBot(discord.Client):
    def __init__(self, token_index=0):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.token_index = token_index
        self.config = self.load_config()
        self.user_id = None
        self.last_messages = {}
        self.auto_reacts = {}
        self.rpc_list = []
        self.rpc_task = None
        self.rpc_index = 0

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {"prefix": "-", "safe_mode": True}

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    async def setup_hook(self):
        print(f"[Client {self.token_index + 1}] Logged in as {self.user}")
        await self.change_presence(activity=None)

    async def on_ready(self):
        self.user_id = self.user.id
        print(f'[Client {self.token_index + 1}] Selfbot ready. User ID: {self.user_id}')
        print(f'[Client {self.token_index + 1}] Prefix: {self.config["prefix"]}')

    def bypass_text(self, text):
        if not self.config.get('safe_mode'):
            return text

        def replace_number(match):
            num = int(match.group())
            return "99" if num < 13 else match.group()

        text = re.sub(r'\b\d+\b', replace_number, text)
        text = re.sub(r'underage', 'overage', text, flags=re.IGNORECASE)
        text = re.sub(r'\bi\b', 'you', text, flags=re.IGNORECASE)
        text = re.sub(r'\bme\b', 'you', text, flags=re.IGNORECASE)
        return text

    # --- RPC HELPERS ---
    def build_activity(self, rpc_entry):
        """
        Build a discord.Activity that renders images on USER accounts.
        For user accounts, the reliable path is:
          - type=playing/listening/watching
          - assets={'large_image': <raw or mp:external url>, 'large_text': ...}
        """
        rtype = rpc_entry['type']
        text = rpc_entry['text']
        image = rpc_entry.get('image')
        small = rpc_entry.get('small_image')

        assets = {}
        if image:
            # Pass raw URL; discord.py sends it in assets.large_image.
            # Discord's client proxies external URLs for user accounts.
            assets['large_image'] = image
            assets['large_text'] = text
        if small:
            assets['small_image'] = small

        if rtype == 'playing':
            return discord.Activity(
                type=discord.ActivityType.playing,
                name=text,
                assets=assets,
            )
        elif rtype == 'listening':
            return discord.Activity(
                type=discord.ActivityType.listening,
                name=text,
                assets=assets,
            )
        elif rtype == 'watching':
            return discord.Activity(
                type=discord.ActivityType.watching,
                name=text,
                assets=assets,
            )
        elif rtype == 'streaming':
            # Streaming never renders assets; just the Live button.
            return discord.Streaming(name=text, url="https://twitch.tv/yourusername")
        return None

    async def _rpc_rotation_loop(self):
        try:
            while self.rpc_list:
                if len(self.rpc_list) == 1:
                    self.rpc_index = 0
                    act = self.build_activity(self.rpc_list[0])
                    if act:
                        await self.change_presence(activity=act)
                    await asyncio.sleep(30)
                    continue

                self.rpc_index %= len(self.rpc_list)
                act = self.build_activity(self.rpc_list[self.rpc_index])
                if act:
                    await self.change_presence(activity=act)
                self.rpc_index = (self.rpc_index + 1) % len(self.rpc_list)
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Client {self.token_index + 1}] RPC loop error: {e}")

    def restart_rpc_rotation(self):
        if self.rpc_task and not self.rpc_task.done():
            self.rpc_task.cancel()
        self.rpc_index = 0
        if self.rpc_list:
            self.rpc_task = asyncio.create_task(self._rpc_rotation_loop())

    async def on_message(self, message):
        if message.author == self.user:
            return

        channel_key = str(message.channel.id)
        user_key = str(message.author.id)
        if channel_key not in self.last_messages:
            self.last_messages[channel_key] = {}
        self.last_messages[channel_key][user_key] = message.content

        for uid_str, emojis in self.auto_reacts.items():
            if str(message.author.id) == uid_str and emojis:
                try:
                    for emoji in emojis:
                        await message.add_reaction(emoji)
                except Exception:
                    pass

        if not message.content.startswith(self.config['prefix']):
            return

        args = message.content[len(self.config['prefix']):].strip().split()
        cmd = args[0].lower() if args else ""
        rest_args = args[1:]

        async def get_user_from_arg(arg):
            if arg.startswith('<@') and arg.endswith('>'):
                uid = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
                return await self.fetch_user(uid)
            elif arg.isdigit():
                return await self.fetch_user(int(arg))
            return None

        if cmd == 'help':
            embed = discord.Embed(title="Selfbot Commands", color=0x7289da)
            embed.add_field(name="Utility", value=f"```{self.config['prefix']}help\n{self.config['prefix']}setprefix <char>\n{self.config['prefix']}setpfp <url/@user>\n{self.config['prefix']}customstatus <text>\n{self.config['prefix']}clearstatus\n{self.config['prefix']}userinfo <@user>\n{self.config['prefix']}serverinfo\n{self.config['prefix']}avatar <@user>\n{self.config['prefix']}channel_info\n{self.config['prefix']}say <text>\n{self.config['prefix']}ping```", inline=False)
            embed.add_field(name="Rich Presence", value=f"```{self.config['prefix']}rpc set <type> <text> [image|none] [small_image|none]\n{self.config['prefix']}rpc add <type> <text> [image|none] [small_image|none]\n{self.config['prefix']}rpc clear\n\nTypes: playing, streaming, listening, watching\nImage URLs render on user accounts.\nMultiple entries cycle every 15s.```", inline=False)
            embed.add_field(name="Fun", value=f"```{self.config['prefix']}mock <@user>\n{self.config['prefix']}pack <@user>\n{self.config['prefix']}qs start```", inline=False)
            embed.add_field(name="Autoreact", value=f"```{self.config['prefix']}ar/-react/-autoreact <@user> set <emoji>\n{self.config['prefix']}ar/-react/-autoreact <@user> add <emoji>\n{self.config['prefix']}ar/-react/-autoreact <@user> clear```", inline=False)
            await message.channel.send(embed=embed)

        elif cmd == 'setprefix':
            if rest_args:
                self.config['prefix'] = rest_args[0]
                self.save_config()
                await message.channel.send(f"```Prefix changed to `{self.config['prefix']}````")
            else:
                await message.channel.send(f"```Current prefix: `{self.config['prefix']}````")

        elif cmd == 'setpfp':
            url = None
            if rest_args:
                arg = rest_args[0]
                if arg.startswith('<@') and arg.endswith('>'):
                    uid = arg.replace('<@', '').replace('>', '').replace('!', '')
                    try:
                        user = await self.fetch_user(int(uid))
                        url = user.avatar.url if user.avatar else user.default_avatar.url
                    except Exception:
                        await message.channel.send("```Could not fetch user avatar.```")
                        return
                elif arg.startswith('http'):
                    url = arg
                else:
                    await message.channel.send("```Usage: `<url>` or `@mention````")
                    return
            if url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            img = await resp.read()
                            await self.user.edit(avatar=img)
                            await message.channel.send("```PFP updated!```")
                        else:
                            await message.channel.send("```Failed to download image.```")
            else:
                await message.channel.send("```Provide a URL or mention a user.```")

        elif cmd == 'customstatus' or cmd == 'cs':
            text = " ".join(rest_args)
            if text:
                try:
                    await self.change_presence(activity=discord.CustomActivity(name=text))
                except AttributeError:
                    await self.change_presence(activity=discord.Activity(type=discord.ActivityType.custom, name=" ", state=text))
                await message.channel.send(f"```Custom status set to: `{text}````")
            else:
                await message.channel.send("```Provide status text.```")

        elif cmd == 'clearstatus':
            self.rpc_list.clear()
            if self.rpc_task and not self.rpc_task.done():
                self.rpc_task.cancel()
            await self.change_presence(activity=None)
            await message.channel.send("```Status and RPC cleared.```")

        elif cmd == 'rpc':
            usage = (
                f"```Usage:\n"
                f"{self.config['prefix']}rpc set <type> <text> [image|none] [small_image|none]\n"
                f"{self.config['prefix']}rpc add <type> <text> [image|none] [small_image|none]\n"
                f"{self.config['prefix']}rpc clear\n\n"
                f"Types: {', '.join(RPC_TYPES)}\n"
                f"Example: {self.config['prefix']}rpc set watching 67 https://i.imgur.com/abc.png```"
            )

            if not rest_args:
                await message.channel.send(usage)
                return

            action = rest_args[0].lower()

            if action == 'clear':
                self.rpc_list.clear()
                if self.rpc_task and not self.rpc_task.done():
                    self.rpc_task.cancel()
                await self.change_presence(activity=None)
                await message.channel.send("```All RPC entries cleared.```")
                return

            if action not in ['set', 'add']:
                await message.channel.send("```Unknown action. Use `set`, `add`, or `clear`.```")
                return

            if len(rest_args) < 3:
                await message.channel.send(usage)
                return

            rtype = rest_args[1].lower()
            if rtype not in RPC_TYPES:
                await message.channel.send(f"```Invalid type `{rtype}`. Valid: {', '.join(RPC_TYPES)}```")
                return

            remaining = rest_args[2:]
            image = None
            small_image = None

            # Pull trailing image args (up to 2): could be [large] or [large small]
            def is_img_token(tok):
                tl = tok.lower()
                return tl == 'none' or tl.startswith('http://') or tl.startswith('https://')

            img_tokens = []
            while remaining and is_img_token(remaining[-1]) and len(img_tokens) < 2:
                img_tokens.insert(0, remaining[-1])
                remaining = remaining[:-1]

            if len(img_tokens) == 1:
                image = None if img_tokens[0].lower() == 'none' else img_tokens[0]
            elif len(img_tokens) == 2:
                image = None if img_tokens[0].lower() == 'none' else img_tokens[0]
                small_image = None if img_tokens[1].lower() == 'none' else img_tokens[1]

            text = " ".join(remaining).strip()
            if not text:
                await message.channel.send("```Provide some text for the activity.```")
                return

            entry = {"type": rtype, "text": text, "image": image, "small_image": small_image}

            if action == 'set':
                self.rpc_list = [entry]
                self.restart_rpc_rotation()
                note = []
                if image: note.append(f"image: {image}")
                if small_image: note.append(f"small: {small_image}")
                note_str = f" ({', '.join(note)})" if note else ""
                await message.channel.send(f"```RPC set to: `{rtype}` {text}{note_str}```")
            else:
                self.rpc_list.append(entry)
                self.restart_rpc_rotation()
                await message.channel.send(f"```RPC added: `{rtype}` {text} (total: {len(self.rpc_list)})```")

        elif cmd == 'mock':
            if not rest_args:
                await message.channel.send("```Usage: `-mock <@user>````")
                return
            target_user = await get_user_from_arg(rest_args[0])
            if not target_user:
                await message.channel.send("```Could not find that user.```")
                return
            channel_key = str(message.channel.id)
            user_key = str(target_user.id)
            last_msg_content = self.last_messages.get(channel_key, {}).get(user_key, "No recent messages found.")
            safe_text = self.bypass_text(last_msg_content)
            await message.channel.send(f"```\n{safe_text}\n```")

        elif cmd == 'pack':
            if rest_args:
                await message.channel.send(f"```Pack {rest_args[0]}```")
            else:
                await message.channel.send("```Who do I pack? Mention someone.```")

        elif cmd == 'qs':
            if rest_args and rest_args[0] == 'start':
                await message.channel.send("```Quest tracking started.```")
            else:
                await message.channel.send("```Usage: `-qs start````")

        elif cmd in ['ar', 'react', 'autoreact']:
            if len(rest_args) < 2:
                await message.channel.send("```Usage: `-ar <@user> set/add/clear <emoji>````")
                return
            target_user = await get_user_from_arg(rest_args[0])
            if not target_user:
                await message.channel.send("```Could not find that user.```")
                return
            action = rest_args[1].lower()
            emoji = " ".join(rest_args[2:]) if len(rest_args) > 2 else ""
            user_id_str = str(target_user.id)

            if action == 'set':
                if emoji:
                    self.auto_reacts[user_id_str] = [emoji]
                    await message.channel.send(f"```Autoreact for {target_user} set to: `{emoji}````")
                else:
                    await message.channel.send("```Provide an emoji.```")
            elif action == 'add':
                if emoji:
                    self.auto_reacts.setdefault(user_id_str, [])
                    if emoji not in self.auto_reacts[user_id_str]:
                        self.auto_reacts[user_id_str].append(emoji)
                        await message.channel.send(f"```Added `{emoji}` for {target_user}.```")
                    else:
                        await message.channel.send(f"```Warning: `{emoji}` already in list.```")
                else:
                    await message.channel.send("```Provide an emoji.```")
            elif action == 'clear':
                if user_id_str in self.auto_reacts:
                    del self.auto_reacts[user_id_str]
                    await message.channel.send(f"```Autoreact cleared for {target_user}.```")
                else:
                    await message.channel.send(f"```Warning: No autoreact set for {target_user}.```")
            else:
                await message.channel.send("```Unknown action. Use `set`, `add`, or `clear`.```")

        elif cmd == 'userinfo' or cmd == 'ui':
            target = message.author
            if rest_args:
                target = await get_user_from_arg(rest_args[0]) or target
            if not target:
                await message.channel.send("```Could not find that user.```")
                return
            embed = discord.Embed(title=f"User Info: {target}", color=target.color if target.color else 0x7289da)
            embed.add_field(name="Username", value=f"```{target.name}#{target.discriminator}```", inline=True)
            embed.add_field(name="User ID", value=f"```{target.id}```", inline=True)
            embed.add_field(name="Created At", value=f"```{target.created_at.strftime('%Y-%m-%d %H:%M:%S')}```", inline=True)
            embed.add_field(name="Joined Server At", value=f"```{message.guild.me.joined_at.strftime('%Y-%m-%d %H:%M:%S') if message.guild else 'N/A'}```", inline=True)
            embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
            await message.channel.send(embed=embed)

        elif cmd == 'serverinfo' or cmd == 'si':
            guild = message.guild
            if not guild:
                await message.channel.send("```This command must be used in a server.```")
                return
            embed = discord.Embed(title=f"Server Info: {guild.name}", color=guild.icon.color if guild.icon else 0x7289da)
            embed.add_field(name="Server Name", value=f"```{guild.name}```", inline=True)
            embed.add_field(name="Server ID", value=f"```{guild.id}```", inline=True)
            embed.add_field(name="Owner", value=f"```{guild.owner.name}#{guild.owner.discriminator}```", inline=True)
            embed.add_field(name="Members", value=f"```{guild.member_count}```", inline=True)
            embed.add_field(name="Channels", value=f"```Text: {len(guild.text_channels)}\nVoice: {len(guild.voice_channels)}```", inline=False)
            embed.add_field(name="Roles", value=f"```{len(guild.roles)}```", inline=True)
            embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
            await message.channel.send(embed=embed)

        elif cmd == 'avatar' or cmd == 'av':
            target = message.author
            if rest_args:
                target = await get_user_from_arg(rest_args[0]) or target
            if not target:
                await message.channel.send("```Could not find that user.```")
                return
            embed = discord.Embed(title=f"Avatar of {target}", color=0x7289da)
            embed.set_image(url=target.avatar.url if target.avatar else target.default_avatar.url)
            await message.channel.send(embed=embed)

        elif cmd == 'ping':
            await message.channel.send(f"```Ping: {round(self.latency * 1000, 2)}ms```")

        elif cmd == 'say':
            text = " ".join(rest_args)
            if text:
                await message.channel.send(f"```{text}```")
            else:
                await message.channel.send("```Provide text to say.```")

        elif cmd == 'channel_info' or cmd == 'ci':
            channel = message.channel
            embed = discord.Embed(title=f"Channel Info: {channel.name}", color=0x7289da)
            embed.add_field(name="Channel Name", value=f"```{channel.name}```", inline=True)
            embed.add_field(name="Channel ID", value=f"```{channel.id}```", inline=True)
            embed.add_field(name="Category", value=f"```{channel.category.name if channel.category else 'None'}```", inline=True)
            embed.add_field(name="Topic", value=f"```{channel.topic or 'No topic'}```", inline=False)
            embed.add_field(name="Position", value=f"```{channel.position}```", inline=True)
            embed.add_field(name="NSFW", value=f"```{channel.nsfw}```", inline=True)
            await message.channel.send(embed=embed)

        else:
            pass

    async def on_message_delete(self, message):
        channel_key = str(message.channel.id)
        user_key = str(message.author.id)
        if channel_key in self.last_messages and user_key in self.last_messages[channel_key]:
            del self.last_messages[channel_key][user_key]

    async def on_message_update(self, before, after):
        if before.content != after.content:
            channel_key = str(after.channel.id)
            user_key = str(after.author.id)
            self.last_messages.setdefault(channel_key, {})[user_key] = after.content


def run_all_clients():
    clients = [SafeSelfBot(token_index=i) for i in range(len(TOKENS))]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def start_all():
        tasks = [c.start(t) for c, t in zip(clients, TOKENS)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"[Client {i + 1}] Crashed: {r}")

    try:
        loop.run_until_complete(start_all())
    except KeyboardInterrupt:
        print("Shutting down all clients...")
    finally:
        for c in clients:
            if not c.is_closed():
                loop.run_until_complete(c.close())
        loop.close()


if __name__ == "__main__":
    run_all_clients()