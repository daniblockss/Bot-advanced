#!/usr/bin/env python3
"""BotHub Admin: tickets, points, bot registration and API panels."""
import os,json,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import discord
from discord.ext import commands
ROOT=Path(__file__).resolve().parent
CFG=json.loads((ROOT/"config.json").read_text(encoding="utf-8"))
TOKEN=str(CFG.get("discord_token") or "")
BOT_ID=str(CFG.get("bot_id") or ROOT.name)
API_KEY="AIzaSyDS_KvyPWGgzYqIVgkagw5DAwzlenNZtiE"
DB="https://bothub-bca02-default-rtdb.firebaseio.com"
AUTH=None
CREATOR_ID=int(CFG.get("creator_id") or 0)
def admin_config():
 d=get("botHubAdminConfig/"+BOT_ID) or {}
 return d if isinstance(d,dict) else {}
def staff_ids():
 return {int(x) for x in admin_config().get("staffIds",[]) if str(x).isdigit()} | ({CREATOR_ID} if CREATOR_ID else set())
def is_admin(user): return bool(CREATOR_ID and user.id==CREATOR_ID)
def is_staff(user): return user.id in staff_ids()
PREFIX=str(CFG.get("prefix") or "!")
intents=discord.Intents.default()
intents.message_content=True
intents.members=True
bot=commands.Bot(command_prefix=PREFIX,intents=intents,help_command=None)
ticket_locks=set()
def fb(method,path,value=None,_retried=False,etag=False,match=None):
 global AUTH
 if not AUTH:
  shared=os.getenv("BOTHUB_SHARED_STATE_DIR","").strip()
  token_file=Path(shared)/"firebase-worker-token.json" if shared else None
  if token_file and token_file.is_file():
   try: AUTH=str(json.loads(token_file.read_text(encoding="utf-8")).get("idToken") or "") or None
   except Exception: AUTH=None
  if not AUTH:
   req=Request("https://identitytoolkit.googleapis.com/v1/accounts:signUp?key="+API_KEY,data=b'{"returnSecureToken":true}',headers={"Content-Type":"application/json"},method="POST")
   with urlopen(req,timeout=20) as r: AUTH=json.loads(r.read())["idToken"]
 url=DB+"/"+path.strip("/")+".json?auth="+AUTH
 data=None if value is None else json.dumps(value,ensure_ascii=False).encode()
 headers={"Content-Type":"application/json"}
 if etag: headers["X-Firebase-ETag"]="true"
 if match: headers["If-Match"]=match
 try:
  with urlopen(Request(url,data=data,headers=headers,method=method),timeout=20) as r:
   result=json.loads(r.read() or b"null")
   return (result,r.headers.get("ETag")) if etag else result
 except HTTPError as e:
  if e.code==401:
   AUTH=None
   if not _retried:
    __import__("time").sleep(0.4)
    return fb(method,path,value,_retried=True,etag=etag,match=match)
  if e.code==412:return ("CONFLICT",None)
  try: detail=e.read().decode("utf-8","replace")[:500]
  except Exception: detail=""
  raise RuntimeError("Firebase HTTP "+str(e.code)+((": "+detail) if detail else ""))
def get(path): return fb("GET",path)
def put(path,value): return fb("PUT",path,value)
def delete(path): return fb("DELETE",path)
def points(uid):
 d=get("botHubPoints/"+str(uid)) or {}
 return int(d.get("balance",0)) if isinstance(d,dict) else 0
def change_points(uid,delta,actor,reason):
 path="botHubPoints/"+str(uid); old=get(path) or {}
 balance=max(0,int(old.get("balance",0))+int(delta))
 put(path,{"balance":balance,"updatedAt":int(time.time()*1000),"lastActor":str(actor),"lastReason":reason[:160]})
 return balance
