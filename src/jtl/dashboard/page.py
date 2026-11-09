"""Simple, Arabic-first leaderboard page: one card per bot, plain words, no jargon up front."""

from __future__ import annotations

import html

from jtl import HYPOTHETICAL_BANNER

BOT_INFO: dict[str, tuple[str, str]] = {
    "sma50-200": (
        "المتوسطات البطيئة",
        "بيشتري لما الاتجاه العام طالع (معدّل آخر 50 يوم أعلى من معدّل آخر 200 يوم)، وبيبيع لما ينقلب. قليل الحركة.",
    ),
    "sma20-100": ("المتوسطات المتوسطة", "نفس الفكرة بس أسرع شوي: معدّل 20 يوم مقابل معدّل 100 يوم."),
    "sma10-50": ("المتوسطات السريعة", "أسرع واحد: معدّل 10 أيام مقابل 50 يوم. بيتحرك كتير."),
    "mom126": ("زخم 6 شهور", "بيشتري إذا السعر اليوم أعلى من قبل 6 شهور، وبيطلع إذا صار أقل."),
    "mom63": ("زخم 3 شهور", "متل اللي قبله، بس بيقارن مع السعر من 3 شهور."),
    "hold": ("اشتري وخلّيه", "بيشتري مرة وحدة وبيضل محتفظ، ضمن حدود الأمان."),
}

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--text:#1d2129;--muted:#667085;--line:#e4e7ec;--up:#12805c;--upbg:#e3f5ec;
--down:#c4320a;--downbg:#fdebe5;--flat:#667085;--flatbg:#eef0f3;--warn:#8a5a00;--warnbg:#fff4d6;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--text:#e8eaee;--muted:#98a2b3;--line:#2a2f38;
--up:#4cc38a;--upbg:#12301f;--down:#ff7a59;--downbg:#3a1a12;--flat:#98a2b3;--flatbg:#232831;--warn:#ffcf66;
--warnbg:#33290f;--accent:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:"Segoe UI",Tahoma,system-ui,sans-serif;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:26px;margin:0}h2{font-size:19px;margin:28px 0 12px}
.sub{color:var(--muted);margin:4px 0 0}
.fake{display:inline-block;background:var(--warnbg);color:var(--warn);border-radius:999px;padding:4px 12px;
font-weight:600;font-size:14px;margin-top:10px}
.info{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:18px}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.box .k{color:var(--muted);font-size:13px}.box .v{font-size:20px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;display:flex;
flex-direction:column;gap:8px}
.card.first{border:2px solid var(--accent)}
.top{display:flex;align-items:center;gap:10px}
.rank{width:30px;height:30px;border-radius:50%;background:var(--flatbg);display:grid;place-items:center;
font-weight:700;flex:none}.first .rank{background:var(--accent);color:#fff}
.name{font-weight:700;font-size:17px}.desc{color:var(--muted);font-size:14px;min-height:44px}
.val{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.big{font-size:30px;font-weight:800}
.pill{border-radius:999px;padding:2px 10px;font-weight:700;font-size:14px}
.pill.up{background:var(--upbg);color:var(--up)}.pill.down{background:var(--downbg);color:var(--down)}
.pill.flat{background:var(--flatbg);color:var(--flat)}
.st{font-size:14px;display:flex;align-items:center;gap:8px}
.dot{width:10px;height:10px;border-radius:50%;flex:none}
.foot{color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:8px}
svg.sp{width:100%;height:44px}
ol.how{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 36px 16px 16px;margin:0}
ol.how li{margin:6px 0}
details{margin-top:24px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
summary{cursor:pointer;font-weight:600}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;direction:ltr;margin-top:10px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td:first-child,th:first-child{text-align:left}
.en{color:var(--muted);font-size:12px;margin-top:18px;direction:ltr;text-align:left}
.live{margin-top:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.pulse{width:10px;height:10px;border-radius:50%;background:var(--flat);flex:none}
.pulse.on{background:#e5484d;animation:p 1.4s infinite}@keyframes p{50%{opacity:.25}}
.live b{font-size:18px}.live .m{color:var(--muted);font-size:13px}
.tag{font-size:12px;color:var(--muted)}
"""


LIVE_BOX = """<div class="live" id="live"><span class="pulse" id="lp"></span>
<span id="lt">السعر المباشر: عم يحمّل...</span><span class="m" id="lm"></span></div>"""

LIVE_JS = """<script>
const fmt = v => "$" + v.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const pct = v => (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
const ltr = s => "<span dir='ltr'>" + s + "</span>";
async function tick() {
  let next = 300000;
  try {
    const r = await fetch("/api/live", {cache: "no-store"});
    const d = await r.json();
    const lp = document.getElementById("lp"), lt = document.getElementById("lt"), lm = document.getElementById("lm");
    if (d.market_open) next = 30000;
    if (!d.ok) {
      lp.className = "pulse";
      lt.textContent = "السعر المباشر مش متوفر هلأ";
      lm.textContent = d.market_open ? "" : "السوق مسكّر - بيفتح 15:30 بتوقيتك بأيام التداول";
    } else {
      lp.className = d.market_open ? "pulse on" : "pulse";
      const t = new Date(d.time).toLocaleTimeString("de-DE", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
      const ch = d.last_close ? d.price / d.last_close - 1 : 0;
      lt.innerHTML = (d.market_open ? "مباشر" : "آخر سعر") + ": SPY <b>" + ltr(fmt(d.price)) + "</b> " + ltr("(" + pct(ch) + ")");
      lm.textContent = "الساعة " + t + (d.market_open ? " - بيتحدّث كل 30 ثانية" : " - السوق مسكّر") +
        " - للعرض بس، البوتات بتقرر مرة باليوم";
      for (const [name, b] of Object.entries(d.bots)) {
        if (!b.live) continue;
        const v = document.querySelector("[data-v='" + name + "']");
        const p = document.querySelector("[data-p='" + name + "']");
        const tag = document.querySelector("[data-t='" + name + "']");
        if (v) v.innerHTML = ltr(fmt(b.value));
        if (p) {
          p.innerHTML = ltr(pct(b.change));
          p.className = "pill " + (b.change > 0.00005 ? "up" : b.change < -0.00005 ? "down" : "flat");
        }
        if (tag) tag.textContent = "مباشر";
      }
    }
  } catch (e) { /* keep the last values */ }
  setTimeout(tick, next);
}
tick();
</script>"""


def _money(v: float) -> str:
    return f'<span dir="ltr">${v:,.2f}</span>'


def _pct(v: float) -> str:
    return f'<span dir="ltr">{v:+.2%}</span>'


def _cls(v: float) -> str:
    return "up" if v > 0.00005 else "down" if v < -0.00005 else "flat"


def _spark(curve: list, start: float) -> str:
    vals = [start] + [v for _, v in curve]
    if len(vals) < 3:
        return '<svg class="sp" viewBox="0 0 300 44" preserveAspectRatio="none"><line x1="0" x2="300" y1="22" y2="22" stroke="var(--line)" stroke-width="2"/></svg>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(vals) - 1
    pts = " ".join(
        f"{300 - i / n * 300:.1f},{40 - (v - lo) / span * 36:.1f}" for i, v in enumerate(vals)
    )  # RTL: newest on the left
    color = "var(--up)" if vals[-1] >= start else "var(--down)"
    base = 40 - (start - lo) / span * 36
    return (
        f'<svg class="sp" viewBox="0 0 300 44" preserveAspectRatio="none" aria-hidden="true">'
        f'<line x1="0" x2="300" y1="{base:.1f}" y2="{base:.1f}" stroke="var(--line)" stroke-dasharray="4"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.2" points="{pts}"/></svg>'
    )


def _status(r: dict) -> tuple[str, str]:
    br = set(r.get("breakers") or [])
    if r.get("halted") or "drawdown" in br:
        return "var(--down)", "متوقف عن الشراء للأمان (خسر كتير من أعلى نقطة)"
    if r.get("pending_order") == "buy":
        return "var(--accent)", "قرّر يشتري - بيتنفذ على افتتاح يوم التداول الجاي"
    if r.get("pending_order") == "sell":
        return "var(--accent)", "قرّر يبيع - بيتنفذ على افتتاح يوم التداول الجاي"
    if r.get("in_market"):
        inv = r.get("invested_now") or 0.0
        return "var(--up)", f"داخل السوق - مستثمر {_money(inv)} والباقي كاش"
    if br & {"daily_loss", "weekly_loss"}:
        return "var(--warn)", "استراحة مؤقتة بعد خسارة"
    return "var(--flat)", "كاش - مستني إشارة شراء"


def _last_trade(r: dict) -> str:
    t = r.get("last_trade")
    if not t:
        return "لسا ما عمل ولا صفقة"
    side = "شرى" if t["side"] == "buy" else "باع"
    if t.get("kind", "").startswith("stop"):
        side = "باع (وقف خسارة)"
    return f'آخر صفقة: {side} بسعر {_money(float(t["price"]))} يوم <span dir="ltr">{html.escape(t["session"])}</span>'


def render_board(b: dict) -> str:
    e = html.escape
    forward = str(b.get("period", "")).startswith("FORWARD")
    cash = float(b["starting_cash"])
    if forward:
        headline = f"تجربة حيّة: كل بوت بلّش بـ{_money(cash)} يوم <span dir='ltr'>{e(b['start'])}</span>"
        updated = "كل يوم الساعة 23:30 تلقائياً (بعد ما يسكّر السوق الأمريكي)"
    else:
        headline = (
            f"تجربة على الماضي: كل بوت بـ{_money(cash)} من <span dir='ltr'>{e(b['start'])}</span>"
            f" لـ <span dir='ltr'>{e(b['end'])}</span>"
        )
        updated = "هاي تجربة على أسعار قديمة، ما بتتحدّث"
    bots = b["bots"]
    cards = []
    for r in bots:
        name, desc = BOT_INFO.get(r["name"], (r["title"], ""))
        color, status = _status(r)
        ret = float(r["total_return"])
        cards.append(
            f"""<div class="card{" first" if r["rank"] == 1 else ""}">
<div class="top"><div class="rank">{r["rank"]}</div><div class="name">{e(name)}</div></div>
<div class="desc">{e(desc)}</div>
<div class="val"><span class="big" data-v="{e(r["name"])}">{_money(float(r["end_value"]))}</span>
<span class="pill {_cls(ret)}" data-p="{e(r["name"])}">{_pct(ret)}</span><span class="tag" data-t="{e(r["name"])}"></span></div>
{_spark(r.get("curve") or [], cash)}
<div class="st"><span class="dot" style="background:{color}"></span><span>{status}</span></div>
<div class="foot">عدد الصفقات: {r["trades"]} &middot; {_last_trade(r)}</div></div>"""
        )
    spy = next((m for m in b["benchmarks"] if "price-only" in m["label"]), None)
    spy_box = (
        f'<div class="box"><div class="k">لو حطيت الـ100 كلها بـSPY وتركتها (بدون قواعد أمان)</div>'
        f'<div class="v">{_money(float(spy["end_value"]))} <span class="pill {_cls(spy["total_return"])}">'
        f"{_pct(float(spy['total_return']))}</span></div></div>"
        if spy
        else '<div class="box"><div class="k">لو حطيت الـ100 كلها بـSPY</div><div class="v">بتبيّن بعد أول يوم</div></div>'
    )
    rows = "".join(
        f"<tr><td>{e(r['title'])}</td><td>${r['end_value']:,.2f}</td><td>{r['total_return']:+.2%}</td>"
        f"<td>{r['cagr']:+.2%}</td><td>{r['max_drawdown']:.2%}</td><td>{r['trades']}</td>"
        f"<td>{e(', '.join(r['breakers']) or '-')}</td></tr>"
        for r in bots
    ) + "".join(
        f"<tr><td>{e(m['label'])}</td><td>${m['end_value']:,.2f}</td><td>{m['total_return']:+.2%}</td>"
        f"<td>{m['cagr']:+.2%}</td><td>{m['max_drawdown']:.2%}</td><td>-</td><td>-</td></tr>"
        for m in b["benchmarks"]
    )
    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Bot leaderboard - لوحة البوتات</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>مختبر جارفس للتداول</h1>
<p class="sub">{headline}</p>
<span class="fake">فلوس وهمية - ولا قرش حقيقي، وما في أي طلب بيطلع من جهازك</span>
<div class="info">
<div class="box"><div class="k">آخر يوم محسوب</div><div class="v" dir="ltr" style="text-align:right">{e(b["end"])}</div></div>
<div class="box"><div class="k">التحديث</div><div class="v" style="font-size:15px">{updated}</div></div>
{spy_box}
</div>
{LIVE_BOX if forward else ""}
<h2>البوتات (الأحسن أول)</h2>
<div class="grid">{"".join(cards)}</div>
<h2>كيف بيشتغل؟</h2>
<ol class="how">
<li>كل يوم بعد ما يسكّر السوق الأمريكي، البرنامج بيجيب سعر <b>SPY</b> الحقيقي (صندوق فيه أكبر 500 شركة أمريكية).</li>
<li>كل بوت بيطّلع على الأسعار وبيقرر: <b>يشتري</b>، <b>يبيع</b>، أو <b>يستنى</b>. كل بوت إلو طريقته، ومكتوبة على بطاقته.</li>
<li>القرار بيتنفذ افتراضياً على سعر افتتاح يوم التداول اللي بعده، مع حساب تكاليف الشراء والبيع.</li>
<li>قواعد الأمان: البوت ما بيخاطر بأكتر من نص بالمية بالصفقة، وكل صفقة إلها وقف خسارة 5%. لهيك أغلب الفلوس بتضل كاش، والربح والخسارة بيطلعوا صغار.</li>
<li>بعد كم شهر منشوف مين الأحسن. الأيام القليلة الأولى ما بتعني كتير.</li>
</ol>
<details><summary>تفاصيل تقنية</summary><div class="tbl"><table>
<tr><th>Bot</th><th>End value</th><th>Return</th><th>CAGR</th><th>Max drawdown</th><th>Trades</th><th>Breakers</th></tr>
{rows}</table></div>
<p class="en">Data: {e(b["data_label"])} &middot; {e(b["period"])}</p></details>
<p class="en">{e(b.get("disclaimer", HYPOTHETICAL_BANNER))}</p>
</div>{LIVE_JS if forward else ""}</body></html>"""
