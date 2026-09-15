import os
import logging
import asyncio
import json
import re
import threading
from flask import Flask
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError
from dotenv import load_dotenv

# --- SERVIDOR WEB EN RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "¡Bot activo y funcionando 24/7 en Render!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- CONFIGURACIÓN DE TELEGRAM ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID') 
USER_SESSION_STRING = os.getenv('USER_SESSION_STRING')

try:
    CHANNEL_ID = int(CHANNEL_ID)
    API_ID = int(API_ID)
except ValueError:
    pass

user_searches = {}
waiting_manual_move = {}  # Control para búsqueda manual de texto al mover
INDEX_FILE = 'indice_categorias.json'

def cargar_indice():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def guardar_indice(datos):
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4)

def extraer_categorias(message):
    if not (message.photo or message.video or message.document):
        return []

    categorias = set()

    if message.text:
        hashtags = re.findall(r'#(\w+)', message.text)
        for tag in hashtags:
            categorias.add(tag.lower())

    texto_base = ""
    if message.file and message.file.name:
        texto_base = message.file.name.lower()
    elif message.text:
        texto_base = message.text.lower()

    if texto_base:
        palabras = re.findall(r'[a-z]+', texto_base)
        ignoradas = {
            'jpg', 'png', 'gif', 'mp4', 'mov', 'jpeg', 'heic', 'avi', 'mkv', 'mp',
            'webp', 'mp3', 'ogg', 'opus', 'pdf', 'doc', 'docx',
            'the', 'for', 'with', 'con', 'los', 'las', 'una', 'uno', 'que',
            'del', 'por', 'para', 'and', 'set', 'new', 'tmp', 'temp',
            'file', 'part', 'clip', 'hd', 'sd', 'mix', 'vol', 'ver',
            'pre', 'old', 'cut', 'raw', 'web', 'cam', 'vip'
        }

        for p in palabras:
            if p in ignoradas or len(p) < 3:
                continue
            if p in ['img', 'image', 'foto']:
                categorias.add('img')
            elif p in ['vid', 'video']:
                categorias.add('vid')
            elif p == 'whatsapp':
                categorias.add('whatsapp')
            elif p == 'screenshot':
                categorias.add('screenshot')
            elif p == 'gif':
                categorias.add('gif')
            else:
                categorias.add(p)

    return list(categorias)

def crear_barra_progreso(porcentaje, longitud=10):
    llenos = int(round(longitud * porcentaje / 100))
    vacios = longitud - llenos
    return "▓" * llenos + "░" * vacios