def emb(title,desc=""): return discord.Embed(title=title,description=desc,color=0x38BDF8)
async def ensure_ticket(guild,user,initial=None):
 existing=discord.utils.find(lambda c:c.topic==f"bothub-ticket:{user.id}",guild.text_channels)
 if existing:return existing
 cfg=admin_config(); category_id=int(cfg.get("categoryId") or 0)
 category=guild.get_channel(category_id) if category_id else None
 overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False),user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True),guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,read_message_history=True)}
 for uid in staff_ids():
  member=guild.get_member(uid)
  if member:overwrites[member]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
 ch=await guild.create_text_channel(("ticket-"+user.name.lower().replace(" ","-"))[:90],category=category if isinstance(category,discord.CategoryChannel) else None,overwrites=overwrites,topic=f"bothub-ticket:{user.id}")
 await ch.send(f"{user.mention}, este é seu atendimento privado do BotHub. Use !help para ajuda e !fechar para encerrar.")
 if initial:await ch.send("Mensagem inicial: "+discord.utils.escape_markdown(initial[:1200]))
 return ch
def api_endpoint(provider,custom=""):
 return {"openrouter":"https://openrouter.ai/api/v1/chat/completions","groq":"https://api.groq.com/openai/v1/chat/completions","llm7":"https://api.llm7.io/v1/chat/completions","chatgpt":"https://api.openai.com/v1/responses","blockrun":"https://blockrun.ai/api/v1/chat/completions"}.get(provider,custom)
def consume_global_point(uid):
 path="botHubPoints/"+str(uid)
 for _ in range(3):
  data,tag=fb("GET",path,etag=True)
  data=data if isinstance(data,dict) else {}
  balance=int(data.get("balance",0))
  if balance<1:return False
  updated=dict(data);updated.update(balance=balance-1,updatedAt=int(time.time()*1000),lastReason="Uso de API global",lastActor=BOT_ID)
  result=fb("PUT",path,updated,match=tag)
  if not (isinstance(result,tuple) and result and result[0]=="CONFLICT"):return True
 return False
def request_provider(item,text):
 provider=str(item.get("provider","")).lower()
 endpoint=api_endpoint(provider,str(item.get("endpoint") or ""))
 if not endpoint:raise RuntimeError("provedor não suportado: "+provider)
 ai_cfg=CFG.get("ai") if isinstance(CFG.get("ai"),dict) else {}
 defaults={"chatgpt":"gpt-6-luna","openrouter":"openai/gpt-4o-mini","groq":"llama-3.3-70b-versatile","llm7":"fast","blockrun":"nvidia/nemotron-3.5-lightning"}
 models=ai_cfg.get("models") if isinstance(ai_cfg.get("models"),dict) else {}
 model=str(item.get("model") or models.get(provider) or defaults.get(provider,"")).strip()
 settings=ai_cfg.get("model_settings") if isinstance(ai_cfg.get("model_settings"),dict) else {}
 provider_settings=settings.get(provider) if isinstance(settings.get(provider),dict) else {}
 model_settings=provider_settings.get(model) if isinstance(provider_settings.get(model),dict) else provider_settings
 system="Você é o assistente oficial do BotHub. Responda em português, com clareza e concisão. Ajude com tickets, pontos, bots e APIs."
 messages=[{"role":"system","content":system},{"role":"user","content":text[:4000]}]
 headers={"Content-Type":"application/json"}
 key=str(item.get("key") or "").strip()
 if key:headers["Authorization"]="Bearer "+key
 if provider=="openrouter":headers.update({"HTTP-Referer":"https://discord.com","X-Title":"Discord Bot"})
 if provider=="chatgpt":
  payload={"model":model,"instructions":system,"input":[{"role":"user","content":messages[1]["content"]}],
           "reasoning":{"effort":str(model_settings.get("reasoning_effort","none"))},
           "max_output_tokens":int(model_settings.get("max_output_tokens",500)),"store":True}
 else:
  payload={"model":model,"messages":messages,"stream":False}
  if provider!="blockrun":
   payload["temperature"]=float(model_settings.get("temperature",0.6))
   payload["max_tokens"]=min(8000,max(1,int(model_settings.get("max_tokens",700))))
 req=Request(endpoint,data=json.dumps(payload,ensure_ascii=False).encode(),headers=headers,method="POST")
 try:
  with urlopen(req,timeout=60) as response:data=json.loads(response.read())
 except HTTPError as error:
  detail=error.read().decode("utf-8","replace")[:400]
  raise RuntimeError(provider+" HTTP "+str(error.code)+((": "+detail) if detail else "")) from error
 if provider=="chatgpt":
  answer=data.get("output_text")
  if not answer:
   answer="".join(part.get("text","") for output in data.get("output",[]) if isinstance(output,dict)
                  for part in output.get("content",[]) if isinstance(part,dict)
                  and part.get("type") in {"output_text","text"})
 else:
  answer=data.get("choices",[{}])[0].get("message",{}).get("content","")
 if isinstance(answer,list):
  answer="".join(str(part.get("text","")) for part in answer if isinstance(part,dict))
 if not isinstance(answer,str) or not answer.strip():raise RuntimeError(provider+" retornou resposta vazia")
 return answer.strip()[:3800]
