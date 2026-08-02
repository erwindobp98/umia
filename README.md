# 🚀 UMIA Finance Auto Bot

Bot otomatis untuk **UMIA Finance Testnet (Base Sepolia)** yang mendukung multi-wallet, dashboard real-time, bidding otomatis, swap otomatis, faucet, serta auto claim reward auction.

> ⚠️ **Peringatan Security:** Khusus untuk **Testnet Base Sepolia (Chain ID 84532)**. Script memiliki proteksi agar tidak dapat dijalankan pada mainnet.

---

## ✨ Features

### 🔐 Secure Authentication
* **Login Otomatis:** Menggunakan Privy SIWE (*Sign-In With Ethereum*).
* **Captcha Solver:** Integrasi Capsolver untuk menyelesaikan Cloudflare Turnstile Captcha secara otomatis.
* **Auto Refresh Session:** Auto refresh JWT Token ketika sesi berakhir.
* **Privacy First:** Menyembunyikan private key dari log/error.

### 👛 Multi Wallet Support
* Mendukung banyak wallet sekaligus.
* Membaca private key dari file `private_keys.txt`.
* Menjalankan seluruh wallet secara paralel menggunakan `ThreadPool`.
* Jumlah worker dapat diatur sesuai kebutuhan.

### 📊 Live Realtime Dashboard
Dashboard terminal menggunakan **Rich Library** yang menampilkan:
* Status setiap wallet
* Address wallet
* Saldo USDC
* Hash transaksi terakhir
* Worker aktif
* Status RPC
* Status Captcha

*Semua informasi diperbarui secara realtime tanpa memenuhi terminal.*

### 💧 Auto Faucet
* Claim faucet otomatis.
* Automatic retry ketika gagal.
* Auto-update saldo setelah faucet berhasil.

### 🔄 Auto Swap
* Mendukung swap otomatis melalui API UMIA.
* Nominal swap acak (random amount).
* Slippage dapat dikonfigurasi.
* Auto approval token & auto cek saldo sebelum swap.
* Auto kirim transaksi on-chain.

### 💰 Auto Auction Bid
* Mendeteksi auction yang sedang berlangsung secara otomatis.
* Menghitung harga bid otomatis.
* Random nominal bid.
* Generate Permit2 Signature (EIP-712).
* Submit bid otomatis & auto approval USDC.

### 🎁 Auto Exit & Claim
* Mengecek seluruh auction yang telah berakhir.
* Exit bid & claim reward secara otomatis.
* Mendeteksi token hasil auction (tidak perlu claim manual).

### 🔁 Auto Swap Reward
* Mendeteksi seluruh token reward setelah di-claim.
* Approve token otomatis.
* Swap kembali ke USDC untuk memutar modal secara otomatis.

### ⛽ Gas Protection
* Mengecek saldo ETH sebelum transaksi dijalankan.
* Memastikan saldo cukup untuk membayar gas fee.
* Menghentikan transaksi apabila saldo ETH terlalu kecil.

### 🔒 Safety Protection
Script dibatasi secara ketat untuk mencegah transaksi tidak sengaja pada jaringan utama:
* ✅ **Hanya Mengizinkan:** Base Sepolia (84532)
* ❌ **Memblokir:** Mainnet Ethereum, Base Mainnet, Arbitrum, Optimism, Polygon.

### ⚙️ Fully Configurable
Semua parameter dapat diubah langsung dari script:
* Jumlah worker & random delay
* Swap amount & Bid amount
* Slippage settings
* Retry captcha & Retry faucet
* Shuffle wallet & Shuffle action
* Auto Claim & Auto Swap Back
* Gas Multiplier

---

## 📂 File Requirements

Hanya membutuhkan dua file konfigurasi sederhana tanpa perlu database:
1. `private_keys.txt` — Berisi daftar private key wallet Anda.
2. `capsolver_key.txt` — Berisi API key Capsolver.

---

## 🚀 Parallel Processing

Bot menggunakan sistem multi-threading:
* Multi-threading execution
* Parallel wallet execution
* Independent worker untuk setiap wallet

*Banyak wallet dapat dijalankan secara bersamaan dengan cepat dan efisien.*

---

## 📈 Automatic Workflow

Setelah dijalankan, bot akan bekerja secara otomatis dengan alur (*flowchart*) berikut:

```text
1. [Login]                ──► Berhasil dapat JWT Token

# loop daily:

2. [(Optional) Faucet]    ──► Skipped (Kondisi acak tidak terpenuhi)

3. [(Optional) Swap]      ──► EKSEKUSI DAILY SWAP (Diacak dapat $5 USDC -> Swap USDC to Token)

#loop 5-8 detik

4. [Check Live Auction]   ──► Ada Pool #101 Aktif

5. [Submit Bid]           ──► Bid 10 USDC ke Pool #103

6. [Check Ended Auction]  ──► Menemukan Pool #102 Selesai

7. [Exit Bid]             ──► Sukses Exit Bid

8. [Claim Reward]         ──► Sukses Claim 100 FNDR

9. [Swap Reward -> USDC]  ──► Swap 100 FNDR -> 25 USDC (Auto Liquidate)

10. [Cooldown]            ──► Tidur 5 - 8 detik ──► Repeat Loop 
```


