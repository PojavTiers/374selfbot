import discord
import aiohttp
import json
import os
import re
import asyncio
import io

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

    def generate_help(self, category=None, page=1):
        prefix = self.config.get('prefix', '-')
        
        if category is None:
            header = "```ansi\n\u001b[1;36m374 SelfBot | Main Menu\u001b[0m\n\u001b[0;37mPage 1 of 1\u001b[0m\n```"
            body = (
                "```ini\n"
                f"[ UTILITY ] - {prefix}ping, {prefix}avatar, {prefix}setprefix\n"
                f"[ MODERATION ] - {prefix}purge, {prefix}dm\n"
                f"[ FUN ] - {prefix}mock, {prefix}react, {prefix}stop\n"
                f"[ INFO ] - {prefix}userinfo, {prefix}serverinfo\n"
                f"[ RPC ] - {prefix}rpc\n"
                "```"
            )
            footer = f"```ansi\n\u001b[2;30mType {prefix}help <category> to view commands. (e.g. {prefix}help fun)\u001b[0m\n```"
            return f"{header}\n{body}\n{footer}"

        categories = {
            "utility": [
                {"cmd": f"{prefix}ping", "desc": "Check bot latency"},
                {"cmd": f"{prefix}setprefix <char>", "desc": "Change command prefix"},
                {"cmd": f"{prefix}avatar <@user>", "desc": "Get user's avatar"},
                {"cmd": f"{prefix}banner <@user>", "desc": "Get user's profile banner"}
            ],
            "moderation": [
                {"cmd": f"{prefix}purge <1-100>", "desc": "Delete your recent messages"},
                {"cmd": f"{prefix}dm <@user> <msg>", "desc": "Send a direct message"}
            ],
            "fun": [
                {"cmd": f"{prefix}mock <@user>", "desc": "Repeat their messages"},
                {"cmd": f"{prefix}react <@user> <emoji>", "desc": "Auto-react to a user"},
                {"cmd": f"{prefix}stop", "desc": "Stop all mocks and reacts"}
            ],
            "info": [
                {"cmd": f"{prefix}userinfo <@user>", "desc": "Get account details"},
                {"cmd": f"{prefix}serverinfo", "desc": "Get server statistics"}
            ],
            "rpc": [
                {"cmd": f"{prefix}rpc <type> <text>", "desc": "Set custom rich presence"},
                {"cmd": "", "desc": "Types: playing, watching, listening"}
            ]
        }

        cat_lower = category.lower()
        if cat_lower not in categories:
            return "> **Invalid category.** Available: utility, moderation, fun, info, rpc"

        cmds = categories[cat_lower]
        
        items_per_page = 3
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
            if item["cmd"]:
                body_lines.append(f"{item['cmd']}\n> {item['desc']}")
            else:
                body_lines.append(f"> {item['desc']}")
        
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

                category = None
                page = 1
                
                if len(rest_args) >= 1:
                    category = rest_args[0].lower()
                if len(rest_args) >= 2 and rest_args[1].isdigit():
                    page = int(rest_args[1])

                help_text = self.generate_help(category, page)
                await message.channel.send(help_text)

            elif cmd == 'setprefix':
                if rest_args:
                    self.config['prefix'] = rest_args[0]
                    self.save_config()
                    await message.channel.send(f"> **Prefix changed to** `{self.config['prefix']}`")

            elif cmd == 'ping':
                await message.channel.send(f"> **Ping:** `{round(self.latency * 1000, 2)}ms`")

            elif cmd == 'avatar':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
                    return

                avatar_url = target.display_avatar.url if hasattr(target, 'display_avatar') else target.avatar.url
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            file = discord.File(io.BytesIO(img_data), filename="avatar.png")
                            await message.channel.send(f"> **{target.name}’s Avatar**", file=file)
                        else:
                            await message.channel.send("> **Failed to download avatar.**")

            elif cmd == 'banner':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
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
                                await message.channel.send("> **Failed to download banner.**")
                else:
                    await message.channel.send("> **User has no banner.**")

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

            elif cmd == 'dm':
                if len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-dm <@user> <message>`")
                    return
                
                target = await self.resolve_user(message, rest_args[0])
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
                    return
                
                text = " ".join(rest_args[1:])
                try:
                    await target.send(text)
                    await message.channel.send(f"> **Sent DM to** `{target.name}`")
                except Exception:
                    await message.channel.send("> **Failed to send DM** (User has DMs closed).")

            elif cmd == 'mock':
                if not rest_args:
                    await message.channel.send("> **Usage:** `-mock <@user>`")
                    return
                
                target = await self.resolve_user(message, rest_args[0])
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("> **You cannot mock yourself.**")
                    return
                
                self.auto_mocks[str(target.id)] = True
                # FIXED OUTPUT HERE
                await message.channel.send(f"> **Mocking {target.name}**")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-react <@user> <emoji>`")
                    return
                
                target = await self.resolve_user(message, rest_args[0])
                emoji = rest_args[1]
                
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("> **You cannot autoreact to yourself.**")
                    return
                
                self.auto_reacts[str(target.id)] = [emoji]
                await message.channel.send(f"> **Reacting to {target.name} with {emoji}**")

            elif cmd == 'stop':
                self.auto_reacts.clear()
                self.auto_mocks.clear()
                await message.channel.send("> **All auto-reacts and auto-mocks have been cleared.**")

            elif cmd == 'userinfo':
                target = await self.resolve_user(message, rest_args[0] if rest_args else None)
                if not target:
                    await message.channel.send("> **Could not find user.** Try replying to them or pinging them.")
                    return
                
                info_text = (
                    f"> **User:** `{target.name}`\n"
                    f"> **ID:** `{target.id}`\n"
                    f"> **Created:** `{target.created_at.strftime('%Y-%m-%d')}`"
                )
                await message.channel.send(info_text)

            elif cmd == 'serverinfo':
                if not message.guild:
                    await message.channel.send("> **Must be used in a server.**")
                    return
                server_text = (
                    f"> **Server:** `{message.guild.name}`\n"
                    f"> **Members:** `{message.guild.member_count}`\n"
                    f"> **Created:** `{message.guild.created_at.strftime('%Y-%m-%d')}`"
                )
                await message.channel.send(server_text)

            elif cmd == 'rpc':
                if not rest_args or len(rest_args) < 2:
                    await message.channel.send("> **Usage:** `-rpc <playing/watching/listening> <text>`")
                    return
                rtype = rest_args[0].lower()
                text = " ".join(rest_args[1:])
                
                if rtype == 'playing':
                    act = discord.Activity(type=discord.ActivityType.playing, name=text)
                elif rtype == 'watching':
                    act = discord.Activity(type=discord.ActivityType.watching, name=text)
                elif rtype == 'listening':
                    act = discord.Activity(type=discord.ActivityType.listening, name=text)
                else:
                    await message.channel.send("> **Invalid type.** Use playing, watching, or listening.")
                    return
                
                await self.change_presence(activity=act)
                await message.channel.send(f"> **RPC set to** `{rtype}` **{text}**")

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