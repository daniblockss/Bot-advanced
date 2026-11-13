#!/usr/bin/env python3
"""BotHub Standard: command-only Discord bot configured through config.json."""
import json, pathlib, discord
from discord.ext import commands
ROOT=pathlib.Path(__file__).resolve().parent
CFG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
TOKEN=str(CFG.get("discord_token") or "")
PREFIX=str(CFG.get("prefix") or "!")
COMMANDS=CFG.get("standard_commands") or {}
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
@bot.event
async def on_ready():print(f"[BotHub Standard] Conectado como {bot.user}",flush=True)
@bot.command(name="help")
async def help_cmd(ctx):
 lines=[f"{PREFIX}help — lista de comandos"]
 for name,item in COMMANDS.items():
  if isinstance(item,dict):lines.append(f"{PREFIX}{name} — {str(item.get('description') or 'Comando configurado')[:100]}")
 await ctx.reply("\n".join(lines)[:1900])
@bot.event
async def on_message(message):
 if message.author.bot:return
 if message.content.startswith(PREFIX):
  name=message.content[len(PREFIX):].split(maxsplit=1)[0].lower() if message.content[len(PREFIX):].strip() else ""
  item=COMMANDS.get(name)
  if isinstance(item,dict) and item.get("response"):
   await message.reply(str(item["response"])[:1900],mention_author=False)
   return
 await bot.process_commands(message)
if __name__=="__main__":
 if not TOKEN:raise SystemExit("discord_token ausente em config.json")
 bot.run(TOKEN)