def call_ai(uid,text):
 ai_cfg=CFG.get("ai") if isinstance(CFG.get("ai"),dict) else {}
 configured=ai_cfg.get("api_keys") if isinstance(ai_cfg.get("api_keys"),dict) else {}
 order=ai_cfg.get("fallback_order") if isinstance(ai_cfg.get("fallback_order"),list) else ["chatgpt","openrouter","groq","llm7","blockrun"]
 pool=[]
 personal=get(f"botHubUserApis/{uid}/{BOT_ID}") or {}
 # APIs globais seguem a ativação por usuário/bot e o saldo do IA CHAT.
 opt=get(f"botHubGlobalOptIn/{uid}/{BOT_ID}") or {}
 points_data=get("botHubPoints/"+str(uid)) or {}
 has_points=isinstance(points_data,dict) and int(points_data.get("balance",0))>0
 global_items=get("botHubGlobalApis") or {}
 use_global=bool(isinstance(opt,dict) and opt.get("enabled") and has_points and isinstance(global_items,dict))
 # Ordem por provedor: chaves locais, API pessoal, APIs globais e próximo provedor.
 for provider in order:
  provider=str(provider).lower()
  if provider not in {"chatgpt","openrouter","groq","llm7","blockrun"}:continue
  if provider=="llm7":
   pool.append(({"provider":"llm7","model":"fast","key":""},False))
   pool.append(({"provider":"llm7","model":"fast","key":"auto-generated"},False))
  keys=configured.get(provider,[]) if provider!="blockrun" else []
  if isinstance(keys,str):keys=[keys]
  env_names={"chatgpt":("CHATGPT_API_KEYS","CHATGPT_API_KEY","OPENAI_API_KEY"),
             "openrouter":("OPENROUTER_API_KEYS","OPENROUTER_API_KEY"),
             "groq":("GROQ_API_KEYS","GROQ_API_KEY"),
             "llm7":("LLM7_API_KEYS","LLM7_API_KEY")}.get(provider,())
  for env_name in env_names:
   keys.extend([part.strip() for part in os.getenv(env_name,"").replace("\\n",",").replace(";",",").split(",") if part.strip()])
  if isinstance(keys,list):
   for key in keys:
    if isinstance(key,str) and key.strip() and key.strip()!="auto-generated":
     pool.append(({"provider":provider,"key":key.strip()},False))
  if isinstance(personal,dict) and personal.get("enabled") and personal.get("key") and str(personal.get("provider","")).lower()==provider:
   pool.append((personal,False))
  if use_global:
   for item in global_items.values():
    if not isinstance(item,dict) or str(item.get("provider","")).lower()!=provider:continue
    if not item.get("enabled",True) or not item.get("key"):continue
    if item.get("available") is False:
     until=int(item.get("availableUntil") or 0)
     if not until or until>int(time.time()*1000):continue
    pool.append((item,True))
 # BlockRun público continua como último fallback, sem consumir ponto global.
 if not any(isinstance(item,dict) and item.get("provider")=="blockrun" for item,_ in pool):
  pool.append(({"provider":"blockrun","model":(ai_cfg.get("models") or {}).get("blockrun","nvidia/nemotron-3.5-lightning"),"key":""},False))
 errors=[]
 seen=set()
 for item,is_global in pool:
  signature=(str(item.get("provider")),str(item.get("key") or ""),str(item.get("model") or ""))
  if signature in seen:continue
  seen.add(signature)
  try:
   answer=request_provider(item,text)
   if is_global and not consume_global_point(uid):
    errors.append("API global respondeu, mas não foi possível confirmar o débito de 1 ponto.")
    continue
   return answer
  except Exception as error:
   errors.append(str(error)[:240])
 return "As APIs configuradas não responderam: "+(" | ".join(errors[-6:]) or "nenhum provedor disponível.")