async def main():
    bot = TelegramClient('bot_session', int(API_ID), API_HASH)
    user = TelegramClient(StringSession(USER_SESSION_STRING), int(API_ID), API_HASH)
    
    await bot.start(bot_token=BOT_TOKEN)
    await user.start()

    async def send_page(chat_id):
        data = user_searches.get(chat_id)
        if not data: return
        page = data["page"]
        filter_type = data.get("filter", "all")
        query = data["query"]
        origen = data.get("origen", "menu")
        
        # Selección de lista según el filtro activo
        if filter_type == "photos":
            current_list = data["photos"]
        elif filter_type == "videos":
            current_list = data["videos"]
        elif filter_type == "gifs":
            current_list = data["gifs"]
        else:
            current_list = data["all_ids"]
            
        start = page * 5
        end = start + 5
        current_ids = current_list[start:end]
        
        if not current_ids:
            botones_vacio = [
                [Button.inline(f"🗑️ Eliminar '{query}' del índice y canal", data=f"del_cat_{query}".encode())],
                [Button.inline("⬅️ Volver al menú", data="volver_menu".encode())]
            ]
            await bot.send_message(
                chat_id, 
                f"❌ No hay archivos para este filtro en '{query}'.\nPuedes eliminar esta categoría por completo aquí:", 
                buttons=botones_vacio
            )
            return

        for msg_id in current_ids:
            try:
                botones_acciones = [
                    [
                        Button.inline("🔄 Mover", data=f"req_mover_{msg_id}".encode()),
                        Button.inline("🗑️ Eliminar", data=f"req_del_{msg_id}".encode())
                    ]
                ]
                await bot.forward_messages(chat_id, msg_id, from_peer=CHANNEL_ID)
                await bot.send_message(chat_id, f"🛠️ Opciones para el archivo (ID: `{msg_id}`):", buttons=botones_acciones)
            except Exception:
                pass
        
        botones = []
        filtros_row = []
        if filter_type != "all":
            filtros_row.append(Button.inline("📁 Ver Todo", data=b"filter_all"))
        if filter_type != "photos" and len(data["photos"]) > 0:
            filtros_row.append(Button.inline(f"🖼️ Fotos ({len(data['photos'])})", data=b"filter_photos"))
        if filter_type != "videos" and len(data["videos"]) > 0:
            filtros_row.append(Button.inline(f"🎥 Videos ({len(data['videos'])})", data=b"filter_videos"))
        if filter_type != "gifs" and len(data["gifs"]) > 0:
            filtros_row.append(Button.inline(f"🎞️ GIFs ({len(data['gifs'])})", data=b"filter_gifs"))
            
        if filtros_row:
            botones.append(filtros_row)

        fila_nav = []
        if end < len(current_list):
            fila_nav.append(Button.inline("➡️ Más archivos", data=b"next_page"))
        fila_nav.append(Button.inline("⬅️ Volver", data=f"volver_{origen}".encode()))
        botones.append(fila_nav)

        msg_text = f"📄 Mostrando {start+1} a {min(end, len(current_list))} de **{len(current_list)}** en '{query}'."
        if end >= len(current_list):
            msg_text += "\n✅ Fin de los resultados."

        await bot.send_message(chat_id, msg_text, buttons=botones)

    async def mostrar_archivo_para_mover(chat_id):
        data = user_searches.get(chat_id)
        if not data or "mover_ids" not in data:
            return

        idx = data["mover_index"]
        ids = data["mover_ids"]
        origen = data["origen_mov"]
        destino = data["destino_mov"]

        if idx >= len(ids):
            await bot.send_message(chat_id, f"✅ **¡Proceso individual finalizado!** Se revisaron los {len(ids)} archivos.")
            return

        msg_id = ids[idx]
        await bot.forward_messages(chat_id, msg_id, from_peer=CHANNEL_ID)

        botones = [
            [
                Button.inline(f"✅ Mover a #{destino}", data=f"confirm_mover_{msg_id}".encode()),
                Button.inline("⏭️ Omitir", data=b"skip_mover")
            ]
        ]

        await bot.send_message(
            chat_id,
            f"📌 **Archivo {idx + 1} de {len(ids)}**\n¿Mover de `#{origen}` a `#{destino}`?",
            buttons=botones
        )

    @bot.on(events.NewMessage)
    async def bot_handler(event):
        texto = event.raw_text.strip()
        texto_lower = texto.lower()
        chat_id = event.chat_id

        if chat_id in waiting_manual_move and waiting_manual_move[chat_id]:
            msg_id = waiting_manual_move[chat_id]
            waiting_manual_move[chat_id] = None 
            destino = texto.lower().replace('#', '').strip()

            message = await user.get_messages(CHANNEL_ID, ids=msg_id)
            if message:
                texto_actual = message.text or ""
                if f"#{destino}" not in texto_actual.lower():
                    nuevo_texto = f"{texto_actual}\n#{destino}".strip()
                else:
                    nuevo_texto = texto_actual

                try:
                    await user.edit_message(CHANNEL_ID, msg_id, text=nuevo_texto)
                    indice = cargar_indice()
                    indice[destino] = indice.get(destino, 0) + 1
                    guardar_indice(indice)
                    await event.reply(f"✅ **¡Archivo movido manualmente con éxito!** Se le asignó `#{destino}` (ID: `{msg_id}`).")
                except Exception as e:
                    await event.reply(f"❌ Error al actualizar el mensaje: {str(e)}")
            else:
                await event.reply("❌ No se encontró el mensaje original.")
            return
        
        if texto_lower == '/start':
            await event.reply("¡Hola! Envíame cualquier palabra o usa /index para navegar.")
            return

        if texto_lower.startswith('/eliminar_carpeta'):
            partes = texto.split()
            if len(partes) < 2:
                await event.reply("⚠️ **Uso incorrecto.**\nEjemplo: `/eliminar_carpeta nombre_categoria`")
                return
            
            carpeta_a_borrar = partes[1].lower().replace('#', '')
            status_del = await event.reply(f"🗑️ Eliminando `#{carpeta_a_borrar}` del índice y del canal...")
            
            indice = cargar_indice()
            if carpeta_a_borrar in indice:
                del indice[carpeta_a_borrar]
                guardar_indice(indice)

            contador_borrados = 0
            try:
                async for message in user.iter_messages(CHANNEL_ID, search=carpeta_a_borrar, limit=300):
                    if message.photo or message.video or message.document:
                        await user.delete_messages(CHANNEL_ID, [message.id])
                        contador_borrados += 1
                        await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Error borrando archivos del canal por comando: {e}")

            await status_del.edit(f"✅ Categoría `#{carpeta_a_borrar}` borrada del índice. Se eliminaron **{contador_borrados}** archivos del canal.")
            return
            
        if texto_lower == '/crear_indice':
            status = await event.reply("⏳ Calculando total de mensajes...")
            
            res_total = await user.get_messages(CHANNEL_ID, limit=0)
            total_mensajes = res_total.total or 1
            
            indice = {}
            procesados = 0
            offset_id = 0

            while procesados < total_mensajes:
                try:
                    mensajes = await user.get_messages(
                        CHANNEL_ID, 
                        limit=100, 
                        offset_id=offset_id
                    )

                    if not mensajes:
                        break

                    for message in mensajes:
                        procesados += 1
                        offset_id = message.id

                        if message.photo or message.video or message.document:
                            cats = extraer_categorias(message)
                            if cats:
                                for cat in cats:
                                    indice[cat] = indice.get(cat, 0) + 1
                            else:
                                indice['sin_nombre'] = indice.get('sin_nombre', 0) + 1

                    await asyncio.sleep(0.05)

                    if procesados % 2500 == 0 or procesados >= total_mensajes:
                        porcentaje = int((procesados / total_mensajes) * 100)
                        barra = crear_barra_progreso(porcentaje)
                        try:
                            await status.edit(
                                f"⏳ **Indexando canal...**\n\n"
                                f"`[{barra}]` **{porcentaje}%**\n"
                                f"📊 Procesados: **{procesados:,} / {total_mensajes:,}** msgs"
                            )
                        except Exception:
                            pass

                except FloodWaitError as e:
                    logger.warning(f"Telegram forzó pausa por FloodWait: {e.seconds}s")
                    await asyncio.sleep(e.seconds + 1)
                except Exception as e:
                    logger.error(f"Error en bucle de indexación: {e}")
                    await asyncio.sleep(2)

            guardar_indice(indice)
            await status.edit(
                f"✅ **¡Índice creado con éxito!**\n\n"
                f"🗂️ Categorías encontradas: **{len(indice):,}**\n"
                f"📂 Archivos sin nombre: **{indice.get('sin_nombre', 0):,}**\n\n"
                f"Escribe /index para abrir el menú."
            )
            return
            
        if texto_lower == '/index':
            indice = cargar_indice()
            if not indice:
                await event.reply("El índice está vacío. Escribe /crear_indice primero.")
                return
            await mostrar_menu_principal(event.chat_id, indice)
            return

        if texto_lower.startswith('/mover'):
            partes = texto.split()
            if len(partes) < 3:
                await event.reply("⚠️ **Uso incorrecto.**\nEjemplo: `/mover rojo azul`")
                return

            origen = partes[1].lower().replace('#', '')
            destino = partes[2].lower().replace('#', '')

            status = await event.reply(f"🔍 Buscando archivos con **#{origen}**...")
            ids = []
            async for message in user.iter_messages(CHANNEL_ID, search=origen, limit=300):
                if message.photo or message.video or message.document:
                    ids.append(message.id)

            if not ids:
                await status.edit(f"❌ No se encontraron archivos para `#{origen}`.")
                return

            user_searches[event.chat_id] = {
                "mover_ids": ids,
                "mover_index": 0,
                "origen_mov": origen,
                "destino_mov": destino
            }

            botones = [
                [Button.inline(f"🚀 Mover TODOS ({len(ids)}) de golpe", data=b"mover_modo_todos")],
                [Button.inline("👁️ Seleccionar / Mover 1 por 1", data=b"mover_modo_indiv")]
            ]
            await status.edit(
                f"📂 Se encontraron **{len(ids)}** archivos etiquetados como `#{origen}`.\n"
                f"¿Cómo deseas moverlos a `#{destino}`?",
                buttons=botones
            )
            return

        query = event.raw_text
        status_msg = await event.reply(f"🔍 Buscando '{query}'...")
        all_ids, photos, videos, gifs = [], [], [], []

        async for message in user.iter_messages(CHANNEL_ID, search=query, limit=200):
            if message.photo or message.video or message.document:
                all_ids.append(message.id)
                if message.photo:
                    photos.append(message.id)
                elif message.video:
                    videos.append(message.id)
                elif message.document:
                    # Detectar si es un GIF por extensión o atributos del archivo
                    is_gif = False
                    if message.file and message.file.name and message.file.name.lower().endswith('.gif'):
                        is_gif = True
                    elif message.file and message.file.mime_type == 'image/gif':
                        is_gif = True
                    elif 'gif' in extraer_categorias(message):
                        is_gif = True
                        
                    if is_gif:
                        gifs.append(message.id)

        if not all_ids:
            query_limpia = query.lower().replace('#', '').strip()
            indice = cargar_indice()
            
            botones_vacio = [Button.inline("⬅️ Volver al menú", data="volver_menu".encode())]
            if query_limpia in indice:
                botones_vacio.insert(0, Button.inline(f"🗑️ Eliminar '{query_limpia}' del índice y canal", data=f"del_cat_{query_limpia}".encode()))

            await status_msg.edit(f"No se encontraron archivos para '{query}'.", buttons=botones_vacio)
            return

        user_searches[event.chat_id] = {
            "all_ids": all_ids,
            "photos": photos,
            "videos": videos,
            "gifs": gifs,
            "page": 0,
            "filter": "all",
            "query": query,
            "origen": "menu"
        }
        await status_msg.delete()
        await send_page(event.chat_id)

    GRUPOS = [
        ("A-C", "abc"), ("D-F", "def"), ("G-I", "ghi"),
        ("J-L", "jkl"), ("M-O", "mno"), ("P-R", "pqr"),
        ("S-U", "stu"), ("V-Z", "vwxyz")
    ]

    async def mostrar_menu_principal(chat_id, indice=None):
        if indice is None: indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}

        botones = []
        for label, letras in GRUPOS:
            count = sum(1 for k in categorias_validas if k[0] in letras)
            if count > 0:
                botones.append([Button.inline(f"🔤 {label} ({count} nombres)", data=f"grupo_{label}".encode())])

        sin_nombre_count = indice.get("sin_nombre", 0)
        if sin_nombre_count > 0:
            botones.append([Button.inline(f"📂 Sin nombre ({sin_nombre_count:,} archivos)", data=b"search_sin_nombre")])

        total = sum(categorias_validas.values())
        await bot.send_message(
            chat_id,
            f"📚 **Índice del Canal**\n_{len(categorias_validas)} nombres · {total:,} archivos_\n\nElige una opción:",
            buttons=botones
        )

    async def mostrar_grupo(chat_id, label, letras):
        indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}
        botones = []
        for letra in letras:
            cats = [(k, v) for k, v in categorias_validas.items() if k.startswith(letra)]
            if len(cats) > 0:
                botones.append([Button.inline(f"🔡 {letra.upper()} — {len(cats)} carpetas", data=f"letra_{letra}|{label}|{letras}".encode())])

        botones.append([Button.inline("⬅️ Volver", data=b"volver_menu")])
        await bot.send_message(chat_id, f"🔤 **Grupo {label}**", buttons=botones)

    async def mostrar_letra(chat_id, letra, label_grupo, letras_grupo):
        indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}
        filtradas = sorted([(k, v) for k, v in categorias_validas.items() if k.startswith(letra)], key=lambda x: x[0])

        botones = [[Button.inline(f"📁 {k.capitalize()} ({v:,})", data=f"search_{k}".encode())] for k, v in filtradas]
        botones.append([Button.inline("⬅️ Volver", data=f"volver_grupo_{label_grupo}".encode())])

        for i in range(0, len(botones), 95):
            await bot.send_message(chat_id, f"🔡 **Letra {letra.upper()}**", buttons=botones[i:i + 95])

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode('utf-8')
        chat_id = event.chat_id

        if data.startswith("del_cat_"):
            cat_a_borrar = data.replace("del_cat_", "").lower().strip()
            indice = cargar_indice()
            
            if cat_a_borrar in indice:
                del indice[cat_a_borrar]
                guardar_indice(indice)

            await event.edit(f"🗑️ Eliminando `#{cat_a_borrar}` del índice y buscando archivos en el canal para borrarlos...")
            contador_borrados = 0
            try:
                async for message in user.iter_messages(CHANNEL_ID, search=cat_a_borrar, limit=300):
                    if message.photo or message.video or message.document:
                        await user.delete_messages(CHANNEL_ID, [message.id])
                        contador_borrados += 1
                        await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Error al borrar archivos del canal: {e}")

            await event.edit(f"🗑️ Categoría `#{cat_a_borrar}` eliminada del índice.\n🔥 Se borraron **{contador_borrados}** archivos del canal exitosamente.")
            return

        if data == "next_page":
            if chat_id in user_searches:
                user_searches[chat_id]["page"] += 1
                await event.delete()
                await send_page(chat_id)

        elif data.startswith("filter_"):
            tipo = data[len("filter_"):]
            if chat_id in user_searches:
                user_searches[chat_id]["filter"] = tipo
                user_searches[chat_id]["page"] = 0
                await event.delete()
                await send_page(chat_id)

        elif data == "volver_menu":
            await event.delete()
            await mostrar_menu_principal(chat_id)

        elif data.startswith("volver_grupo_"):
            label = data[len("volver_grupo_"):]
            letras = next((l for lbl, l in GRUPOS if lbl == label), "")
            await event.delete()
            await mostrar_grupo(chat_id, label, letras)

        elif data.startswith("grupo_"):
            label = data[len("grupo_"):]
            letras = next((l for lbl, l in GRUPOS if lbl == label), "")
            await event.delete()
            await mostrar_grupo(chat_id, label, letras)

        elif data.startswith("letra_"):
            partes = data[len("letra_"):].split("|")
            await event.delete()
            await mostrar_letra(chat_id, partes[0], partes[1], partes[2])

        elif data.startswith("search_"):
            query = data[len("search_"):]
            await event.delete()

            status_msg = await bot.send_message(chat_id, f"🔍 Cargando '{query}'...")
            all_ids, photos, videos, gifs = [], [], [], []

            if query == "sin_nombre":
                async for message in user.iter_messages(CHANNEL_ID, limit=5000):
                    if (message.photo or message.video or message.document) and not extraer_categorias(message):
                        all_ids.append(message.id)
                        if message.photo: photos.append(message.id)
                        elif message.video: videos.append(message.id)
                        elif message.document:
                            is_gif = False
                            if message.file and message.file.name and message.file.name.lower().endswith('.gif'):
                                is_gif = True
                            elif message.file and message.file.mime_type == 'image/gif':
                                is_gif = True
                            if is_gif: gifs.append(message.id)
                            
                        if len(all_ids) >= 200: break
                display_query = "Sin nombre"
            else:
                async for message in user.iter_messages(CHANNEL_ID, search=query, limit=200):
                    if message.photo or message.video or message.document:
                        all_ids.append(message.id)
                        if message.photo: 
                            photos.append(message.id)
                        elif message.video: 
                            videos.append(message.id)
                        elif message.document:
                            is_gif = False
                            if message.file and message.file.name and message.file.name.lower().endswith('.gif'):
                                is_gif = True
                            elif message.file and message.file.mime_type == 'image/gif':
                                is_gif = True
                            elif 'gif' in extraer_categorias(message):
                                is_gif = True
                            if is_gif:
                                gifs.append(message.id)
                display_query = query

            user_searches[chat_id] = {
                "all_ids": all_ids, "photos": photos, "videos": videos, "gifs": gifs,
                "page": 0, "filter": "all", "query": display_query, "origen": "menu"
            }
            await status_msg.delete()
            await send_page(chat_id)

        elif data.startswith("req_del_"):
            msg_id = int(data.replace("req_del_", ""))
            botones_confirmacion = [
                [
                    Button.inline("⚠️ Sí, eliminar", data=f"del_{msg_id}".encode()),
                    Button.inline("❌ Cancelar", data=f"cancel_del_{msg_id}".encode())
                ]
            ]
            await event.edit(
                text=f"⚠️ **¿Estás seguro de que deseas eliminar este archivo?** (ID: `{msg_id}`)",
                buttons=botones_confirmacion
            )

        elif data.startswith("cancel_del_"):
            msg_id = int(data.replace("cancel_del_", ""))
            botones_acciones = [
                [
                    Button.inline("🔄 Mover", data=f"req_mover_{msg_id}".encode()),
                    Button.inline("🗑️ Eliminar", data=f"req_del_{msg_id}".encode())
                ]
            ]
            await event.edit(
                text=f"🛠️ Opciones para el archivo (ID: `{msg_id}`):",
                buttons=botones_acciones
            )

        elif data.startswith("del_"):
            msg_id = int(data.replace("del_", ""))
            try:
                await user.delete_messages(CHANNEL_ID, [msg_id])
                await event.answer("🗑️ Archivo eliminado del canal exitosamente.", alert=True)
                await event.edit(text="🗑️ *[Archivo eliminado]*", buttons=None)
            except Exception as e:
                await event.answer(f"❌ Error al eliminar: {str(e)}", alert=True)

        elif data.startswith("req_mover_"):
            msg_id = int(data.replace("req_mover_", ""))
            if chat_id not in user_searches:
                user_searches[chat_id] = {}
            user_searches[chat_id]["single_mover_id"] = msg_id

            indice = cargar_indice()
            categorias_validas = {k: v for k, v in indice.items() if v >= 3}
            
            botones = [
                [Button.inline("⌨️ 🔍 Escribir destino manualmente", data=f"smove_manual_{msg_id}".encode())]
            ]
            for label, letras in GRUPOS:
                count = sum(1 for k in categorias_validas if k[0] in letras)
                if count > 0:
                    botones.append([Button.inline(f"🔤 Grupo {label}", data=f"smove_grupo_{label}".encode())])
            botones.append([Button.inline("❌ Cancelar", data=b"cancel_smove")])

            await event.edit(
                f"🔄 **Mover archivo (ID: `{msg_id}`)**\n\nElige una opción o escribe directamente el destino:",
                buttons=botones
            )

        elif data.startswith("smove_manual_"):
            msg_id = int(data.replace("smove_manual_", ""))
            waiting_manual_move[chat_id] = msg_id
            await event.edit(
                f"✍️ **Búsqueda manual de destino (ID: `{msg_id}`)**\n\n"
                f"Por favor, **escribe el nombre de la categoría/carpeta destino** en el chat (ejemplo: `rojo`):"
            )

        elif data.startswith("smove_grupo_"):
            label = data[len("smove_grupo_"):]
            letras = next((l for lbl, l in GRUPOS if lbl == label), "")
            indice = cargar_indice()
            categorias_validas = {k: v for k, v in indice.items() if v >= 3}

            botones = []
            for letra in letras:
                cats = [(k, v) for k, v in categorias_validas.items() if k.startswith(letra)]
                if len(cats) > 0:
                    botones.append([Button.inline(f"🔡 {letra.upper()} — {len(cats)} carpetas", data=f"smove_letra_{letra}|{label}".encode())])
            botones.append([Button.inline("⬅️ Volver", data=b"back_smove_grupos")])

            await event.edit(f"🔤 **Grupo {label}** — Elige una letra:", buttons=botones)

        elif data.startswith("smove_letra_"):
            partes = data[len("smove_letra_"):].split("|")
            letra, label_grupo = partes[0], partes[1]
            indice = cargar_indice()
            categorias_validas = {k: v for k, v in indice.items() if v >= 3}
            filtradas = sorted([(k, v) for k, v in categorias_validas.items() if k.startswith(letra)], key=lambda x: x[0])

            botones = [[Button.inline(f"📁 #{k.capitalize()} ({v:,})", data=f"smove_target_{k}".encode())] for k, v in filtradas]
            botones.append([Button.inline("⬅️ Volver", data=f"smove_grupo_{label_grupo}".encode())])

            for i in range(0, len(botones), 95):
                await event.edit(f"🔡 **Letra {letra.upper()}** — Selecciona la categoría de destino:", buttons=botones[i:i + 95])

        elif data == "back_smove_grupos":
            chat_data = user_searches.get(chat_id, {})
            msg_id = chat_data.get("single_mover_id")
            indice = cargar_indice()
            categorias_validas = {k: v for k, v in indice.items() if v >= 3}
            
            botones = [
                [Button.inline("⌨️ 🔍 Escribir destino manualmente", data=f"smove_manual_{msg_id}".encode())]
            ]
            for label, letras in GRUPOS:
                count = sum(1 for k in categorias_validas if k[0] in letras)
                if count > 0:
                    botones.append([Button.inline(f"🔤 Grupo {label}", data=f"smove_grupo_{label}".encode())])
            botones.append([Button.inline("❌ Cancelar", data=b"cancel_smove")])

            await event.edit(
                f"🔄 **Mover archivo (ID: `{msg_id}`)**\n\nElige una opción o escribe directamente el destino:",
                buttons=botones
            )

        elif data.startswith("smove_target_"):
            destino = data[len("smove_target_"):]
            chat_data = user_searches.get(chat_id, {})
            msg_id = chat_data.get("single_mover_id")

            if not msg_id:
                await event.answer("❌ Error: No se encontró el ID del archivo.", alert=True)
                return

            message = await user.get_messages(CHANNEL_ID, ids=msg_id)
            if message:
                texto_actual = message.text or ""
                if f"#{destino}" not in texto_actual.lower():
                    nuevo_texto = f"{texto_actual}\n#{destino}".strip()
                else:
                    nuevo_texto = texto_actual

                try:
                    await user.edit_message(CHANNEL_ID, msg_id, text=nuevo_texto)
                    await event.edit(f"✅ **¡Archivo movido con éxito!**\nSe le añadió la etiqueta `#{destino}` (ID: `{msg_id}`).")
                except Exception as e:
                    await event.edit(f"❌ Error al editar el mensaje en Telegram: {str(e)}")
            else:
                await event.edit("❌ No se pudo encontrar el mensaje original en el canal.")

        elif data == "cancel_smove":
            await event.edit("❌ Operación de movimiento cancelada.")

        elif data == "mover_modo_todos":
            info = user_searches.get(chat_id)
            if not info: return
            await event.edit("⏳ Moviendo todos los archivos en lote...")
            origen, destino = info["origen_mov"], info["destino_mov"]
            count = 0

            for msg_id in info["mover_ids"]:
                message = await user.get_messages(CHANNEL_ID, ids=msg_id)
                if message:
                    texto_actual = message.text or ""
                    nuevo_texto = re.sub(rf'#{re.escape(origen)}\b', f'#{destino}', texto_actual, flags=re.IGNORECASE)
                    if nuevo_texto != texto_actual:
                        await user.edit_message(CHANNEL_ID, msg_id, text=nuevo_texto)
                        count += 1
                        await asyncio.sleep(1)

            await event.edit(f"✅ Se movieron **{count}** archivos de `#{origen}` a `#{destino}`.")

        elif data == "mover_modo_indiv":
            await event.delete()
            await mostrar_archivo_para_mover(chat_id)

        elif data.startswith("confirm_mover_"):
            msg_id = int(data[len("confirm_mover_"):])
            info = user_searches.get(chat_id)
            if info:
                origen, destino = info["origen_mov"], info["destino_mov"]
                message = await user.get_messages(CHANNEL_ID, ids=msg_id)
                if message:
                    texto_actual = message.text or ""
                    nuevo_texto = re.sub(rf'#{re.escape(origen)}\b', f'#{destino}', texto_actual, flags=re.IGNORECASE)
                    if nuevo_texto == texto_actual and origen in texto_actual.lower():
                        nuevo_texto = re.sub(rf'\b{re.escape(origen)}\b', destino, texto_actual, flags=re.IGNORECASE)

                    try:
                        await user.edit_message(CHANNEL_ID, msg_id, text=nuevo_texto)
                        await event.answer("✅ Movido y limpiado de ubicación anterior")
                    except Exception:
                        await event.answer("❌ Error")

                info["mover_index"] += 1
                await event.delete()
                await mostrar_archivo_para_mover(chat_id)

        elif data == "skip_mover":
            info = user_searches.get(chat_id)
            if info:
                info["mover_index"] += 1
                await event.delete()
                await mostrar_archivo_para_mover(chat_id)

    @user.on(events.NewMessage(chats=CHANNEL_ID))
    async def auto_update_index(event):
        cats = extraer_categorias(event.message)
        if cats:
            indice = cargar_indice()
            for cat in cats:
                indice[cat] = indice.get(cat, 0) + 1
            guardar_indice(indice)

    await asyncio.gather(
        bot.run_until_disconnected(),
        user.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())
