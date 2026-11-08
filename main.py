import discord
import aiohttp
import json
import os
import re
import asyncio
import io
import random
import urllib.parse
import datetime

# --- CONFIGURATION ---
CONFIG_FILE = 'config.json'
TOKENS_RAW = os.getenv('DISCORD_TOKEN')

if not TOKENS_RAW:
    raise ValueError("Please set the DISCORD_TOKEN environment variable.")

TOKENS = [t.strip().strip('"').strip("'") for t in TOKENS_RAW.split(',') if t.strip()]
if not TOKENS:
    raise ValueError("No valid tokens found in DISCORD_TOKEN environment variable.")

print(f"Found {len(TOKENS)} token(s). Starting clients...")

class SafeSelfBot(discord.Client):
    def __init__(self, token_index=0):
        super().__init__(self_bot=True)
        self.token_index = token_index
        self.config = self.load_config()
        self.user_id = None
        self.auto_reacts = {}
        self.auto_mocks = {} 
        self.cached_users = {} 
        self.processed_messages = set()
        
        self.sniped_messages = {}
        self.editsniped_messages = {}
        self.current_rpc = None
        self.help_message_id = None 

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {"prefix": "-", "safe_mode": True}

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    async def on_ready(self):
        self.user_id = self.user.id
        print(f'[Client {self.token_index + 1}] Selfbot ready. User ID: {self.user_id}')
        print(f'[Client {self.token_index + 1}] Prefix: {self.config["prefix"]}')
        
        try:
            await self.change_presence(activity=None)
        except Exception:
            pass

    async def on_member_join(self, member):
        self.cached_users[member.id] = member

    async def on_member_update(self, before, after):
        self.cached_users[after.id] = after

    async def on_user_update(self, before, after):
        self.cached_users[after.id] = after

    async def on_message_delete(self, message):
        if not message.author.bot and message.guild:
            self.sniped_messages[message.channel.id] = (message.content, message.author, datetime.datetime.now())

    async def on_message_edit(self, before, after):
        if not before.author.bot and before.guild and before.content != after.content:
            self.editsniped_messages[before.channel.id] = (before.content, after.content, before.author)

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

    async def resolve_user(self, message, arg):
        if message.mentions:
            return message.mentions[0]
        if message.reference and message.reference.resolved:
            if isinstance(message.reference.resolved, discord.Message):
                return message.reference.resolved.author
                
        target_id = None
        if arg and arg.startswith('<@') and arg.endswith('>'):
            target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
        elif arg and arg.isdigit():
            target_id = int(arg)
            
        if target_id:
            if target_id in self.cached_users:
                return self.cached_users[target_id]
            if message.guild:
                member = message.guild.get_member(target_id)
                if member:
                    self.cached_users[target_id] = member
                    return member
            try:
                return await self.fetch_user(target_id)
            except Exception:
                return None
        return None

    # --- SWAPPED TO A RELIABLE API (Nekos.best) ---
    async def get_anime_gif(self, category):
        # Map commands to Nekos.best endpoints
        endpoint_map = {
            'hug': 'hug',
            'slap': 'slap',
            'kiss': 'kiss',
            'pat': 'pat'
        }
        endpoint = endpoint_map.get(category, 'hug')
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://nekos.best/api/v2/{endpoint}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data['results'][0]['url']
            except Exception as e:
                print(f"GIF API Error: {e}")
        return None

    def generate_help(self, category=None, page=1):
        prefix = self.config.get('prefix', '-')
        
        if category is None:
            header = "```ansi\n\u001b[1;36m374 SelfBot | Main Menu\u001b[0m\n\u001b[0;37mPage 1 of 1\u001b[0m\n```"
            body = (
                "```ini\n"
                f"[ UTILITY ] - {prefix}ping, {prefix}avatar, {prefix}setbio\n"
                f"[ MODERATION ] - {prefix}purge, {prefix}dm, {prefix}leaveall\n"
                f"[ FUN ] - {prefix}mock, {prefix}react, {prefix}hug, {prefix}8ball\n"
                f"[ INFO ] - {prefix}userinfo, {prefix}snowflake\n"
                f"[ RPC ] - {prefix}rpc playing, {prefix}rpc image\n"
                "```"
            )
            footer = f"```ansi\n\u001b[2;30mType {prefix}help <category> to view commands. (e.g. {prefix}help fun)\u001b[0m\n```"
            return f"{header}\n{body}\n{footer}"

        categories = {
            "utility": [
                {"cmd": f"{prefix}ping", "desc": "Check bot latency"},
                {"cmd": f"{prefix}setprefix <char>", "desc": "Change command prefix"},
                {"cmd": f"{prefix}avatar <@user>", "desc": "Get user's avatar"},
                {"cmd": f"{prefix}banner <@user>", "desc": "Get user's profile banner"},
                {"cmd": f"{prefix}setbio <text>", "desc": "Change your profile bio"},
                {"cmd": f"{prefix}setstatus <status> [text]", "desc": "Change status and text"},
                {"cmd": f"{prefix}serverbanner", "desc": "Get server banner"},
                {"cmd": f"{prefix}servericon", "desc": "Get server icon"},
                {"cmd": f"{prefix}snowflake <ID>", "desc": "Get creation date of an ID"},
                {"cmd": f"{prefix}joined <@user>", "desc": "When they joined the server"},
                {"cmd": f"{prefix}created <@user>", "desc": "When they created account"},
                {"cmd": f"{prefix}channelinfo", "desc": "Info about current channel"},
                {"cmd": f"{prefix}invite", "desc": "Get server invite"},
                {"cmd": f"{prefix}poll <question>", "desc": "Simple 10s text poll"}
            ],
            "moderation": [
                {"cmd": f"{prefix}purge <1-100>", "desc": "Delete your recent messages"},
                {"cmd": f"{prefix}purgeuser <@user>", "desc": "Delete their recent messages"},
                {"cmd": f"{prefix}purgebots", "desc": "Delete bot messages"},
                {"cmd": f"{prefix}purgeimages", "desc": "Delete images"},
                {"cmd": f"{prefix}purgecontains <text>", "desc": "Delete messages with text"},
                {"cmd": f"{prefix}dm <@user> <msg>", "desc": "Send DM"},
                {"cmd": f"{prefix}massdm <msg>", "desc": "DM everyone in server"},
                {"cmd": f"{prefix}ghostping", "desc": "Ping and instantly delete"},
                {"cmd": f"{prefix}snipe / s", "desc": "See last deleted message"},
                {"cmd": f"{prefix}editsnipe / es", "desc": "See last edited message"},
                {"cmd": f"{prefix}clearreactions", "desc": "Remove reactions from a msg"},
                {"cmd": f"{prefix}block <@user>", "desc": "Block a user"},
                {"cmd": f"{prefix}unblock <@user>", "desc": "Unblock a user"},
                {"cmd": f"{prefix}leaveall", "desc": "Leave EVERY server"}
            ],
            "fun": [
                {"cmd": f"{prefix}mock <@user>", "desc": "Repeat their messages"},
                {"cmd": f"{prefix}react <@user> <emoji>", "desc": "Auto-react to a user"},
                {"cmd": f"{prefix}stopmock / stopreact / stop", "desc": "Stop actions"},
                {"cmd": f"{prefix}spam <amount> <msg>", "desc": "Spam text"},
                {"cmd": f"{prefix}uwuify <text>", "desc": "Turns text into UwU"},
                {"cmd": f"{prefix}reverse <text>", "desc": "Reverses text"},
                {"cmd": f"{prefix}ascii <text>", "desc": "Turns text into ASCII art"},
                {"cmd": f"{prefix}8ball <question>", "desc": "Magic 8-ball"},
                {"cmd": f"{prefix}coinflip", "desc": "Heads or tails"},
                {"cmd": f"{prefix}roll <number>", "desc": "Roll a dice"},
                {"cmd": f"{prefix}meme", "desc": "Random meme"},
                {"cmd": f"{prefix}hug <@user>", "desc": "Hug someone (GIF)"},
                {"cmd": f"{prefix}slap <@user>", "desc": "Slap someone (GIF)"},
                {"cmd": f"{prefix}kiss <@user>", "desc": "Kiss someone (GIF)"},
                {"cmd": f"{prefix}pat <@user>", "desc": "Pat someone (GIF)"},
                {"cmd": f"{prefix}ship <@user1> <@user2>", "desc": "Calculate love %"},
                {"cmd": f"{prefix}iq <@user>", "desc": "Calculate IQ"},
                {"cmd": f"{prefix}rate <text>", "desc": "Rate something out of 10"}
            ],
            "info": [
                {"cmd": f"{prefix}userinfo <@user>", "desc": "Account details"},
                {"cmd": f"{prefix}botinfo", "desc": "Info about the selfbot"},
                {"cmd": f"{prefix}uptime", "desc": "Bot uptime"},
                {"cmd": f"{prefix}status <@user>", "desc": "Their current status"},
                {"cmd": f"{prefix}about <@user>", "desc": "Their bio"},
                {"cmd": f"{prefix}connections <@user>", "desc": "Linked accounts"},
                {"cmd": f"{prefix}guilds", "desc": "List all servers you are in"},
                {"cmd": f"{prefix}blocked", "desc": "List all blocked users"}
            ],
            "rpc": [
                {"cmd": f"{prefix}rpc <type> <text>", "desc": "Set RPC (playing/watching/etc)"},
                {"cmd": f"{prefix}rpc image <url>", "desc": "Add image to current RPC"},
                {"cmd": f"{prefix}rpc streaming <text> <url>", "desc": "Set streaming RPC"},
                {"cmd": f"{prefix}clearrpc", "desc": "Remove RPC"}
            ]
        }

        cat_lower = category.lower()
        if cat_lower not in categories:
            return "> **Invalid category.** Available: utility, moderation, fun, info, rpc"

        cmds = categories[cat_lower]
        items_per_page = 5 
        total_pages = max(1, -(-len(cmds) // items_per_page))
        
        if page < 1: page = 1
        if page > total_pages: page = total_pages

        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        page_cmds = cmds[start_idx:end_idx]

        header = (
            "```ansi\n"
            f"\u001b[1;36m374 SelfBot | {cat_lower.capitalize()} Commands\u001b[0m\n"
            f"\u001b[0;37mPage {page} of {total_pages}\u001b[0m\n"
            "```"
        )

        body_lines = []
        for item in page_cmds:
            body_lines.append(f"{item['cmd']}\n> {item['desc']}")
        
        body = "```ini\n" + "\n\n".join(body_lines) + "\n```"

        nav_hints = []
        if page > 1:
            nav_hints.append(f"Prev: {prefix}help {cat_lower} {page-1}")
        if page < total_pages:
            nav_hints.append(f"Next: {prefix}help {cat_lower} {page+1}")
        
        if nav_hints:
            footer_text = " | ".join(nav_hints)
        else:
            footer_text = f"Type {prefix}help to go back to main menu."

        footer = f"```ansi\n\u001b[2;30m{footer_text}\u001b[0m\n```"

        return f"{header}\n{body}\n{footer}"

    async def on_message(self, message):
        if message.id in self.processed_messages:
            return
        self.processed_messages.add(message.id)
        
        if len(self.processed_messages) > 500:
            self.processed_messages.clear()

        if message.author.bot:
            return

        self.cached_users[message.author.id] = message.author

        if message.author.id != self.user.id:
            if str(message.author.id) in self.auto_reacts:
                for emoji in self.auto_reacts[str(message.author.id)]:
                    try:
                        await message.add_reaction(emoji)
                    except Exception:
                        pass
            
            if str(message.author.id) in self.auto_mocks:
                safe_text = self.bypass_text(message.content)
                if safe_text.strip(): 
                    await message.channel.send(safe_text)
            
            return 

        prefix = self.config.get('prefix', '-')
        if not message.content.startswith(prefix):
            return

        args = message.content[len(prefix):].strip().split()
        cmd = args[0].lower() if args else ""
        rest_args = args[1:]

        try:
            if cmd == 'help':
                try:
                    await message.delete()
                except Exception:
                    pass
                    
                if self.help_message_id:
                    try:
                        old_msg = await message.channel.fetch_message(self.help_message_id)
                        await old_msg.delete()
                    except Exception:
                        pass

                category = None
                page = 1
                
                if len(rest_args) >= 1:
                    category = rest_args[0].lower()
                if len(rest_args) >= 2 and rest_args[1].isdigit():
                    page = int(rest_args[1])

                help_text = self.generate_help(category, page)
                new_help_msg = await message.channel.send(help_text)
                self.help_message_id = new_help_msg.id

            # --- UTILITY ---
            elif cmd == 'setprefix':
                if rest_args:
                    self.config['prefix'] = rest_args[0]
                    self.save_config()
                    await message.channel.send(f"> **Prefix changed to** `{self.config['prefix']}`")

            elif cmd == 'ping':
                await message.channel.send(f"> **Ping:** `{round(self.latency * 1000, 2)}ms`")

            elif cmd == 'setbio':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-setbio <text>`")
                    return
                bio = " ".join(rest_args)
                try:
                    await self.user.edit(about_me=bio)
                    await message.channel.send(f"> **Bio changed to** `{bio}`")
                except Exception:
                    await message.channel.send("> **Failed to change bio.** Discord may have blocked it.")

            elif cmd == 'setstatus':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-setstatus <online/idle/dnd/invisible> [text]`")
                    return
                status_type = rest_args[0].lower()
                text = " ".join(rest_args[1:]) if len(rest_args) > 1 else None
                
                status_map = {
                    'online': discord.Status.online,
                    'idle': discord.Status.idle,
                    'dnd': discord.Status.do_not_disturb,
                    'invisible': discord.Status.invisible
                }
                
                if status_type in status_map:
                    act = discord.CustomActivity(name=text) if text else None
                    await self.change_presence(status=status_map[status_type], activity=act)
                    await message.channel.send(f"> **Status set to** `{status_type}` **with text** `{text if text else 'None'}`")
                else:
                    await message.channel.send("> **Invalid status.** Use online, idle, dnd, or invisible.")

            elif cmd == 'avatar':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.**")
                    return
                avatar_url = target.display_avatar.url if hasattr(target, 'display_avatar') else target.avatar.url
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            file = discord.File(io.BytesIO(img_data), filename="avatar.png")
                            await message.channel.send(f"> **{target.name}’s Avatar**", file=file)

            elif cmd == 'banner':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.**")
                    return
                if hasattr(target, 'banner') and target.banner:
                    banner_url = target.banner.url
                    async with aiohttp.ClientSession() as session:
                        async with session.get(banner_url) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                file = discord.File(io.BytesIO(img_data), filename="banner.png")
                                await message.channel.send(f"> **{target.name}’s Banner**", file=file)
                else:
                    await message.channel.send("> **User has no banner.**")

            elif cmd == 'serverbanner':
                if not message.guild or not message.guild.banner:
                    await message.channel.send("> **No server banner.**")
                    return
                async with aiohttp.ClientSession() as session:
                    async with session.get(message.guild.banner.url) as resp:
                        if resp.status == 200:
                            file = discord.File(io.BytesIO(await resp.read()), filename="serverbanner.png")
                            await message.channel.send("> **Server Banner**", file=file)

            elif cmd == 'servericon':
                if not message.guild or not message.guild.icon:
                    await message.channel.send("> **No server icon.**")
                    return
                async with aiohttp.ClientSession() as session:
                    async with session.get(message.guild.icon.url) as resp:
                        if resp.status == 200:
                            file = discord.File(io.BytesIO(await resp.read()), filename="servericon.png")
                            await message.channel.send("> **Server Icon**", file=file)

            elif cmd == 'snowflake':
                if not rest_args or not rest_args[0].isdigit():
                    await message.channel.send("> **Usage:** `-snowflake <ID>`")
                    return
                try:
                    timestamp = ((int(rest_args[0]) >> 22) + 1420070400000) / 1000
                    dt = datetime.datetime.fromtimestamp(timestamp)
                    await message.channel.send(f"> **Created on:** `{dt.strftime('%Y-%m-%d %H:%M:%S')}`")
                except Exception:
                    await message.channel.send("> **Invalid ID.**")

            elif cmd == 'joined':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target and message.guild:
                    member = message.guild.get_member(target.id)
                    if member and member.joined_at:
                        await message.channel.send(f"> **{target.name} joined on:** `{member.joined_at.strftime('%Y-%m-%d')}`")
                    else:
                        await message.channel.send("> **User not in server.**")

            elif cmd == 'created':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    await message.channel.send(f"> **{target.name} created account on:** `{target.created_at.strftime('%Y-%m-%d')}`")

            elif cmd == 'channelinfo':
                ch = message.channel
                await message.channel.send(f"> **Channel:** `{ch.name}`\n> **ID:** `{ch.id}`\n> **NSFW:** `{ch.is_nsfw()}`")

            elif cmd == 'invite':
                if message.guild:
                    try:
                        inv = await message.channel.create_invite(max_age=0, max_uses=0)
                        await message.channel.send(f"> **Invite:** {inv.url}")
                    except Exception:
                        await message.channel.send("> **Failed to create invite.**")

            elif cmd == 'poll':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-poll <question>`")
                    return
                question = " ".join(rest_args)
                msg = await message.channel.send(f"> **Poll:** {question}")
                await msg.add_reaction("👍")
                await msg.add_reaction("👎")
                await asyncio.sleep(10)
                try:
                    await msg.delete()
                    await message.channel.send(f"> **Poll ended:** `{question}`")
                except Exception:
                    pass

            # --- MODERATION ---
            elif cmd == 'purge':
                if not rest_args or not rest_args[0].isdigit():
                    await message.channel.send("> **Usage:** `-purge <amount>`")
                    return
                amount = min(int(rest_args[0]), 100) 
                deleted = 0
                async for msg in message.channel.history(limit=200):
                    if msg.author.id == self.user.id and deleted < amount:
                        try:
                            await msg.delete()
                            deleted += 1
                        except Exception:
                            pass
                await message.channel.send(f"> **Purged** `{deleted}` **messages.**")

            elif cmd == 'purgeuser':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.**")
                    return
                deleted = 0
                async for msg in message.channel.history(limit=200):
                    if msg.author.id == target.id and deleted < 50:
                        try:
                            await msg.delete()
                            deleted += 1
                            await asyncio.sleep(1) 
                        except Exception:
                            pass
                await message.channel.send(f"> **Purged** `{deleted}` **messages from {target.name}.**")

            elif cmd == 'purgebots':
                deleted = 0
                async for msg in message.channel.history(limit=100):
                    if msg.author.bot and deleted < 50:
                        try:
                            await msg.delete()
                            deleted += 1
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                await message.channel.send(f"> **Purged** `{deleted}` **bot messages.**")

            elif cmd == 'purgeimages':
                deleted = 0
                async for msg in message.channel.history(limit=100):
                    if msg.attachments and deleted < 50:
                        try:
                            await msg.delete()
                            deleted += 1
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                await message.channel.send(f"> **Purged** `{deleted}` **images.**")

            elif cmd == 'purgecontains':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-purgecontains <text>`")
                    return
                text_to_find = " ".join(rest_args).lower()
                deleted = 0
                async for msg in message.channel.history(limit=100):
                    if text_to_find in msg.content.lower() and deleted < 50:
                        try:
                            await msg.delete()
                            deleted += 1
                            await asyncio.sleep(1)
                        except Exception:
                            pass
                await message.channel.send(f"> **Purged** `{deleted}` **messages containing that text.**")

            elif cmd == 'dm':
                if len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-dm <@user> <message>`")
                    return
                target = await self.resolve_user(message, rest_args[0])
                if not target:
                    await message.channel.send("> **Could not find user.**")
                    return
                text = " ".join(rest_args[1:])
                try:
                    await target.send(text)
                    await message.channel.send(f"> **Sent DM to** `{target.name}`")
                except Exception:
                    await message.channel.send("> **Failed to send DM.**")

            elif cmd == 'massdm':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-massdm <msg>`")
                    return
                text = " ".join(rest_args)
                sent = 0
                await message.channel.send("> **Starting Mass DM...**")
                if message.guild:
                    for member in message.guild.members:
                        if not member.bot and member.id != self.user.id:
                            try:
                                await member.send(text)
                                sent += 1
                                await asyncio.sleep(2) 
                            except Exception:
                                pass
                await message.channel.send(f"> **Mass DM finished. Sent to** `{sent}` **users.**")

            elif cmd == 'ghostping':
                try:
                    await message.delete()
                except Exception:
                    pass
                ping_msg = await message.channel.send(message.author.mention)
                await asyncio.sleep(1)
                try:
                    await ping_msg.delete()
                except Exception:
                    pass

            elif cmd in ['snipe', 's']:
                if message.channel.id in self.sniped_messages:
                    content, author, time = self.sniped_messages[message.channel.id]
                    await message.channel.send(f"> **Sniped:** `{content}`\n> **Author:** `{author.name}`")
                else:
                    await message.channel.send("> **Nothing to snipe.**")

            elif cmd in ['editsnipe', 'es']:
                if message.channel.id in self.editsniped_messages:
                    before, after, author = self.editsniped_messages[message.channel.id]
                    await message.channel.send(f"> **Before:** `{before}`\n> **After:** `{after}`\n> **Author:** `{author.name}`")
                else:
                    await message.channel.send("> **Nothing to edit snipe.**")

            elif cmd == 'clearreactions':
                if message.reference and message.reference.resolved:
                    try:
                        await message.reference.resolved.clear_reactions()
                        await message.channel.send("> **Cleared reactions.**")
                    except Exception:
                        await message.channel.send("> **Failed to clear reactions.**")

            elif cmd == 'block':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    try:
                        await target.block()
                        await message.channel.send(f"> **Blocked** `{target.name}`")
                    except Exception:
                        await message.channel.send("> **Failed to block.**")

            elif cmd == 'unblock':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    try:
                        await target.unblock()
                        await message.channel.send(f"> **Unblocked** `{target.name}`")
                    except Exception:
                        await message.channel.send("> **Failed to unblock.**")

            elif cmd == 'leaveall':
                await message.channel.send("> **Leaving all servers...**")
                for guild in self.guilds:
                    try:
                        await guild.leave()
                        await asyncio.sleep(1)
                    except Exception:
                        pass
                await message.channel.send("> **Left all servers.**")

            # --- FUN ---
            elif cmd == 'mock':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-mock <@user>`")
                    return
                target = await self.resolve_user(message, rest_args[0])
                if target:
                    self.auto_mocks[str(target.id)] = True
                    await message.channel.send(f"> **Mocking {target.name}**")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-react <@user> <emoji>`")
                    return
                target = await self.resolve_user(message, rest_args[0])
                emoji = rest_args[1]
                if target:
                    self.auto_reacts[str(target.id)] = [emoji]
                    await message.channel.send(f"> **Reacting to {target.name} with {emoji}**")

            elif cmd == 'stopmock':
                self.auto_mocks.clear()
                await message.channel.send("> **Stopped mocking.**")

            elif cmd == 'stopreact':
                self.auto_reacts.clear()
                await message.channel.send("> **Stopped reacting.**")

            elif cmd == 'stop':
                self.auto_mocks.clear()
                self.auto_reacts.clear()
                await message.channel.send("> **Stopped all.**")

            elif cmd == 'spam':
                if len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-spam <amount> <msg>`")
                    return
                amount = min(int(rest_args[0]), 10) if rest_args[0].isdigit() else 0
                text = " ".join(rest_args[1:])
                for _ in range(amount):
                    await message.channel.send(text)
                    await asyncio.sleep(1)
                await message.channel.send("> **Spam finished.**")

            elif cmd == 'uwuify':
                if not rest_args:
                    return
                text = " ".join(rest_args)
                uwu = text.replace("r", "w").replace("l", "w").replace("R", "W").replace("L", "W") + " uwu"
                await message.channel.send(f"> {uwu}")

            elif cmd == 'reverse':
                if not rest_args:
                    return
                await message.channel.send(f"> `{rest_args[0][::-1]}`")

            elif cmd == 'ascii':
                if not rest_args:
                    return
                ascii_out = " ".join([f":regional_indicator_{c.lower()}:" for c in " ".join(rest_args) if c.isalpha()])
                await message.channel.send(f"> {ascii_out[:2000] if ascii_out else 'No letters.'}")

            elif cmd == '8ball':
                if not rest_args:
                    return
                responses = ["Yes.", "No.", "Maybe.", "Definitely.", "Absolutely not.", "Ask again later."]
                await message.channel.send(f"> **Question:** {(' '.join(rest_args))}\n> **Answer:** `{random.choice(responses)}`")

            elif cmd == 'coinflip':
                await message.channel.send(f"> **Result:** `{random.choice(['Heads', 'Tails'])}`")

            elif cmd == 'roll':
                max_num = int(rest_args[0]) if rest_args and rest_args[0].isdigit() else 6
                await message.channel.send(f"> **Rolled:** `{random.randint(1, max_num)}`")

            elif cmd == 'meme':
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://meme-api.com/gimme") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            await message.channel.send(f"> **{data['title']}**\n{data['url']}")

            elif cmd in ['hug', 'slap', 'kiss', 'pat']:
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.**")
                    return
                
                gif_url = await self.get_anime_gif(cmd)
                if gif_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(gif_url) as resp:
                            if resp.status == 200:
                                file = discord.File(io.BytesIO(await resp.read()), filename="action.gif")
                                await message.channel.send(f"> **{message.author.name}** {cmd}s **{target.name}**", file=file)
                            else:
                                # Fallback if image download fails
                                await message.channel.send(f"> **{message.author.name}** {cmd}s **{target.name}**")
                else:
                    # Fallback if API fails completely
                    await message.channel.send(f"> **{message.author.name}** {cmd}s **{target.name}**")

            elif cmd == 'ship':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    pct = random.randint(1, 100)
                    await message.channel.send(f"> **{message.author.name} + {target.name} = {pct}%**")

            elif cmd == 'iq':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    await message.channel.send(f"> **{target.name}'s IQ is** `{random.randint(1, 200)}`")

            elif cmd == 'rate':
                if not rest_args:
                    return
                await message.channel.send(f"> **Rating** `{(' '.join(rest_args))}`: **{random.randint(1, 10)}/10**")

            # --- INFO ---
            elif cmd == 'userinfo':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    info_text = (
                        f"> **User:** `{target.name}`\n"
                        f"> **ID:** `{target.id}`\n"
                        f"> **Created:** `{target.created_at.strftime('%Y-%m-%d')}`"
                    )
                    await message.channel.send(info_text)

            elif cmd == 'botinfo':
                await message.channel.send(f"> **374 SelfBot**\n> **Ping:** `{round(self.latency * 1000, 2)}ms`\n> **Python:** `3.9+`\n> **Library:** `discord.py-self`")

            elif cmd == 'uptime':
                await message.channel.send("> **Bot has been running since deployment.**")

            elif cmd == 'status':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    await message.channel.send(f"> **{target.name}'s status is** `{target.status}`")

            elif cmd == 'about':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target and hasattr(target, 'bio'):
                    await message.channel.send(f"> **{target.name}'s bio:** `{target.bio if target.bio else 'None'}`")

            elif cmd == 'connections':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if target:
                    try:
                        conns = await target.connections()
                        if conns:
                            await message.channel.send(f"> **{target.name} has {len(conns)} connections.**")
                        else:
                            await message.channel.send(f"> **{target.name} has no connections.**")
                    except Exception:
                        await message.channel.send("> **Failed to fetch connections.**")

            elif cmd == 'guilds':
                guilds = [g.name for g in self.guilds]
                await message.channel.send(f"> **You are in {len(guilds)} servers.**\n> `{', '.join(guilds)[:1000]}`")

            elif cmd == 'blocked':
                try:
                    blocked = await self.fetch_blocked_users()
                    await message.channel.send(f"> **You have blocked {len(blocked)} users.**")
                except Exception:
                    await message.channel.send("> **Failed to fetch blocked users.**")

            # --- RPC ---
            elif cmd == 'rpc':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-rpc <playing/watching/listening/streaming> <text> [url]`")
                    return
                rtype = rest_args[0].lower()
                text = rest_args[1] if len(rest_args) > 1 else ""
                
                if rtype in ['playing', 'watching', 'listening']:
                    act = discord.Activity(type=getattr(discord.ActivityType, rtype), name=text)
                    self.current_rpc = act
                    await self.change_presence(activity=act)
                    await message.channel.send(f"> **RPC set to** `{rtype}` **{text}**")
                
                elif rtype == 'streaming' and len(rest_args) >= 3:
                    url = rest_args[2]
                    act = discord.Streaming(name=text, url=url)
                    self.current_rpc = act
                    await self.change_presence(activity=act)
                    await message.channel.send(f"> **RPC set to streaming** `{text}`")

                elif rtype == 'image':
                    if not rest_args[1:]:
                        await message.channel.send("> **Usage:** `-rpc image <url>`")
                        return
                    img_url = rest_args[1]
                    
                    if self.current_rpc:
                        self.current_rpc.assets = {'large_image': img_url}
                        await self.change_presence(activity=self.current_rpc)
                        await message.channel.send("> **Added image to current RPC.**")
                    else:
                        act = discord.Activity(type=discord.ActivityType.playing, name="374 SelfBot", assets={'large_image': img_url})
                        self.current_rpc = act
                        await self.change_presence(activity=act)
                        await message.channel.send("> **Created new RPC with image.**")

            elif cmd == 'clearrpc':
                self.current_rpc = None
                await self.change_presence(activity=None)
                await message.channel.send("> **RPC cleared.**")

        except Exception as e:
            await message.channel.send(f"> **Error:** `{str(e)}`")

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