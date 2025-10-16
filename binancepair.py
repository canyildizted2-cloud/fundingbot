import asyncio
import aiohttp
from telegram import Bot
import requests
from datetime import datetime, timezone, timedelta

# ==========================
# 🔧 AYARLAR
# ==========================
TOKEN = "8216123185:AAFFagX3te2flGeolABABqKRcpfeeTrVFVs"
CHAT_ID = "-4644896817"
FUNDING_THRESHOLD = 0.5  # %1 veya -%1 olduğunda tetikleme
CHECK_INTERVAL = 14400  # saniye (4 saat)
PARITY_FILE = "pariteler.txt"  # Paritelerin yazılı olduğu dosya
SCHEDULED_HOURS = [3.85, 7.85, 11.85, 15.85, 19.85, 23.85]  # UTC saatleri

# ==========================
# 📥 BINANCE FUTURES PAIR'LARINI ÇEK VE DOSYAYA YAZ
# ==========================
def fetch_binance_futures_pairs():
    """
    Binance futures pair'larını çekip dosyaya kaydeder
    """
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    
    try:
        print("🔍 Binance futures pair'ları çekiliyor...")
        response = requests.get(url)
        data = response.json()
        
        symbols = data['symbols']
        
        # USDT pair'larını filtrele
        usdt_pairs = [symbol['symbol'] for symbol in symbols 
                     if symbol['status'] == 'TRADING' and symbol['symbol'].endswith(('USDT' , 'USDC'))]
        
        usdt_pairs.sort()
        
        # Dosyaya yaz
        with open(PARITY_FILE, 'w', encoding='utf-8') as f:
            for pair in usdt_pairs:
                f.write(pair + '\n')
        
        print(f"✅ {len(usdt_pairs)} Binance futures pair'ı '{PARITY_FILE}' dosyasına kaydedildi!")
        
        # İlk ve son 5 pair'ı göster
        print(f"📋 İlk 5 pair: {usdt_pairs[:5]}")
        print(f"📋 Son 5 pair: {usdt_pairs[-5:]}")
        
        return usdt_pairs
        
    except Exception as e:
        print(f"❌ Binance pair'ları çekilemedi: {e}")
        return []

# ==========================
# 🔍 PARİTELERİ DOSYADAN OKU
# ==========================
def load_symbols(file_path):
    try:
        with open(file_path, "r") as f:
            symbols = [line.strip() for line in f if line.strip()]
        print(f"📖 {len(symbols)} parite dosyadan okundu")
        return symbols
    except Exception as e:
        print(f"❌ Parite dosyası okunamadı: {e}")
        return []

# ==========================
# 🔍 BINANCE FUNDING ORANI ÇEK
# ==========================
async def get_binance_funding_rate(session, symbol):
    """
    Binance'den funding rate çeker
    """
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    rate = float(data[0]['fundingRate'])
                    return symbol, rate
            return symbol, None
    except Exception as e:
        print(f"⚠️ {symbol} funding rate alınamadı: {e}")
        return symbol, None

# ==========================
# 🔍 BINANCE PREMIUM INDEX ÇEK (Alternatif)
# ==========================
async def get_binance_premium_index(session, symbol):
    """
    Binance premium index verisini çeker (alternatif metod)
    """
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if 'lastFundingRate' in data:
                    rate = float(data['lastFundingRate'])
                    return symbol, rate
            return symbol, None
    except Exception as e:
        print(f"⚠️ {symbol} premium index alınamadı: {e}")
        return symbol, None

# ==========================
# 🚨 TELEGRAM MESAJI GÖNDER
# ==========================
async def send_telegram_alert(bot, symbol, rate):
    rate_percent = rate * 100
    if rate_percent > 0:
        emoji = "📈"
        direction = "POZİTİF"
    else:
        emoji = "📉"
        direction = "NEGATİF"
    
    message = (
        f"{emoji} *Binance Funding Alert!*\n\n"
        f"💰 *{symbol}*\n"
        f"📊 Funding Rate: *{rate_percent:.3f}%*\n"
        f"⚡ Durum: *{direction}*"
    )
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        print(f"✅ Telegram mesajı gönderildi: {symbol} - {rate_percent:.3f}%")
    except Exception as e:
        print(f"❌ Telegram gönderme hatası: {e}")

# ==========================
# 🔍 TÜM FUNDING RATE'LERİ TOPLU ÇEK
# ==========================
async def get_all_funding_rates(session):
    """
    Tüm pair'ların funding rate'lerini tek seferde çeker
    """
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                funding_rates = {}
                for item in data:
                    if 'lastFundingRate' in item:
                        symbol = item['symbol']
                        rate = float(item['lastFundingRate'])
                        funding_rates[symbol] = rate
                return funding_rates
            return {}
    except Exception as e:
        print(f"❌ Toplu funding rate alınamadı: {e}")
        return {}

# ==========================
# ⏰ SONRAKI ZAMANLANMIŞ ÇALIŞMA SAATİNİ HESAPLA
# ==========================
def get_next_scheduled_time():
    """
    Bir sonraki zamanlanmış çalışma saatini UTC'ye göre hesaplar
    """
    now = datetime.now(timezone.utc)
    current_hour = now.hour + now.minute / 60.0
    
    # Bugün için zamanlanmış saatlerden sonraki ilkini bul
    for scheduled_hour in SCHEDULED_HOURS:
        if current_hour < scheduled_hour:
            next_time = now.replace(hour=int(scheduled_hour), minute=int((scheduled_hour % 1) * 60), second=0, microsecond=0)
            return next_time
    
    # Bugün için uygun saat yok, yarının ilk saatini al
    next_time = (now + timedelta(days=1)).replace(hour=int(SCHEDULED_HOURS[0]), minute=int((SCHEDULED_HOURS[0] % 1) * 60), second=0, microsecond=0)
    return next_time