def validate_api_key(provider,key,model):
 defaults={"chatgpt":"gpt-6-luna","openrouter":"openai/gpt-4o-mini","groq":"llama-3.3-70b-versatile","llm7":"fast","blockrun":"nvidia/nemotron-3.5-lightning"}
 chosen=model or defaults.get(provider,"")
 request_provider({"provider":provider,"key":key,"model":chosen}, "Responda apenas OK.")
 return chosen
class ApiModal(discord.ui.Modal,title="Cadastrar API"):
 def __init__(self,target_bot_id):
  super().__init__()
  self.target.default=str(target_bot_id)
 scope=discord.ui.TextInput(label="Destino: pessoal ou global",default="pessoal",max_length=15)
 provider=discord.ui.TextInput(label="Provedor: chatgpt, openrouter, groq, llm7 ou blockrun",default="openrouter",max_length=30)
 key=discord.ui.TextInput(label="Chave da API",max_length=500)
 model=discord.ui.TextInput(label="Modelo (opcional)",required=False,max_length=120)
 target=discord.ui.TextInput(label="ID do seu bot (para API pessoal)",required=False,max_length=40)
 async def on_submit(self,interaction):
  scope=str(self.scope.value).strip().lower(); p=str(self.provider.value).strip().lower(); key=str(self.key.value).strip(); model=str(self.model.value).strip()
  if p not in {"openrouter","groq","llm7","chatgpt","blockrun"}:return await interaction.response.send_message("Provedor não suportado.",ephemeral=True)
  if scope not in {"pessoal","global"}:return await interaction.response.send_message("Destino deve ser pessoal ou global.",ephemeral=True)
  if scope=="pessoal":
   bid=str(self.target.value).strip() or BOT_ID
   item=get("bots/"+bid) or {}
   if bid!=BOT_ID and str(item.get("ownerId"))!=str(interaction.user.id):return await interaction.response.send_message("Esse bot não pertence à sua conta.",ephemeral=True)
   put(f"botHubUserApis/{interaction.user.id}/{bid}",{"provider":p,"key":key,"model":model,"enabled":True,"updatedAt":int(time.time()*1000)})
   return await interaction.response.send_message("API pessoal validada e salva no bot selecionado.",ephemeral=True)
  await interaction.response.defer(ephemeral=True)
  try:
   chosen=await __import__("asyncio").to_thread(validate_api_key,p,key,model)
   import hashlib
   digest=hashlib.sha256((p+":"+key).encode()).hexdigest()
   api_id=uuid.uuid4().hex
   put("botHubGlobalApis/"+api_id,{"provider":p,"key":key,"model":chosen,"enabled":True,"available":True,"status":"Disponível","addedBy":str(interaction.user.id),"addedByName":str(interaction.user),"createdAt":int(time.time()*1000),"updatedAt":int(time.time()*1000)})
   contribution=f"botHubApiContributions/{interaction.user.id}/{digest}"
   if not get(contribution):
    put(contribution,{"apiId":api_id,"provider":p,"createdAt":int(time.time()*1000)})
    balance=change_points(interaction.user.id,1,BOT_ID,"Contribuição de API global válida")
    await interaction.followup.send(f"API global validada e cadastrada. Você recebeu 1 ponto de contribuição. Saldo: {balance}.",ephemeral=True)
   else:
    await interaction.followup.send("API global validada e cadastrada. Esta chave já recebeu o ponto de contribuição anteriormente.",ephemeral=True)
  except Exception as e:
   await interaction.followup.send("A chave não passou na validação: "+str(e)[:180],ephemeral=True)
