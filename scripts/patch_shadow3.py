# -*- coding: utf-8 -*-
"""Тени v3, часть 1: меню статистики в канале «Фон» (кнопки: таймфрейм и вид сделки: отбой LONG, отбой SHORT, пробой). Патч поверх tg_bot.py с патчем v2. Идемпотентный.
Использование: python3 patch_shadow3.py tg_bot.py"""
import os, sys

CODE = '''def shadow_menu_ensure(chat):
    """Одно закрепляемое сообщение-меню в канале теней: кнопки таймфрейма и вида сделки, сводка меняется по нажатию."""
    m = SH.msg_get("menu")
    if m.get("mid") or time.time() < _SHW[0]: return
    r = _shc("sendMessage", {"chat_id": chat, "text": SH.stats_text("all", "all"), "reply_markup": json.dumps({"inline_keyboard": SH.menu_keyboard("all", "all")}, ensure_ascii=False), "disable_notification": "true"})
    if r[0] is True and _mid_of(r):
        SH.msg_set("menu", mid=_mid_of(r))
        try: tg_try("pinChatMessage", {"chat_id": chat, "message_id": _mid_of(r), "disable_notification": "true"})
        except Exception as e: log("shadow: закрепить меню не удалось: %s" % e)


def shadow_stats_cb(msg, cid, p):
    """Нажатие в меню статистики теней: shs:<таймфрейм|all>:<all|bl|bs|brk>."""
    tf = p[1] if len(p) > 1 and p[1] in ("all", "5m", "15m", "1h", "4h", "1d") else "all"; kind = p[2] if len(p) > 2 and p[2] in ("all", "bl", "bs", "brk") else "all"
    try: api("answerCallbackQuery", callback_query_id=cid)
    except Exception: pass
    try: api("editMessageText", chat_id=(msg.get("chat") or {}).get("id"), message_id=msg.get("message_id"), text=SH.stats_text(tf, kind), reply_markup={"inline_keyboard": SH.menu_keyboard(tf, kind)})
    except Exception as e: log("shadow stats: %s" % str(e)[:200])


def shadow_tg_loop():'''

BOT = [
 ("cb", '    elif p[0] == "cr":      # откат коррекции порога', '    elif p[0] == "shs": shadow_stats_cb(msg, cid, p)      # меню статистики теней в канале\n    elif p[0] == "cr":      # откат коррекции порога', "shadow_stats_cb(msg, cid, p)"),
 ("code", "def shadow_tg_loop():", CODE, "def shadow_stats_cb"),
 ("ens", '    n = 0\n    for it in sorted(SH.snapshot(), key=lambda x: x["id"]):\n        if n >= n_max or time.time() < _SHW[0]: break', '    shadow_menu_ensure(chat)\n    n = 0\n    for it in sorted(SH.snapshot(), key=lambda x: x["id"]):\n        if n >= n_max or time.time() < _SHW[0]: break', "    shadow_menu_ensure(chat)\n    n = 0"),
]


def patch(path):
    base = os.path.basename(path)
    if base != "tg_bot.py": print("SKIP", path); return 0
    s = open(path, encoding="utf-8").read(); out = s; bad = 0
    for name, old, new, marker in BOT:
        if marker in out: print("ALREADY", base, name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", base, name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
