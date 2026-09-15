import os
import logging
import asyncio
import json
import re
import threading
from flask import Flask
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from dotenv import load_dotenv

# --- SERVIDOR WEB PARA MANTENER ACTIVO EL WEB SERVICE EN RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "¡Bot activo y funcionando 24/7 en Render!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# Iniciar el servidor web en un hilo independiente
threading.Thread(target=run_flask, daemon=True).start()

# --- CONFIGURACIÓN DE TELEGRAM Y TELETHON ---
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
except ValueError:
    pass

user_searches = {}
INDEX_FILE = 'indice_categorias.json'

def cargar_indice():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r') as f:
            return json.load(f)
    return {}

def guardar_indice(datos):
    with open(INDEX_FILE, 'w') as f:
        json.dump(datos, f, indent=4)

def extraer_categorias(message):
    """
    Extrae TODAS las palabras significativas de un mensaje.
    Ej: 'nicolette_shea_01.mp4' -> ['nicolette', 'shea']
    Retorna una lista (puede ser vacía).
    """
    if not (message.photo or message.video or message.document):
        return []

    categorias = set()

    # 1. Buscar hashtags (#shea, #nicolette, etc.)
    if message.text:
        hashtags = re.findall(r'#(\w+)', message.text)
        for tag in hashtags:
            categorias.add(tag.lower())

    # 2. Extraer palabras del nombre del archivo o del texto
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
            else:
                categorias.add(p)

    return list(categorias)