class ApiTargetSelect(discord.ui.Select):
 def __init__(self,view,uid):
  self.parent=view; options=[discord.SelectOption(label="BOT ADMIN",value=BOT_ID,description="Configuração do próprio painel Discord")]
  data=get("bots") or {}
  for bid,item in list(data.items())[:24]:
   if str(item.get("ownerId"))==str(uid):
    options.append(discord.SelectOption(label=str(item.get("name","Bot"))[:100],value=bid,description=str(item.get("botType","ia_chat"))[:100]))
  super().__init__(placeholder="Escolha em qual bot configurar a API",options=options[:25])
 async def callback(self,interaction):
  self.parent.target_bot_id=self.values[0]
  await interaction.response.send_message("Bot selecionado para as próximas ações: "+self.values[0],ephemeral=True)
class ApiView(discord.ui.View):
 def __init__(self,uid):
  super().__init__(timeout=180);self.target_bot_id=BOT_ID;self.add_item(ApiTargetSelect(self,uid))
 @discord.ui.button(label="Adicionar API",style=discord.ButtonStyle.primary)
 async def add(self,i,b):await i.response.send_modal(ApiModal(self.target_bot_id))
 @discord.ui.button(label="Ativar/desativar APIs globais",style=discord.ButtonStyle.success)
 async def toggle(self,i,b):
  path=f"botHubGlobalOptIn/{i.user.id}/{self.target_bot_id}";old=get(path) or {};enabled=not bool(old.get("enabled"))
  put(path,{"enabled":enabled,"updatedAt":int(time.time()*1000)})
  await i.response.send_message("APIs globais "+("ativadas" if enabled else "desativadas")+". Cada resposta que usar uma API global custa 1 ponto.",ephemeral=True)
 @discord.ui.button(label="Remover API pessoal",style=discord.ButtonStyle.danger)
 async def remove(self,i,b):
  delete(f"botHubUserApis/{i.user.id}/{self.target_bot_id}");await i.response.send_message("API pessoal removida do bot selecionado.",ephemeral=True)
class BotSelect(discord.ui.Select):
 def __init__(self,uid):
  opts=[]; data=get("bots") or {}
  for bid,item in list(data.items())[:25]:
   if str(item.get("ownerId"))==str(uid):opts.append(discord.SelectOption(label=str(item.get("name","Bot"))[:100],value=bid,description=str(item.get("botType","ia_chat"))[:100]))
  if not opts:opts=[discord.SelectOption(label="Nenhum bot cadastrado",value="none")]
  super().__init__(placeholder="Selecione um bot",options=opts)
 async def callback(self,i):
  bid=self.values[0]
  if bid=="none":return await i.response.send_message("Você ainda não cadastrou bots.",ephemeral=True)
  item=get("bots/"+bid) or {}
  invite="Convite indisponível."
  try:
   req=Request("https://discord.com/api/v10/users/@me",headers={"Authorization":"Bot "+str(item.get("token") or "")})
   with urlopen(req,timeout=12) as r: profile=json.loads(r.read())
   permissions=8
   invite=f"https://discord.com/oauth2/authorize?client_id={profile['id']}&scope=bot%20applications.commands&permissions={permissions}"
  except Exception:pass
  await i.response.send_message(f"**{item.get('name','Bot')}** | tipo: {item.get('botType','ia_chat')} | estado: {'ON' if item.get('enabled') else 'OFF'}\nID: {bid}\nConvite: {invite}",ephemeral=True)
