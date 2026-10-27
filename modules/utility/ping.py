import time
from telegram import Update
from telegram.ext import ContextTypes

def get_android_network_usage():
    try:
        total_rx = 0
        total_tx = 0
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()
        for line in lines[2:]:
            parts = line.split(':')
            if len(parts) == 2:
                iface = parts[0].strip()
                if iface == 'lo':
                    continue
                data = parts[1].split()
                if len(data) >= 9:
                    total_rx += int(data[0])
                    total_tx += int(data[8])
        return total_rx / (1024 * 1024), total_tx / (1024 * 1024)
    except Exception:
        return 0.0, 0.0

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000, 2)

    bytes_recv_mb, bytes_sent_mb = get_android_network_usage()

    text = (
        f"🏓 <b>Pong!</b>\n\n"
        f"⏱ <b>Latency:</b> <code>{latency} ms</code>\n\n"
        f"📊 <b>Tablet Network Stats:</b>\n"
        f"📤 <b>Sent:</b> <code>{bytes_sent_mb:.2f} MB</code>\n"
        f"📥 <b>Received:</b> <code>{bytes_recv_mb:.2f} MB</code>"
    )
    await msg.edit_text(text, parse_mode='HTML')
