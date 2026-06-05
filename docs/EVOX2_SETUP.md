# EvoX2 Setup — MT5 Bridge + OpenD

Run all commands in **PowerShell as Administrator** on the EvoX2 Windows machine (192.168.0.26).

---

## 0. Prerequisites

Make sure you have:
- Python 3.12 installed
- MetaTrader 5 installed and logged into your BlackBull **demo** account
- Moomoo OpenD app installed
- The `sigma` repo cloned on EvoX2 (same path or just the `services/mt5-bridge/` folder)

---

## 1. MT5 Bridge

```powershell
# Navigate to the bridge
cd C:\path\to\sigma\services\mt5-bridge

# Create virtualenv and install deps
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Create .env from the example (then fill in your BlackBull credentials)
copy .env.example .env
notepad .env
```

Fill in your BlackBull demo credentials (all other values are pre-set):

```ini
MT5_BRIDGE_HOST=0.0.0.0
MT5_BRIDGE_PORT=8787
MT5_BRIDGE_SECRET=f67825f066cc19466fae306fed990a6883050d9801fcf04efd902bdf309a46cf
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=BlackBullMarkets-Demo
MT5_PATH=
MT5_PAPER=true
MT5_DEVIATION_POINTS=20
```

Start the bridge:

```powershell
.venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8787
```

Leave this terminal window open. Keep the bridge running.

---

## 2. OpenD (Moomoo Options)

1. Launch the **Moomoo OpenD** app
2. Log into your **paper / simulate** trading account
3. Confirm the OpenD window shows it's listening (usually port `11111` by default)

---

## 3. Firewall Rules

In a **new PowerShell as Admin** window:

```powershell
netsh advfirewall firewall add rule name="MT5 Bridge" dir=in action=allow protocol=TCP localport=8787
netsh advfirewall firewall add rule name="OpenD" dir=in action=allow protocol=TCP localport=11111
```

---

## 4. Verify (from EvoX2 itself)

Test the bridge locally:

```powershell
curl.exe -H "X-MT5-Bridge-Secret: f67825f066cc19466fae306fed990a6883050d9801fcf04efd902bdf309a46cf" http://localhost:8787/health
```

Test OpenD locally:

```powershell
curl.exe http://127.0.0.1:11111 > $null
```

---

## 5. Activate from DGX

Once both services pass their local curl tests above, run this from the DGX:

```bash
cd /home/roc/quantumGlobalGroup/sigma/apps/api
PYTHONPATH=. .venv/bin/python scripts/activate_evox2.py
```

The script verifies MT5 bridge + OpenD health, then automatically updates `.env`
to flip `FOREX_EXECUTOR=mt5` and `OPTION_EXECUTOR=moomoo` and expands
`FOREX_MT5_SYMBOLS` to the full forex universe.