class ConfigView(discord.ui.View):
 def __init__(self,uid):super().__init__(timeout=180);self.add_item(BotSelect(uid))
@bot.event
async def on_ready():
 global CREATOR_ID
 try:
  req=Request("https://discord.com/api/v10/applications/@me",headers={"Authorization":"Bot "+TOKEN})
  with urlopen(req,timeout=15) as r: app=json.loads(r.read())
  owner=app.get("owner") or {}
  if owner.get("id"): CREATOR_ID=int(owner["id"])
 except Exception as e: print("[BotHub Admin] Não foi possível obter o criador da aplicação:",str(e)[:160],flush=True)
 try:(ROOT/".bothub_discord_ready").write_text(str(int(time.time()*1000)),encoding="utf-8")
 except OSError:pass
 print(f"[BotHub Admin] Conectado como {bot.user} ({bot.user.id}); criador={CREATOR_ID or 'não identificado'}",flush=True)
@bot.event
async def on_disconnect():
 try:(ROOT/".bothub_discord_ready").unlink(missing_ok=True)
 except OSError:pass
@bot.event
async def on_resumed():
 try:(ROOT/".bothub_discord_ready").write_text(str(int(time.time()*1000)),encoding="utf-8")
 except OSError:pass
@bot.event
async def on_message(message):
 if message.author.bot:return
 if message.guild and ((int(admin_config().get("entryChannelId") or 0) and message.channel.id==int(admin_config().get("entryChannelId") or 0)) or (bot.user and bot.user in message.mentions)) and message.content.strip() and message.author.id not in staff_ids():
  if message.author.id not in ticket_locks:
   ticket_locks.add(message.author.id)
   try:
    ch=await ensure_ticket(message.guild,message.author,message.content)
    await ch.send(f"{message.author.mention}, seu ticket privado: {ch.mention}")
   finally:ticket_locks.discard(message.author.id)
  return
 if message.guild and str(getattr(message.channel,"topic","") or "").startswith("bothub-ticket:") and not message.content.startswith("!"):
  text=message.content.lower()
  if "api" in text and any(term in text for term in ("abrir","adicion","gerenciar","configur","painel","minhas")):
   await message.channel.send(embed=emb("Painel de APIs","Escolha em qual bot configurar suas APIs."),view=ApiView(message.author.id));return
  if any(term in text for term in ("meus bots","configurar bot","configurações dos bots","painel dos bots")):
   await message.channel.send(embed=emb("Configurações dos seus bots","Selecione um bot para consultar estado e convite."),view=ConfigView(message.author.id));return
  if any(term in text for term in ("quantos pontos","meus pontos","saldo de pontos","ver pontos","consultar pontos")):
   await message.channel.send(f"Você tem **{points(message.author.id)} pontos**.");return
  if "comprar pontos" in text or "quero pontos" in text:
   await message.channel.send("Use !comprar-pontos quantidade para registrar sua solicitação. A equipe confirma o pagamento antes de adicionar.");return
  response=await __import__("asyncio").to_thread(call_ai,message.author.id,message.content)
  await message.channel.send(response);return
 await bot.process_commands(message)
@bot.command(name="ticket")
async def ticket(ctx):
 if ctx.guild:
  ch=await ensure_ticket(ctx.guild,ctx.author);await ctx.reply(f"Seu atendimento: {ch.mention}",delete_after=20)
