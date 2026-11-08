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
        self.active_channels = set() 
        self.cache_task = None

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
        
        if self.cache_task is None or self.cache_task.done():
            self.cache_task = asyncio.create_task(self.background_cache_refresher())

    async def background_cache_refresher(self):
        while True:
            try:
                for channel in list(self.active_channels):
                    try:
                        async for msg in channel.history(limit=20):
                            if not msg.author.bot:
                                self.cached_users[msg.author.id] = msg.author
                    except Exception:
                        pass 
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(3) 

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

    async def get_cached_user(self, message, arg):
        target_id = None
        if arg.startswith('<@') and arg.endswith('>'):
            target_id = int(arg.replace('<@', '').replace('>', '').replace('!', ''))
        elif arg.isdigit():
            target_id = int(arg)
        
        if not target_id:
            return None
            
        if target_id in self.cached_users:
            return self.cached_users[target_id]
            
        if message.guild:
            member = message.guild.get_member(target_id)
            if member:
                self.cached_users[target_id] = member
                return member

        try:
            user = await self.fetch_user(target_id)
            self.cached_users[target_id] = user
            return user
        except Exception:
            return None

    # --- HELP PAGINATION GENERATOR ---
    def generate_help(self, category=None, page=1):
        prefix = self.config.get('prefix', '-')
        
        if category is None:
            return (
                "```ini\n"
                "374 SelfBot Prefix: -\n\n"
                f"[ UTILITY ] - Utility commands {prefix}ping, {prefix}avatar, {prefix}setprefix\n"
                f"[ MODERATION ] - Moderation commands {prefix}purge, {prefix}dm\n"
                f"[ FUN ] - Fun commands {prefix}mock, {prefix}react, {prefix}stop\n"
                f"[ INFO ] - Info commands {prefix}userinfo, {prefix}serverinfo\n"
                f"[ RPC ] - Rich presence commands {prefix}rpc\n\n"
                f"Type {prefix}help <category> to see all commands. (e.g. {prefix}help utility)\n"
                "```"
            )
        
        # Detailed Categories
        categories = {
            "utility": [
                [f"{prefix}ping", f"{prefix}setprefix <char>", f"{prefix}avatar <@user>"],
                [f"{prefix}banner <@user>", f"More utilities coming soon..."]
            ],
            "moderation": [
                [f"{prefix}purge <1-100>", f"{prefix}dm <@user> <msg>"]
            ],
            "fun": [
                [f"{prefix}mock <@user>", f"{prefix}react <@user> <emoji>", f"{prefix}stop"]
            ],
            "info": [
                [f"{prefix}userinfo <@user>", f"{prefix}serverinfo"]
            ],
            "rpc": [
                [f"{prefix}rpc <playing/watching/listening> <text>"]
            ]
        }

        cat_lower = category.lower()
        if cat_lower not in categories:
            return f"```\nInvalid category. Available: utility, moderation, fun, info, rpc\n```"

        pages = categories[cat_lower]
        total_pages = len(pages)
        
        if page < 1 or page > total_pages:
            page = 1

        cmd_list = "\n".join([f"- {cmd}" for cmd in pages[page - 1]])
        
        return (
            "```ini\n"
            f"374 SelfBot | {cat_lower.capitalize()} Commands\n"
            f"Page {page} of {total_pages}\n\n"
            f"{cmd_list}\n"
            "```"
        )

    async def on_message(self, message):
        if message.author.bot:
            return
            
        if message.guild:
            self.active_channels.add(message.channel)

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
            # --- NEW HELP SYSTEM ---
            if cmd == 'help':
                # 1. Delete the command you just typed
                try:
                    await message.delete()
                except Exception:
                    pass

                # 2. Parse category and page
                category = None
                page = 1
                
                if len(rest_args) >= 1:
                    category = rest_args[0].lower()
                if len(rest_args) >= 2 and rest_args[1].isdigit():
                    page = int(rest_args[1])

                # 3. Generate and send the new help menu
                help_text = self.generate_help(category, page)
                await message.channel.send(help_text)

            # --- UTILITY ---
            elif cmd == 'setprefix':
                if rest_args:
                    self.config['prefix'] = rest_args[0]
                    self.save_config()
                    await message.channel.send(f"```Prefix changed to {self.config['prefix']}```")

            elif cmd == 'ping':
                await message.channel.send(f"```Ping: {round(self.latency * 1000, 2)}ms```")

            elif cmd == 'avatar':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                else:
                    target = message.author

                avatar_url = target.display_avatar.url if hasattr(target, 'display_avatar') else target.avatar.url
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar_url) as resp:
                        if resp.status == 200:
                            img_data = await resp.read()
                            file = discord.File(io.BytesIO(img_data), filename="avatar.png")
                            await message.channel.send(f"> **{target.name}’s Avatar**", file=file)
                        else:
                            await message.channel.send("```Failed to download avatar.```")

            elif cmd == 'banner':
                target = None
                if message.reference and message.reference.resolved:
                    target = message.reference.resolved.author
                elif rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                else:
                    target = message.author

                if hasattr(target, 'banner') and target.banner:
                    banner_url = target.banner.url
                    async with aiohttp.ClientSession() as session:
                        async with session.get(banner_url) as resp:
                            if resp.status == 200:
                                img_data = await resp.read()
                                file = discord.File(io.BytesIO(img_data), filename="banner.png")
                                await message.channel.send(f"> **{target.name}’s Banner**", file=file)
                            else:
                                await message.channel.send("```Failed to download banner.```")
                else:
                    await message.channel.send("```User has no banner or is not cached.```")

            # --- MODERATION ---
            elif cmd == 'purge':
                if not rest_args or not rest_args[0].isdigit():
                    await message.channel.send("```Usage: -purge <amount>```")
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
                await message.channel.send(f"```Purged {deleted} messages.```")

            elif cmd == 'dm':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -dm <@user> <message>```")
                    return
                
                target = await self.get_cached_user(message, rest_args[0])
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                text = " ".join(rest_args[1:])
                try:
                    await target.send(text)
                    await message.channel.send(f"```Sent DM to {target.name}```")
                except Exception:
                    await message.channel.send("```Failed to send DM (User has DMs closed).```")

            # --- FUN & INTERACTIONS ---
            elif cmd == 'mock':
                if not rest_args:
                    await message.channel.send("```Usage: -mock <@user>```")
                    return
                
                target = await self.get_cached_user(message, rest_args[0])
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("```You cannot mock yourself.```")
                    return
                
                self.auto_mocks[str(target.id)] = True
                await message.channel.send(f"```Now mocking {target.name}. Every message they send will be repeated.```")

            elif cmd == 'react':
                if len(rest_args) < 2:
                    await message.channel.send("```Usage: -react <@user> <emoji>```")
                    return
                
                target = await self.get_cached_user(message, rest_args[0])
                emoji = rest_args[1]
                
                if not target:
                    await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                    return
                
                if target.id == self.user.id:
                    await message.channel.send("```You cannot autoreact to yourself.```")
                    return
                
                self.auto_reacts[str(target.id)] = [emoji]
                await message.channel.send(f"```Autoreact set for {target.name} with {emoji}```")

            elif cmd == 'stop':
                self.auto_reacts.clear()
                self.auto_mocks.clear()
                await message.channel.send("```All auto-reacts and auto-mocks have been cleared.```")

            # --- INFORMATION ---
            elif cmd == 'userinfo':
                target = message.author
                if rest_args:
                    target = await self.get_cached_user(message, rest_args[0])
                    if not target:
                        await message.channel.send("```Could not find user. Wait 3 seconds for cache to refresh.```")
                        return
                
                info_text = (
                    f"```ini\n"
                    f"User: {target.name}\n"
                    f"ID: {target.id}\n"
                    f"Created: {target.created_at.strftime('%Y-%m-%d')}\n"
                    f"```"
                )
                await message.channel.send(info_text)

            elif cmd == 'serverinfo':
                if not message.guild:
                    await message.channel.send("```Must be used in a server.```")
                    return
                server_text = (
                    f"```ini\n"
                    f"Server: {message.guild.name}\n"
                    f"Members: {message.guild.member_count}\n"
                    f"Created: {message.guild.created_at.strftime('%Y-%m-%d')}\n"
                    f"```"
                )
                await message.channel.send(server_text)

            # --- RPC ---
            elif cmd == 'rpc':
                if not rest_args or len(rest_args) < 2:
                    await message.channel.send("```Usage: -rpc <playing/watching/listening> <text>```")
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
                    await message.channel.send("```Invalid type. Use playing, watching, or listening.```")
                    return
                
                await self.change_presence(activity=act)
                await message.channel.send(f"```RPC set to {rtype} {text}```")

        except Exception as e:
            await message.channel.send(f"```Error: {str(e)}```")

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