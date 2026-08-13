# 🏴‍☠️ Luffy Panel

A lightweight VLESS + Trojan proxy panel built with FastAPI, deployable on [Render](https://render.com) or [Railway](https://railway.app).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/luffy-sh-op/LUFFY_PANEL)
&nbsp;&nbsp;
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/luffy-sh-op/LUFFY_PANEL)

---

## ✨ Features

- **MTProto (Telegram) proxy** as a separate inbound type, with its own quotas/expiry/Clean IPs and sponsor-tag field
- Per-inbound **Clean IP selection** — pick exactly which addresses go into each inbound's configs instead of always using the whole global list
- Two auto-generated **info configs** per inbound showing remaining volume and remaining days, right inside the client's config list
- **VLESS and Trojan**, each independently enable-able **per inbound** — one inbound can serve both protocols at once, each with its own transport/fingerprint/ALPN
- **Transports:** WebSocket, XHTTP (packet-up mode), XHTTP (stream-up mode)
- Selectable **uTLS fingerprint** per protocol (chrome, firefox, safari, ios, android, edge, 360, qq, random, randomized)
- Selectable **ALPN** per protocol from a fixed set: `h3`, `h2`, `http/1.1`, `h3,h2,http/1.1`, `h3,h2`, `h2,http/1.1`
- Port is **fixed at 443** for every config (no per-link port customization)
- Multi-inbound management with per-user traffic quotas
- Connection limits per inbound (max IPs)
- Expiry date support per inbound
- Subscription link (`/sub/<uid>`) compatible with v2rayNG, Hiddify, etc. — automatically lists every enabled protocol/address combination
- Clean IP / alternative address management, with a one-click **Railway IP** bulk-import button (reads from `railway_ips.txt`)
- Real-time dashboard: CPU, memory, hourly traffic chart
- Bilingual UI (English / Persian)
- Dark & Light mode
- Session-based authentication with password change
- Keep-alive mechanism for free-tier hosting
- **Persistent SQLite storage** — inbounds, addresses, and settings survive restarts

---

## 🗂️ Project Structure

```
.
├── main.py               # FastAPI application (gateway + panel UI)
├── xhttp_transport.py    # XHTTP transport (packet-up / stream-up) router
├── mtproto-proxy.py      # Standalone MTProto (Telegram) proxy engine, auto-spawned by main.py
├── railway_ips.txt       # Optional: your own list of clean IPs for the Railway IP import button
├── requirements.txt      # Python dependencies
├── render.yaml            # Render deployment config
└── Procfile               # Process entry point
```

---

## 🔐 Protocols & Transports

Each inbound (link) has two independent **variants**: `vless` and `trojan`. Either or both can be enabled at the same time. Each enabled variant has its own:

- **Transport:** `ws` (WebSocket) or `xhttp-packet-up` / `xhttp-stream-up` (XHTTP)
- **Fingerprint:** any of the supported uTLS fingerprints
- **ALPN:** one of the 6 fixed combinations listed above

When both VLESS and Trojan are enabled on the same inbound, the subscription page and `/sub/<uid>` output will contain a separate config line for **each** enabled protocol (and for each configured alternative address).

### Routing

Because a single inbound can serve two different wire protocols, the auth type is now part of the URL path so the server knows which parser to use:

- WebSocket: `/ws/{auth}/{uuid}` where `{auth}` is `vless` or `trojan`
- XHTTP downlink: `/xhttp/{auth}/{mode}/{uuid}/{session_id}`
- XHTTP packet-up uplink: `/xhttp/{auth}/packet-up/{uuid}/{session_id}/{seq}`
- XHTTP stream-up uplink: `/xhttp/{auth}/stream-up/{uuid}/{session_id}`

> ⚠️ If you're upgrading from an older version of this panel, previously-issued config links (`/ws/{uuid}` without an auth segment) will stop working. Re-copy/re-scan configs from the panel after upgrading.

---

## 🚀 Deploy on Render

### One-click via `render.yaml`

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/luffy-sh-op/LUFFY_PANEL)

1. Fork or push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New Web Service** → connect your repo.
3. Render will auto-detect `render.yaml` and configure everything.
4. Set your `ADMIN_PASSWORD` environment variable (default: `admin`).

> 💡 **Tip:** For better speed, set the **Region** to **Frankfurt (EU)** in Render settings.

### Manual Setup

| Field | Value |
|---|---|
| **Environment** | Python |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python main.py` |

### 🌐 Render & Cloudflare Clean IPs

> **This panel on Render routes through Cloudflare's clean IPs exclusively.**
>
> Render's infrastructure sits behind Cloudflare's network, so all configs will automatically use **Cloudflare clean IP ranges** — which are generally unblocked and stable in restricted regions.
>
> ✅ Use the panel URL directly — Cloudflare CDN handles routing automatically.
>
> If configs don't connect, try manually adding a known Cloudflare clean IP (e.g. `104.21.x.x` or `172.67.x.x`) from the **Clean IP** page in your client instead of the hostname.

---

## 🚂 Deploy on Railway

### One-click deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/luffy-sh-op/LUFFY_PANEL)

1. Fork or push this repo to GitHub.
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select your repo.
3. Wait for the deployment to finish. You'll be given a URL — that's your service domain. To access the panel, just add `/login` to the end of your domain.

### ⚠️ Railway IP Addresses

> **Railway does NOT use Cloudflare. It uses its own dedicated IP ranges.**
>
> Railway's outbound IPs typically fall in the range **`69.46.46.x`**, so your configs will use Railway's own IPs — not Cloudflare's. These may or may not be accessible depending on your network restrictions.
>
> **If configs don't work on Railway:**
> 1. Check whether the `69.46.46.x` range is reachable from your network.
> 2. Add your own known-working IPs to `railway_ips.txt` (one per line, next to `main.py`) and click the **🚄 Railway IP** button on the **Clean IP** page to bulk-import them into the panel in one click.
> 3. Enable **Fragment Mode** in your v2ray / v2rayNG client (see section below).
> 4. Switch to Render for Cloudflare clean IP routing.

---

## 🌍 Clean IP Page

The **Clean IP** page lets you manage alternative addresses that get appended to every generated config (in addition to the panel's own domain), so clients can fall back to a working IP if the main hostname is blocked.

- **+ Add** — add a single address manually
- **🚄 Railway IP** — bulk-imports every line from `railway_ips.txt` (placed next to `main.py`) in a single request, skipping duplicates
- **Delete All** — clears the list

> There is no default/pre-filled address anymore — the list starts empty until you add your own.

---

## 📡 MTProto Proxy

Luffy Panel can also run a Telegram **MTProto proxy**, managed from its own **MTProto** tab in the panel — completely separate from the VLESS/Trojan inbounds.

- Add as many secrets ("inbounds") as you want, each with its own traffic quota, expiry date, max connections, set of Clean IPs, and **its own internal port**.
- Each inbound gets a ready `tg://proxy?server=...&port=...&secret=...` link (and QR code).
- **Sponsor / promoted channel:** register your proxy's IP, port and secret with Telegram's official **@MTProxybot** to have Telegram show your channel to your proxy's users. Paste the tag it gives you into the "Sponsor Tag" field — that's just a reminder field in the panel; the actual ad delivery is handled entirely by Telegram once you've registered.