@bot.command(name="pontos")
async def show_points(ctx):await ctx.reply(f"Você tem **{points(ctx.author.id)} pontos**.")
@bot.command(name="comprar-pontos",aliases=["comprar"])
async def buy(ctx,amount:int=0):
 if amount<1 or amount>1000000:return await ctx.reply("Use !comprar-pontos quantidade. A equipe confirmará o pagamento antes de adicionar pontos.")
 request_id=uuid.uuid4().hex
 put(f"botHubPointPurchases/{ctx.author.id}/{request_id}",{"amount":amount,"status":"pending","createdAt":int(time.time()*1000),"guildId":str(ctx.guild.id if ctx.guild else 0),"ticketChannelId":str(ctx.channel.id)})
 mentions=" ".join(f"<@{uid}>" for uid in staff_ids())
 await ctx.reply(f"{mentions} {ctx.author.mention} solicitou a compra de **{amount} pontos**. Pedido: `{request_id[:8]}`. A equipe deve confirmar o pagamento antes de usar !add.",allowed_mentions=discord.AllowedMentions(users=True))
@bot.command(name="add-bot")
async def add_bot(ctx,*,args=""):
 try: await ctx.message.delete()
 except Exception: pass
 parts=args.split(maxsplit=1)
 if len(parts)!=2 or len(parts[1])<30:return await ctx.reply("Use !add-bot nome token.")
 name,token=parts
 try:
  req=Request("https://discord.com/api/v10/users/@me",headers={"Authorization":"Bot "+token})
  with urlopen(req,timeout=15) as r:profile=json.loads(r.read())
 except Exception:return await ctx.reply("Token inválido ou não foi possível validar no Discord.")
 bid=uuid.uuid4().hex
 put("bots/"+bid,{"name":name[:100],"token":token,"botType":"ia_chat","ownerId":str(ctx.author.id),"enabled":True,"desiredState":"on","workerId":None,"createdAt":int(time.time()*1000),"config":{"bot_authorization":{"allow_user_ids":[str(ctx.author.id)]}}})
 await ctx.reply(f"Bot {discord.utils.escape_markdown(name)} validado ({profile.get('username','bot')}) e cadastrado. O cluster fará a distribuição quando houver worker.")
class AdminConfigView(discord.ui.View):
 def __init__(self):
  super().__init__(timeout=300)
  self.add_item(EntryChannelSelect())
  self.add_item(TicketCategorySelect())
  self.add_item(StaffUserSelect())
class EntryChannelSelect(discord.ui.ChannelSelect):
 def __init__(self):
  super().__init__(placeholder="Canal de entrada dos tickets",channel_types=[discord.ChannelType.text],min_values=1,max_values=1)
 async def callback(self,interaction):
  if not is_admin(interaction.user):return await interaction.response.send_message("Somente o criador do bot pode alterar.",ephemeral=True)
  cfg=admin_config();cfg["entryChannelId"]=str(self.values[0].id);put("botHubAdminConfig/"+BOT_ID,cfg)
  await interaction.response.send_message("Canal de entrada salvo: "+self.values[0].mention,ephemeral=True)
class TicketCategorySelect(discord.ui.ChannelSelect):
 def __init__(self):
  super().__init__(placeholder="Categoria dos tickets",channel_types=[discord.ChannelType.category],min_values=1,max_values=1)
 async def callback(self,interaction):
  if not is_admin(interaction.user):return await interaction.response.send_message("Somente o criador do bot pode alterar.",ephemeral=True)
  cfg=admin_config();cfg["categoryId"]=str(self.values[0].id);put("botHubAdminConfig/"+BOT_ID,cfg)
  await interaction.response.send_message("Categoria salva: "+self.values[0].name,ephemeral=True)
class StaffUserSelect(discord.ui.UserSelect):
 def __init__(self):
  super().__init__(placeholder="Equipe de atendimento",min_values=1,max_values=10)
 async def callback(self,interaction):
  if not is_admin(interaction.user):return await interaction.response.send_message("Somente o criador do bot pode alterar.",ephemeral=True)
  cfg=admin_config();cfg["staffIds"]=[str(u.id) for u in self.values if u.id!=CREATOR_ID];put("botHubAdminConfig/"+BOT_ID,cfg)
  await interaction.response.send_message("Equipe de atendimento atualizada.",ephemeral=True)