async def main():
    print("Iniciando conexión...")
    
    bot = TelegramClient('bot_session', int(API_ID), API_HASH)
    user = TelegramClient(StringSession(USER_SESSION_STRING), int(API_ID), API_HASH)
    
    await bot.start(bot_token=BOT_TOKEN)
    await user.start()
    
    print("\n" + "="*50)
    print("✅ ¡Bot con Índice Automático listo!")
    print("="*50 + "\n")

    async def send_page(chat_id):
        data = user_searches.get(chat_id)
        if not data: return
        page = data["page"]
        ids = data["ids"]
        query = data["query"]
        origen = data.get("origen", "menu")
        
        start = page * 5
        end = start + 5
        current_ids = ids[start:end]
        
        try:
            await bot.forward_messages(chat_id, current_ids, from_peer=CHANNEL_ID)
        except Exception as e:
            await bot.send_message(chat_id, "Error al reenviar los archivos.")
            return
        
        fila_nav = []
        if end < len(ids):
            fila_nav.append(Button.inline("➡️ Más archivos", data=b"next_page"))
        
        fila_nav.append(Button.inline("⬅️ Volver", data=f"volver_{origen}".encode()))

        msg_text = f"📄 Mostrando archivos {start+1} a {min(end, len(ids))} de **{len(ids)}** encontrados para '{query}'."
        if end >= len(ids):
            msg_text += "\n✅ Fin de los resultados."

        await bot.send_message(chat_id, msg_text, buttons=[fila_nav])

    @bot.on(events.NewMessage)
    async def bot_handler(event):
        texto = event.raw_text.lower().strip()
        
        if texto == '/start':
            await event.reply(
                "¡Hola! Envíame cualquier palabra para buscar.\n\n"
                "Comandos especiales:\n"
                "/crear_indice - Escanea el canal para armar el menú\n"
                "/index - Muestra el menú de nombres\n"
                "/mover origen destino - Mueve archivos de una etiqueta a otra (Ej: `/mover rojo azul`)"
            )
            return
            
        if texto == '/crear_indice':
            status = await event.reply("⏳ Iniciando escaneo profundo para crear el índice... (Esto tomará unos minutos).")
            indice = {}
            count = 0
            
            async for message in user.iter_messages(CHANNEL_ID):
                count += 1
                if count % 10000 == 0:
                    await status.edit(f"⏳ Escaneando... {count} mensajes revisados...")
                
                if not (message.photo or message.video or message.document):
                    continue

                cats = extraer_categorias(message)
                if cats:
                    for cat in cats:
                        indice[cat] = indice.get(cat, 0) + 1
                else:
                    indice['sin_nombre'] = indice.get('sin_nombre', 0) + 1
            
            guardar_indice(indice)
            sin_nombre = indice.get('sin_nombre', 0)
            await status.edit(
                f"✅ ¡Índice creado con éxito!\n"
                f"Se encontraron **{len(indice)}** categorías distintas.\n"
                f"📁 Archivos sin nombre detectados: **{sin_nombre:,}**\n"
                f"Escribe **/index** para ver el menú."
            )
            return
            
        if texto == '/index':
            indice = cargar_indice()
            if not indice:
                await event.reply("El índice está vacío. Escribe /crear_indice primero.")
                return
            await mostrar_menu_principal(event.chat_id, indice)
            return

        if texto.startswith('/mover'):
            partes = event.raw_text.split()
            if len(partes) < 3:
                await event.reply("⚠️ **Uso incorrecto.**\nEjemplo: `/mover rojo azul` (mueve los archivos etiquetados como 'rojo' a la carpeta 'azul').")
                return

            origen = partes[1].lower().replace('#', '')
            destino = partes[2].lower().replace('#', '')

            status = await event.reply(f"⏳ Buscando archivos de **#{origen}** para moverlos a **#{destino}**...")

            count = 0
            async for message in user.iter_messages(CHANNEL_ID, search=origen):
                if not (message.photo or message.video or message.document):
                    continue

                texto_actual = message.text or ""
                
                nuevo_texto = re.sub(rf'#{re.escape(origen)}\b', f'#{destino}', texto_actual, flags=re.IGNORECASE)
                
                if nuevo_texto == texto_actual and origen in texto_actual.lower():
                    nuevo_texto = re.sub(rf'\b{re.escape(origen)}\b', destino, texto_actual, flags=re.IGNORECASE)

                if nuevo_texto != texto_actual:
                    try:
                        await user.edit_message(CHANNEL_ID, message.id, text=nuevo_texto)
                        count += 1
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Error editando mensaje {message.id}: {e}")

            if count > 0:
                indice = cargar_indice()
                
                if origen in indice:
                    indice[origen] = max(0, indice[origen] - count)
                    if indice[origen] == 0:
                        del indice[origen]

                indice[destino] = indice.get(destino, 0) + count
                guardar_indice(indice)

                await status.edit(f"✅ **¡Movimiento completado!**\nSe actualizaron **{count}** archivos de `#{origen}` a `#{destino}`.")
            else:
                await status.edit(f"❌ No se encontraron mensajes con la etiqueta `#{origen}` para modificar.")
            return

        query = event.raw_text
        status_msg = await event.reply(f"🔍 Buscando '{query}'...")
        try:
            ids = []
            async for message in user.iter_messages(CHANNEL_ID, search=query, limit=200):
                if message.photo or message.video or message.document:
                    ids.append(message.id)
            if not ids:
                await status_msg.edit(f"No encontré archivos para '{query}'.")
                return
            user_searches[event.chat_id] = {"ids": ids, "page": 0, "query": query}
            await status_msg.edit(f"✅ Encontré **{len(ids)}** archivos. Enviando los primeros 5:")
            await send_page(event.chat_id)
        except Exception as e:
            await status_msg.edit("Hubo un error al buscar.")

    GRUPOS = [
        ("A-C", "abc"),
        ("D-F", "def"),
        ("G-I", "ghi"),
        ("J-L", "jkl"),
        ("M-O", "mno"),
        ("P-R", "pqr"),
        ("S-U", "stu"),
        ("V-Z", "vwxyz"),
        ("📂 Sin nombre / Otros", ""),
    ]

    async def mostrar_menu_principal(chat_id, indice=None):
        if indice is None:
            indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}

        botones = []
        for label, letras in GRUPOS:
            if letras:
                count = sum(1 for k in categorias_validas if k[0] in letras)
            else:
                count = sum(1 for k in categorias_validas if not k[0].isalpha())
            if count > 0:
                botones.append([Button.inline(f"🔤 {label}  ({count} nombres)", data=f"grupo_{label}".encode())])

        if not botones:
            await bot.send_message(chat_id, "No hay categorías disponibles.")
            return

        total = sum(categorias_validas.values())
        await bot.send_message(
            chat_id,
            f"📚 **Índice de tu Canal**\n_{len(categorias_validas)} nombres · {total:,} archivos indexados_\n\nElige un grupo de letras:",
            buttons=botones
        )

    async def mostrar_grupo(chat_id, label, letras):
        indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}

        if not letras:
            await mostrar_letra(chat_id, "", label, letras)
            return

        botones = []
        for letra in letras:
            cats = [(k, v) for k, v in categorias_validas.items() if k.startswith(letra)]
            count_cats = len(cats)
            count_files = sum(v for _, v in cats)
            if count_cats > 0:
                botones.append([Button.inline(
                    f"🔡 {letra.upper()}  —  {count_cats} carpetas · {count_files:,} archivos",
                    data=f"letra_{letra}|{label}|{letras}".encode()
                )])

        if not botones:
            await bot.send_message(chat_id, "No hay nombres en este grupo.")
            return

        botones.append([Button.inline("⬅️ Volver al menú principal", data=b"volver_menu")])
        await bot.send_message(
            chat_id,
            f"🔤 **Grupo {label}**\nElige una letra:",
            buttons=botones
        )

    async def mostrar_letra(chat_id, letra, label_grupo, letras_grupo):
        indice = cargar_indice()
        categorias_validas = {k: v for k, v in indice.items() if v >= 3}

        if letra:
            filtradas = [(k, v) for k, v in categorias_validas.items() if k.startswith(letra)]
            filtradas = sorted(filtradas, key=lambda x: x[0])
            header = f"🔡 **Letra {letra.upper()}** — {len(filtradas)} carpetas\nElige una:"
            volver_data = f"volver_grupo_{label_grupo}".encode()
        else:
            filtradas = [(k, v) for k, v in categorias_validas.items() if not k[0].isalpha()]
            filtradas = sorted(filtradas, key=lambda x: (x[0] != 'sin_nombre', x[0]))
            header = f"📂 **Sin nombre / Otros** — {len(filtradas)} categorías\nElige una:"
            volver_data = b"volver_menu"

        if not filtradas:
            await bot.send_message(chat_id, "No hay carpetas aquí.")
            return

        botones = []
        for nombre, cantidad in filtradas:
            display = "📂 Sin nombre" if nombre == "sin_nombre" else nombre.capitalize()
            botones.append([Button.inline(f"📁 {display} ({cantidad:,})", data=f"search_{nombre}".encode())])

        botones.append([Button.inline("⬅️ Volver", data=volver_data)])

        chunk_size = 95
        for i in range(0, len(botones), chunk_size):
            chunk = botones[i:i + chunk_size]
            msg = header if i == 0 else f"🔡 **{letra.upper() if letra else 'Otros'}** (continuación)"
            await bot.send_message(chat_id, msg, buttons=chunk)

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data.decode('utf-8')
        chat_id = event.chat_id

        if data == "next_page":
            if chat_id in user_searches:
                user_searches[chat_id]["page"] += 1
                await event.delete()
                await send_page(chat_id)
            else:
                await event.answer("Búsqueda expirada.")

        elif data.startswith("volver_"):
            destino = data[len("volver_"):]
            await event.delete()
            if destino == "menu":
                await mostrar_menu_principal(chat_id)
            elif destino.startswith("grupo_"):
                label = destino[len("grupo_"):]
                letras = next((l for lbl, l in GRUPOS if lbl == label), "")
                await mostrar_grupo(chat_id, label, letras)
            else:
                await mostrar_menu_principal(chat_id)

        elif data.startswith("grupo_"):
            label = data[len("grupo_"):]
            letras = next((l for lbl, l in GRUPOS if lbl == label), "")
            await event.delete()
            await mostrar_grupo(chat_id, label, letras)

        elif data.startswith("letra_"):
            partes = data[len("letra_"):].split("|")
            letra = partes[0]
            label_grupo = partes[1] if len(partes) > 1 else ""
            letras_grupo = partes[2] if len(partes) > 2 else ""
            await event.delete()
            await mostrar_letra(chat_id, letra, label_grupo, letras_grupo)

        elif data.startswith("search_"):
            query = data[len("search_"):]

            primera = query[0] if query else ""
            origen_grupo = next(
                (f"grupo_{lbl}" for lbl, letras in GRUPOS if primera in letras),
                "menu"
            )

            await event.delete()

            if query == "sin_nombre":
                status_msg = await bot.send_message(chat_id, "🔍 Buscando archivos sin nombre (esto puede tardar un poco)...")
                ids = []
                async for message in user.iter_messages(CHANNEL_ID, limit=5000):
                    if not (message.photo or message.video or message.document):
                        continue
                    cats = extraer_categorias(message)
                    if not cats:
                        ids.append(message.id)
                    if len(ids) >= 200:
                        break
                display_query = "Sin nombre"
            else:
                status_msg = await bot.send_message(chat_id, f"🔍 Buscando '{query}'...")
                ids = []
                async for message in user.iter_messages(CHANNEL_ID, search=query, limit=200):
                    if message.photo or message.video or message.document:
                        ids.append(message.id)
                display_query = query

            if not ids:
                await status_msg.edit(f"No encontré archivos para '{display_query}'.")
                return
            user_searches[chat_id] = {"ids": ids, "page": 0, "query": display_query, "origen": origen_grupo}
            await status_msg.edit(f"✅ Encontré **{len(ids)}** archivos para '{display_query}'. Enviando los primeros 5:")
            await send_page(chat_id)

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