### Two engines — build with the Dockerfile for the reliable one

The proxy is supervised by `mtproto-proxy.py`, spawned automatically by `main.py` on boot. It picks its engine automatically:

1. **mtg (recommended)** — the real, battle-tested [mtg](https://github.com/9seconds/mtg) binary. This repo's **`Dockerfile`** builds it in by copying the binary straight out of the official `nineseconds/mtg` image, so if you deploy with Docker (which Railway and Render both do automatically when a `Dockerfile` is present) you get it for free — no extra setup. One `mtg` process runs per active inbound, each on its own internal port.
2. **Built-in Python engine (fallback)** — only used if the `mtg` binary isn't found (e.g. you deployed without Docker, using just `Procfile`/buildpacks). It implements the MTProto handshake from scratch; see the limitations below.

> Traffic usage (`used_bytes`) only updates live under the built-in Python engine — `mtg` doesn't expose clean per-secret byte counters. Quota/expiry/active enforcement still works with `mtg` either way (an inbound that goes over quota or expires simply has its `mtg` process stopped); you just won't see the live counter tick up. Use the "Reset"/limit fields to manage it manually if you're on the `mtg` engine.

### TCP Proxy — created automatically via the Railway API

**MTProto is not HTTP.** It cannot share the panel's HTTPS port the way VLESS/Trojan configs do (those piggyback on the web server itself). It needs its own raw TCP port exposed publicly, one per inbound.

The panel can create that TCP proxy **for you**, with no trip to the Railway dashboard, using the Railway API token you already set in **Settings** (the same one used for the Static IP / permanent-volume features):

- The moment you create an MTProto inbound, the panel calls Railway's API to create a TCP Proxy pointed at that inbound's internal port, and saves the public host/port it gets back — the "🟢 detected" indicator lights up automatically, no copy-pasting.
- **The MTProto tab also has its own "🚂 Railway — Auto TCP Proxy" card**: paste your token, hit **Fetch Projects**, pick the project this panel is deployed in, then hit **Deploy**. It backfills a TCP Proxy for every existing MTProto inbound that doesn't have a public endpoint yet, in one click — useful for inbounds you created before setting up the token, or for provisioning everything at once after a fresh deploy.
- Any single inbound that still doesn't have one can also be retried from its own **Edit** dialog → **"Auto-create TCP Proxy on Railway"** button.
- If automatic creation isn't possible for some reason, the same **Edit** dialog has "Public Host" / "Public Port" fields to paste in a TCP proxy you made by hand in **Settings → Networking → TCP Proxy** on Railway.
- This needs a Railway API token, sourced in this priority order: (1) whatever you paste into the MTProto tab's card or the panel's Settings page, or (2) a `RAILWAY_TOKEN` environment variable set once on this service in Railway's own **Variables** tab (Railway's standard convention for a Project Token — generate one under your project's Settings → Tokens). Option 2 means **zero clicks in the panel, ever** — set it once in Railway and every future inbound provisions itself automatically, including on fresh deploys. Either way the app also needs `RAILWAY_SERVICE_ID`/`RAILWAY_ENVIRONMENT_ID`, which Railway injects automatically — nothing to configure there. There is no way to make this work with *zero* credentials anywhere — Railway doesn't grant a running container permission to modify its own infrastructure without one, by design.

> **Honesty note:** this calls Railway's GraphQL API (`tcpProxyCreate`) using the shape Railway's own tooling uses, but that API isn't publicly documented/versioned, and this environment had no network access to test it live. If auto-creation fails, the panel surfaces the real error instead of pretending it worked, and the manual override fields always work as a fallback regardless.

- **Render:** raw TCP proxying isn't available on standard web services; you'd need a paid "Private Service"/TCP-capable plan, or run `mtproto-proxy.py` on a separate host that does support exposing a TCP port.

### Limitations of the built-in fallback engine (only relevant if you're not using the Dockerfile)

- Supports the **abridged** and **intermediate** client transports (what the vast majority of MTProto clients, including official Telegram apps, use). **Padded-intermediate** and fake-TLS ("dd"-secret / SNI masking) are not implemented — those clients are rejected rather than silently mismatched.
- The handshake follows the publicly documented MTProto "obfuscated2" scheme used by open-source proxies like MTProxy/mtg/mtprotoproxy, and was verified locally byte-for-byte, but it has **not** been tested against a live Telegram datacenter (this environment has no outbound network access). Test it after you deploy, and open an issue if a client can't connect. This caveat does not apply to the `mtg` engine — it's an established, independently maintained project.

## 🔧 Fragment Mode (v2rayNG / v2ray)

If your configurations are not connecting — especially on Railway — enable **Fragment Mode** in your client:

**v2rayNG (Android):**
1. Go to **Settings → Fragment**
2. Enable Fragment and set: Packets `tlshello`, Length `10-30`, Interval `10-20`
3. Reconnect

**v2ray (Desktop):** Add to your `outbound` → `streamSettings`:

```json
"sockopt": {
  "dialerProxy": "fragment",
  "tcpKeepAliveIdle": 100
}
```

Fragment mode splits the TLS ClientHello packet to bypass deep packet inspection (DPI) firewalls.

---

## ▶️ Run Locally

```bash
pip install -r requirements.txt
python main.py
```

Panel will be available at: `http://localhost:8000/login`

> After deploying on Render or Railway, access your panel at: `https://yourdomain/login`

---

## ⚙️ Environment Variables

| Variable | Description | Default |
|---|---|---|
| `ADMIN_PASSWORD` | Panel login password | `admin` |
| `SECRET_KEY` | Session & hash secret (auto-generated) | random |
| `PORT` | Server port | `8000` |

> ⚠️ **Change `ADMIN_PASSWORD` before deploying to production.**

---

## 📦 Dependencies

```
fastapi==0.104.1
uvicorn==0.24.0
websockets==12.0
httpx==0.25.1
psutil==5.9.6
cryptography>=42.0.0   # used by mtproto-proxy.py
```

---

## 📌 Static IPs

| Platform | Static IP? | Notes |
|---|---|---|
| **Render** (Free) | ❌ No | Shared Cloudflare IPs; clean and stable |
| **Render** (Paid) | ✅ Yes | Available on Starter plan and above |
| **Railway** | ✅ Optional | Enable via Settings → Networking → Static IP (paid feature) |

---

## 🔌 API Endpoints

### Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/login` | Login with password |
| `POST` | `/api/logout` | Logout |
| `GET` | `/api/me` | Check session status |
| `POST` | `/api/change-password` | Change admin password |

### Inbounds
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/links` | List all inbounds |
| `POST` | `/api/links` | Create new inbound |
| `PATCH` | `/api/links/{uid}` | Edit inbound |
| `DELETE` | `/api/links/{uid}` | Delete inbound |
| `GET` | `/api/links/{uid}/sub` | Get subscription info |

**Create/edit body fields** (protocol port is always forced to `443` server-side):

| Field | Description |
|---|---|
| `label`, `limit_value`, `limit_unit`, `max_connections`, `days_valid` | Standard quota/expiry fields |
| `vless_enabled` | `true`/`false` — enable VLESS on this inbound |
| `vless_transport` | `ws` \| `xhttp-packet-up` \| `xhttp-stream-up` |
| `vless_fingerprint` | uTLS fingerprint for the VLESS variant |
| `vless_alpn` | ALPN for the VLESS variant (one of the 6 fixed options) |
| `trojan_enabled` | `true`/`false` — enable Trojan on this inbound |
| `trojan_transport` | `ws` \| `xhttp-packet-up` \| `xhttp-stream-up` |
| `trojan_fingerprint` | uTLS fingerprint for the Trojan variant |
| `trojan_alpn` | ALPN for the Trojan variant |

At least one of `vless_enabled` / `trojan_enabled` must end up `true` (the panel defaults to VLESS if neither is set).

Both create and edit also accept `selected_addresses` (array of strings) — the subset of Clean IPs to use for this inbound's configs. Omit or send an empty array to fall back to every Clean IP (the old default behavior).

### MTProto
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/mtproto` | List all MTProto inbounds (also returns the proxy's listening `port`) |
| `POST` | `/api/mtproto` | Create new MTProto inbound |
| `PATCH` | `/api/mtproto/{id}` | Edit MTProto inbound |
| `DELETE` | `/api/mtproto/{id}` | Delete MTProto inbound |
| `POST` | `/api/mtproto/{id}/provision-tcp-proxy` | Retry automatic Railway TCP proxy creation for this inbound |
| `POST` | `/api/railway/mtproto-provision` | The "Deploy" button — provisions TCP proxies for every inbound in one call |

**Create/edit body fields:**

| Field | Description |
|---|---|
| `label` | Name shown in the panel |
| `secret` | 32 hex-char (16-byte) secret; auto-generated if omitted |
| `limit_value`, `limit_unit`, `max_connections`, `days_valid` | Standard quota/expiry fields |
| `dc_id` | Target Telegram DC, `1`-`5` (default `2`) |
| `sponsor_tag` | Free-text reminder of the tag @MTProxybot gave you |
| `selected_addresses` | Array of Clean IPs to build `tg://proxy` links for (plus the panel domain) |

### Subscription
| Method | Path | Description |
|---|---|---|
| `GET` | `/sub/{uid}` | Base64 subscription (v2ray/Hiddify compatible) — includes one line per enabled protocol × address |

### Clean IPs
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/addresses` | List alternative addresses |
| `POST` | `/api/addresses` | Add address |
| `DELETE` | `/api/addresses/{index}` | Remove one address |
| `DELETE` | `/api/addresses` | Remove all addresses |
| `POST` | `/api/addresses/import/{source}` | Bulk-import addresses from a local file in one request. `{source}` currently supports `railway` (reads `railway_ips.txt`) |

### System
| Method | Path | Description |
|---|---|---|
| `GET` | `/stats` | Server stats (auth required) |
| `GET` | `/health` | Health check |

---

## 🌐 Config Formats

**VLESS:**
```
vless://<uuid>@<domain>:443?encryption=none&security=tls&type=ws&host=<domain>&path=/ws/vless/<uuid>&sni=<domain>&fp=chrome&alpn=http/1.1#Luffy-<name>
```

**Trojan:**
```
trojan://<uuid>@<domain>:443?security=tls&type=ws&host=<domain>&path=/ws/trojan/<uuid>&sni=<domain>&fp=chrome&alpn=http/1.1#Luffy-<name>
```

For XHTTP transports, `type=xhttp` and `mode=packet-up` or `mode=stream-up` are used instead, with `path=/xhttp/<auth>/<mode>/<uuid>`.

> Note: authentication is really enforced by the secret `uuid` embedded in the URL path — not by the UUID/password value inside the VLESS/Trojan wire header, which the server doesn't validate. This keeps both protocols consistent and simple to manage from one panel.

---

## 🖥️ Panel Pages

| Page | Description |
|---|---|
| **Dashboard** | Traffic, uptime, CPU/memory, hourly chart |
| **Inbounds** | Create/edit/delete users, per-protocol (VLESS/Trojan) settings, copy config, QR code |
| **Traffic** | Total stats |
| **Clean IP** | Manage alternative subscription addresses, bulk-import from Railway |
| **Security** | Change password |

---

## 📱 Client Setup (v2rayNG / Hiddify)

1. Open the panel and go to **Inbounds**.
2. Click **Sub** to copy the subscription URL.
3. In your client app, add a new subscription with that URL.
4. Update subscription — configs for every enabled protocol will appear automatically.

---

## ⚠️ Notes

- Inbounds, addresses, and settings are stored in a **local SQLite database**, so they survive restarts and redeploys (as long as the disk/volume persists).
- The keep-alive task pings `/health` every 10 minutes to prevent Render free-tier spin-down.

---

## 🤝 Contributing

1. Fork the repository
2. Create a new branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to your branch: `git push origin feature/amazing-feature`
5. Open a **Pull Request**

---

## 📄 License

MIT — use freely, modify as needed.

---

[My Telegram channel](https://t.me/Luffy_sh_op)

---
---
---

# 🏴‍☠️ لوفی پنل

یک پنل پراکسی سبک VLESS + Trojan ساخته‌شده با FastAPI، قابل استقرار روی [Render](https://render.com) یا [Railway](https://railway.app).

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/luffy-sh-op/LUFFY_PANEL)
&nbsp;&nbsp;
[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/luffy-sh-op/LUFFY_PANEL)

---

## ✨ امکانات

- پروکسی **MTProto (تلگرام)** به‌عنوان یک نوع اینباند مجزا، با محدودیت/انقضا/آی‌پی تمیز و فیلد تگ اسپانسر مخصوص خودش
- انتخاب **آی‌پی تمیز مخصوص هر اینباند** — به‌جای استفاده‌ی همیشگی از کل لیست سراسری
- دو **کانفیگ اطلاع‌رسانی** خودکار برای هر اینباند که حجم و روزهای باقی‌مانده رو مستقیم داخل لیست کانفیگ‌های کلاینت نشون می‌دن
- **VLESS و Trojan**، هرکدوم مستقل از دیگری برای هر اینباند قابل فعال‌سازی — یک اینباند می‌تونه هم‌زمان هر دو پروتکل رو داشته باشه، هرکدوم با ترابرد/فینگرپرینت/ALPN خودش
- **ترابردها:** WebSocket، XHTTP (مد packet-up)، XHTTP (مد stream-up)
- انتخاب **فینگرپرینت uTLS** جدا برای هر پروتکل (chrome، firefox، safari، ios، android، edge، 360، qq، random، randomized)
- انتخاب **ALPN** جدا برای هر پروتکل از یک لیست ثابت: `h3`، `h2`، `http/1.1`، `h3,h2,http/1.1`، `h3,h2`، `h2,http/1.1`
- پورت برای همه‌ی کانفیگ‌ها **ثابت روی 443** است (دیگه قابل تغییر نیست)
- مدیریت چند اینباند با محدودیت ترافیک برای هر کاربر
- محدودیت تعداد اتصال (IP) برای هر اینباند
- پشتیبانی از تاریخ انقضا برای هر اینباند
- لینک اشتراک (`/sub/<uid>`) سازگار با v2rayNG، Hiddify و غیره — به‌صورت خودکار برای هر ترکیب پروتکل/آدرس فعال، یک کانفیگ جدا می‌سازه
- مدیریت آی‌پی تمیز / آدرس‌های جایگزین، با دکمه‌ی **Railway IP** برای ایمپورت یکجا (از فایل `railway_ips.txt`)
- داشبورد لحظه‌ای: CPU، حافظه، نمودار ترافیک ساعتی
- رابط کاربری دو زبانه (فارسی / انگلیسی)
- حالت تاریک و روشن
- احراز هویت مبتنی بر session با امکان تغییر رمز
- مکانیزم keep-alive برای هاستینگ رایگان
- **ذخیره‌سازی دائمی با SQLite** — اینباندها، آدرس‌ها و تنظیمات با ریستارت از بین نمی‌رن

---

## 🗂️ ساختار پروژه

```
.
├── main.py               # اپلیکیشن FastAPI (گیت‌وی + رابط پنل)
├── xhttp_transport.py    # روتر ترابرد XHTTP (packet-up / stream-up)
├── mtproto-proxy.py      # موتور مستقل پروکسی MTProto (تلگرام)، خودکار توسط main.py اجرا می‌شه
├── railway_ips.txt       # اختیاری: لیست آی‌پی‌های تمیز خودت برای دکمه‌ی Railway IP
├── requirements.txt      # وابستگی‌های پایتون
├── render.yaml            # تنظیمات استقرار Render
└── Procfile               # نقطه ورود پروسه
```

---

## 🔐 پروتکل‌ها و ترابردها

هر اینباند (لینک) دو **variant** مستقل از هم داره: `vless` و `trojan`. هرکدوم یا هر دو می‌تونن هم‌زمان فعال باشن. هر variant فعال‌شده تنظیمات مستقل خودش رو داره:

- **ترابرد:** `ws` (وب‌سوکت) یا `xhttp-packet-up` / `xhttp-stream-up` (XHTTP)
- **فینگرپرینت:** هرکدوم از فینگرپرینت‌های uTLS پشتیبانی‌شده
- **ALPN:** یکی از ۶ ترکیب ثابت بالا

وقتی هم VLESS و هم Trojan روی یک اینباند فعال باشن، صفحه‌ی اشتراک و خروجی `/sub/<uid>` برای **هرکدوم** از پروتکل‌های فعال (و برای هر آدرس جایگزین تنظیم‌شده) یک خط کانفیگ جدا نشون می‌ده.

### مسیریابی

چون یک اینباند می‌تونه دو پروتکل سیمی متفاوت رو سرویس بده، نوع auth (vless/trojan) الان بخشی از مسیر URL هست تا سرور بفهمه با کدوم پارسر باید هدر رو بخونه:

- WebSocket: `/ws/{auth}/{uuid}` که `{auth}` یا `vless` هست یا `trojan`
- دانلینک XHTTP: `/xhttp/{auth}/{mode}/{uuid}/{session_id}`
- آپلینک XHTTP packet-up: `/xhttp/{auth}/packet-up/{uuid}/{session_id}/{seq}`
- آپلینک XHTTP stream-up: `/xhttp/{auth}/stream-up/{uuid}/{session_id}`

> ⚠️ اگه از نسخه‌ی قدیمی‌تر این پنل آپدیت می‌کنی، لینک‌های کانفیگی که قبلاً صادر شدن (`/ws/{uuid}` بدون بخش auth) دیگه کار نمی‌کنن. بعد از آپدیت، کانفیگ‌ها رو دوباره از پنل کپی/اسکن کن.

---

## 🚀 استقرار روی Render

### یک‌کلیکی با `render.yaml`

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/luffy-sh-op/LUFFY_PANEL)

1. ریپو را fork کنید یا روی GitHub آپلود کنید.
2. به [render.com](https://render.com) بروید ← **New Web Service** ← ریپو را متصل کنید.
3. Render به‌صورت خودکار `render.yaml` را شناسایی و همه چیز را تنظیم می‌کند.
4. متغیر `ADMIN_PASSWORD` را تنظیم کنید (پیش‌فرض: `admin`).

> 💡 **نکته:** برای سرعت بهتر، **Region** را روی **Frankfurt (EU)** تنظیم کنید.

### تنظیم دستی

| فیلد | مقدار |
|---|---|
| **محیط** | Python |
| **دستور Build** | `pip install -r requirements.txt` |
| **دستور Start** | `python main.py` |

### 🌐 Render و آی‌پی‌های تمیز Cloudflare

> **⭐ این پنل روی Render فقط از آی‌پی‌های تمیز Cloudflare استفاده می‌کند.**
>
> زیرساخت Render پشت شبکه Cloudflare قرار دارد، بنابراین تمام کانفیگ‌ها به‌صورت خودکار از **آی‌پی‌های تمیز Cloudflare** عبور می‌کنند — که معمولاً آنبلاک و پایدار هستند.
>
> ✅ URL پنل را مستقیم استفاده کنید — Cloudflare CDN مسیریابی را خودکار انجام می‌دهد.
>
> اگر کانفیگ‌ها وصل نشدند، از صفحه‌ی **آی‌پی تمیز** یک آی‌پی تمیز شناخته‌شده‌ی Cloudflare (مثل `104.21.x.x` یا `172.67.x.x`) اضافه کنید و به جای hostname در کلاینت خود استفاده کنید.

---

## 🚂 استقرار روی Railway

### استقرار یک‌کلیکی

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/luffy-sh-op/LUFFY_PANEL)

1. ریپو را fork کنید یا روی GitHub آپلود کنید.
2. به [railway.app](https://railway.app) بروید ← **New Project** ← **Deploy from GitHub repo** ← ریپو را انتخاب کنید.
3. صبر کنید تا deploy شود؛ بعد از deploy یک url به شما داده می‌شود که آن دامنه سرویس شماست. برای ورود به پنل کافیست به آخر دامنه‌تان `/login` اضافه کنید.

### ⚠️ آی‌پی‌های Railway

> **⭐ Railway از Cloudflare استفاده نمی‌کند و از آی‌پی‌های اختصاصی خودش استفاده می‌کند.**
>
> آی‌پی‌های خروجی Railway معمولاً در رنج **`69.46.46.x`** هستند، بنابراین کانفیگ‌های شما از آی‌پی‌های خود Railway عبور می‌کنند — نه از Cloudflare. این آی‌پی‌ها ممکن است بسته به محدودیت‌های شبکه شما در دسترس باشند یا نباشند.
>
> **اگر کانفیگ‌ها روی Railway کار نکرد:**
> 1. بررسی کنید که رنج `69.46.46.x` از شبکه شما در دسترس است.
> 2. آی‌پی‌های تست‌شده و سالم خودتون رو داخل `railway_ips.txt` (کنار `main.py`) بریزید و از صفحه‌ی **آی‌پی تمیز** روی دکمه‌ی **🚄 Railway IP** بزنید تا همه‌شون یکجا به پنل اضافه بشن.
> 3. **حالت Fragment را در کلاینت v2ray / v2rayNG فعال کنید** (بخش زیر را ببینید).
> 4. برای استفاده از آی‌پی‌های تمیز Cloudflare، به Render بروید.

---

## 🌍 صفحه‌ی آی‌پی تمیز

صفحه‌ی **آی‌پی تمیز** بهت اجازه می‌ده آدرس‌های جایگزینی رو مدیریت کنی که به هر کانفیگ ساخته‌شده اضافه می‌شن (علاوه بر دامنه‌ی خودِ پنل)، تا اگه hostname اصلی بلاک بود، کلاینت بتونه از یه آی‌پی سالم استفاده کنه.

- **+ افزودن** — افزودن دستی یک آدرس
- **🚄 Railway IP** — همه‌ی خط‌های فایل `railway_ips.txt` (کنار `main.py`) رو در یک درخواست، یکجا و بدون تکراری import می‌کنه
- **پاک کردن همه** — کل لیست رو خالی می‌کنه

> دیگه هیچ آدرس پیش‌فرضی از قبل تو لیست نیست — لیست خالی شروع می‌شه تا خودت آدرس‌هات رو اضافه کنی.

---

## 📡 پروکسی MTProto

لوفی پنل می‌تونه یک پروکسی **MTProto** تلگرام هم اجرا کنه، از طریق تب مجزای **MTProto** توی پنل — کاملاً جدا از اینباندهای VLESS/Trojan.

- هر تعداد سکرت («اینباند») که بخوای اضافه کن، هرکدوم با محدودیت ترافیک، تاریخ انقضا، حداکثر اتصال، لیست آی‌پی تمیز، و **پورت داخلی مخصوص خودش**.
- برای هر اینباند یک لینک آماده‌ی `tg://proxy?server=...&port=...&secret=...` (و QR) ساخته می‌شه.
- **تگ اسپانسر / کانال تبلیغاتی:** آی‌پی، پورت و سکرت پروکسیت رو توی ربات رسمی تلگرام **@MTProxybot** ثبت کن تا تلگرام کانال تو رو به کاربرای پروکسیت نشون بده. تگی که بهت می‌ده رو توی فیلد «تگ اسپانسر» بذار — این فیلد فقط برای یادآوری خودته؛ نمایش تبلیغ کاملاً توسط خودِ تلگرام بعد از ثبت انجام می‌شه.

### دو موتور — با Dockerfile اونی که قابل‌اعتماده رو بگیر

پروکسی توسط `mtproto-proxy.py` مدیریت می‌شه، که پنل موقع بالا اومدن به‌صورت خودکار اجراش می‌کنه. موتور رو خودش انتخاب می‌کنه:

1. **mtg (توصیه‌شده)** — باینری واقعی و باتجربه‌ی [mtg](https://github.com/9seconds/mtg). فایل **`Dockerfile`** همین پروژه، این باینری رو مستقیم از ایمیج رسمی `nineseconds/mtg` کپی می‌کنه — پس اگه با Docker دیپلوی کنی (که Railway و Render هر دو وقتی `Dockerfile` وجود داشته باشه خودکار انجامش می‌دن)، بدون هیچ کار اضافه‌ای این موتور رو داری. به‌ازای هر اینباند فعال، یک پروسه‌ی `mtg` جدا روی پورت داخلی خودش اجرا می‌شه.
2. **موتور داخلی پایتون (fallback)** — فقط وقتی استفاده می‌شه که باینری `mtg` پیدا نشه (مثلاً بدون Docker، فقط با `Procfile`/بیلدپک دیپلوی کرده باشی). این موتور هندشیک MTProto رو از صفر پیاده‌سازی می‌کنه؛ محدودیت‌هاش پایین‌تر اومده.

> مصرف ترافیک (`used_bytes`) فقط زیر موتور داخلی پایتون به‌صورت زنده آپدیت می‌شه — چون `mtg` شمارنده‌ی بایت مجزا برای هر سکرت رو به‌سادگی در اختیار نمی‌ذاره. اعمال محدودیت/انقضا/فعال‌بودن روی `mtg` هم درست کار می‌کنه (اینباندی که از محدودیت رد بشه یا منقضی بشه، پروسه‌ی `mtg` مربوطه‌ش متوقف می‌شه)؛ فقط شمارنده‌ی زنده رو نمی‌بینی. اگه از موتور `mtg` استفاده می‌کنی، از فیلدهای محدودیت/بازنشانی برای مدیریت دستی استفاده کن.

### TCP Proxy — روی Railway نیمه‌خودکار

**MTProto پروتکل HTTP نیست.** برخلاف کانفیگ‌های VLESS/Trojan که از همون سرور وب پنل رد می‌شن، MTProto نمی‌تونه پورت HTTPS پنل رو به اشتراک بذاره و به‌ازای هر اینباند به یک پورت TCP خام و مجزا نیاز داره:

### TCP Proxy — خودکار از طریق API خودِ Railway ساخته می‌شه

**MTProto پروتکل HTTP نیست.** برخلاف کانفیگ‌های VLESS/Trojan که از همون سرور وب پنل رد می‌شن، MTProto نمی‌تونه پورت HTTPS پنل رو به اشتراک بذاره و به‌ازای هر اینباند به یک پورت TCP خام و مجزا نیاز داره.

پنل خودش می‌تونه این TCP Proxy رو **بسازه**، بدون اینکه لازم باشه بری تو داشبورد Railway — با همون توکن API که قبلاً توی **تنظیمات** پنل ثبت کردی (همونی که برای قابلیت آی‌پی استاتیک/دیتابیس دائمی استفاده می‌شه):

- همون لحظه‌ای که یک اینباند MTProto می‌سازی، پنل خودش با API ریلوی تماس می‌گیره و یک TCP Proxy روی پورت داخلی همون اینباند می‌سازه، و دامنه/پورت عمومی‌ای که برمی‌گرده رو ذخیره می‌کنه — نشونگر «🟢 تشخیص داده شد» خودکار روشن می‌شه، بدون کپی‌پیست دستی.
- **توی تب MTProto یک کارت مخصوص «🚂 Railway — ساخت خودکار TCP Proxy» هم هست**: توکنت رو بذار، دکمه‌ی **دریافت پروژه‌ها** رو بزن، پروژه‌ای که این پنل توشه رو انتخاب کن، بعد **Deploy** رو بزن. برای هر اینباند MTProto که هنوز endpoint عمومی نداره، یکجا TCP Proxy می‌سازه — برای اینباندهایی که قبل از تنظیم توکن ساخته بودی، یا برای ساخت همه‌چیز یکجا بعد از یک دیپلوی تازه، به‌کار میاد.
- هر اینباند تک‌تکی که هنوز TCP Proxy نداره رو هم می‌تونی از دیالوگ **ویرایش** خودش با دکمه‌ی **«ساخت خودکار TCP Proxy روی Railway»** دوباره امتحان کنی.
- اگه به هر دلیلی ساخت خودکار ممکن نبود، همون دیالوگ **ویرایش** فیلدهای «دامنه عمومی» / «پورت عمومی» رو داره که می‌تونی یک TCP Proxy ساخته‌شده‌ی دستی (از Settings → Networking → TCP Proxy توی Railway) رو توش پیست کنی.
- برای این کار به یک توکن API ریلوی نیاز داره، با این ترتیب اولویت: (۱) هرچی توی کارت تب MTProto یا صفحه‌ی تنظیمات پنل پیست کنی، یا (۲) یک متغیر محیطی `RAILWAY_TOKEN` که یک‌بار توی تب **Variables** خودِ همین سرویس روی Railway تنظیم کنی (قرارداد استاندارد خودِ Railway برای Project Token — از Settings → Tokens پروژه‌ت بسازش). حالت دوم یعنی **هیچ‌وقت لازم نیست چیزی توی پنل بزنی** — یک‌بار توی Railway تنظیمش کن، بعدش هر اینباند جدید (حتی بعد از دیپلوی‌های تازه) خودش خودکار TCP Proxy می‌گیره. در هر دو حالت، برنامه به `RAILWAY_SERVICE_ID`/`RAILWAY_ENVIRONMENT_ID` هم نیاز داره که خودِ Railway به‌صورت خودکار تزریق می‌کنه — چیز اضافه‌ای برای تنظیم نیست. هیچ راهی نیست که این کار **بدون هیچ اعتبارنامه‌ای** انجام بشه — Railway از قصد به یک کانتینر در حال اجرا اجازه نمی‌ده بدون توکن، زیرساخت خودش رو تغییر بده.

> **نکته‌ی صادقانه:** این قابلیت از API گراف‌کیوال ریلوی (mutation به اسم `tcpProxyCreate`) استفاده می‌کنه، دقیقاً با همون فرمتی که ابزارهای خودِ Railway استفاده می‌کنن، ولی این API عمومی و مستندسازی‌شده نیست و این محیط دسترسی به شبکه نداشت که واقعاً تستش کنم. اگه ساخت خودکار شکست بخوره، پنل خطای واقعی رو نشون می‌ده (نه اینکه وانمود کنه موفق شده)، و فیلدهای دستی همیشه به‌عنوان جایگزین کار می‌کنن.

- **Render:** روی سرویس‌های وب معمولی، TCP خام پشتیبانی نمی‌شه؛ به یک پلن پولی «Private Service»/دارای قابلیت TCP نیاز داری، یا باید `mtproto-proxy.py` رو روی یک هاست جدا که از پورت TCP پشتیبانی می‌کنه اجرا کنی.

### محدودیت‌های موتور داخلی fallback (فقط وقتی مهمه که از Dockerfile استفاده نکرده باشی)

- ترابردهای **abridged** و **intermediate** پشتیبانی می‌شن (چیزی که اکثر قریب‌به‌اتفاق کلاینت‌های MTProto از جمله اپ رسمی تلگرام استفاده می‌کنن). حالت **padded-intermediate** و fake-TLS (سکرت‌های «dd» / پنهان‌سازی SNI) پیاده‌سازی نشدن — این کلاینت‌ها به‌جای رفتار نادرست، مستقیم قطع می‌شن.
- هندشیک بر اساس مشخصات عمومی و مستندِ «obfuscated2» که در پروکسی‌های متن‌باز مثل MTProxy/mtg/mtprotoproxy استفاده می‌شه پیاده‌سازی شده و به‌صورت بایت‌به‌بایت به‌صورت محلی تست شده، ولی روی یک دیتاسنتر واقعی تلگرام تست **نشده** (این محیط دسترسی به شبکه‌ی خروجی نداره). بعد از دیپلوی حتماً تستش کن و اگه کلاینتی وصل نشد گزارش بده. این محدودیت روی موتور `mtg` صدق نمی‌کنه — چون یک پروژه‌ی مستقل و جاافتاده‌ست.

## 🔧 فعال‌کردن Fragment Mode (در v2rayNG / v2ray)

اگر کانفیگ‌ها وصل نمی‌شوند — به‌خصوص روی Railway — **حالت Fragment را فعال کنید:**

**v2rayNG (اندروید):**
1. به **Settings → Fragment** بروید
2. Fragment را فعال کنید و تنظیم کنید: Packets روی `tlshello`، Length روی `10-30`، Interval روی `10-20`
3. مجدداً وصل شوید

**v2ray (دسکتاپ):** به `outbound` → `streamSettings` اضافه کنید:

```json
"sockopt": {
  "dialerProxy": "fragment",
  "tcpKeepAliveIdle": 100
}
```

حالت Fragment بسته TLS ClientHello را تقسیم می‌کند تا از فایروال‌های DPI عبور کند.

---

## ▶️ اجرای محلی

```bash
pip install -r requirements.txt
python main.py
```

پنل در این آدرس در دسترس است: `http://localhost:8000/login`

> بعد از استقرار روی Render یا Railway، از این آدرس وارد پنل شوید: `https://yourdomain/login`

---

## ⚙️ متغیرهای محیطی

| متغیر | توضیح | پیش‌فرض |
|---|---|---|
| `ADMIN_PASSWORD` | رمز ورود به پنل | `admin` |
| `SECRET_KEY` | مخفی session و هش (خودکار تولید می‌شود) | تصادفی |
| `PORT` | پورت سرور | `8000` |

> ⚠️ **بعد از استقرار در محیط عمومی، `ADMIN_PASSWORD` را تغییر دهید.**

---

## 📦 وابستگی‌ها

```
fastapi==0.104.1
uvicorn==0.24.0
websockets==12.0
httpx==0.25.1
psutil==5.9.6
cryptography>=42.0.0   # برای mtproto-proxy.py
```

---

## 📌 آی‌پی استاتیک

| پلتفرم | آی‌پی استاتیک؟ | توضیحات |
|---|---|---|
| **Render** (رایگان) | ❌ خیر | آی‌پی‌های مشترک Cloudflare؛ تمیز و پایدار |
| **Render** (پولی) | ✅ بله | از پلان Starter به بالا در دسترس |
| **Railway** | ✅ اختیاری | از طریق Settings → Networking → Static IP فعال شود (ویژگی پولی) |

---

## 🔌 مسیرهای API

### احراز هویت
| متد | مسیر | توضیح |
|---|---|---|
| `POST` | `/api/login` | ورود با رمز |
| `POST` | `/api/logout` | خروج |
| `GET` | `/api/me` | بررسی وضعیت session |
| `POST` | `/api/change-password` | تغییر رمز ادمین |

### اینباندها
| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/links` | لیست همه اینباندها |
| `POST` | `/api/links` | ایجاد اینباند جدید |
| `PATCH` | `/api/links/{uid}` | ویرایش اینباند |
| `DELETE` | `/api/links/{uid}` | حذف اینباند |
| `GET` | `/api/links/{uid}/sub` | دریافت اطلاعات اشتراک |

**فیلدهای بدنه‌ی ایجاد/ویرایش** (پورت همیشه سمت سرور روی `443` ثابت می‌شه):

| فیلد | توضیح |
|---|---|
| `label`, `limit_value`, `limit_unit`, `max_connections`, `days_valid` | فیلدهای استاندارد محدودیت/انقضا |
| `vless_enabled` | `true`/`false` — فعال کردن VLESS روی این اینباند |
| `vless_transport` | `ws` \| `xhttp-packet-up` \| `xhttp-stream-up` |
| `vless_fingerprint` | فینگرپرینت uTLS برای بخش VLESS |
| `vless_alpn` | ALPN برای بخش VLESS (یکی از ۶ گزینه‌ی ثابت) |
| `trojan_enabled` | `true`/`false` — فعال کردن Trojan روی این اینباند |
| `trojan_transport` | `ws` \| `xhttp-packet-up` \| `xhttp-stream-up` |
| `trojan_fingerprint` | فینگرپرینت uTLS برای بخش Trojan |
| `trojan_alpn` | ALPN برای بخش Trojan |

حداقل یکی از `vless_enabled` / `trojan_enabled` باید `true` باشه (اگه هیچ‌کدوم ست نشه، پنل به‌صورت پیش‌فرض VLESS رو فعال می‌کنه).

ایجاد و ویرایش هر دو فیلد `selected_addresses` (آرایه‌ای از رشته) رو هم می‌پذیرن — زیرمجموعه‌ای از آی‌پی‌های تمیز که برای کانفیگ‌های این اینباند استفاده می‌شه. اگه خالی بذاری یا نفرستی، مثل قبل از کل لیست آی‌پی تمیز استفاده می‌شه.

### MTProto
| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/mtproto` | لیست همه‌ی اینباندهای MTProto (به‌همراه `port` گوش‌دادن پروکسی) |
| `POST` | `/api/mtproto` | ایجاد اینباند MTProto جدید |
| `PATCH` | `/api/mtproto/{id}` | ویرایش اینباند MTProto |
| `DELETE` | `/api/mtproto/{id}` | حذف اینباند MTProto |
| `POST` | `/api/mtproto/{id}/provision-tcp-proxy` | تلاش دوباره برای ساخت خودکار TCP Proxy روی Railway برای این اینباند |
| `POST` | `/api/railway/mtproto-provision` | دکمه‌ی «Deploy» — TCP Proxy همه‌ی اینباندها رو یکجا می‌سازه |

**فیلدهای بدنه‌ی ایجاد/ویرایش:**

| فیلد | توضیح |
|---|---|
| `label` | نامی که توی پنل نشون داده می‌شه |
| `secret` | سکرت ۳۲ کاراکتری هگز (۱۶ بایت)؛ اگه ندی خودکار ساخته می‌شه |
| `limit_value`, `limit_unit`, `max_connections`, `days_valid` | فیلدهای استاندارد محدودیت/انقضا |
| `dc_id` | دیتاسنتر مقصد تلگرام، `1` تا `5` (پیش‌فرض `2`) |
| `sponsor_tag` | یادداشت آزاد برای تگی که @MTProxybot بهت داده |
| `selected_addresses` | آرایه‌ای از آی‌پی‌های تمیز برای ساخت لینک `tg://proxy` (به‌علاوه‌ی دامنه‌ی پنل) |

### اشتراک
| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/sub/{uid}` | اشتراک Base64 (سازگار با v2ray/Hiddify) — شامل یک خط برای هر ترکیب پروتکل فعال × آدرس |

### آی‌پی تمیز
| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/api/addresses` | لیست آدرس‌های جایگزین |
| `POST` | `/api/addresses` | افزودن آدرس |
| `DELETE` | `/api/addresses/{index}` | حذف یک آدرس |
| `DELETE` | `/api/addresses` | حذف همه‌ی آدرس‌ها |
| `POST` | `/api/addresses/import/{source}` | ایمپورت یکجای آدرس‌ها از یک فایل محلی، در یک درخواست. `{source}` فعلاً `railway` رو پشتیبانی می‌کنه (از `railway_ips.txt` می‌خونه) |

### سیستم
| متد | مسیر | توضیح |
|---|---|---|
| `GET` | `/stats` | آمار سرور (نیاز به احراز هویت) |
| `GET` | `/health` | بررسی سلامت سرور |

---

## 🌐 فرمت کانفیگ‌ها

**VLESS:**
```
vless://<uuid>@<domain>:443?encryption=none&security=tls&type=ws&host=<domain>&path=/ws/vless/<uuid>&sni=<domain>&fp=chrome&alpn=http/1.1#Luffy-<name>
```

**Trojan:**
```
trojan://<uuid>@<domain>:443?security=tls&type=ws&host=<domain>&path=/ws/trojan/<uuid>&sni=<domain>&fp=chrome&alpn=http/1.1#Luffy-<name>
```

برای ترابرد XHTTP به‌جای این، از `type=xhttp` و `mode=packet-up` یا `mode=stream-up` استفاده می‌شه، با `path=/xhttp/<auth>/<mode>/<uuid>`.

> نکته: احراز هویت واقعی توسط همون `uuid` مخفیِ داخل مسیر URL انجام می‌شه — نه مقدار UUID/پسورد داخل هدر VLESS/Trojan که سمت سرور اصلاً چک نمی‌شه. این باعث می‌شه هر دو پروتکل یکسان و از یک پنل قابل مدیریت باشن.

---

## 🖥️ صفحات پنل

| صفحه | توضیح |
|---|---|
| **داشبورد** | ترافیک، آپتایم، CPU/حافظه، نمودار ساعتی |
| **اینباندها** | ایجاد/ویرایش/حذف کاربر، تنظیمات جدا برای هر پروتکل (VLESS/Trojan)، کپی کانفیگ، کد QR |
| **ترافیک** | آمار کلی |
| **آی‌پی تمیز** | مدیریت آدرس‌های جایگزین اشتراک، ایمپورت یکجا از Railway |
| **امنیت** | تغییر رمز |

---

## 📱 راه‌اندازی کلاینت (v2rayNG / Hiddify)

1. پنل را باز کنید و به **اینباندها** بروید.
2. روی **Sub** کلیک کنید تا لینک اشتراک کپی شود.
3. در اپ کلاینت، یک اشتراک جدید با آن لینک اضافه کنید.
4. اشتراک را آپدیت کنید — کانفیگ‌های هر پروتکل فعال به‌صورت خودکار نمایش داده می‌شوند.

---

## ⚠️ نکات مهم

- اینباندها، آدرس‌ها و تنظیمات در یک **دیتابیس SQLite محلی** ذخیره می‌شن، پس با ریستارت یا دیپلوی مجدد از بین نمی‌رن (تا وقتی دیسک/ولوم سرویس باقی بمونه).
- تسک keep-alive هر ۱۰ دقیقه به `/health` پینگ می‌زند تا از خواب رفتن سرویس رایگان Render جلوگیری کند.

---

## 📄 لایسنس

MIT — آزادانه استفاده و ویرایش کنید.

---

[چنل تلگراممون](https://t.me/Luffy_sh_op)