@bot.command(name="config")
async def config_cmd(ctx):
 if not is_admin(ctx.author):return await ctx.reply("Somente o criador identificado pelo token pode usar !config.")
 cfg=admin_config()
 e=emb("Configuração do BOT ADMIN","O criador é identificado automaticamente pelo token. Use os seletores abaixo para configurar o atendimento.")
 e.add_field(name="Canal de entrada",value=f"<#{cfg.get('entryChannelId')}>" if cfg.get("entryChannelId") else "Não definido — mencionar o bot também abre ticket.",inline=False)
 e.add_field(name="Categoria",value=f"<#{cfg.get('categoryId')}>" if cfg.get("categoryId") else "Categoria padrão do servidor",inline=False)
 e.add_field(name="Equipe",value=", ".join(f"<@{x}>" for x in cfg.get("staffIds",[])) or "Somente o criador",inline=False)
 await ctx.send(embed=e,view=AdminConfigView())
@bot.command(name="api")
async def api(ctx):await ctx.send(embed=emb("Gerenciamento de APIs","Adicione APIs pessoais ou ative as APIs globais. Cada resposta que usar uma API global custa 1 ponto."),view=ApiView(ctx.author.id))
@bot.command(name="configs")
async def configs(ctx):await ctx.send(embed=emb("Seus bots","Selecione um bot para consultar seu estado."),view=ConfigView(ctx.author.id))
@bot.command(name="help")
async def help_cmd(ctx):
 e=emb("BotHub — Ajuda");e.add_field(name="Usuários",value="!pontos · !comprar-pontos · !add-bot nome token · !api · !configs · !config · !ticket",inline=False);e.add_field(name="Tickets",value="Converse normalmente neste canal privado. !fechar encerra.",inline=False)
 if is_admin(ctx.author):e.add_field(name="Administração",value="!config · !add @usuário pontos · !remove @usuário pontos",inline=False)
 await ctx.reply(embed=e)
@bot.command(name="add")
async def add_points(ctx,member:discord.Member=None,amount:int=0):
 if not is_admin(ctx.author):return await ctx.reply("Sem permissão.")
 if member is None or not 1<=amount<=1000000:return await ctx.reply("Use !add @usuário quantidade.")
 balance=change_points(member.id,amount,ctx.author.id,"Adição administrativa");await ctx.reply(f"{member.mention}: +{amount}. Saldo: **{balance}**.")
@bot.command(name="remove")
async def remove_points(ctx,member:discord.Member=None,amount:int=0):
 if not is_admin(ctx.author):return await ctx.reply("Sem permissão.")
 if member is None or amount<1:return await ctx.reply("Use !remove @usuário quantidade.")
 balance=change_points(member.id,-amount,ctx.author.id,"Remoção administrativa");await ctx.reply(f"{member.mention}: saldo **{balance}**.")
@bot.command(name="fechar")
async def close(ctx):
 topic=str(getattr(ctx.channel,"topic","") or "")
 if not topic.startswith("bothub-ticket:"):return await ctx.reply("Este canal não é um ticket.")
 owner=int(topic.split(":")[-1])
 if ctx.author.id!=owner and not is_admin(ctx.author) and not is_staff(ctx.author):return await ctx.reply("Somente o criador ou a equipe pode fechar.")
 await ctx.reply("Ticket encerrado; canal será removido em 5 segundos.");await __import__("asyncio").sleep(5);await ctx.channel.delete(reason="Ticket BotHub encerrado")
if __name__=="__main__":
 if not TOKEN:raise SystemExit("discord_token ausente em config.json")
 bot.run(TOKEN)