# ==========================
# ⏳ BEKLEME SÜRESİNİ HESAPLA
# ==========================
def get_wait_time_until_next():
    """
    Bir sonraki zamanlanmış çalışmaya kadar geçecek saniye cinsinden süreyi hesaplar
    """
    next_time = get_next_scheduled_time()
    now = datetime.now(timezone.utc)
    wait_seconds = (next_time - now).total_seconds()
    return max(wait_seconds, 0)

# ==========================
# 🔁 ANA DÖNGÜ
# ==========================
async def main():
    bot = Bot(token=TOKEN)
    
    # Önce Binance pair'larını çek ve dosyaya yaz
    print("🚀 Binance Futures Pair'ları çekiliyor...")
    fetched_pairs = fetch_binance_futures_pairs()
    
    if not fetched_pairs:
        print("❌ Pair'lar çekilemedi, dosyadan okumaya çalışılıyor...")
    
    SYMBOLS = load_symbols(PARITY_FILE)
    if not SYMBOLS:
        print("❌ Parite listesi boş veya okunamadı, program sonlandırılıyor.")
        return

    print(f"🎯 {len(SYMBOLS)} parite ile Binance funding oranları izleniyor...")
    print(f"⚡ Eşik değer: %{FUNDING_THRESHOLD}")
    print(f"⏰ UTC Zamanlaması: {SCHEDULED_HOURS}\n")

    async with aiohttp.ClientSession() as session:
        first_run = True
        while True:
            try:
                print("🔍 Binance funding oranları taranıyor...")
                alert_count = 0
                
                # Toplu funding rate çekme (daha hızlı)
                all_funding_rates = await get_all_funding_rates(session)
                
                if all_funding_rates:
                    print("✅ Toplu funding rate verisi alındı")
                    
                    for symbol in SYMBOLS:
                        if symbol in all_funding_rates:
                            rate = all_funding_rates[symbol]
                            rate_percent = rate * 100

                            # 🔥 +%1 veya daha fazla / -%1 veya daha az olduğunda uyarı gönder
                            if rate_percent >= FUNDING_THRESHOLD:
                                print(f"🚨 {symbol}: {rate_percent:.3f}% → Pozitif funding uyarısı gönderiliyor...")
                                await send_telegram_alert(bot, symbol, rate)
                                alert_count += 1
                            elif rate_percent <= -FUNDING_THRESHOLD:
                                print(f"🚨 {symbol}: {rate_percent:.3f}% → Negatif funding uyarısı gönderiliyor...")
                                await send_telegram_alert(bot, symbol, rate)
                                alert_count += 1
                            else:
                                print(f"✅ {symbol}: {rate_percent:.3f}% (normal)")
                        else:
                            print(f"⚠️ {symbol}: funding rate verisi yok")
                
                else:
                    # Toplu çekme başarısız olursa teker teker çek
                    print("⚠️ Toplu veri alınamadı, teker teker çekiliyor...")
                    for symbol in SYMBOLS:
                        sym, rate = await get_binance_premium_index(session, symbol)
                        if rate is None:
                            # Alternatif metod deneyelim
                            sym, rate = await get_binance_funding_rate(session, symbol)
                            
                        if rate is None:
                            print(f"⚠️ {sym}: veri alınamadı")
                            continue

                        rate_percent = rate * 100

                        # 🔥 +%1 veya daha fazla / -%1 veya daha az olduğunda uyarı gönder
                        if rate_percent >= FUNDING_THRESHOLD:
                            print(f"🚨 {sym}: {rate_percent:.3f}% → Pozitif funding uyarısı gönderiliyor...")
                            await send_telegram_alert(bot, sym, rate)
                            alert_count += 1
                        elif rate_percent <= -FUNDING_THRESHOLD:
                            print(f"🚨 {sym}: {rate_percent:.3f}% → Negatif funding uyarısı gönderiliyor...")
                            await send_telegram_alert(bot, sym, rate)
                            alert_count += 1
                        else:
                            print(f"✅ {sym}: {rate_percent:.3f}% (normal)")

                        await asyncio.sleep(0.05)  # rate limit için kısa bekleme

                print(f"\n📊 Tarama tamamlandı. {alert_count} uyarı gönderildi. {len(SYMBOLS)} parite ile Binance funding tarandı")
                
                # Bekleme süresi hesapla
                if first_run:
                    wait_time = get_wait_time_until_next()
                    first_run = False
                else:
                    wait_time = get_wait_time_until_next()
                
                next_time = datetime.now(timezone.utc) + timedelta(seconds=wait_time)
                print(f"🕒 Sonraki çalışma: {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                print(f"⏳ {wait_time/60:.1f} dakika bekleniyor...\n")
                
                await asyncio.sleep(wait_time)

            except Exception as e:
                print(f"❌ Ana döngü hatası: {e}")
                await asyncio.sleep(60)

# ==========================
# ▶️ ÇALIŞTIR
# ==========================
if __name__ == "__main__":
    asyncio.run(main())