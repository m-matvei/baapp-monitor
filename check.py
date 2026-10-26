# Проверка доступности baapp.ru и уведомления в Telegram.
# Запускается GitHub Actions раз в ~5 минут. Состояние хранится в state.json.
import json, os, socket, ssl, subprocess, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

URL = 'https://baapp.ru/api/health'
HOST = 'baapp.ru'
MSK = timezone(timedelta(hours=3))
TOKEN, CHAT = os.environ.get('TG_TOKEN', '').strip(), os.environ.get('TG_CHAT', '').strip()
TEST = os.environ.get('TEST') == 'true'
now = datetime.now(MSK)

def send(text):
    if not TOKEN or not CHAT:
        print('Нет TG_TOKEN или TG_CHAT, сообщение:', text); return
    data = urllib.parse.urlencode({'chat_id': CHAT, 'text': text}).encode()
    for _ in range(3):
        try:
            urllib.request.urlopen(f'https://api.telegram.org/bot{TOKEN}/sendMessage', data, timeout=20); return
        except Exception as e:
            print('Telegram:', e); time.sleep(5)

def check_once():
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'baapp-monitor'}), timeout=20) as r:
            return r.status == 200, f'код {r.status}'
    except urllib.error.HTTPError as e:
        return False, f'код ответа {e.code}'
    except Exception as e:
        return False, type(e).__name__ + (f': {e.reason}' if hasattr(e, 'reason') else '')

def site_up():
    # три попытки с паузой, чтобы не тревожить из-за случайного сбоя сети
    why = ''
    for i in range(3):
        ok, why = check_once()
        if ok: return True, why
        if i < 2: time.sleep(20)
    return False, why

def cert_days():
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((HOST, 443), timeout=15) as s, ctx.wrap_socket(s, server_hostname=HOST) as t:
            exp = datetime.fromtimestamp(ssl.cert_time_to_seconds(t.getpeercert()['notAfter']), MSK)
            return (exp - now).days, exp
    except Exception as e:
        print('Сертификат:', e); return None, None

def dn(n):
    m, m1 = n % 100, n % 10
    return f"{n} {'дней' if 10 < m < 20 else 'дня' if 1 < m1 < 5 else 'день' if m1 == 1 else 'дней'}"

def mins(n):
    m, m1 = n % 100, n % 10
    return f"{n} {'минут' if 10 < m < 20 else 'минуты' if 1 < m1 < 5 else 'минуту' if m1 == 1 else 'минут'}"

try: st = json.load(open('state.json'))
except Exception: st = {}
old = json.dumps(st, sort_keys=True)

up, why = site_up()
if not up and not st.get('down'):
    st['down'] = True; st['since'] = now.isoformat()
    send(f'🔴 baapp.ru не отвечает ({why}). Проверено {now:%d.%m %H:%M} МСК.')
elif up and st.get('down'):
    since = datetime.fromisoformat(st['since']); m = max(1, round((now - since).total_seconds() / 60))
    st['down'] = False; st.pop('since', None)
    send(f'🟢 baapp.ru снова работает. Простой около {mins(m)}.')

# раз в неделю (понедельник утром) или при ручном запуске — короткий отчёт и срок сертификата
week = now.strftime('%G-%V')
if TEST or (now.weekday() == 0 and now.hour >= 9 and st.get('week') != week):
    days, exp = cert_days()
    cert = f'сертификат https действует до {exp:%d.%m.%Y} (ещё {dn(days)})' if days is not None else 'сертификат проверить не удалось'
    if days is not None and days < 20: cert += ' ⚠️ пора проверить продление'
    status = '✅ baapp.ru работает' if up else f'🔴 baapp.ru сейчас не отвечает ({why})'
    send(('Тестовое сообщение. ' if TEST else 'Еженедельная проверка. ') + f'{status}, {cert}.')
    if not TEST: st['week'] = week

if json.dumps(st, sort_keys=True) != old:
    json.dump(st, open('state.json', 'w'), ensure_ascii=False, indent=1)
    subprocess.run('git config user.name monitor && git config user.email monitor@users.noreply.github.com && git add state.json && git commit -m "state" && git push', shell=True)
print('up' if up else 'down', why)
